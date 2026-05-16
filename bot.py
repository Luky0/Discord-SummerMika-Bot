import os
import json
import discord
from discord.ext import commands
import aiohttp
from PIL import Image
import io
import re
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import asyncio
import base64
from openai import OpenAI

load_dotenv("secrets.env")

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("No token found! Make sure you have a .env file.")

DB_FILE = "database.json"
RANKING_CHANNEL_ID = 1408515039077466364

client = OpenAI(
    api_key=os.getenv("CLOUDFLARE_API_KEY"),
    base_url=f"https://api.cloudflare.com/client/v4/accounts/{os.getenv('CLOUDFLARE_ACCOUNT_ID')}/ai/v1"
)

# Initialize intents and bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='~', intents=intents)

bot.remove_command('help')

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            db = json.load(f)
            # Ensure the custom_names dictionary exists in older databases
            if "custom_names" not in db:
                db["custom_names"] = {}
            return db
    return {"processed_messages": [], "days": {}, "custom_names": {}}

def save_db(data):
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def extract_data_from_image(image_bytes, force_parse=False):
    """Uses Cloudflare's free Llama 3.2 Vision model."""
    try:
        original_img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        
        # We still crop and compress to save your free daily Neurons!
        width, height = original_img.size
        cropped_img = original_img.crop((0, int(height * 0.55), width, height))
        
        if cropped_img.width > 800:
            ratio = 800 / cropped_img.width
            new_height = int(cropped_img.height * ratio)
            cropped_img = cropped_img.resize((800, new_height), Image.Resampling.LANCZOS)
            
        # Convert the cropped PIL image back to base64 bytes for the API
        buffered = io.BytesIO()
        cropped_img.save(buffered, format="JPEG")
        base64_image = base64.b64encode(buffered.getvalue()).decode('utf-8')
        
        # Blast it to Cloudflare! No sleep timer needed.
        response = client.chat.completions.create(
            model="@cf/mistralai/mistral-small-3.1-24b-instruct",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Find the '1st place' wins and 'Races' from this game result. Return ONLY a JSON object exactly like this: {\"wins\": 15, \"races\": 40}"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ]
        )
        
        # Parse the JSON from the AI's reply
        reply_text = response.choices[0].message.content
        
        # Quick regex to grab the JSON block in case Llama adds conversational text
        if reply_text:
            json_match = re.search(r'\{.*?\}', reply_text, re.DOTALL)
        else:
            json_match = None
        if json_match:
            data = json.loads(json_match.group(0))
            wins = data.get("wins", -1)
            races = data.get("races", -1)
            
            # Use our bulletproof modulo 5 math check!
            if isinstance(wins, int) and isinstance(races, int):
                if 5 <= races <= 80 and races % 5 == 0 and wins <= races:
                    return wins, races
                    
    except Exception as e:
        print(f"Cloudflare Vision API Error: {e}")
        
    return None, None

