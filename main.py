import discord
from discord.ext import commands
from datetime import datetime, timedelta
import asyncio
import random
from dotenv import load_dotenv
import os
import pytz

load_dotenv()

# Define allowed user IDs
ALLOWED_USER_IDS = {
    #Silver:
    1109541243085656217,
    #Andrew:
    977172586981101598,
    #Lirakos:
    1366875674924679211,
    #Under_files
    1332704506420531252}

# Define log channel names
LOG_CHANNELS = {
    "commands": "log-commands",
    "bans": "log-bans",
    "kicks": "log-kicks",
    "timeouts": "log-timeouts",
    "vc": "log-vc",
    "join": "log-join",
    "left": "log-left",
    "messages": "log-messages",
    "unbans": "log-unbans",
    "roles": "log-roles",
    "channels": "log-channels",
    "invites": "log-invites"
}

intents = discord.Intents.all()
bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None,
    case_insensitive=True
)

def is_allowed_user():
    async def predicate(ctx):
        if ctx.author.id not in ALLOWED_USER_IDS:
            await ctx.send("❌ You are not authorized to use this command", delete_after=5)
            return False
        return True
    return commands.check(predicate)

async def get_log_channel(guild, log_type):
    """Finds the appropriate log channel by name"""
    channel_name = LOG_CHANNELS.get(log_type)
    if not channel_name:
        return None
    
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    return channel

async def send_log(guild, log_type, embed):
    """Sends a log message to the appropriate channel"""
    channel = await get_log_channel(guild, log_type)
    if channel:
        try:
            await channel.send(embed=embed)
        except Exception as e:
            print(f"Failed to send log to {channel.name}: {e}")

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (Prefix: !)")
    
    # Initialize invite tracking
    bot.invites = {}
    for guild in bot.guilds:
        try:
            bot.invites[guild.id] = {invite.code: invite for invite in await guild.invites()}
        except Exception as e:
            print(f"Couldn't fetch invites for {guild.name}: {e}")

# --- LOGGING EVENTS ---
@bot.event
async def on_member_unban(guild, user):
    """Logs unbans"""
    try:
        async for entry in guild.audit_logs(action=discord.AuditLogAction.unban, limit=1):
            if entry.target.id == user.id:
                embed = discord.Embed(
                    title="Member Unbanned",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="User", value=f"{user} ({user.id})")
                embed.add_field(name="Moderator", value=f"{entry.user} ({entry.user.id})")
                embed.set_footer(text=f"User ID: {user.id}")
                
                await send_log(guild, "unbans", embed)
                break
    except Exception as e:
        print(f"Error in on_member_unban: {e}")

@bot.event
async def on_command_completion(ctx):
    """Logs successful command execution"""
    try:
        embed = discord.Embed(
            title="Command Executed",
            description=f"`{ctx.message.content}`",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=f"{ctx.author} ({ctx.author.id})")
        embed.add_field(name="Channel", value=f"{ctx.channel.name} ({ctx.channel.id})")
        embed.set_footer(text=f"User ID: {ctx.author.id}")
        
        await send_log(ctx.guild, "commands", embed)
    except Exception as e:
        print(f"Command logging error: {e}")

@bot.event
async def on_command_error(ctx, error):
    """Logs failed command attempts"""
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.CheckFailure):
        return  # Already handled in is_allowed_user()
    
    try:
        embed = discord.Embed(
            title="Command Failed",
            description=f"`{ctx.message.content}`",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=f"{ctx.author} ({ctx.author.id})")
        embed.add_field(name="Error", value=str(error), inline=False)
        embed.add_field(name="Channel", value=f"{ctx.channel.name} ({ctx.channel.id})")
        embed.set_footer(text=f"User ID: {ctx.author.id}")
        
        await send_log(ctx.guild, "commands", embed)
    except Exception as e:
        print(f"Error logging failed command: {e}")

@bot.event
async def on_message(message):
    """Handles message deletion for commands"""
    if message.author.bot:
        return
    
    # Process commands first
    await bot.process_commands(message)
    
    # Then delete if it was a command
    ctx = await bot.get_context(message)
    if ctx.valid and not isinstance(ctx.command, commands.Group):
        try:
            await asyncio.sleep(0.5)  # Small delay to ensure command processes
            await message.delete()
        except:
            pass

