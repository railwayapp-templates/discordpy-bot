// deploy-commands.js
// Script to register (sync) slash commands for a specific guild or globally
require('dotenv').config();
const { REST, Routes } = require('discord.js');
const fs = require('fs');

const commands = [];
const commandFiles = fs.readdirSync('./commands').filter(file => file.endsWith('.js'));

for (const file of commandFiles) {
  const command = require(`./commands/${file}`);
  if (command.data) commands.push(command.data.toJSON());
}

const rest = new REST({ version: '10' }).setToken(process.env.DISCORD_TOKEN || process.env.BOT_TOKEN);

// List of guild IDs to register commands to
const GUILD_IDS = ['973876472009879583', '1354383405911113728'];
const CLIENT_ID = process.env.CLIENT_ID;

(async () => {
  try {
    for (const GUILD_ID of GUILD_IDS) {
      console.log('Started refreshing application (/) commands for guild:', GUILD_ID);
      await rest.put(
        Routes.applicationGuildCommands(CLIENT_ID, GUILD_ID),
        { body: commands },
      );
      console.log('Successfully reloaded application (/) commands for guild!', GUILD_ID);
    }
  } catch (error) {
    console.error(error);
  }
})();