def get_rankings_text(db, day_num):
    day = str(day_num)
    
    # Calculate the maximum possible races up to this day (Day 1=20, Day 2=40, etc.)
    max_total_races = day_num * 20
    
    # 1. Gather Total Cumulative Data
    total_stats_dict = {}
    custom_names = db.get("custom_names", {}) # Load the custom names map
    
    for d in range(1, day_num + 1):
        d_str = str(d)
        if d_str in db["days"]:
            for uid, data in db["days"][d_str].items():
                # OVERRIDE: Check if this user has a custom name; if not, use their Discord name
                display_name = custom_names.get(uid, data["name"])
                
                total_stats_dict[uid] = {
                    "name": display_name,
                    "wins": data["wins"],
                    "races": data["races"]
                }

    # 2. Gather Previous Day Cumulative Data
    prev_stats_dict = {}
    for d in range(1, day_num): 
        d_str = str(d)
        if d_str in db["days"]:
            for uid, data in db["days"][d_str].items():
                prev_stats_dict[uid] = {"wins": data["wins"], "races": data["races"]}

    daily_stats = []
    total_stats = []

    # 3. Calculate Rates
    for uid, total_data in total_stats_dict.items():
        total_w, total_r = total_data["wins"], total_data["races"]
        total_rate = (total_w / total_r * 100) if total_r > 0 else 0
        total_stats.append({"name": total_data["name"], "wins": total_w, "races": total_r, "rate": total_rate})

        prev_w = prev_stats_dict.get(uid, {}).get("wins", 0)
        prev_r = prev_stats_dict.get(uid, {}).get("races", 0)
        daily_w, daily_r = max(0, total_w - prev_w), max(0, total_r - prev_r)

        if uid in db["days"].get(day, {}) or daily_r > 0:
            daily_rate = (daily_w / daily_r * 100) if daily_r > 0 else 0
            daily_stats.append({"name": total_data["name"], "wins": daily_w, "races": daily_r, "rate": daily_rate})

    # 4. Format Strings
    daily_stats.sort(key=lambda x: x["rate"], reverse=True)
    total_stats.sort(key=lambda x: x["rate"], reverse=True)

    cm_num = db.get("cm_number", "??")
    cm_len = db.get("cm_length", "???m")
    cm_surf = db.get("cm_surface", "???")
    
    # Build the daily message (Names are always just bold here)
    overall_title = f"# **CM{cm_num} ({cm_len} {cm_surf}) - Day {day}**"
    daily_msg = f"{overall_title}\n"
    daily_title = f"### **Day {day}**"
    daily_msg += f"{daily_title}\n"
    if not daily_stats:
        daily_msg += "No daily data found.\n"
    else:
        daily_msg += "\n".join([f"**{p['name']}** {p['rate']:.1f}% ({p['wins']}/{p['races']})" for p in daily_stats])
    
    # Build the total message (Check for missing races here)
    total_title = f"### **Total (Up to Day {day})**"
    total_msg = f"\n{total_title}\n"
    if not total_stats:
        total_msg += "No total data found.\n"
    else:
        total_lines = []
        for p in total_stats:
            # If they have fewer than the max possible races, make them Bold AND Italic
            if p['races'] < max_total_races:
                name_display = f"***{p['name']}***" 
            else:
                name_display = f"**{p['name']}**"
                
            total_lines.append(f"{name_display} {p['rate']:.1f}% ({p['wins']}/{p['races']})")
            
        total_msg += "\n".join(total_lines)
    
    return daily_msg + "\n" + total_msg

@bot.event
async def on_ready():
    print(f'{bot.user} is now running!')

@bot.event
async def on_message(message):
    # CRITICAL: Without this line, your bot will ignore all ~commands!
    await bot.process_commands(message)

    # Ignore messages sent by the bot itself
    if message.author.bot:
        return

    # Only watch the uma-musume channel
    if message.channel.name != "uma-musume":
        return

    # Check if there are attachments
    if not message.attachments:
        return

    valid_images = [att for att in message.attachments if any(att.filename.lower().endswith(ext) for ext in ['png', 'jpg', 'jpeg'])]
    if not valid_images:
        return

    db = load_db()

    # If the CM hasn't started yet, don't scan anything
    if "cm_start_date" not in db or not db["cm_start_date"]:
        return 

    # --- Calculate which day this message belongs to ---
    base_start_time = datetime.strptime(db["cm_start_date"], "%Y-%m-%d").replace(
        hour=22, minute=0, second=0, tzinfo=timezone.utc
    )
    
    # If the message is posted before the CM officially begins, ignore it
    if message.created_at < base_start_time:
        return
        
    delta = message.created_at - base_start_time
    day_num = int(delta.total_seconds() // 86400) + 1
    day_str = str(day_num)

    # --- Process the image(s) ---
    processed_any = False
    message_contains_valid_screenshot = False

    for attachment in valid_images:
        # Add a magnifying glass reaction to show the bot is scanning
        try: await message.add_reaction("🔍")
        except: pass

        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url) as resp:
                if resp.status == 200:
                    image_bytes = await resp.read()
                    
                    wins, races = await asyncio.to_thread(extract_data_from_image, image_bytes, message_contains_valid_screenshot)
                    
                    if wins is not None and races is not None:
                        message_contains_valid_screenshot = True
                        processed_any = True
                        
                        user_id = str(message.author.id)
                        user_name = message.author.display_name
                        
                        if day_str not in db["days"]:
                            db["days"][day_str] = {}
                            
                        if user_id not in db["days"][day_str]:
                            db["days"][day_str][user_id] = {"name": user_name, "wins": 0, "races": 0}
                            
                        db["days"][day_str][user_id]["wins"] += wins
                        db["days"][day_str][user_id]["races"] = max(db["days"][day_str][user_id]["races"], races)
                        
                        print(f"Live processed image from {user_name}: {wins} wins, {races} races.")

