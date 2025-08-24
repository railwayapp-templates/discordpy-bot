const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const fs = require('fs');

module.exports = {
  data: new SlashCommandBuilder()
    .setName('setguildid')
    .setDescription('Set and store the current guild ID in the config (admin only)')
    .setDefaultMemberPermissions(PermissionFlagsBits.Administrator),
  async execute(interaction) {
    const guildId = interaction.guild.id;
    let config = {};
    try {
      config = JSON.parse(fs.readFileSync('./config.json', 'utf8'));
    } catch {}
    if (!config[guildId]) config[guildId] = {};
    config[guildId].guildId = guildId;
    fs.writeFileSync('./config.json', JSON.stringify(config, null, 2));
    await interaction.reply({ content: `Guild ID set and stored: ${guildId}`, ephemeral: true });
  }
};
