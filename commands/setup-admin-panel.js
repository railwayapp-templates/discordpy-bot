const { SlashCommandBuilder, PermissionFlagsBits, ActionRowBuilder, ButtonBuilder, ButtonStyle, EmbedBuilder } = require('discord.js');
const fs = require('fs');
let config = require('../config.json');

function buildAdminPanelEmbed(guildId) {
  const embed = new EmbedBuilder()
    .setTitle('Admin Panel')
    .setColor(0x5865F2)
    .addFields(
      { name: 'Welcome Message', value: config[guildId]?.welcomeMessage || 'Not set', inline: false },
      { name: 'Log Channel', value: config[guildId]?.logChannelId ? `<#${config[guildId].logChannelId}> (${config[guildId].logChannelId})` : 'Not set', inline: false },
      { name: 'Support Role', value: config[guildId]?.supportAgentRoleId ? `<@&${config[guildId].supportAgentRoleId}> (${config[guildId].supportAgentRoleId})` : 'Not set', inline: false },
      { name: 'Mention Roles', value: (config[guildId]?.ticketNotifyRoleIds && config[guildId].ticketNotifyRoleIds.length) ? config[guildId].ticketNotifyRoleIds.map(id => `<@&${id}>`).join(', ') : 'Not set', inline: false },
      { name: 'Reaction Message', value: config[guildId]?.reactionRoles?.messageContent || 'Not set', inline: false }
    );
  if (config[guildId]?.reactionRoles?.emojiRoleMap) {
    let rrText = '';
    for (const [emoji, roleId] of Object.entries(config[guildId].reactionRoles.emojiRoleMap)) {
      const label = config[guildId].reactionRoles.emojiLabels && config[guildId].reactionRoles.emojiLabels[emoji] ? config[guildId].reactionRoles.emojiLabels[emoji] : '';
      rrText += `\n${emoji} \u2192 <@&${roleId}> ${label ? `\u2014 ${label}` : ''}`;
    }
    embed.addFields({ name: 'Reaction Role Mappings', value: rrText || 'No reaction role mappings set.', inline: false });
  } else {
    embed.addFields({ name: 'Reaction Role Mappings', value: 'No reaction role mappings set.', inline: false });
  }
  return embed;
}

module.exports = {
  data: new SlashCommandBuilder()
    .setName('setup-admin-panel')
    .setDescription('Admin panel for welcome message, reaction roles, logs, and support settings')
    .setDefaultMemberPermissions(PermissionFlagsBits.Administrator),
  async execute(interaction) {
    const guildId = interaction.guild.id;
    if (!config[guildId]) config[guildId] = {};
    const embed = buildAdminPanelEmbed(guildId);
    const updateBtn = new ButtonBuilder()
      .setCustomId('admin_panel_update')
      .setLabel('Update Panel')
      .setStyle(ButtonStyle.Primary);
    const grabSupportBtn = new ButtonBuilder()
      .setCustomId('admin_panel_grab_support')
      .setLabel('Grab Support Role')
      .setStyle(ButtonStyle.Success);
    const row = new ActionRowBuilder().addComponents(updateBtn, grabSupportBtn);
    await interaction.reply({ embeds: [embed], components: [row], ephemeral: true });
  }
};
