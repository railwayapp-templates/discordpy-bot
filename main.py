"""MP Multiplayer Discord bot (3.22, runs 24/7 on MP Railway - our own self-hosted Railway).

  /gen CODE  - only in #verification: links the code shown in the game to your Discord account
  /stats     - your game account card (only you see it)   (4.13.15: back to /stats, was /statsdc)
  /help      - 4.13.15: tutorial, how to install and use MP (replaces /chardc; the character look is /stats > Switch view)
  /forgotuser - 3.56: shows the game username of your Discord (only you see it)
  /resetpass  - 3.56: a form to set a new game password (logs out your phones)
  /streaming on|off - 4.13.16: (server managers) the bot joins a voice channel and plays the YouTube live 24/7
  /changelog  - 4.13.20: (server managers) posts the mod release changelog (wagu docs/discord/changelog.md) with @everyone

Settings are environment variables, never put them in the code or in git:
  DISCORD_TOKEN     the bot token (Discord Developer Portal -> Bot -> Reset Token)
  AUTH_PRIVATE_KEY  the login system key (64 hex characters, matches the public key in the mod)
  DATA_DIR          optional, default /data (Docker) or ./data; accounts.db lives here
  VERIFY_CHANNEL    optional, default "verification"
  MP_RAILWAY_APP    set by MP Railway: app name (status beacon topic)
  MP_RAILWAY_COMMIT set by MP Railway: deployed git commit
  MP_RAILWAY_HOST   optional: name shown on the website's Railway page (default "MP Railway")
  VOICE_STREAM_URL  optional: the YouTube live /streaming plays (default the MP live below)
  YT_COOKIES        optional: path to a cookies.txt when YouTube asks the server to "sign in"

On MP Railway:   sudo mp-railway setup        (asks for the two keys, deploys, starts, 24/7)
"""
import asyncio
import datetime
import json
import logging
import os
import platform
import re
import time
import urllib.request

import discord
from discord import app_commands
import paho.mqtt.client as mqtt

from authcore import AuthCore, TOPIC_REQ, TOPIC_RES

VERSION = "4.13.20"
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

    def stop(self, why=""):
        doc = {"app": APP, "online": False, "ver": VERSION, "ts": int(time.time())}
        if why:
            doc["why"] = why   # 4.12.3: the website shows it (e.g. the token was reset)
        offline = json.dumps(doc)
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
    """The account UI: one card, two looks (/stats = account, Switch view = character)."""
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
            await inter.response.send_message("Use /stats yourself to see your own account.", ephemeral=True)
            return
        a = await asyncio.to_thread(core.account_by_discord, inter.user.id)
        if not a:
            await inter.response.edit_message(content="No game account any more.", embed=None, view=None)
            return
        await inter.response.edit_message(embed=account_card(inter.user, a, self.style), view=self)

    @discord.ui.button(label="Switch view", style=discord.ButtonStyle.primary)
    async def switch(self, inter: discord.Interaction, button: discord.ui.Button):
        if inter.user.id != self.owner_id:
            await inter.response.send_message("Use /stats yourself to see your own account.", ephemeral=True)
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


@tree.command(name="stats", description="Your MP Multiplayer account (only you see it)")
async def stats_cmd(inter: discord.Interaction):
    await show_card(inter, "stats")