# --- Update the Leaderboard ---
    if processed_any:
        db["processed_messages"].append(message.id)
        
        # Swap 🔍 for ✅
        try:
            await message.remove_reaction("🔍", bot.user)
            await message.add_reaction("✅")
        except: pass

        ranking_text = get_rankings_text(db, day_num)
        
        # Get the specific ranking channel
        ranking_channel = bot.get_channel(RANKING_CHANNEL_ID)
        if not ranking_channel:
            print("❌ Could not find the ranking channel!")
            return

        if not isinstance(ranking_channel, discord.TextChannel):
            print("❌ Ranking channel is not a text channel!")
            return

        if "day_msg_ids" not in db:
            db["day_msg_ids"] = {}
            
        msg_id_to_edit = db["day_msg_ids"].get(day_str)
        
        if msg_id_to_edit:
            try:
                # Fetch from the ranking channel instead of the current channel
                msg = await ranking_channel.fetch_message(msg_id_to_edit)
                await msg.edit(content=ranking_text)
                save_db(db)
            except discord.NotFound:
                # If the old leaderboard was deleted, post a new one in the ranking channel
                sent_msg = await ranking_channel.send(ranking_text)
                db["day_msg_ids"][day_str] = sent_msg.id
                db["last_ranking_msg_id"] = sent_msg.id
                db["last_ranking_day"] = day_num
                save_db(db)
        else:
            # First image of the day! Post a brand new leaderboard in the ranking channel
            sent_msg = await ranking_channel.send(ranking_text)
            db["day_msg_ids"][day_str] = sent_msg.id
            db["last_ranking_msg_id"] = sent_msg.id
            db["last_ranking_day"] = day_num
            save_db(db)
            
    else:
        # If it scanned the image but couldn't read the numbers, swap 🔍 for ❌
        try:
            await message.remove_reaction("🔍", bot.user)
            await message.add_reaction("❌")
        except: pass

