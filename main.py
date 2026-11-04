"""MP Multiplayer Discord bot (3.22, runs 24/7 on MP Railway - our own self-hosted Railway).

  /gen CODE  - only in #verification: links the code shown in the game to your Discord account
  /statsdc   - your game account card (only you see it)   (3.34: renamed from /stats)
  /chardc    - the same card, character style (only you see it)   (3.34: renamed from /char)
  /forgotuser - 3.56: shows the game username of your Discord (only you see it)
  /resetpass  - 3.56: a form to set a new game password (logs out your phones)

Settings are environment variables, never put them in the code or in git:
  DISCORD_TOKEN     the bot token (Discord Developer Portal -> Bot -> Reset Token)
  AUTH_PRIVATE_KEY  the login system key (64 hex characters, matches the public key in the mod)
  DATA_DIR          optional, default /data (Docker) or ./data; accounts.db lives here
  VERIFY_CHANNEL    optional, default "verification"
  MP_RAILWAY_APP    set by MP Railway: app name (status beacon topic)
  MP_RAILWAY_COMMIT set by MP Railway: deployed git commit
  MP_RAILWAY_HOST   optional: name shown on the website's Railway page (default "MP Railway")

On MP Railway:   sudo mp-railway setup        (asks for the two keys, deploys, starts, 24/7)
"""
import asyncio
import datetime
import json
import logging
import os
import platform
import time

import discord
from discord import app_commands
import paho.mqtt.client as mqtt

from authcore import AuthCore, TOPIC_REQ, TOPIC_RES

VERSION = "4.03"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mpbot")

VERIFY_CHANNEL = os.environ.get("VERIFY_CHANNEL", "verification").lstrip("#").lower()
DATA_DIR = os.environ.get("DATA_DIR") or ("/data" if os.path.isdir("/data") else os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
BROKERS = [("broker.hivemq.com", 1883), ("test.mosquitto.org", 1883), ("broker.emqx.io", 1883)]
APP = os.environ.get("MP_RAILWAY_APP", "discordpy-bot")
COMMIT = (os.environ.get("MP_RAILWAY_COMMIT") or os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "")[:7]
HOST_LABEL = os.environ.get("MP_RAILWAY_HOST", "MP Railway")
STATUS_TOPIC = f"wagu/railway/{APP}/status"     # retained; the website's Railway page reads it
STARTED = int(time.time())

core = AuthCore(os.environ.get("AUTH_PRIVATE_KEY", ""), os.path.join(DATA_DIR, "accounts.db"))
if not core.ready:
    log.warning("AUTH_PRIVATE_KEY is not set: /gen and game logins are off until you add it (sudo mp-railway env set AUTH_PRIVATE_KEY)")
else:
    log.info("login system ready, public key %s...", core.public_hex()[:16])


# ------------------------------------------------------------------ MQTT (phones <-> bot)
class Bridge:
    def __init__(self):
        self.clients = []

    def start(self):
        offline = json.dumps({"app": APP, "online": False, "ver": VERSION})
        for i, (host, port) in enumerate(BROKERS):
            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"mpbot-{os.getpid()}-{i}", clean_session=True)
            c.user_data_set(i)
            c.on_connect = self.on_connect
            c.on_message = self.on_message
            c.reconnect_delay_set(1, 30)
            c.will_set(STATUS_TOPIC, offline, qos=1, retain=True)   # broker marks us offline if we vanish
            try:
                c.connect_async(host, port, keepalive=30)
                c.loop_start()
            except Exception as e:
                log.warning("broker %s: %s", host, e)
            self.clients.append(c)

    def on_connect(self, c, idx, flags, rc, props=None):
        log.info("broker %s connected (%s)", BROKERS[idx][0], rc)
        c.subscribe(TOPIC_REQ, qos=0)

    def on_message(self, c, idx, msg):
        try:
            r = core.handle_frame(msg.payload, idx)
        except Exception:
            log.exception("request failed")
            return
        if r:
            sid, frame = r
            c.publish(TOPIC_RES + sid, frame, qos=0)

    def push(self, sid, frame):
        # on every broker: the phone may have switched broker while you typed /gen
        for c in self.clients:
            c.publish(TOPIC_RES + sid, frame, qos=0)

    def connected(self):
        return sum(1 for c in self.clients if c.is_connected())

    def publish_status(self, doc):
        text = json.dumps(doc, separators=(",", ":"))
        if core.ready:   # signed: the website checks it with the mod's public key (nobody can fake "online")
            text = json.dumps({"s": text, "sig": core.sign_status(text)}, separators=(",", ":"))
        for c in self.clients:
            if c.is_connected():
                c.publish(STATUS_TOPIC, text, qos=1, retain=True)

    def stop(self):
        offline = json.dumps({"app": APP, "online": False, "ver": VERSION, "ts": int(time.time())})
        for c in self.clients:
            try:
                c.publish(STATUS_TOPIC, offline, qos=1, retain=True).wait_for_publish(2)
                c.disconnect()
            except Exception:
                pass


