import discord
from discord.ext import commands
from dotenv import load_dotenv
import json
import os

load_dotenv()

# Fetch the bot token from environment variables
token = os.getenv('DISCORD_BOT_TOKEN')

# Debugging: Print the token to see if it's correctly loaded (remove this in production)
if not token:
    print("No Discord bot token found. Please set the DISCORD_BOT_TOKEN environment variable.")
    raise ValueError("No Discord bot token found. Please set the DISCORD_BOT_TOKEN environment variable.")
else:
    print(f"Bot token: {token}")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

ROLE_ID = 1259317195851305052
ADMIN_ROLE_ID = 1178849360637866044

# Load or initialize the stands data
stand_data = {}
if os.path.exists('stands.json'):
    with open('stands.json', 'r') as f:
        stand_data = json.load(f)
else:
    # Initialize with default values if the file does not exist
    stand_data = {str(i): None for i in range(1, 34)}
    for i in [1, 2, 3, 4, 16, 17, 18]:
        stand_data[str(i)] = 'Taken'

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')

@bot.command()
async def stands(ctx):
    fields = []
    for stand, user_id in stand_data.items():
        status = f"<@{user_id}>" if user_id and user_id != 'Taken' else user_id or 'Available'
        fields.append((f'Stand {stand}', status, False))

    for i in range(0, len(fields), 25):  # Send embed messages with at most 25 fields each
        embed = discord.Embed(title="Available Stands", description="List of stands and their booking status")
        if any(26 <= int(stand[6:]) <= 33 for stand, _, _ in fields[i:i+25]):
            embed.set_image(url="https://i.ibb.co/CWTn2Gf/dsadsadas-1.png")
        for name, value, inline in fields[i:i+25]:
            embed.add_field(name=name, value=value, inline=inline)
        await ctx.send(embed=embed)

def get_user_bookings(user_id):
    return [stand for stand, user in stand_data.items() if user == user_id]

@bot.command()
@commands.has_role(ROLE_ID)
async def book(ctx, stand_number: int):
    if str(stand_number) not in stand_data:
        await ctx.send("Invalid stand number. Please choose a number between 1 and 33.")
        return

    if stand_data[str(stand_number)] == 'Taken' or stand_data[str(stand_number)]:
        await ctx.send("This stand is already taken, please try another stand.")
    else:
        user_id = str(ctx.author.id)
        if get_user_bookings(user_id):
            await ctx.send("You already have an active booking. You can only book one stand at a time.")
        else:
            stand_data[str(stand_number)] = user_id
            with open('stands.json', 'w') as f:
                json.dump(stand_data, f)
            await ctx.send(f"Stand {stand_number} has been successfully booked for {ctx.author.mention}.")

@book.error
async def book_error(ctx, error):
    if isinstance(error, commands.MissingRole):
        await ctx.send("You do not have the required role to book a stand.")

@bot.command()
@commands.has_role(ADMIN_ROLE_ID)
async def reset_bookings(ctx):
    global stand_data
    stand_data = {str(i): None for i in range(1, 34)}
    for i in [1, 2, 3, 4, 16, 17, 18]:
        stand_data[str(i)] = 'Taken'
    with open('stands.json', 'w') as f:
        json.dump(stand_data, f)
    await ctx.send("All bookings have been reset.")

@bot.command()
@commands.has_role(ADMIN_ROLE_ID)
async def revoke_booking(ctx, stand_number: int):
    if str(stand_number) not in stand_data:
        await ctx.send("Invalid stand number. Please choose a number between 1 and 33.")
        return

    if stand_data[str(stand_number)] in ['Taken', None]:
        await ctx.send("This stand is not currently booked by anyone.")
    else:
        stand_data[str(stand_number)] = None
        with open('stands.json', 'w') as f:
            json.dump(stand_data, f)
        await ctx.send(f"Booking for Stand {stand_number} has been revoked and is now available.")

@bot.command()
@commands.has_role(ADMIN_ROLE_ID)
async def book_for(ctx, member: discord.Member, stand_number: int):
    if str(stand_number) not in stand_data:
        await ctx.send("Invalid stand number. Please choose a number between 1 and 33.")
        return

    if stand_data[str(stand_number)] == 'Taken' or stand_data[str(stand_number)]:
        await ctx.send("This stand is already taken, please try another stand.")
    else:
        user_id = str(member.id)
        if get_user_bookings(user_id):
            await ctx.send(f"{member.mention} already has an active booking. They can only book one stand at a time.")
        else:
            stand_data[str(stand_number)] = user_id
            with open('stands.json', 'w') as f:
                json.dump(stand_data, f)
            await ctx.send(f"Stand {stand_number} has been successfully booked for {member.mention}.")

# Debugging: Confirm bot run is starting
print("Starting the bot...")

bot.run(token)