@bot.command()
async def calculate_day(ctx, day: str):
    # --- NEW: Delete the user's command message silently ---
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass # Bot lacks permission, harmless to ignore

    db = load_db()
    
    if "cm_start_date" not in db or not db["cm_start_date"]:
        await ctx.send("Please set the event start date first.", delete_after=5)
        return

    try:
        day_num = int(day)
        if day_num < 1: raise ValueError
    except ValueError:
        await ctx.send("Please provide a valid day number.", delete_after=5)
        return

    base_start_time = datetime.strptime(db["cm_start_date"], "%Y-%m-%d").replace(
        hour=22, minute=0, second=0, tzinfo=timezone.utc
    )
    day_start_time = base_start_time + timedelta(days=(day_num - 1))
    day_end_time = day_start_time + timedelta(days=1)

    channel = discord.utils.get(ctx.guild.channels, name="uma-musume")
    if not channel:
        return

    # --- NEW: Send a temporary scanning message ---
    scan_msg = await ctx.send(f"Scanning `uma-musume` for new Day {day} images...")

    if day not in db["days"]:
        db["days"][day] = {}

    processed_count = 0

    # Look how clean this is! Discord handles the time filtering for us, and we can remove the 'limit' entirely.
    async for message in channel.history(limit=None, after=day_start_time, before=day_end_time):
        
        # Skip if we already processed this message
        if message.id in db["processed_messages"]:
            continue
            
        # Check if message has an image attachment
        if message.attachments:
            # We will do two passes over the attachments. 
            # If any attachment succeeds on pass 1, we set force_parse=True for the rest.
            valid_images_to_process = []
            for attachment in message.attachments:
                if any(attachment.filename.lower().endswith(ext) for ext in ['png', 'jpg', 'jpeg']):
                    valid_images_to_process.append(attachment)
            
            if not valid_images_to_process:
                continue

            # Flag to track if this Discord message contains at least one valid screenshot
            message_contains_valid_screenshot = False
            
            for attachment in valid_images_to_process:
                async with aiohttp.ClientSession() as session:
                    async with session.get(attachment.url) as resp:
                        if resp.status == 200:
                            image_bytes = await resp.read()
                            
                            wins, races = await asyncio.to_thread(extract_data_from_image, image_bytes, message_contains_valid_screenshot)
                            
                            if wins is not None and races is not None:
                                message_contains_valid_screenshot = True 
                                
                                user_id = str(message.author.id)
                                user_name = message.author.display_name
                                
                                if user_id not in db["days"][day]:
                                    db["days"][day][user_id] = {"name": user_name, "wins": 0, "races": 0}
                                    
                                db["days"][day][user_id]["wins"] += wins
                                db["days"][day][user_id]["races"] = max(db["days"][day][user_id]["races"], races)
                                
                                print(f"Processed image from {user_name}: {wins} wins, {races} races.")
                            else:
                                # --- DETAILED ERROR LOGGING ADDED HERE ---
                                print(f"   OCR completely failed to parse all variations of: {attachment.filename}")
                                print(f"   User: {message.author.display_name}")
                                print(f"   Time: {message.created_at.strftime('%Y-%m-%d %H:%M:%S')} (UTC)")
                                print(f"   Message: '{message.content}'\n")

            # Mark message as processed once attachments are handled
            db["processed_messages"].append(message.id)
            processed_count += 1

        
    save_db(db)

    ranking_text = get_rankings_text(db, day_num)
    
    # --- NEW: Smart Message Editing Logic ---
    if "day_msg_ids" not in db:
        db["day_msg_ids"] = {}
        
    msg_id_to_edit = db["day_msg_ids"].get(day)
    edited_successfully = False
    
    # Try to edit the existing message for this specific day
    if msg_id_to_edit:
        try:
            msg = await ctx.channel.fetch_message(msg_id_to_edit)
            await msg.edit(content=ranking_text)
            edited_successfully = True
        except discord.NotFound:
            pass # The old message was manually deleted in Discord, so we will post a new one
            
    # If no message exists (or it was deleted), send a new one
    if not edited_successfully:
        sent_msg = await ctx.send(ranking_text)
        db["day_msg_ids"][day] = sent_msg.id
        db["last_ranking_msg_id"] = sent_msg.id # Keep for edit_score fallback
        db["last_ranking_day"] = day_num
        save_db(db)

    # Clean up the temporary scanning message
    try:
        await scan_msg.delete()
    except:
        pass
        
    # Send a brief self-destructing confirmation
    if processed_count == 0:
        await ctx.send(f"Day {day} updated! (No new images found)", delete_after=3)
    else:
        await ctx.send(f"Day {day} updated! (Processed {processed_count} new images)", delete_after=5)


@bot.command()
async def set_cm_start(ctx, date_str: str, cm_number: int, length: str, surface: str):
    """
    Sets the start date of the CM. Automatically archives old data!
    Usage: ~set_cm_start YYYY-MM-DD 11 3200m Turf
    """
    try:
        valid_date = datetime.strptime(date_str, "%Y-%m-%d")
        db = load_db()
        
        # --- NEW: Archive System ---
        # If a CM was already running and we are starting a NEW one
        if "cm_number" in db and db["cm_number"] != cm_number:
            if "archive" not in db:
                db["archive"] = {}
                
            old_num = str(db["cm_number"])
            db["archive"][old_num] = {
                "days": db.get("days", {}),
                "processed_messages": db.get("processed_messages", []),
                "cm_length": db.get("cm_length", "???m"),
                "cm_surface": db.get("cm_surface", "???")
            }
            
            # Wipe the slate clean for the new CM
            db["days"] = {}
            db["processed_messages"] = []
            db["day_msg_ids"] = {}
            db["last_ranking_msg_id"] = None
            
        # Set the new details
        db["cm_start_date"] = date_str
        db["cm_number"] = cm_number
        db["cm_length"] = length
        db["cm_surface"] = surface.capitalize()
        
        save_db(db)
        
        await ctx.send(f"CM{cm_number} ({length} {db['cm_surface']}) start date set to {date_str}.\n*(Old data was safely archived and the active leaderboard was wiped clean!)*")
    except ValueError:
        await ctx.send("Invalid format. Please use: `~set_cm_start YYYY-MM-DD <number> <length> <surface>`")