bridge = Bridge()


# ------------------------------------------------------------------ Discord
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
synced = {"cmds": [], "guilds": 0, "at": 0}


def in_verify_channel(inter: discord.Interaction) -> bool:
    ch = inter.channel
    name = getattr(ch, "name", "") or ""
    return name.lower().lstrip("#") == VERIFY_CHANNEL or name.lower().endswith(VERIFY_CHANNEL)


@tree.command(name="gen", description="Verify your game login with the code shown in MP Multiplayer")
@app_commands.describe(code="The code from the game screen (8 characters)")
async def gen_cmd(inter: discord.Interaction, code: str):
    if not in_verify_channel(inter):
        await inter.response.send_message(f"Use /gen in the #{VERIFY_CHANNEL} channel.", ephemeral=True)
        return
    if not core.ready:
        await inter.response.send_message("The login system is starting up (no key yet). Try again in a minute.", ephemeral=True)
        return
    text, pushes = await asyncio.to_thread(core.gen, inter.user.id, str(inter.user), code)
    for sid, frame in pushes:
        bridge.push(sid, frame)
    await inter.response.send_message(text, ephemeral=True)   # only you see it: the code stays private


def _ts(t):
    return f"<t:{int(t)}:f>" if t else "-"


def _ago(t):
    return f"<t:{int(t)}:R>" if t else "never"


def account_card(user: discord.abc.User, a: dict, style: str) -> discord.Embed:
    """The account UI: one card, two looks (/statsdc = account, /chardc = character)."""
    if style == "char":
        e = discord.Embed(title=a["user"], description=f"**MP Multiplayer character**\nLinked to {user.mention}", color=0x111111)
        e.add_field(name="Gender", value=a["gender"])
        e.add_field(name="Age", value=str(a["age"]))
        e.add_field(name="Logins", value=str(a["logins"]))
        e.add_field(name="Last seen", value=_ago(a["last_login"]) + (f"\non **{a['last_server']}**" if a["last_server"] else ""), inline=False)
        e.add_field(name="Since", value=_ts(a["created"]), inline=False)
    else:
        e = discord.Embed(title=f"MP account: {a['user']}", description="Your MP Multiplayer login (only you see this).", color=0xD7263D)
        e.add_field(name="User", value=a["user"])
        e.add_field(name="Discord", value=a["discord_name"])
        e.add_field(name="Gender", value=a["gender"])
        e.add_field(name="Age", value=str(a["age"]))
        e.add_field(name="Logins", value=str(a["logins"]))
        e.add_field(name="Created", value=_ts(a["created"]))
        e.add_field(name="Last login", value=_ts(a["last_login"]) + (f"\n{a['last_server']}" if a["last_server"] else ""), inline=False)
    e.set_thumbnail(url=user.display_avatar.url)
    e.set_footer(text=f"MP bot {VERSION} · MP Railway")
    return e


