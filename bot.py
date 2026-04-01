import os
import discord
import responses
from discord.ext import commands
from discord.utils import get
from dotenv import load_dotenv


load_dotenv()

async def send_message(message, user_message, is_private):
    try:
        response = responses.get_response(user_message)
        await message.author.send(response) if is_private else await message.channel.send(response)

    except Exception as e:
        print(e)


def run_discord_bot():
    TOKEN = os.getenv("TOKEN")

    if not TOKEN:
        raise ValueError("No token found! Make sure you have a .env file.")

    intents = discord.Intents.default()
    intents.message_content = True
    client = commands.Bot(command_prefix='~', intents=intents)
    member_ids = [807685011213516811, 214197027829972995, 248090383018491904, 220722173810049034, 168950152847949824, 300752504050679820, 296585736248098816, 225930991833841664, 180180383357337602, 191688386413723648, 513616025699221514, 179367993581633536, 389511325736501269, 224620995602939906, 222429149426483200, 609083617955676161, 621993291772198922, 114142439912112130, 702862162925977671, 538178779902902273, 481741594832404490, 681269087078318318, 167176306117705728, 228706489647366144, 140395952753213440, 744739568074620978, 274968799009177600, 245733679807070209, 173258379207245824, 145097765725274112]

    @client.event
    async def on_ready():
        print(f'{client.user} is now running!')

    @client.command()
    async def test(ctx):
        print(ctx.channel.id)
        member = await ctx.guild.fetch_member(807685011213516811)
        if member:
            print(member.name)
        else:
            print("bruh")

    @client.command()
    async def changeRoles(ctx, g1, g2, g3, g4, g5, g6, g7, g8, g9, g10, g11, g12, g13, g14, g15, g16, g17, g18, g19,
                          g20, g21, g22, g23, g24, g25, g26, g27, g28, g29, g30):
        if ctx.channel.id == 929393229504331836:
            groups = [g1, g2, g3, g4, g5, g6, g7, g8, g9, g10, g11, g12, g13, g14, g15, g16, g17, g18, g19, g20, g21,
                      g22, g23, g24, g25, g26, g27, g28, g29, g30]
            i = 0
            for x in groups:
                y = int(x)
                if 18 >= y >= 1:
                    role = get(ctx.guild.roles, name='Crimson Group ' + x)
                    member = await ctx.guild.fetch_member(member_ids[i])
                    print(member.name)
                    if role not in member.roles:
                        await member.add_roles(role)
                    if ' Group ' not in member.display_name:
                        if len(member.display_name) >= 25:
                            zuViel = -abs(33 - len(member.display_name))
                            await member.edit(nick=member.display_name[:zuViel])
                            await member.edit(nick=member.display_name + ' Group ' + x)
                        else:
                            await member.edit(nick=member.display_name + ' Group ' + x)
                else:
                    await ctx.send("Role for Group " + x + "doesnt exist")
                i = i + 1
            await ctx.send("done")

    @client.command()
    async def removeRoles(ctx):
        if ctx.channel.id == 929393229504331836:
            i = 0
            for x in member_ids:
                member = await ctx.guild.fetch_member(member_ids[i])
                for x in member.roles:
                    if x.name[:13] == 'Crimson Group':
                        await member.remove_roles(x)
                if ' Group ' in member.display_name:
                    await member.edit(nick=member.display_name[:-8])
                i = i + 1
            await ctx.send("done")

    client.run(TOKEN)
