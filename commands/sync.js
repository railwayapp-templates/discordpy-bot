const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { REST, Routes } = require('discord.js');
const fs = require('fs');
require('dotenv').config();

module.exports = {
  data: new SlashCommandBuilder()
    .setName('sync')
    .setDescription('Sync slash commands with this guild (admin only)')
    .setDefaultMemberPermissions(PermissionFlagsBits.Administrator),
  async execute(interaction) {
    const clientId = process.env.CLIENT_ID;
    const token = process.env.BOT_TOKEN;
    const guildId = interaction.guild.id;
    const commands = interaction.client.commands.map(cmd => cmd.data.toJSON());
    const rest = new REST({ version: '10' }).setToken(token);
    try {
      await rest.put(
        Routes.applicationGuildCommands(clientId, guildId),
        { body: commands }
      );
      await interaction.reply({ content: 'Commands synced with this guild!', ephemeral: true });
    } catch (error) {
      console.error(error);
      await interaction.reply({ content: 'Failed to sync commands.', ephemeral: true });
    }
  }
};