@bot.command()
async def reset_cm_data(ctx):
    """Emergency command to wipe the active leaderboard."""
    db = load_db()
    
    # Reset all active tracking
    db["days"] = {}
    db["processed_messages"] = []
    db["day_msg_ids"] = {}
    db["last_ranking_msg_id"] = None
    
    save_db(db)
    await ctx.send("Active leaderboard and scanned image memory have been completely wiped", delete_after=5)


@bot.command()
async def edit_score(ctx, day: str, user_input: str, wins: int, races: int):
    """
    Manually fix a score. 
    Usage: 
    ~edit_score 1 123456789012345678 15 20  (By ID)
    ~edit_score 1 @User 15 20               (By Mention)
    ~edit_score 1 "User Name" 15 20         (By Name in quotes)
    """
    db = load_db()

    try:
        await ctx.message.delete()
    except discord.Forbidden:
        print("Bot lacks 'Manage Messages' permission to delete the user's command.")
    except Exception as e:
        print(f"Error deleting message: {e}")
    
    # 1. Try to find the member
    member = None
    
    # Try by ID or Mention
    try:
        # converter.MemberConverter handles mentions and IDs automatically
        converter = commands.MemberConverter()
        member = await converter.convert(ctx, user_input)
    except commands.BadArgument:
        # If that fails, search by name in the current guild
        member = discord.utils.get(ctx.guild.members, name=user_input) or \
                 discord.utils.get(ctx.guild.members, display_name=user_input)

    if not member:
        await ctx.send(f"❌ Could not find user '{user_input}'. Try using their User ID.")
        return

    db = load_db()
    day_num = int(day)
    user_id = str(member.id)
    
   # Update data
    if str(day_num) not in db["days"]: db["days"][str(day_num)] = {}
    db["days"][str(day_num)][user_id] = {"name": member.display_name, "wins": wins, "races": races}
    save_db(db)

    await ctx.send(f"Updated **{member.display_name}** to {wins}/{races}. Refreshing table...", delete_after=5)

    # --- AUTO-EDIT THE SPECIFIC DAY'S MESSAGE ---
    msg_id = db.get("day_msg_ids", {}).get(str(day_num))
    ranking_channel = bot.get_channel(RANKING_CHANNEL_ID)
    
    if ranking_channel and isinstance(ranking_channel, discord.TextChannel):
        updated_text = get_rankings_text(db, day_num)
        edited_successfully = False

        if msg_id:
            try:
                # Try to fetch and edit the existing message
                msg = await ranking_channel.fetch_message(msg_id)
                await msg.edit(content=updated_text)
                edited_successfully = True
            except discord.NotFound:
                # 404 Error: The message was deleted or is in the old channel!
                pass 
            except Exception as e:
                await ctx.send(f"Score saved, but could not edit the ranking table: {e}", delete_after=5)
                edited_successfully = True # Prevent it from posting a new one on a random API error

        # If the old message couldn't be found (404), post a brand new one!
        if not edited_successfully:
            sent_msg = await ranking_channel.send(updated_text)
            
            # Update the database with the NEW message ID
            if "day_msg_ids" not in db: 
                db["day_msg_ids"] = {}
                
            db["day_msg_ids"][str(day_num)] = sent_msg.id
            db["last_ranking_msg_id"] = sent_msg.id
            save_db(db)


