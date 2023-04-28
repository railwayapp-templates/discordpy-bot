# This example requires the 'message_content' privileged intents

import os
import discord
from discord.ext import commands

rolesList =[]
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    
@client.event

async def on_message(message):
    global rolesList
    text = message.content
    print(str(text))

    if text.startswith('!swb'):
        
        if(text.split()[-1].isdigit()):
            playersNumber=int(text.split()[-1])
            theifsNumber=playersNumber//3
            policeNumber=playersNumber-theifsNumber

            rolesList = ["Sera9"] * theifsNumber + ["Boulice"] * policeNumber
            await message.channel.send("Tor7 fih {} sore9 w {} boulicya".format(theifsNumber,policeNumber))
    elif text.startswith('!korr'):
        if rolesList:
            role = random.choice(rolesList)
            await message.author.send(role)
            rolesList.remove(role)
        else:
            await message.channel.send("Famesh wre9! Lanci torh b '!swb'")

@bot.command()
async def ping(ctx):
    await ctx.send('pong')

@bot.command()
async def hello(ctx):
    await ctx.send("Choo choo! 🚅")


bot.run(os.environ["DISCORD_TOKEN"])