# 4.13.15: /chardc is gone (the character look is still the "Switch view" button of /stats).
# /help is the tutorial: how to install MP, link your account, play, and the commands - page buttons, only you see it.
HELP_PAGES = [
    ("1/5 - Install MP Multiplayer",
     "1. GTA SA 2.00 (Android) with **AML 1.4.0**.\n"
     "2. Download MP from **https://mpsamp-open.github.io** (or the newest release on GitHub: ThirtyFoxMCx00E1/wagu).\n"
     "3. Copy `libMP64.so` (64-bit game) or `libMP32.so` (32-bit game) to\n`Android/data/com.rockstargames.gtasa/mods/`\n"
     "4. Copy the `MP` folder to `Android/data/com.rockstargames.gtasa/files/TYFMC/MP/`\n"
     "5. Start the game and tap the **MP** bubble on the right edge of the screen."),
    ("2/5 - Your MP account (login)",
     "Servers with the login system on ask you to log in:\n"
     "1. Join the server: the game shows an **8-character code** (new every time).\n"
     f"2. Type `/gen CODE` in **#{VERIFY_CHANNEL}** (only works there, only you see the answer).\n"
     "3. In the game: **Sign up** (user, password, gender, age) -> Create. Next time: just Login.\n"
     "Up to 3 accounts per Discord. The default server has the login off unless an [ADMIN] / [MOD] turns it on."),
    ("3/5 - Playing",
     "- **Default server**: tap *Connect* - everybody on the same Wi-Fi / hotspot or the internet lobby meets there.\n"
     "- **Custom server**: *Host your own server*, pick a name + port (1923+), turn on *Host server*. Others tap **Join**.\n"
     "- **Mission sync**: player list > Mission sync - your group sees each other on missions.\n"
     "- **Co-op story (2 players)**: player list > Co-op story or `/coop invite <id>` - play the host's story together.\n"
     "- **Map editor** (owner of a custom server): `/mapedit` - add, move, turn and delete objects."),
    ("4/5 - Discord commands",
     f"`/gen CODE` - link the game's code to your Discord (in #{VERIFY_CHANNEL})\n"
     "`/stats` - your account card (Refresh / Switch view = character look)\n"
     "`/forgotuser` - shows your game username(s)\n"
     "`/resetpass` - set a new game password (logs out your phones)\n"
     "`/help` - this tutorial\n"
     "`/streaming on` / `off` - (server managers) 24/7 YouTube live in a voice channel: sound by the bot, video with the Watch video button\n"
     "In the game: `/stats`, `/char`, `/coop help`, `/mapedit help`."),
    ("5/5 - Problems?",
     "- **No code / can't log in**: check Wi-Fi or mobile data; the login needs the internet.\n"
     "- **Code not accepted**: it changes every join - use the newest one, in the right channel.\n"
     "- **Forgot username / password**: `/forgotuser`, `/resetpass` (or in the game: Login screen > Forgot...).\n"
     "- **Black loading screen / freeze on join**: update to the newest MP (4.13.15+).\n"
     "- Still stuck? Ask in the server with a screenshot."),
]


def help_embed(i: int) -> discord.Embed:
    t, d = HELP_PAGES[i]
    e = discord.Embed(title=f"MP Multiplayer tutorial - {t}", description=d, color=0xD7263D)
    e.set_footer(text=f"MP bot {VERSION} · only you see this")
    return e


class HelpView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=900)
        self.owner_id, self.page = owner_id, 0
        self._fix()

    def _fix(self):
        self.prev.disabled = self.page == 0
        self.next.disabled = self.page == len(HELP_PAGES) - 1

    async def _go(self, inter: discord.Interaction, d: int):
        if inter.user.id != self.owner_id:
            await inter.response.send_message("Use /help yourself to open your own tutorial.", ephemeral=True)
            return
        self.page = max(0, min(len(HELP_PAGES) - 1, self.page + d))
        self._fix()
        await inter.response.edit_message(embed=help_embed(self.page), view=self)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def prev(self, inter: discord.Interaction, button: discord.ui.Button):
        await self._go(inter, -1)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next(self, inter: discord.Interaction, button: discord.ui.Button):
        await self._go(inter, 1)


@tree.command(name="help", description="Tutorial: how to install and use MP Multiplayer (only you see it)")
async def help_cmd(inter: discord.Interaction):
    await inter.response.send_message(embed=help_embed(0), view=HelpView(inter.user.id), ephemeral=True)


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


