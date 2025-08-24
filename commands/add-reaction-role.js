const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const fs = require('fs');
let config = require('../config.json');

module.exports = {
  data: new SlashCommandBuilder()
    .setName('add-reaction-role')
    .setDescription('Add a reaction role mapping (owner only)')
    .addStringOption(option =>
      option.setName('emoji')
        .setDescription('Emoji to use')
        .setRequired(true))
    .addRoleOption(option =>
      option.setName('role')
        .setDescription('Role to assign')
        .setRequired(true))
    .setDefaultMemberPermissions(PermissionFlagsBits.Administrator),
  async execute(interaction) {
    // Only allow server owner
    if (!interaction.member.permissions.has(PermissionFlagsBits.Administrator)) {
      return interaction.reply({ content: 'Only administrators can use this command.', flags: 64 });
    }
    const guildId = interaction.guild.id;
    if (!config[guildId]) config[guildId] = {};
    if (!config[guildId].reactionRoles) config[guildId].reactionRoles = {};
    if (!config[guildId].reactionRoles.emojiRoleMap) config[guildId].reactionRoles.emojiRoleMap = {};
    const emoji = interaction.options.getString('emoji');
    const role = interaction.options.getRole('role');
    config[guildId].reactionRoles.emojiRoleMap[emoji] = role.id;
    fs.writeFileSync('./config.json', JSON.stringify(config, null, 2));
    return interaction.reply({ content: `Mapped emoji ${emoji} to role <@&${role.id}>.`, ephemeral: true });
  }
};
