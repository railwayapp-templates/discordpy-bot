import os
import discord
from discord.ext import commands

# Define intents for the bot
intents = discord.Intents.default()
intents.message_content = True  # This is needed to read message content

# Create a bot instance
bot = commands.Bot(command_prefix='!', intents=intents)

# Event when the bot is ready
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

# Command that responds with "pong" to the !ping command
@bot.command()
async def ping(ctx):
    await ctx.send('pong')

# Command that responds with "Choo choo!" to the !hello command
@bot.command()
async def hello(ctx):
    await ctx.send("Choo choo! 🚅")

# Event that triggers when a message is sent in a channel
@bot.event
async def on_message(message):
    # Prevent the bot from replying to itself
    if message.author == bot.user:
        return
    
    # Check if the message is "hi" and respond with the package information
    if message.content.lower() == 'hi':
        await message.channel.send('''
      **What package do you want to buy? Here is what Simon offers:**

      **Simon Plus:**
      - Unrigger
      - Prediction
      - 3 algorithms for each game
      - ESP
      - **Price**: 400 weekly, 700 monthly, 1450 lifetime

      **Plus+ (Recommended):**
      - 30 algorithms (5-7 for each game)
      - We have a bot as well
      - Same as Plus but better
      - **Price**: 850 weekly, 1475 monthly, 2000 lifetime paid

      **Paid:**
      - 15 algorithms for each game
      - Best Unrigger with 6 methods
      - Best ESP
      - Best UI
      - Best Predictor
      - **This package is better than** 3vil, Mystic, Star, Thunder, and many others.
      - The only predictor that is better is LunarR.
      - Includes machine learning and AI player
      - **Price**: Custom pricing

      **Paid+:**
      - 100 algorithms in total
      - Powerful machine learning, AI algorithms, and AI player
      - Best AI algorithm and powerful machine learning combined
      - We also offer a bot
      - **Price**: Custom pricing

      **Bot:**
      - Best bot right now
      - Machine learning and advanced algorithms
        ''')
    
    # Ensure the bot processes commands even after handling messages
    await bot.process_commands(message)

# Run the bot with the token stored in an environment variable
bot.run(os.environ["DISCORD_TOKEN"])