@bot.event
async def on_guild_channel_create(channel):
    """Logs channel creation"""
    try:
        async for entry in channel.guild.audit_logs(action=discord.AuditLogAction.channel_create, limit=1):
            if entry.target.id == channel.id:
                embed = discord.Embed(
                    title="Channel Created",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Channel", value=f"{channel.mention} ({channel.id})")
                embed.add_field(name="Type", value=str(channel.type).title())
                embed.add_field(name="Created By", value=f"{entry.user} ({entry.user.id})")
                await send_log(channel.guild, "channels", embed)
                break
    except Exception as e:
        print(f"Error logging channel creation: {e}")

@bot.event
async def on_guild_channel_delete(channel):
    """Logs channel deletion"""
    try:
        async for entry in channel.guild.audit_logs(action=discord.AuditLogAction.channel_delete, limit=1):
            if entry.target.id == channel.id:
                embed = discord.Embed(
                    title="Channel Deleted",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Channel", value=f"#{channel.name} ({channel.id})")
                embed.add_field(name="Type", value=str(channel.type).title())
                embed.add_field(name="Deleted By", value=f"{entry.user} ({entry.user.id})")
                await send_log(channel.guild, "channels", embed)
                break
    except Exception as e:
        print(f"Error logging channel deletion: {e}")

@bot.event
async def on_guild_channel_update(before, after):
    """Logs channel updates"""
    try:
        # Only log if name or permissions changed
        if before.name != after.name or before.overwrites != after.overwrites:
            async for entry in after.guild.audit_logs(action=discord.AuditLogAction.channel_update, limit=1):
                if entry.target.id == after.id:
                    embed = discord.Embed(
                        title="Channel Updated",
                        color=discord.Color.blue(),
                        timestamp=datetime.utcnow()
                    )
                    embed.add_field(name="Channel", value=f"{after.mention} ({after.id})")
                    
                    if before.name != after.name:
                        embed.add_field(name="Name Changed", value=f"`{before.name}` → `{after.name}`")
                    
                    # Check for permission changes
                    if before.overwrites != after.overwrites:
                        overwrite_changes = []
                        # Check for new overwrites
                        for target, overwrite in after.overwrites.items():
                            if target not in before.overwrites:
                                overwrite_changes.append(f"Added permissions for {target.name}")
                        
                        # Check for removed overwrites
                        for target, overwrite in before.overwrites.items():
                            if target not in after.overwrites:
                                overwrite_changes.append(f"Removed permissions for {target.name}")
                        
                        # Check for modified overwrites
                        for target, after_overwrite in after.overwrites.items():
                            if target in before.overwrites:
                                before_overwrite = before.overwrites[target]
                                if before_overwrite.pair() != after_overwrite.pair():
                                    overwrite_changes.append(f"Updated permissions for {target.name}")
                        
                        if overwrite_changes:
                            embed.add_field(name="Permission Changes", value="\n".join(overwrite_changes), inline=False)
                    
                    embed.add_field(name="Updated By", value=f"{entry.user} ({entry.user.id})")
                    await send_log(after.guild, "channels", embed)
                    break
    except Exception as e:
        print(f"Error logging channel update: {e}")

@bot.event
async def on_member_ban(guild, user):
    """Logs bans"""
    try:
        async for entry in guild.audit_logs(action=discord.AuditLogAction.ban, limit=1):
            if entry.target.id == user.id:
                embed = discord.Embed(
                    title="Member Banned",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="User", value=f"{user} ({user.id})")
                embed.add_field(name="Moderator", value=f"{entry.user} ({entry.user.id})")
                if entry.reason:
                    embed.add_field(name="Reason", value=entry.reason, inline=False)
                embed.set_footer(text=f"User ID: {user.id}")
                
                await send_log(guild, "bans", embed)
                break
    except Exception as e:
        print(f"Error in on_member_ban: {e}")

@bot.event
async def on_member_remove(member):
    try:       
        # Regular leave (no audit log entry found)
        embed = discord.Embed(
            title="Member Left",
            color=discord.Color.dark_grey(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=f"{member} ({member.id})")
        if member.joined_at:
            embed.add_field(name="Joined", value=member.joined_at.strftime('%Y-%m-%d %H:%M'))
        embed.set_footer(text=f"User ID: {member.id}")
        await send_log(member.guild, "left", embed)
        
    except Exception as e:
        print(f"Error logging member leave: {e}")

@bot.event
async def on_member_join(member):
    """Logs new members with invite information"""
    try:
        # Get Greece timezone
        greece_tz = pytz.timezone('Europe/Athens')
        timestamp = datetime.now(greece_tz)
        
        # Create basic embed
        embed = discord.Embed(
            title="Member Joined",
            color=discord.Color.green(),
            timestamp=timestamp
        )
        embed.add_field(name="User", value=f"{member.mention} ({member.id})")
        embed.add_field(name="Account Created", value=member.created_at.strftime('%Y-%m-%d %H:%M'))
        
        # Try to get invite information
        try:
            invites_before = bot.invites.get(member.guild.id, {})
            invites_after = await member.guild.invites()
            
            # Find which invite was used
            used_invite = None
            for code, invite in invites_before.items():
                for new_invite in invites_after:
                    if new_invite.code == code and new_invite.uses > invite.uses:
                        used_invite = new_invite
                        break
                if used_invite:
                    break
            
            if used_invite:
                inviter = used_invite.inviter
                embed.add_field(
                    name="Invite Used",
                    value=f"Code: {used_invite.code}\n"
                          f"Created by: {inviter.mention if inviter else 'Unknown'}\n"
                          f"Uses: {used_invite.uses}",
                    inline=False
                )
        
        except Exception as e:
            print(f"Couldn't get invite info: {e}")
        
        embed.set_footer(text=f"User ID: {member.id}")
        await send_log(member.guild, "join", embed)
        
        # Update cached invites
        try:
            bot.invites[member.guild.id] = {invite.code: invite for invite in await member.guild.invites()}
        except:
            pass
        
    except Exception as e:
        print(f"Error logging member join: {e}")

@bot.event
async def on_member_update(before, after):
    """Logs timeouts and role changes"""
    try:
        guild = before.guild
        
        # Timeout logging
        if before.timed_out_until != after.timed_out_until:
            log_type = "timeouts"
            action = "Timed Out" if after.timed_out_until else "Timeout Removed"
            color = discord.Color.dark_orange()
            
            async for entry in guild.audit_logs(action=discord.AuditLogAction.member_update, limit=1):
                if entry.target.id == after.id and (before.timed_out_until != after.timed_out_until):
                    embed = discord.Embed(
                        title=f"Member {action}",
                        color=color,
                        timestamp=datetime.utcnow()
                    )
                    embed.add_field(name="User", value=f"{after} ({after.id})")
                    embed.add_field(name="Moderator", value=f"{entry.user} ({entry.user.id})")
                    
                    if after.timed_out_until:
                        embed.add_field(name="Duration", value=f"Until {discord.utils.format_dt(after.timed_out_until)}", inline=False)
                    
                    if entry.reason:
                        embed.add_field(name="Reason", value=entry.reason, inline=False)
                    
                    embed.set_footer(text=f"User ID: {after.id}")
                    await send_log(guild, log_type, embed)
                    break
        
        # Role changes
        if before.roles != after.roles:
            added_roles = [role for role in after.roles if role not in before.roles]
            removed_roles = [role for role in before.roles if role not in after.roles]
            
            if added_roles or removed_roles:
                async for entry in guild.audit_logs(action=discord.AuditLogAction.member_role_update, limit=1):
                    if entry.target.id == after.id:
                        embed = discord.Embed(
                            title="Member Roles Updated",
                            color=discord.Color.blurple(),
                            timestamp=datetime.utcnow()
                        )
                        embed.add_field(name="User", value=f"{after} ({after.id})")
                        embed.add_field(name="Moderator", value=f"{entry.user} ({entry.user.id})")
                        
                        if added_roles:
                            embed.add_field(name="Roles Added", value=", ".join([r.mention for r in added_roles]), inline=False)
                        if removed_roles:
                            embed.add_field(name="Roles Removed", value=", ".join([r.mention for r in removed_roles]), inline=False)
                        
                        if entry.reason:
                            embed.add_field(name="Reason", value=entry.reason, inline=False)
                        
                        embed.set_footer(text=f"User ID: {after.id}")
                        await send_log(guild, "roles", embed)
                        break
    
    except Exception as e:
        print(f"Error in on_member_update: {e}")

@bot.event
async def on_voice_state_update(member, before, after):
    """Handles all voice state changes including mutes and deafens"""
    try:
        guild = member.guild
        
        # Voice channel changes
        if (before.channel != after.channel):
            # Member joined a voice channel
            if before.channel is None and after.channel is not None:
                embed = discord.Embed(
                    title="Member Joined Voice Channel",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="User", value=f"{member} ({member.id})")
                embed.add_field(name="Channel", value=after.channel.mention)
                await send_log(guild, "vc", embed)
            
            # Member left a voice channel
            elif before.channel is not None and after.channel is None:
                embed = discord.Embed(
                    title="Member Left Voice Channel",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="User", value=f"{member} ({member.id})")
                embed.add_field(name="Channel", value=before.channel.mention)
                await send_log(guild, "vc", embed)
            
            # Member moved between voice channels
            else:
                embed = discord.Embed(
                    title="Member Moved Voice Channels",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="User", value=f"{member} ({member.id})")
                embed.add_field(name="From", value=before.channel.mention)
                embed.add_field(name="To", value=after.channel.mention)
                await send_log(guild, "vc", embed)
        
        # Server mute/deafen changes (only if channel didn't change)
        elif before.channel == after.channel:
            # Server mute change
            if before.mute != after.mute:
                action = "Server Muted" if after.mute else "Server Unmuted"
                embed = discord.Embed(
                    title=f"Member {action}",
                    color=discord.Color.dark_purple(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="User", value=f"{member} ({member.id})")
                embed.add_field(name="Channel", value=after.channel.mention if after.channel else "Unknown")
                embed.add_field(name="Action", value=action)
                await send_log(guild, "vc", embed)
            
            # Server deafen change
            if before.deaf != after.deaf:
                action = "Server Deafened" if after.deaf else "Server Undeafened"
                embed = discord.Embed(
                    title=f"Member {action}",
                    color=discord.Color.dark_blue(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="User", value=f"{member} ({member.id})")
                embed.add_field(name="Channel", value=after.channel.mention if after.channel else "Unknown")
                embed.add_field(name="Action", value=action)
                await send_log(guild, "vc", embed)
            
            # Self mute/deafen changes
            if before.self_mute != after.self_mute:
                action = "Self Muted" if after.self_mute else "Self Unmuted"
                embed = discord.Embed(
                    title=f"Member {action}",
                    color=discord.Color.purple(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="User", value=f"{member} ({member.id})")
                embed.add_field(name="Channel", value=after.channel.mention if after.channel else "Unknown")
                embed.add_field(name="Action", value=action)
                await send_log(guild, "vc", embed)
            
            if before.self_deaf != after.self_deaf:
                action = "Self Deafened" if after.self_deaf else "Self Undeafened"
                embed = discord.Embed(
                    title=f"Member {action}",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="User", value=f"{member} ({member.id})")
                embed.add_field(name="Channel", value=after.channel.mention if after.channel else "Unknown")
                embed.add_field(name="Action", value=action)
                await send_log(guild, "vc", embed)
    
    except Exception as e:
        print(f"Error in on_voice_state_update: {e}")

@bot.event
async def on_message_delete(message):
    """Logs deleted messages"""
    if message.author.bot:
        return
    
    try:
        embed = discord.Embed(
            title="Message Deleted",
            description=message.content[:2000] if message.content else "*No text content*",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Author", value=f"{message.author} ({message.author.id})")
        embed.add_field(name="Channel", value=f"{message.channel.name} ({message.channel.id})")
        
        if message.attachments:
            embed.add_field(name="Attachments", value=f"{len(message.attachments)} attachment(s)", inline=False)
        
        embed.set_footer(text=f"User ID: {message.author.id}")
        
        await send_log(message.guild, "messages", embed)
    except Exception as e:
        print(f"Error logging message delete: {e}")

@bot.event
async def on_message_edit(before, after):
    """Logs edited messages"""
    if before.author.bot or before.content == after.content:
        return
    
    try:
        embed = discord.Embed(
            title="Message Edited",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Author", value=f"{before.author} ({before.author.id})")
        embed.add_field(name="Channel", value=f"{before.channel.name} ({before.channel.id})")
        
        # Truncate long messages
        before_content = before.content[:1000] + "..." if len(before.content) > 1000 else before.content
        after_content = after.content[:1000] + "..." if len(after.content) > 1000 else after.content
        
        embed.add_field(name="Before", value=before_content or "*No content*", inline=False)
        embed.add_field(name="After", value=after_content or "*No content*", inline=False)
        
        embed.set_footer(text=f"User ID: {before.author.id}")
        
        await send_log(before.guild, "messages", embed)
    except Exception as e:
        print(f"Error logging message edit: {e}")

# --- HELP COMMAND ---
@bot.group(invoke_without_command=True)
async def help(ctx):
    """Shows all available commands"""
    embed = discord.Embed(title="📜 Bot Commands Help", color=discord.Color.blue())
    
    # Main Commands
    embed.add_field(
        name="🔹 Main Commands",
        value="""```
!help - Shows this message
!help <command> - Shows help for specific command
!help color - Shows available embed colors

!say <message>
!embed [color] <message>
!clear [amount]
!lock [channel]
!unlock [channel]
!serverinfo
!userinfo [member]
!roleall <role>
!giveaway <winners> <minutes> <prize>
!giveawayend <message_id> <winners>
!edit <message_id> <new_content>```""",
        inline=False
    )
    
    # DM Commands
    embed.add_field(
        name="🔹 DM Commands",
        value="""```
!dmtext
!dmmember <member_id> <message>
!dmall <message>
!dmrole <role_id> <message>
!dmspam <member> <amount> <message>
!dmspamEmb <user> <color> <title> <message>```""",
        inline=False
    )
    
    # Logging Info
    embed.add_field(
        name="🔹 Logging Channels",
        value="""```
log-commands - Command usage
log-bans - Ban records
log-kicks - Kick records
log-timeouts - Timeout actions
log-vc - Voice chat actions
log-join - New members
log-left - Members leaving
log-messages - Deleted/edited messages```""",
        inline=False
    )
    
    embed.set_footer(text="Seeing the commands is not enough, you need to use them!")
    await ctx.send(embed=embed)

@help.command()
async def color(ctx):
    """Shows available embed colors"""
    colors = [
        "default", "teal", "dark_teal", "green", "dark_green",
        "blue", "dark_blue", "purple", "dark_purple", "magenta",
        "dark_magenta", "gold", "dark_gold", "orange", "dark_orange",
        "red", "dark_red", "lighter_grey", "darker_grey", "blurple",
        "greyple", "black", "white"
    ]
    
    embed = discord.Embed(
        title="🎨 Available Embed Colors",
        description="\n".join([f"• {color}" for color in colors]),
        color=discord.Color.blurple()
    )
    embed.set_footer(text="Use with commands like !embed or !dmspamEmb")
    await ctx.send(embed=embed)



# Auto-delete command messages
@bot.event
async def on_command(ctx):
    try:
        await ctx.message.delete()
    except:
        pass


# Individual command helps
@help.command()
async def say(ctx):
    """Help for !say command"""
    embed = discord.Embed(
        title="!say <message>",
        description="Repeats your message",
        color=discord.Color.blue()
    )
    embed.add_field(name="Example", value="`!say Hello world!`")
    await ctx.send(embed=embed)

@help.command()
async def embed(ctx):
    """Help for !embed command"""
    embed = discord.Embed(
        title="!embed [color] <message>",
        description="Sends your message as an embed!\n*cColor is optional, for colors do !help color)*",
        color=discord.Color.blue()
    )
    embed.add_field(name="Example", value="`!embed This is important!`")
    embed.add_field(name="Note", value="Use `!help color` for color options")
    await ctx.send(embed=embed)

@help.command()
async def clear(ctx):
    """Help for !clear command"""
    embed = discord.Embed(
        title="!clear [amount]",
        description="Clears specified number of messages (default: 5)",
        color=discord.Color.blue()
    )
    embed.add_field(name="Example", value="`!clear 10`")
    await ctx.send(embed=embed)

@help.command()
async def lock(ctx):
    """Help for !lock command"""
    embed = discord.Embed(
        title="!lock [channel]",
        description="Locks a channel (default: current channel)",
        color=discord.Color.blue()
    )
    embed.add_field(name="Example", value="`!lock #general`")
    await ctx.send(embed=embed)

@help.command()
async def unlock(ctx):
    """Help for !unlock command"""
    embed = discord.Embed(
        title="!unlock [channel]",
        description="Unlocks a channel (default: current channel)",
        color=discord.Color.blue()
    )
    embed.add_field(name="Example", value="`!unlock #general`")
    await ctx.send(embed=embed)

@help.command()
async def serverinfo(ctx):
    """Help for !serverinfo command"""
    embed = discord.Embed(
        title="!serverinfo",
        description="Shows server information",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)

@help.command()
async def userinfo(ctx):
    """Help for !userinfo command"""
    embed = discord.Embed(
        title="!userinfo [member]",
        description="Shows information about a user (default: yourself)",
        color=discord.Color.blue()
    )
    embed.add_field(name="Example", value="`!userinfo @User`")
    await ctx.send(embed=embed)

@help.command()
async def roleall(ctx):
    """Help for !roleall command"""
    embed = discord.Embed(
        title="!roleall <role>",
        description="Adds a role to all server members",
        color=discord.Color.blue()
    )
    embed.add_field(name="Example", value="`!roleall @Members`")
    await ctx.send(embed=embed)

@help.command()
async def giveaway(ctx):
    """Help for !giveaway command"""
    embed = discord.Embed(
        title="!giveaway <winners> <minutes> <prize>",
        description="Starts a giveaway",
        color=discord.Color.blue()
    )
    embed.add_field(name="Example", value="`!giveaway 1 60 Discord Nitro`")
    await ctx.send(embed=embed)

@help.command()
async def giveawayend(ctx):
    """Help for !giveawayend command"""
    embed = discord.Embed(
        title="!giveawayend <message_id> <winners>",
        description="Ends a giveaway early",
        color=discord.Color.blue()
    )
    embed.add_field(name="Example", value="`!giveawayend 123456789 1`")
    await ctx.send(embed=embed)

@help.command()
async def edit(ctx):
    """Help for !edit command"""
    embed = discord.Embed(
        title="!edit <message_id> <new_content>",
        description="Edits a bot's message",
        color=discord.Color.blue()
    )
    embed.add_field(name="Example", value="`!edit 123456789 New message`")
    await ctx.send(embed=embed)

@help.command()
async def dmtext(ctx):
    """Help for !dmtext command"""
    embed = discord.Embed(
        title="!dmtext",
        description="Sends a test DM to yourself",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)

@help.command()
async def dmmember(ctx):
    """Help for !dmmember command"""
    embed = discord.Embed(
        title="!dmmember <member_id> <message>",
        description="Sends a DM to a specific member",
        color=discord.Color.blue()
    )
    embed.add_field(name="Example", value="`!dmmember 123456789 Hello!`")
    await ctx.send(embed=embed)

@help.command()
async def dmall(ctx):
    """Help for !dmall command"""
    embed = discord.Embed(
        title="!dmall <message>",
        description="Sends a DM to all server members",
        color=discord.Color.blue()
    )
    embed.add_field(name="Example", value="`!dmall Important announcement!`")
    await ctx.send(embed=embed)

@help.command()
async def dmrole(ctx):
    """Help for !dmrole command"""
    embed = discord.Embed(
        title="!dmrole <role_id> <message>",
        description="Sends a DM to all members with a specific role",
        color=discord.Color.blue()
    )
    embed.add_field(name="Example", value="`!dmrole 123456789 Important update!`")
    await ctx.send(embed=embed)

@help.command()
async def dmspam(ctx):
    """Help for !dmspam command"""
    embed = discord.Embed(
        title="!dmspam <member> <amount> <message>",
        description="Spams a member with DMs (max 50)",
        color=discord.Color.blue()
    )
    embed.add_field(name="Example", value="`!dmspam @User 5 Hello!`")
    await ctx.send(embed=embed)

@help.command()
async def dmspamEmb(ctx):
    """Help for !dmspamEmb command"""
    embed = discord.Embed(
        title="!dmspamEmb <user> <color> <title> <message>",
        description="Sends an embed DM to a user",
        color=discord.Color.blue()
    )
    embed.add_field(name="Color Options", value="Use `!help color` to see options")
    embed.add_field(name="Example", value="`!dmspamEmb @User blue Important Hello!`")
    await ctx.send(embed=embed)

# --- MAIN COMMANDS ---
@bot.command()
@is_allowed_user()
async def say(ctx, *, message: str):
    await ctx.send(message)

@bot.command()
@is_allowed_user()
async def embed(ctx, color: str = None, *, message: str = "No content provided"):
    """
    Creates an embed with optional color
    Usage: !embed [color] <message>
    Example: !embed red This is important!
    """
    # Get color from input or default to blurple
    embed_color = discord.Color.blurple()  # Default color
    
    if color:
        # Check if the color is a valid option
        color = color.lower()
        color_mapping = {
            "default": discord.Color.default(),
            "teal": discord.Color.teal(),
            "dark_teal": discord.Color.dark_teal(),
            "green": discord.Color.green(),
            "dark_green": discord.Color.dark_green(),
            "blue": discord.Color.blue(),
            "dark_blue": discord.Color.dark_blue(),
            "purple": discord.Color.purple(),
            "dark_purple": discord.Color.dark_purple(),
            "magenta": discord.Color.magenta(),
            "dark_magenta": discord.Color.dark_magenta(),
            "gold": discord.Color.gold(),
            "dark_gold": discord.Color.dark_gold(),
            "orange": discord.Color.orange(),
            "dark_orange": discord.Color.dark_orange(),
            "red": discord.Color.red(),
            "dark_red": discord.Color.dark_red(),
            "lighter_grey": discord.Color.lighter_grey(),
            "darker_grey": discord.Color.darker_grey(),
            "blurple": discord.Color.blurple(),
            "greyple": discord.Color.greyple(),
            "black": discord.Color.from_rgb(0, 0, 0),
            "white": discord.Color.from_rgb(255, 255, 255),
        }
        
        # Also support hex colors (e.g., #FF0000 for red)
        if color.startswith("#") and len(color) == 7:
            try:
                embed_color = discord.Color(int(color[1:], 16))
            except:
                await ctx.send("❌ Invalid hex color format. Using default color.", delete_after=5)
        elif color in color_mapping:
            embed_color = color_mapping[color]
        else:
            await ctx.send(f"❌ Invalid color. Using default. See `!help color` for options.", delete_after=5)
            # Show color help if the color is invalid
            await ctx.invoke(bot.get_command('help'), 'color')
    
    # Create and send the embed
    embed = discord.Embed(description=message, color=embed_color)
    await ctx.send(embed=embed)

@bot.command()
@is_allowed_user()
async def clear(ctx, amount: int = 5):
    await ctx.channel.purge(limit=amount + 1)
    msg = await ctx.send(f"🧹 Cleared {amount} messages.", delete_after=3)
    await asyncio.sleep(3)
    await msg.delete()

@bot.command()
@is_allowed_user()
async def lock(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    await channel.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send(f"🔒 {channel.mention} has been locked")

@bot.command()
@is_allowed_user()
async def unlock(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    await channel.set_permissions(ctx.guild.default_role, send_messages=True)
    await ctx.send(f"🔓 {channel.mention} has been unlocked")

@bot.command()
async def serverinfo(ctx):
    guild = ctx.guild
    embed = discord.Embed(title=f"{guild.name} Info", color=discord.Color.green())
    embed.add_field(name="Owner", value=guild.owner, inline=True)
    embed.add_field(name="Members", value=guild.member_count, inline=True)
    embed.add_field(name="Created", value=guild.created_at.strftime('%Y-%m-%d'), inline=True)
    embed.add_field(name="Roles", value=len(guild.roles), inline=True)
    embed.add_field(name="Channels", value=len(guild.channels), inline=True)
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    await ctx.send(embed=embed)

@bot.command()
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author
    embed = discord.Embed(title=f"{member.name}'s Info", color=discord.Color.blue())
    embed.set_thumbnail(url=member.avatar.url if member.avatar else None)
    embed.add_field(name="ID", value=member.id, inline=False)
    embed.add_field(name="Nickname", value=member.nick or "None", inline=True)
    embed.add_field(name="Status", value=str(member.status).title(), inline=True)
    embed.add_field(name="Joined", value=member.joined_at.strftime('%Y-%m-%d %H:%M'), inline=True)
    embed.add_field(name="Created", value=member.created_at.strftime('%Y-%m-%d %H:%M'), inline=True)
    await ctx.send(embed=embed)

@bot.command()
@is_allowed_user()
async def roleall(ctx, *, role: discord.Role):
    added = 0
    for member in ctx.guild.members:
        if role not in member.roles:
            try:
                await member.add_roles(role)
                added += 1
                await asyncio.sleep(0.5)
            except:
                continue
    await ctx.send(f"✅ Added {role.mention} to {added} members")

@bot.command()
@is_allowed_user()
async def giveaway(ctx, winners: int, minutes: int, *, prize: str):
    if winners <= 0 or minutes <= 0:
        return await ctx.send("❌ Winners and minutes must be greater than 0")
    
    embed = discord.Embed(
        title="🎉 Giveaway 🎉",
        description=f"**Prize:** {prize}\n**Winners:** {winners}\n**Ends:** {discord.utils.format_dt(discord.utils.utcnow() + timedelta(minutes=minutes), 'R')}",
        color=discord.Color.gold()
    )
    embed.set_footer(text=f"Hosted by {ctx.author}")
    msg = await ctx.send(embed=embed)
    await msg.add_reaction("🎉")

    await asyncio.sleep(minutes * 60)

    refreshed_msg = await ctx.channel.fetch_message(msg.id)
    users = [user async for user in refreshed_msg.reactions[0].users() if not user.bot]

    if len(users) < winners:
        await ctx.send("❌ Not enough participants")
    else:
        winners_list = random.sample(users, winners)
        await ctx.send(f"🎊 Winners: {', '.join([winner.mention for winner in winners_list])}")

@bot.command()
@is_allowed_user()
async def giveawayend(ctx, message_id: int, winners: int):
    try:
        msg = await ctx.channel.fetch_message(message_id)
        users = [user async for user in msg.reactions[0].users() if not user.bot]

        if len(users) < winners:
            await ctx.send("❌ Not enough participants")
        else:
            winners_list = random.sample(users, winners)
            await ctx.send(f"🎊 Giveaway ended! Winners: {', '.join([winner.mention for winner in winners_list])}")
            await msg.delete()
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

@bot.command()
@is_allowed_user()
async def edit(ctx, message_id: int, *, new_content: str):
    try:
        msg = await ctx.channel.fetch_message(message_id)
        if msg.author == bot.user:
            await msg.edit(content=new_content)
            await ctx.send("✅ Message edited", delete_after=3)
        else:
            await ctx.send("❌ Can only edit bot's messages", delete_after=3)
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

# --- DM COMMANDS ---
@bot.command()
@is_allowed_user()
async def dmtext(ctx):
    """Sends a test DM to you"""
    try:
        await ctx.author.send("This is a test DM!")
        await ctx.send("✅ Test DM sent!", delete_after=3)
    except:
        await ctx.send("❌ Could not send DM", delete_after=3)

@bot.command()
@is_allowed_user()
async def dmmember(ctx, member_id: int, *, message: str):
    """DMs a specific member"""
    member = ctx.guild.get_member(member_id)
    if not member:
        return await ctx.send("❌ Member not found", delete_after=3)
    
    try:
        await member.send(message)
        await ctx.send(f"✅ DM sent to {member.display_name}", delete_after=3)
    except:
        await ctx.send(f"❌ Could not DM {member.display_name}", delete_after=3)

@bot.command()
@is_allowed_user()
async def dmall(ctx, *, message: str):
    """DMs all server members"""
    sent = 0
    failed = 0
    for member in ctx.guild.members:
        if not member.bot:
            try:
                await member.send(message)
                sent += 1
                await asyncio.sleep(1)  # Rate limiting
            except:
                failed += 1
    await ctx.send(f"✅ DMs sent: {sent} | Failed: {failed}")

@bot.command()
@is_allowed_user()
async def dmrole(ctx, role_id: int, *, message: str):
    """DMs all members with a specific role"""
    role = ctx.guild.get_role(role_id)
    if not role:
        return await ctx.send("❌ Role not found", delete_after=3)
    
    sent = 0
    failed = 0
    for member in role.members:
        if not member.bot:
            try:
                await member.send(message)
                sent += 1
                await asyncio.sleep(1)  # Rate limiting
            except:
                failed += 1
    await ctx.send(f"✅ DMs sent to {role.name}: {sent} | Failed: {failed}")

@bot.command()
@is_allowed_user()
async def dmspam(ctx, member: discord.Member, amount: int, *, message: str):
    """Spams a member with DMs"""
    if amount > 50:
        return await ctx.send("❌ Maximum 50 messages", delete_after=3)
    
    for i in range(amount):
        try:
            await member.send(f"{message} ({i+1}/{amount})")
            await asyncio.sleep(1)  # Rate limiting
        except:
            pass
    await ctx.send(f"✅ Sent {amount} DMs to {member.display_name}", delete_after=3)

@bot.command()
@is_allowed_user()
async def dmspamEmb(ctx, user: discord.Member, color: str, title: str, *, message: str):
    """Spams a member with embed DMs"""
    try:
        color = int(color.replace("#", ""), 16) if color.startswith("#") else getattr(discord.Color, color.lower(), discord.Color.blue())
    except:
        color = discord.Color.blue()
    
    embed = discord.Embed(
        title=title,
        description=message,
        color=color
    )
    
    try:
        await user.send(embed=embed)
        await ctx.send(f"✅ Embed DM sent to {user.display_name}", delete_after=3)
    except:
        await ctx.send(f"❌ Could not send embed DM", delete_after=3)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        pass
    elif isinstance(error, commands.CheckFailure):
        pass  # Already handled in is_allowed_user()
    else:
        print(f"Error: {error}")

bot.run(os.getenv("DISCORD_BOT_TOKEN"))
