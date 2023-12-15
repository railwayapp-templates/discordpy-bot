import os
import discord
from discord.ext import commands
import requests  # You might need to install this with: pip install requests

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    # Check if the message is in the #ai channel
    if message.channel.name == "ai":
        # Make a request to the ChatGPT API with the message content
        response = get_chatgpt_response(message.content)

        # Send the ChatGPT response back to the Discord channel
        await message.channel.send(response)

    await bot.process_commands(message)

@bot.command()
async def ping(ctx):
    await ctx.send('pong')

@bot.command()
async def hello(ctx):
    await ctx.send("Choo choo! 🚅")

def get_chatgpt_response(input_text):
    # Make a request to the ChatGPT API with the input text
    # Replace 'YOUR_CHATGPT_API_KEY' with your actual ChatGPT API key
    api_key = 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




    api_url = 'https://api.openai.com/v1/chat/completions'
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'}

    payload = {
        'model': 'gpt-3.5-turbo',
        'messages': [{'role': 'user', 'content': input_text}],
    }

    response = requests.post(api_url, json=payload, headers=headers)
    return response.json()['choices'][0]['message']['content']

bot.run(os.environ["DISCORD_TOKEN"])
