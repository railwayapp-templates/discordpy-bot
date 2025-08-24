const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const fs = require('fs');
const config = require('../config.json');

module.exports = {
  data: new SlashCommandBuilder()
    .setName('setup')
    .setDescription('Start the interactive setup interface (admin only)')
    .setDefaultMemberPermissions(PermissionFlagsBits.Administrator),
  async execute(interaction) {
    if (!interaction.member.permissions.has(PermissionFlagsBits.Administrator)) {
      return interaction.reply({ content: 'Only administrators can run setup.', flags: 64 });
    }
    // Create an interactive setup interface with buttons
    const { ActionRowBuilder, ButtonBuilder, ButtonStyle } = require('discord.js');
    const ticketBtn = new ButtonBuilder()
      .setCustomId('setup_ticket_flow')
      .setLabel('Setup Ticket Support')
      .setStyle(ButtonStyle.Primary);
    const rrBtn = new ButtonBuilder()
      .setCustomId('setup_reaction_roles_flow')
      .setLabel('Setup Reaction Roles')
      .setStyle(ButtonStyle.Secondary);
    const row = new ActionRowBuilder().addComponents(ticketBtn, rrBtn);
    await interaction.reply({
      content: 'Welcome to the Z3D bot setup! Choose what you want to configure:',
      components: [row],
      ephemeral: false
    });
  },
};
