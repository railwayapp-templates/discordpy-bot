# Run the MP login bot 24/7

The bot only makes OUTBOUND connections (Discord + MQTT), so it needs no open ports and no domain.

## MP Railway (recommended, our own Railway)

On the HiveMQ server or any Ubuntu / Debian machine that stays on:

    curl -fsSL https://raw.githubusercontent.com/ThirtyFoxMCx00E1/HiveMQ/main/railway/install.sh | sudo bash

On an Android phone (Termux, from F-Droid; install Termux:Boot to start after a reboot):

    curl -fsSL https://raw.githubusercontent.com/ThirtyFoxMCx00E1/HiveMQ/main/railway/install.sh | bash

Pushes to `main` are deployed by themselves within 2 minutes (`mp-railway status` shows the commit).

## Plain Docker (any VPS)

    git clone https://github.com/ThirtyFoxMCx00E1/discordpy-bot
    cd discordpy-bot
    cp .env.example .env && nano .env
    docker compose up -d --build
    docker compose logs -f      # look for "Logged in as ..." and "Slash commands in ..."

## Coolify / Dokploy / CapRover / Nixpacks

Point the app at this repo (Dockerfile build; CapRover reads `captain-definition`, Nixpacks reads
`nixpacks.toml`), set `DISCORD_TOKEN` and `AUTH_PRIVATE_KEY` in the panel's environment settings,
and add a persistent volume mounted at `/data`. No port / domain needed (it is a worker).

## Check

- Log shows "Logged in as <bot>" -> bot is online in Discord.
- Log shows "Slash commands in <server>: /gen, /stats, /char" -> commands synced.
- "No slash commands ... re-invite" -> invite again with the printed link (needs the
  applications.commands scope).

Do NOT commit your Discord token or AUTH_PRIVATE_KEY.
