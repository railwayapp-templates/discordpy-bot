---
title: MP login bot
description: Discord verification + account bot for the GTA SA MP mod (wagu)
tags:
  - python
  - discord.py
---

# MP login bot

The account system of the MP mod (3.21.6+, bot 3.21.7): the default server, Brief Case War and every custom
server with "Authentication system" on.

1. A player connects: the game shows a random code (8 characters, new every time).
2. In the Discord server ([discord.gg/tbsDknk34y](https://discord.gg/tbsDknk34y)) the player types
   `/gen CODE` in **#verification** (the command works only there; the answer is only visible to them).
3. The game shows Sign up: user, password, gender, age -> **Create**. Next time: Login only.
4. `/statsdc` (Discord, only visible to you, card with Refresh / Switch view buttons - Switch view = the character look) or `/stats` / `/char` in the game: your account.
   `/help` (4.13.15, replaces `/chardc`): the tutorial - install, account, playing, commands, problems (pages, only visible to you).
5. Forgot your account (3.56): `/forgotuser` shows your game username, `/resetpass` opens a form for a new password (all phones get logged out). In the game: Login screen > Forgot username? / Forgot password?, then `/gen CODE` in #verification.

Accounts are stored only here (SQLite, password hashed with PBKDF2-SHA256 + salt). The game and the
bot talk end-to-end encrypted (ECDH P-256 + AES-256-GCM) over public MQTT brokers; the bot signs a
one-time login ticket (ECDSA P-256) that the MP server checks. The host never sees a password.

## Runs on MP Railway (24/7, our own Railway)

Railway.app no longer takes new accounts, so the bot runs on **MP Railway**: a small self-hosted
Railway that lives on our HiveMQ server (or on a Termux phone). It clones this repo, installs
`requirements.txt`, starts `Procfile` (`worker: python main.py`), restarts on crash and on reboot,
and **deploys every new commit on `main` by itself within 2 minutes**.

**Automatic (no command on the server):** add the repository secrets `DISCORD_TOKEN` and
`SSH_PASSWORD` (or `SSH_KEY`) in Settings > Secrets and variables > Actions (`AUTH_PRIVATE_KEY` is
already there). The **Deploy to MP Railway** workflow then logs in to the server
(`mpsamp.duckdns.org`, user `root`; change with the `SSH_HOST` / `SSH_USER` variables) and installs /
updates the bot on every push. Run it any time: Actions > Deploy to MP Railway > Run workflow.

Or by hand on the HiveMQ server (once):

```bash
curl -fsSL https://raw.githubusercontent.com/ThirtyFoxMCx00E1/HiveMQ/main/railway/install.sh | sudo bash
```

It asks for `DISCORD_TOKEN` and `AUTH_PRIVATE_KEY` (hidden input, stored in
`/etc/mp-railway/discordpy-bot.env`, mode 600, never in git), deploys and prints
`ONLINE - /gen, /statsdc, /help are in your Discord server`. Termius console: **r) MP Railway**.

```
sudo mp-railway status        online? commit? which servers have the commands
sudo mp-railway logs -f       live log
sudo mp-railway deploy        deploy now (instead of waiting for the 2 min check)
sudo mp-railway env set DISCORD_TOKEN     change a secret (asks, hidden), restarts
```

Live status: [MP Railway page](https://thirtyfoxmcx00e1.github.io/wagu/railway.html) (the bot
publishes a signed status every 30 s; the page checks the signature with the mod's public key).

## Variables

Never put them in the code:

| Variable | Value |
|---|---|
| `DISCORD_TOKEN` | the bot token (Discord Developer Portal > Bot > Reset Token) |
| `AUTH_PRIVATE_KEY` | the 64-hex private key that matches the public key built into the mod |
| `VERIFY_CHANNEL` | optional, default `verification` |
| `STREAM_URL` | optional (4.12.2); YouTube / Twitch link for the 24/7 **Streaming** status, `off` = no status. `STATUS_TEXTS` (titles split by `|`) and `STATUS_SECONDS` (default 30) |
| `DATA_DIR` | optional; MP Railway sets `/var/lib/mp-railway/discordpy-bot`, Docker uses `/data` (volume) |
| `GLOBAL_SYNC` | optional, `1` = also register the commands globally (they then show twice in servers the bot is in) |

Discord: invite the bot with the `bot` and `applications.commands` scopes, create a text channel
named `verification`, and let the bot read/send there. Slash commands are synced to every server the
bot is in when it starts, and to new servers when it joins.

## Other hosts

Docker / Coolify / Dokploy / CapRover / Nixpacks work too: see [README-deploy.md](README-deploy.md)
(`Dockerfile`, `docker-compose.yml`, `captain-definition`, `nixpacks.toml`).