# ------------------------------------------------------------------ 4.13.16: /streaming (24/7 YouTube live in a voice channel)
# Discord bots can not "Go Live" (screen share video), so the bot joins the voice channel and plays the live's
# sound 24/7, and posts a "Watch video" button (Watch Together activity) that shows the video in the voice channel.
# On: remembered in DATA_DIR/voice_stream.json, so after a redeploy / restart / disconnect the bot comes back by itself.
# Needs ffmpeg on the server (MP Railway installs it), yt-dlp + deno (requirements.txt).
VOICE_STREAM_URL = os.environ.get("VOICE_STREAM_URL", "https://www.youtube.com/live/rFZHOHl-L8A").strip()
YT_COOKIES = os.environ.get("YT_COOKIES", "").strip() or os.path.join(DATA_DIR, "yt_cookies.txt")
FFMPEG_BEFORE = "-reconnect 1 -reconnect_streamed 1 -reconnect_on_network_error 1 -reconnect_delay_max 10 -rw_timeout 15000000"


def _yt_resolve(url):
    """The live's audio address (expires after a few hours; ffmpeg ends then and we resolve again)."""
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "format": "bestaudio/best",
            "live_from_start": False, "socket_timeout": 20}
    if os.path.isfile(YT_COOKIES):
        opts["cookiefile"] = YT_COOKIES
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=False)
    if "entries" in info:
        info = next(e for e in info["entries"] if e)
    return info["url"], (info.get("title") or "MP live")[:80], info.get("http_headers") or {}


