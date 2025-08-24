const { SlashCommandBuilder, PermissionFlagsBits, EmbedBuilder, ActionRowBuilder, ButtonBuilder, ButtonStyle } = require('discord.js');

module.exports = {
  data: new SlashCommandBuilder()
    .setName('open_admin_panel')
    .setDescription('Open the admin moderation panel for a user')
    .addUserOption(option =>
      option.setName('user')
        .setDescription('The user to moderate')
        .setRequired(true)
    )
    .setDefaultMemberPermissions(PermissionFlagsBits.Administrator),

  async execute(interaction) {
    const user = interaction.options.getUser('user');
    const embed = new EmbedBuilder()
      .setTitle('Admin Moderation Panel')
      .setDescription(`Moderation actions for <@${user.id}> (${user.id})`)
      .setColor(0xED4245);

    const row = new ActionRowBuilder().addComponents(
      new ButtonBuilder()
        .setCustomId(`admin_report_${user.id}`)
        .setLabel('Report')
        .setStyle(ButtonStyle.Secondary),
      new ButtonBuilder()
        .setCustomId(`admin_warn_${user.id}`)
        .setLabel('Warn')
        .setStyle(ButtonStyle.Primary),
      new ButtonBuilder()
        .setCustomId(`admin_ban_${user.id}`)
        .setLabel('Ban')
        .setStyle(ButtonStyle.Danger)
    );

    await interaction.reply({ embeds: [embed], components: [row], ephemeral: true });
  }
};
