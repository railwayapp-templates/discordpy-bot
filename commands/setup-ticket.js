require('dotenv').config();
const { SlashCommandBuilder, ButtonBuilder, ButtonStyle, ActionRowBuilder, PermissionFlagsBits } = require('discord.js');

module.exports = {
  data: new SlashCommandBuilder()
    .setName('setup-ticket-panel')
    .setDescription('Post a ticket panel with Open Ticket button (admin only)')
    .setDefaultMemberPermissions(PermissionFlagsBits.Administrator),
  async execute(interaction) {
    const openBtn = new ButtonBuilder()
      .setCustomId('open_ticket')
      .setLabel('Open Ticket')
      .setStyle(ButtonStyle.Success);
    const row = new ActionRowBuilder().addComponents(openBtn);
    await interaction.reply({
      content: 'Need help? Click below to open a private support ticket.',
      components: [row],
      ephemeral: false
    });
  }
};