@bot.command()
async def set_name(ctx, user_input: str, *, custom_name: str):
    """
    Sets a permanent custom leaderboard name for a user.
    Usage: ~set_name @User Cool Name
    """
    try:
        await ctx.message.delete()
    except:
        pass

    db = load_db()
    
    # 1. Try to find the member
    member = None
    try:
        converter = commands.MemberConverter()
        member = await converter.convert(ctx, user_input)
    except commands.BadArgument:
        member = discord.utils.get(ctx.guild.members, name=user_input) or \
                 discord.utils.get(ctx.guild.members, display_name=user_input)

    if not member:
        await ctx.send(f"Could not find user '{user_input}'. Try using their User ID.", delete_after=5)
        return

    user_id = str(member.id)
    
    # Save the custom name
    db["custom_names"][user_id] = custom_name
    save_db(db)

    await ctx.send(f"**{member.display_name}** will now be shown as **{custom_name}** on the leaderboard.", delete_after=5)

    # --- AUTO-REFRESH THE LEADERBOARD ---
    day_num = db.get("last_ranking_day")
    if day_num:
        msg_id = db.get("day_msg_ids", {}).get(str(day_num))
        ranking_channel = bot.get_channel(RANKING_CHANNEL_ID)
        
        if msg_id and ranking_channel and isinstance(ranking_channel, discord.TextChannel):
            try:
                updated_text = get_rankings_text(db, day_num)
                msg = await ranking_channel.fetch_message(msg_id)
                await msg.edit(content=updated_text)
            except:
                pass

@bot.command()
async def unlink_day(ctx, day: str):
    """Makes the bot forget the old message ID so it creates a new leaderboard."""
    try: 
        await ctx.message.delete()
    except: 
        pass

    db = load_db()
    if "day_msg_ids" in db and day in db["day_msg_ids"]:
        del db["day_msg_ids"][day]
        save_db(db)
        await ctx.send(f"🔗 Unlinked the old message for Day {day}! The next update will post a brand new leaderboard.", delete_after=5)
    else:
        await ctx.send(f"⚠️ No message ID found for Day {day}.", delete_after=5)



@bot.command(name='help')
async def help_command(ctx):
    """Displays a beautiful custom help menu."""
    
    # We use a Discord Embed to make it look like an official UI panel
    embed = discord.Embed(
        title="Uma Musume CM Leaderboard Bot",
        description="Welcome to the CM Leaderboard! Here is how to use my commands:",
        color=discord.Color.green() # You can change this to .blue(), .red(), .gold(), etc.
    )
    
    # 1. Set CM Start
    embed.add_field(
        name="`~set_cm_start <Date> <Number> <Length> <Surface>`",
        value=(
            "Initializes the Champions Meeting settings. **You must run this first!**\n"
            "**Format:** `YYYY-MM-DD`\n"
            "**Example:** `~set_cm_start 2026-03-30 11 3200m Turf`"
        ),
        inline=False
    )
    
    # 2. Calculate Day
    embed.add_field(
        name="`~calculate_day <Day Number>`",
        value=(
            "Scans the `uma-musume` channel for all screenshots posted during that specific day. "
            "It automatically extracts the wins/races and generates the leaderboard.\n"
            "**Example:** `~calculate_day 1`"
        ),
        inline=False
    )
    
    # 3. Edit Score
    embed.add_field(
        name="`~edit_score <Day> <User> <Wins> <Races>`",
        value=(
            "Manually fixes a score if the AI makes a mistake reading a screenshot. "
            "Automatically updates the active leaderboard message without spamming the chat.\n"
            "*(You can use a @mention, a User ID, or their \"Name in quotes\")*\n"
            "**Example:** `~edit_score 1 @Zyf 18 20`"
        ),
        inline=False
    )

    # 4. Set Custom Name
    embed.add_field(
        name="`~set_name <User> <Custom Name>`",
        value=(
            "Forces the leaderboard to use a specific name for a user instead of their Discord nickname.\n"
            "**Example:** `~set_name @Zyf Uma Master`"
        ),
        inline=False
    )

    await ctx.send(embed=embed)


if __name__ == '__main__':
    bot.run(TOKEN)