class CardView(discord.ui.View):
    def __init__(self, owner_id: int, style: str):
        super().__init__(timeout=600)
        self.owner_id, self.style = owner_id, style

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary)
    async def refresh(self, inter: discord.Interaction, button: discord.ui.Button):
        if inter.user.id != self.owner_id:
            await inter.response.send_message("Use /statsdc yourself to see your own account.", ephemeral=True)
            return
        a = await asyncio.to_thread(core.account_by_discord, inter.user.id)
        if not a:
            await inter.response.edit_message(content="No game account any more.", embed=None, view=None)
            return
        await inter.response.edit_message(embed=account_card(inter.user, a, self.style), view=self)

    @discord.ui.button(label="Switch view", style=discord.ButtonStyle.primary)
    async def switch(self, inter: discord.Interaction, button: discord.ui.Button):
        if inter.user.id != self.owner_id:
            await inter.response.send_message("Use /statsdc yourself to see your own account.", ephemeral=True)
            return
        self.style = "stats" if self.style == "char" else "char"
        a = await asyncio.to_thread(core.account_by_discord, inter.user.id)
        if not a:
            await inter.response.edit_message(content="No game account any more.", embed=None, view=None)
            return
        await inter.response.edit_message(embed=account_card(inter.user, a, self.style), view=self)


async def show_card(inter: discord.Interaction, style: str):
    a = await asyncio.to_thread(core.account_by_discord, inter.user.id)
    if not a:
        e = discord.Embed(title="No MP account yet",
                          description=f"1. Join a server in MP Multiplayer: a code appears.\n2. Type `/gen CODE` in #{VERIFY_CHANNEL}.\n3. Sign up in the game.",
                          color=0x555555)
        e.set_footer(text=f"MP bot {VERSION} · MP Railway")
        await inter.response.send_message(embed=e, ephemeral=True)
        return
    await inter.response.send_message(embed=account_card(inter.user, a, style), view=CardView(inter.user.id, style), ephemeral=True)


@tree.command(name="statsdc", description="Your MP Multiplayer account (only you see it)")
async def stats_cmd(inter: discord.Interaction):
    await show_card(inter, "stats")


@tree.command(name="chardc", description="Your MP Multiplayer character card (only you see it)")
async def char_cmd(inter: discord.Interaction):
    await show_card(inter, "char")


@tree.command(name="forgotuser", description="Forgot your MP Multiplayer username? Shows it (only you see it)")
async def forgotuser_cmd(inter: discord.Interaction):
    al = await asyncio.to_thread(core.accounts_by_discord, inter.user.id)
    if not al:
        await inter.response.send_message("This Discord has no game account yet. In the game: Login screen > New account (Discord code).", ephemeral=True)
        return
    names = ", ".join(f"**{a['user']}**" for a in al)
    word = "username is" if len(al) == 1 else f"usernames ({len(al)}/3) are"
    await inter.response.send_message(f"Your MP Multiplayer {word} {names}. Forgot the password too? Use /resetpass.", ephemeral=True)


class ResetPassModal(discord.ui.Modal, title="MP Multiplayer - new password"):
    user = discord.ui.TextInput(label="Username (needed when you have 2-3 accounts)", required=False, max_length=20)
    pw = discord.ui.TextInput(label="New password (6-32)", min_length=6, max_length=32)
    pw2 = discord.ui.TextInput(label="Confirm new password", min_length=6, max_length=32)

    async def on_submit(self, inter: discord.Interaction):
        if self.pw.value != self.pw2.value:
            await inter.response.send_message("The passwords do not match. Try /resetpass again.", ephemeral=True)
            return
        ok, msg = await asyncio.to_thread(core.reset_by_discord, inter.user.id, self.pw.value, self.user.value or "")
        if ok:
            msg = f"Password changed for **{msg}**. Log in with it in the game (your phones were logged out)."
        await inter.response.send_message(msg, ephemeral=True)


@tree.command(name="resetpass", description="Forgot your MP Multiplayer password? Set a new one (only you see it)")
async def resetpass_cmd(inter: discord.Interaction):
    a = await asyncio.to_thread(core.account_by_discord, inter.user.id)
    if not a:
        await inter.response.send_message("This Discord has no game account yet. In the game: Login screen > New account (Discord code).", ephemeral=True)
        return
    await inter.response.send_modal(ResetPassModal())


async def _sync_guild(g):
    try:
        tree.copy_global_to(guild=g)
        cmds = await tree.sync(guild=g)
        names = ["/" + c.name for c in cmds]
        synced["cmds"] = names
        log.info("Slash commands in %s: %s", g, ", ".join(names))
    except discord.Forbidden:
        log.warning("No slash commands in %s: re-invite the bot WITH the applications.commands scope (link above)", g)
    except Exception as e:
        log.warning("sync %s: %s", g, e)