class VoiceStream:
    def __init__(self):
        self.file = os.path.join(DATA_DIR, "voice_stream.json")
        try:
            self.state = {int(k): v for k, v in json.load(open(self.file)).items()}
        except Exception:
            self.state = {}                      # guild id -> {"ch": channel id, "url": link}
        self.tasks, self.info = {}, {}

    def save(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(self.file + ".tmp", "w") as f:
                json.dump({str(k): v for k, v in self.state.items()}, f)
            os.replace(self.file + ".tmp", self.file)
        except Exception as e:
            log.warning("voice stream save: %s", e)

    def resume(self):
        for gid in list(self.state):
            self.start(gid)

    def start(self, gid):
        t = self.tasks.get(gid)
        if t and not t.done():
            t.cancel()
        self.tasks[gid] = asyncio.create_task(self.loop(gid))

    async def stop(self, guild):
        self.state.pop(guild.id, None)
        self.save()
        t = self.tasks.pop(guild.id, None)
        if t:
            t.cancel()
        vc = guild.voice_client
        if vc:
            await self.set_status(vc.channel, None)
            await vc.disconnect(force=True)

    async def set_status(self, ch, text):
        try:
            if isinstance(ch, discord.VoiceChannel):
                await ch.edit(status=text)
        except Exception:
            pass                                 # needs "Set Voice Channel Status"; only cosmetic

    async def loop(self, gid):
        fails = 0
        while gid in self.state:
            try:
                st = self.state[gid]
                g = client.get_guild(gid)
                ch = g and g.get_channel(st["ch"])
                if not ch:
                    await asyncio.sleep(30)
                    continue
                vc = g.voice_client
                if not vc or not vc.is_connected():
                    if vc:
                        await vc.disconnect(force=True)
                    vc = await ch.connect(timeout=30, reconnect=True, self_deaf=True)
                elif vc.channel.id != ch.id:
                    await vc.move_to(ch)
                if not vc.is_playing():
                    src, title, hdr = await asyncio.to_thread(_yt_resolve, st["url"])
                    before = FFMPEG_BEFORE
                    if hdr.get("User-Agent"):
                        before += ' -user_agent "%s"' % hdr["User-Agent"].replace('"', "")
                    done = asyncio.Event()
                    loop = asyncio.get_running_loop()
                    audio = discord.FFmpegOpusAudio(src, before_options=before, options="-vn -loglevel error")
                    vc.play(audio, after=lambda e: (e and log.warning("voice stream ended: %s", e), loop.call_soon_threadsafe(done.set)))
                    self.info[gid] = {"title": title, "since": int(time.time())}
                    await self.set_status(ch, ("LIVE 24/7: " + title)[:500])
                    log.info("voice stream on in %s / %s: %s", g, ch, title)
                    fails = 0
                    while vc.is_connected() and gid in self.state and not done.is_set():
                        try:
                            await asyncio.wait_for(done.wait(), 20)
                        except asyncio.TimeoutError:
                            pass
                await asyncio.sleep(3)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                fails += 1
                self.info[gid] = {"error": str(e)[:300], "at": int(time.time())}
                log.warning("voice stream %s (try %d): %s", gid, fails, e)
                await asyncio.sleep(min(300, 10 * fails))


vstream = VoiceStream()

# 4.13.16b: Discord blocks video / Go Live for bot accounts, so the video part is Discord's own
# Watch Together activity: an invite that opens the YouTube player INSIDE the voice channel for everybody who taps it.
WATCH_TOGETHER_ID = 880218394199220334


async def post_watch_panel(ch, url):
    try:
        inv = await ch.create_invite(max_age=0, max_uses=0, unique=False, reason="/streaming 24/7",
                                     target_type=discord.InviteTarget.embedded_application,
                                     target_application_id=WATCH_TOGETHER_ID)
    except Exception as e:
        log.warning("watch together invite: %s", e)
        inv = None
    title = vstream.info.get(ch.guild.id, {}).get("title") or "MP 24/7 live"
    e = discord.Embed(title="LIVE 24/7 - " + title[:200], url=url, color=0xFF0000,
                      description="**Sound**: the bot is playing it in this voice channel now - just join.\n"
                                  "**Video**: tap **Watch video** - Discord opens Watch Together in this voice channel, "
                                  "paste the link below in its search and press play; everybody in the activity sees it together.\n"
                                  f"`{url}`")
    e.set_footer(text=f"MP bot {VERSION} · /streaming")
    v = discord.ui.View(timeout=None)
    if inv:
        v.add_item(discord.ui.Button(label="Watch video (in voice)", style=discord.ButtonStyle.link, url=inv.url))
    v.add_item(discord.ui.Button(label="Open on YouTube", style=discord.ButtonStyle.link, url=url))
    try:
        await ch.send(embed=e, view=v)
        return True
    except Exception as ex:
        log.warning("watch panel: %s", ex)
        return False


CHANGELOG_URL = os.environ.get("CHANGELOG_URL", "https://raw.githubusercontent.com/ThirtyFoxMCx00E1/wagu/main/docs/discord/changelog.md")


def _fetch_changelog() -> str:
    req = urllib.request.Request(CHANGELOG_URL + "?t=" + str(int(time.time())), headers={"User-Agent": "mpbot", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8").strip()


# 4.13.20: mod release changelog post. The text lives in wagu docs/discord/changelog.md (edit it with each
# release); link: swaps the download link (e.g. a modsfire link), preview: shows it only to you first.
@tree.command(name="changelog", description="Post the MP mod release changelog with @everyone (server managers)")
@app_commands.describe(channel="where to post it (default: this channel)", link="download link to use instead of the GitHub one",
                       preview="only show it to you, don't post")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def changelog_cmd(inter: discord.Interaction, channel: discord.TextChannel | None = None,
                        link: str | None = None, preview: bool = False):
    if not inter.user.guild_permissions.manage_guild:
        await inter.response.send_message("Only server managers can post the changelog.", ephemeral=True)
        return
    await inter.response.defer(ephemeral=True)
    try:
        text = await asyncio.to_thread(_fetch_changelog)
    except Exception as ex:
        await inter.followup.send(f"Couldn't load the changelog: `{str(ex)[:180]}`", ephemeral=True)
        return
    if link:
        link = link.strip().strip("<>")
        if not link.startswith(("http://", "https://")):
            await inter.followup.send("The link has to start with https://", ephemeral=True)
            return
        links = list(re.finditer(r"\]\((https?://[^)\s]+)\)", text))
        if links:
            m = links[-1]
            text = text[:m.start(1)] + link + text[m.end(1):]
        else:
            text += "\n\n" + link
    if len(text) > 2000:
        text = text[:1997] + "..."
    if preview:
        await inter.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        return
    ch = channel or inter.channel
    perms = ch.permissions_for(inter.guild.me)
    if not perms.send_messages:
        await inter.followup.send(f"I can't send messages in {ch.mention}.", ephemeral=True)
        return
    if "@everyone" in text and not perms.mention_everyone:
        await inter.followup.send(f"Posting without the ping: give me **Mention @everyone** in {ch.mention} for it to ping.", ephemeral=True)
    try:
        await ch.send(text, allowed_mentions=discord.AllowedMentions(everyone=True, roles=False, users=False))
    except discord.HTTPException as ex:
        await inter.followup.send(f"Discord refused the post: `{str(ex)[:180]}`", ephemeral=True)
        return
    await inter.followup.send(f"Changelog posted in {ch.mention}.", ephemeral=True)


@tree.command(name="streaming", description="Play the MP YouTube live 24/7 in a voice channel (server managers)")
@app_commands.describe(mode="on = start 24/7, off = stop, status = what is playing, watch = post the video panel",
                       channel="voice channel (default: the one you are in)", link="another YouTube live link (optional)")
@app_commands.choices(mode=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off"),
                            app_commands.Choice(name="status", value="status"),
                            app_commands.Choice(name="watch (post the video panel again)", value="watch")])
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def streaming_cmd(inter: discord.Interaction, mode: app_commands.Choice[str],
                        channel: discord.VoiceChannel | None = None, link: str | None = None):
    g = inter.guild
    if not inter.user.guild_permissions.manage_guild:
        await inter.response.send_message("Only server managers can turn the 24/7 stream on or off.", ephemeral=True)
        return
    if mode.value == "off":
        await inter.response.defer(ephemeral=True)
        await vstream.stop(g)
        await inter.followup.send("24/7 stream **off** - the bot left the voice channel.", ephemeral=True)
        return
    if mode.value == "status":
        st, info = vstream.state.get(g.id), vstream.info.get(g.id, {})
        if not st:
            await inter.response.send_message("24/7 stream is **off**. Turn it on: `/streaming on` (in a voice channel).", ephemeral=True)
            return
        ch = g.get_channel(st["ch"])
        msg = f"24/7 stream **on** in {ch.mention if ch else 'a deleted channel'}\n{st['url']}"
        if info.get("title"):
            msg += f"\nPlaying: **{info['title']}** since <t:{info['since']}:R>"
        if info.get("error"):
            msg += f"\nLast problem: `{info['error'][:180]}` (it keeps trying)"
            if "sign in" in info["error"].lower():
                msg += "\nYouTube wants a login from the server: put a cookies.txt at `" + YT_COOKIES + "`."
        await inter.response.send_message(msg, ephemeral=True)
        return
    if mode.value == "watch":
        st = vstream.state.get(g.id)
        ch = channel or (g.get_channel(st["ch"]) if st else None) or (inter.user.voice.channel if inter.user.voice else None)
        if not ch:
            await inter.response.send_message("Join a voice channel first, or pick one with `channel:`.", ephemeral=True)
            return
        await inter.response.defer(ephemeral=True)
        ok = await post_watch_panel(ch, (link or "").strip() or (st or {}).get("url") or VOICE_STREAM_URL)
        await inter.followup.send("Watch video panel posted in " + ch.mention if ok else "I need Send Messages + Create Invite in " + ch.mention, ephemeral=True)
        return
    ch = channel or (inter.user.voice.channel if inter.user.voice else None)
    if not ch:
        await inter.response.send_message("Join a voice channel first, or pick one: `/streaming on channel:#voice`.", ephemeral=True)
        return
    perms = ch.permissions_for(g.me)
    if not (perms.connect and perms.speak):
        await inter.response.send_message(f"I need **Connect** and **Speak** in {ch.mention}.", ephemeral=True)
        return
    url = (link or "").strip() or vstream.state.get(g.id, {}).get("url") or VOICE_STREAM_URL
    if not (url.startswith("https://") and ("youtube.com/" in url or "youtu.be/" in url)):
        await inter.response.send_message("The link must be a YouTube link (https://www.youtube.com/live/...).", ephemeral=True)
        return
    vstream.state[g.id] = {"ch": ch.id, "url": url, "by": inter.user.id}
    vstream.save()
    if g.voice_client and g.voice_client.is_playing() and link:
        g.voice_client.stop()                    # new link: the loop starts it
    vstream.start(g.id)
    await inter.response.defer(ephemeral=True)
    posted = await post_watch_panel(ch, url)
    await inter.followup.send(
        f"24/7 stream **on** in {ch.mention}: {url}\nThe bot plays the live's sound there 24/7 (back by itself after restarts). "
        + ("The **Watch video** panel is posted in the voice channel's chat: one tap opens the video inside the voice channel (Watch Together). "
           if posted else "Could not post the Watch video panel (I need Send Messages + Create Invite in that channel). ")
        + "Stop it with `/streaming off`.", ephemeral=True)


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
    log.info("Invite link (bot + slash commands): https://discord.com/oauth2/authorize?client_id=%s&scope=bot+applications.commands&permissions=281752005249025", client.user.id)
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
    vstream.resume()
    if not getattr(client, "_stream", None) and STREAM_URL:
        client._stream = asyncio.create_task(stream_loop())


# 4.12.2: 24/7 "Streaming" status (YouTube) in this same bot - no second process on the same token.
# STREAM_URL (YouTube / Twitch link, "off" = no status), STATUS_TEXTS (titles split by |), STATUS_SECONDS.
STREAM_URL = os.environ.get("STREAM_URL", "https://www.youtube.com/live/rFZHOHl-L8A").strip()
if STREAM_URL.lower() in ("", "off", "0", "none"):
    STREAM_URL = ""
STATUS_TEXTS = [t.strip() for t in os.environ.get(
    "STATUS_TEXTS", "Watch on YouTube|Subscribe on YouTube|Join discord.gg/tbsDknk34y|Playing MP - GTA SA Multiplayer").split("|") if t.strip()] or ["Live on YouTube"]
try:
    STATUS_SECONDS = max(15, int(os.environ.get("STATUS_SECONDS", "30") or 30))
except ValueError:
    STATUS_SECONDS = 30


async def stream_loop():
    log.info("streaming status on: %s (%d titles, every %d s)", STREAM_URL, len(STATUS_TEXTS), STATUS_SECONDS)
    i = 0
    while True:
        try:
            if client.is_ready():
                await client.change_presence(status=discord.Status.online,
                                             activity=discord.Streaming(name=STATUS_TEXTS[i % len(STATUS_TEXTS)], url=STREAM_URL))
                i += 1
        except Exception as e:
            log.warning("streaming status: %s", e)
        await asyncio.sleep(STATUS_SECONDS)


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
                "cmds": synced["cmds"] or ["/gen", "/stats", "/help", "/forgotuser", "/resetpass", "/streaming"], "login": core.ready,
                "accounts": await asyncio.to_thread(core.account_count), "brokers": bridge.connected(),
                "ping": round(client.latency * 1000) if client.latency == client.latency else -1,
                "started": STARTED, "ts": int(time.time()), "py": platform.python_version(), "stream": STREAM_URL,
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
    why = ""
    try:
        client.run(token, log_handler=None)
    except discord.LoginFailure:
        # 4.12.3: the token was reset in the Developer Portal - tell the website, and wait before the restart
        # (a fast restart loop with a dead token can get the server's IP blocked by Discord)
        why = "token rejected (reset?) - on the server: sudo mp-railway env set DISCORD_TOKEN"
        log.error("Improper token: %s", why)
        time.sleep(3)
    except discord.PrivilegedIntentsRequired:
        why = "privileged intent off - Developer Portal > Bot > Privileged Gateway Intents"
        log.error(why)
    finally:
        bridge.stop(why)
    if why:
        time.sleep(60)
        raise SystemExit(why)
