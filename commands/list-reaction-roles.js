const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const fs = require('fs');
const config = require('../config.json');

module.exports = {
  data: new SlashCommandBuilder()
    .setName('list-reaction-roles')
    .setDescription('List all current reaction role mappings (owner only)')
    .setDefaultMemberPermissions(PermissionFlagsBits.Administrator),
  async execute(interaction) {
    // Only allow server owner
    if (!interaction.member.permissions.has(PermissionFlagsBits.Administrator)) {
      return interaction.reply({ content: 'Only administrators can use this command.', flags: 64 });
    }
    if (!config.reactionRoles || !config.reactionRoles.emojiRoleMap || Object.keys(config.reactionRoles.emojiRoleMap).length === 0) {
      return interaction.reply({ content: 'No reaction role mappings set.', ephemeral: true });
    }
    const lines = Object.entries(config.reactionRoles.emojiRoleMap).map(([emoji, roleId]) => `${emoji} → <@&${roleId}>`);
    return interaction.reply({ content: lines.join('\n'), ephemeral: true });
  }
};
