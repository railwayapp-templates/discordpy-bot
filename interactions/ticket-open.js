const { ChannelType, PermissionFlagsBits, ButtonBuilder, ButtonStyle, ActionRowBuilder, Events } = require('discord.js');
const config = require('../config.json');

module.exports = {
  init(client) {
    client.on('interactionCreate', async interaction => {
      if (!interaction.isButton() || interaction.customId !== 'open_ticket') return;
      const guild = interaction.guild;
      const user = interaction.user;
      const guildId = guild.id;
      const guildConfig = config[guildId] || {};
      const supportAgentRole = guildConfig.supportAgentRoleId;
      // Collect all admin role IDs
      const adminRoleIds = guild.roles.cache.filter(r => r.permissions.has(PermissionFlagsBits.Administrator)).map(r => r.id);
      // Build permission overwrites, filtering out any undefined/invalid IDs
      const permissionOverwrites = [
        { id: guild.id, deny: [PermissionFlagsBits.ViewChannel] }, // @everyone
        { id: user.id, allow: [PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages] },
      ];
      if (supportAgentRole && guild.roles.cache.has(supportAgentRole)) {
        permissionOverwrites.push({ id: supportAgentRole, allow: [PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages] });
      }
      if (guild.members.me && guild.members.me.id) {
        permissionOverwrites.push({ id: guild.members.me.id, allow: [PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages] });
      }
      for (const id of adminRoleIds) {
        if (id && id !== supportAgentRole) {
          permissionOverwrites.push({ id, allow: [PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages] });
        }
      }
      // Create ticket channel with restricted permissions
      const channel = await guild.channels.create({
        name: `ticket-${user.username}`,
        type: ChannelType.GuildText,
        permissionOverwrites
      });
      // Add close button
      const closeBtn = new ButtonBuilder()
        .setCustomId('close_ticket')
        .setLabel('Close Ticket')
        .setStyle(ButtonStyle.Danger);
      const row = new ActionRowBuilder().addComponents(closeBtn);
      // Notify roles
      let notifyMentions = '';
      if (Array.isArray(guildConfig.ticketNotifyRoleIds) && guildConfig.ticketNotifyRoleIds.length > 0) {
        notifyMentions = guildConfig.ticketNotifyRoleIds.map(id => `<@&${id}>`).join(' ');
      }
      await channel.send({
        content: `${notifyMentions} <@${user.id}> Your ticket is open. A support member will be with you soon.`.trim(),
        components: [row]
      });
      // Log event
      client.emit('ticketOpened', { user: user.tag, channel: channel.name });
    });
  }
};
