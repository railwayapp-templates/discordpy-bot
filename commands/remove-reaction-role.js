const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const fs = require('fs');
let config = require('../config.json');

module.exports = {
  data: new SlashCommandBuilder()
    .setName('remove-reaction-role')
    .setDescription('Remove a reaction role mapping (owner only)')
    .addStringOption(option =>
      option.setName('emoji')
        .setDescription('Emoji to remove')
        .setRequired(true))
    .setDefaultMemberPermissions(PermissionFlagsBits.Administrator),
  async execute(interaction) {
    // Only allow server owner
    if (!interaction.member.permissions.has(PermissionFlagsBits.Administrator)) {
      return interaction.reply({ content: 'Only administrators can use this command.', flags: 64 });
    }
    const guildId = interaction.guild.id;
    if (!config[guildId] || !config[guildId].reactionRoles) {
      return interaction.reply({ content: 'No reaction roles configured for this guild.', ephemeral: true });
    }
    const emoji = interaction.options.getString('emoji');
    const hasMapping = config[guildId].reactionRoles.emojiRoleMap && config[guildId].reactionRoles.emojiRoleMap[emoji];
    const hasLabel = config[guildId].reactionRoles.emojiLabels && config[guildId].reactionRoles.emojiLabels[emoji];
    if (!hasMapping && !hasLabel) {
      return interaction.reply({ content: `No mapping or label found for emoji ${emoji}.`, ephemeral: true });
    }
    if (hasMapping) {
      delete config[guildId].reactionRoles.emojiRoleMap[emoji];
    }
    if (hasLabel) {
      delete config[guildId].reactionRoles.emojiLabels[emoji];
    }
    fs.writeFileSync('./config.json', JSON.stringify(config, null, 2));
    return interaction.reply({ content: `Removed mapping and/or label for emoji ${emoji}.`, ephemeral: true });
  }
};