@client.event
async def on_ready():
    log.info("Logged in as %s, in %d server(s) - MP bot %s %s", client.user, len(client.guilds), VERSION, COMMIT)
    log.info("Invite link (bot + slash commands): https://discord.com/oauth2/authorize?client_id=%s&scope=bot+applications.commands&permissions=277025392640", client.user.id)
    for g in client.guilds:   # guild sync: the commands show up at once
        await _sync_guild(g)
    synced["guilds"], synced["at"] = len(client.guilds), int(time.time())
    try:
        if os.environ.get("GLOBAL_SYNC", "0") == "1":
            await tree.sync()   # global copy too (each command then shows twice in these servers)
        elif await tree.fetch_commands():
            # 3.21.6 also synced globally, so every command showed twice: drop the global copies
            # (the per-server copies above stay; the tree itself is not touched)
            await client.http.bulk_upsert_global_commands(client.application_id, [])
            log.info("removed the old global command copies (no more double /gen)")
    except Exception as e:
        log.warning("global commands: %s", e)
    if not getattr(client, "_beacon", None):
        client._beacon = asyncio.create_task(beacon())
    if not getattr(client, "_repush", None):
        client._repush = asyncio.create_task(repush_loop())
    if not getattr(client, "_avatars", None):
        client._avatars = asyncio.create_task(avatar_loop())


@client.event
async def on_guild_join(g):
    log.info("Joined %s", g)
    await _sync_guild(g)


async def repush_loop():
    """3.21.7: keeps sending "verified" to a phone that was in the background during /gen."""
    while True:
        try:
            for sid, frame in await asyncio.to_thread(core.repush):
                bridge.push(sid, frame)
        except Exception as e:
            log.warning("repush: %s", e)
        await asyncio.sleep(3)


async def fetch_avatar_png(discord_id):
    """3.24: the Discord profile picture as a 64 px PNG (animated ones: the first frame)."""
    user = client.get_user(int(discord_id)) or await client.fetch_user(int(discord_id))
    asset = user.display_avatar
    try:
        asset = asset.replace(size=64, static_format="png", format="png")
    except Exception:
        try:
            asset = asset.with_static_format("png").with_size(64)
        except Exception:
            pass                              # default avatars: already a small PNG
    data = await asset.read()
    return data if data[:4] == b"\x89PNG" and len(data) < 96 * 1024 else None


async def avatar_loop():
    """3.24: the launcher asks for its profile picture; fetch it from Discord and push it to the phone."""
    while True:
        try:
            for sid, did, dname in await asyncio.to_thread(core.take_avatar_jobs):
                png = None
                try:
                    png = await fetch_avatar_png(did)
                except Exception as e:
                    log.warning("avatar %s: %s", did, e)
                frame = await asyncio.to_thread(core.avatar_done, sid, did, dname, png)
                if frame:
                    bridge.push(sid, frame)
        except Exception as e:
            log.warning("avatar loop: %s", e)
        await asyncio.sleep(1)


async def beacon():
    """Every 30 s: a signed, retained status message for the website (MP Railway page)."""
    while True:
        try:
            doc = {
                "app": APP, "online": client.is_ready(), "ver": VERSION, "commit": COMMIT, "host": HOST_LABEL,
                "bot": str(client.user) if client.user else "", "guilds": len(client.guilds),
                "cmds": synced["cmds"] or ["/gen", "/statsdc", "/chardc", "/forgotuser", "/resetpass"], "login": core.ready,
                "accounts": await asyncio.to_thread(core.account_count), "brokers": bridge.connected(),
                "ping": round(client.latency * 1000) if client.latency == client.latency else -1,
                "started": STARTED, "ts": int(time.time()), "py": platform.python_version(),
            }
            bridge.publish_status(doc)
        except Exception as e:
            log.warning("status beacon: %s", e)
        await asyncio.sleep(30)


if __name__ == "__main__":
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_TOKEN is not set (on MP Railway: sudo mp-railway env set DISCORD_TOKEN)")
    bridge.start()
    try:
        client.run(token, log_handler=None)
    finally:
        bridge.stop()
