const { ActionRowBuilder, ButtonBuilder, ButtonStyle, ChannelType, PermissionFlagsBits, Events } = require('discord.js');
const fs = require('fs');
let config = require('../config.json');

module.exports = {
  init(client) {
    client.on('interactionCreate', async interaction => {
      if (!interaction.isButton()) return;
      const guildId = interaction.guild?.id;
      if (!guildId) return;
      // Ticket setup flow
      if (interaction.customId === 'setup_ticket_flow') {
        if (!interaction.member.permissions.has(PermissionFlagsBits.Administrator)) {
          return interaction.reply({ content: 'Only administrators can run this setup.', flags: 64 });
        }
        // Immediately reply to the interaction to avoid expiration
        await interaction.reply({ content: 'Ticket setup started! Please follow the instructions in this channel.', flags: 64 });
        // Ask for support agent role (mention or ID)
        await interaction.channel.send('Please mention the support agent role (e.g., @SupportAgent) or provide the role ID (e.g., 123456789012345678). Only members with this role or admins will be able to view tickets.');
        const filter = m => m.author.id === interaction.user.id && (m.mentions.roles.size > 0 || /^\d{17,19}$/.test(m.content.trim()));
        try {
          const collected = await interaction.channel.awaitMessages({ filter, max: 1, time: 60000, errors: ['time'] });
          let supportAgentRoleId;
          if (collected.first().mentions.roles.size > 0) {
            supportAgentRoleId = collected.first().mentions.roles.first().id;
          } else {
            supportAgentRoleId = collected.first().content.trim();
          }
          if (!config[guildId]) config[guildId] = {};
          config[guildId].supportAgentRoleId = supportAgentRoleId;
          // Ask for log channel ID
          await interaction.channel.send('Please provide the log channel ID (e.g., 1375124421659857019).');
          const filter2 = m => m.author.id === interaction.user.id && /^\d{17,19}$/.test(m.content.trim());
          const collected2 = await interaction.channel.awaitMessages({ filter: filter2, max: 1, time: 60000, errors: ['time'] });
          const logChannelId = collected2.first().content.trim();
          config[guildId].logChannelId = logChannelId;
          // Ask for roles to notify (mention or IDs, space/comma separated)
          await interaction.channel.send('Please mention the role(s) to notify when a ticket is opened, or provide their IDs (separated by spaces or commas).');
          const filter3 = m => m.author.id === interaction.user.id && (m.mentions.roles.size > 0 || /\d{17,19}/.test(m.content));
          const collected3 = await interaction.channel.awaitMessages({ filter: filter3, max: 1, time: 60000, errors: ['time'] });
          const msg3 = collected3.first();
          let notifyRoleIds = [];
          if (msg3.mentions.roles.size > 0) {
            notifyRoleIds = msg3.mentions.roles.map(r => r.id);
          } else {
            notifyRoleIds = msg3.content.match(/\d{17,19}/g) || [];
          }
          config[guildId].ticketNotifyRoleIds = notifyRoleIds;
          fs.writeFileSync('./config.json', JSON.stringify(config, null, 2));
          await interaction.channel.send('✅ Ticket support setup complete!');
        } catch (e) {
          await interaction.channel.send('Setup timed out or failed. Please try again.');
        }
      }
      // Reaction role setup flow
      if (interaction.customId === 'setup_reaction_roles_flow') {
        if (!interaction.member.permissions.has(PermissionFlagsBits.Administrator)) {
          return interaction.reply({ content: 'Only administrators can run this setup.', ephemeral: true });
        }
        if (!config[guildId]) config[guildId] = {};
        config[guildId].reactionRoles = config[guildId].reactionRoles || { emojiRoleMap: {}, emojiLabels: {} };
        let adding = true;
        await interaction.reply({ content: 'Send an emoji, mention a role, and a label for the button (e.g., 🔥 @Role Support), or type `done` to finish. The label is what the reaction is for (e.g., Support, Events, Updates, etc).', ephemeral: true });
        while (adding) {
          const filter = m => m.author.id === interaction.user.id;
          try {
            const collected = await interaction.channel.awaitMessages({ filter, max: 1, time: 60000, errors: ['time'] });
            const msg = collected.first();
            if (msg.content.toLowerCase() === 'done') break;
            // Parse: emoji, role (mention or ID), label
            const match = msg.content.trim().match(/^(\p{Emoji}|\S+)\s+(<@&\d{17,19}>|\d{17,19})\s+(.+)$/u);
            if (!match) {
              await interaction.channel.send('Invalid format. Please send an emoji, mention a role, and a label (e.g., 🔥 @Role Support).');
              continue;
            }
            const emoji = match[1];
            let roleId;
            if (match[2].startsWith('<@&')) {
              roleId = match[2].replace(/<@&(\d{17,19})>/, '$1');
            } else {
              roleId = match[2];
            }
            const label = match[3].trim();
            config[guildId].reactionRoles.emojiRoleMap[emoji] = roleId;
            config[guildId].reactionRoles.emojiLabels = config[guildId].reactionRoles.emojiLabels || {};
            config[guildId].reactionRoles.emojiLabels[emoji] = label;
            await interaction.channel.send(`Mapped ${emoji} to <@&${roleId}> for "${label}".`);
          } catch (e) {
            await interaction.channel.send('Setup timed out or failed. Please try again.');
            break;
          }
        }
        fs.writeFileSync('./config.json', JSON.stringify(config, null, 2));
        await interaction.channel.send('✅ Reaction role setup complete!');
      }
      // Admin panel update button
      if (interaction.customId === 'admin_panel_update') {
        const { EmbedBuilder, ActionRowBuilder, ButtonBuilder, ButtonStyle } = require('discord.js');
        const config = require('../config.json');
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
        const updateBtn = new ButtonBuilder()
          .setCustomId('admin_panel_update')
          .setLabel('Update Panel')
          .setStyle(ButtonStyle.Primary);
        const grabSupportBtn = new ButtonBuilder()
          .setCustomId('admin_panel_grab_support')
          .setLabel('Grab Support Role')
          .setStyle(ButtonStyle.Success);
        const row = new ActionRowBuilder().addComponents(updateBtn, grabSupportBtn);
        await interaction.update({ embeds: [embed], components: [row] });
        return;
      }
      // Admin panel grab support role button
      if (interaction.customId === 'admin_panel_grab_support') {
        const config = require('../config.json');
        const supportRoleId = config[guildId]?.supportAgentRoleId;
        if (!supportRoleId) {
          return interaction.reply({ content: 'No support role is set for this guild.', ephemeral: true });
        }
        const member = await interaction.guild.members.fetch(interaction.user.id);
        if (member.roles.cache.has(supportRoleId)) {
          return interaction.reply({ content: 'You already have the support role.', ephemeral: true });
        }
        await member.roles.add(supportRoleId);
        await interaction.reply({ content: `You have been given the support role <@&${supportRoleId}>.`, ephemeral: true });
        return;
      }
      // Admin panel moderation buttons
      if (interaction.isButton() && interaction.customId.startsWith('admin_')) {
        const [ , action, userId ] = interaction.customId.split('_');
        const config = require('../config.json');
        const logChannelId = config[guildId]?.logChannelId;
        let logChannel = null;
        if (logChannelId) {
          logChannel = interaction.guild.channels.cache.get(logChannelId);
        }
        if (action === 'report') {
          if (logChannel) {
            await logChannel.send(`📝 **Report:** <@${interaction.user.id}> reported <@${userId}>`);
          }
          await interaction.reply({ content: `User <@${userId}> has been reported and logged.`, ephemeral: true });
          return;
        }
        if (action === 'warn') {
          if (logChannel) {
            await logChannel.send(`⚠️ **Warn:** <@${interaction.user.id}> warned <@${userId}>`);
          }
          await interaction.reply({ content: `User <@${userId}> has been warned and logged.`, ephemeral: true });
          return;
        }
        if (action === 'ban') {
          try {
            await interaction.guild.members.ban(userId, { reason: `Banned by ${interaction.user.tag} via admin panel.` });
            if (logChannel) {
              await logChannel.send(`🔨 **Ban:** <@${interaction.user.id}> banned <@${userId}>`);
            }
            await interaction.reply({ content: `User <@${userId}> has been banned and logged.`, ephemeral: true });
          } catch (e) {
            await interaction.reply({ content: `Failed to ban user: ${e.message}`, ephemeral: true });
          }
          return;
        }
      }
    });
  }
};
