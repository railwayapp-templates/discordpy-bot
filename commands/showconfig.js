const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const fs = require('fs');

module.exports = {
  data: new SlashCommandBuilder()
    .setName('showconfig')
    .setDescription('Display the current config and mappings')
    .setDefaultMemberPermissions(PermissionFlagsBits.Administrator),
  async execute(interaction) {
    try {
      const config = JSON.parse(fs.readFileSync('./config.json', 'utf8'));
      const guildId = interaction.guild.id;
      const guildConfig = config[guildId];
      if (!guildConfig) {
        return interaction.reply({ content: 'No config found for this guild.', flags: 64 });
      }
      let output = 'Current Config:\n';
      output += `Log Channel: ${guildConfig.logChannelId ? `<#${guildConfig.logChannelId}> (${guildConfig.logChannelId})` : 'Not set'}\n`;
      output += `Support Role: ${guildConfig.supportRoleId ? `<@&${guildConfig.supportRoleId}> (${guildConfig.supportRoleId})` : 'Not set'}\n`;
      if (guildConfig.reactionRoles && guildConfig.reactionRoles.emojiRoleMap) {
        output += '\nReaction Role Mappings:';
        for (const [emoji, roleId] of Object.entries(guildConfig.reactionRoles.emojiRoleMap)) {
          const label = guildConfig.reactionRoles.emojiLabels && guildConfig.reactionRoles.emojiLabels[emoji] ? guildConfig.reactionRoles.emojiLabels[emoji] : '';
          output += `\n${emoji} \u2192 <@&${roleId}> ${label ? `\u2014 ${label}` : ''}`;
        }
      } else {
        output += '\nNo reaction role mappings set.';
      }
      await interaction.reply({ content: output, flags: 64 });
    } catch (e) {
      await interaction.reply({ content: 'Failed to load config.', flags: 64 });
    }
  }
};
