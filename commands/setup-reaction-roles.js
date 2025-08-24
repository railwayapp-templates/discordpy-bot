const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const fs = require('fs');
let config = require('../config.json');

module.exports = {
  data: new SlashCommandBuilder()
    .setName('setup-reaction-panel')
    .setDescription('Post a reaction role panel message with all mapped roles and explanations')
    .setDefaultMemberPermissions(PermissionFlagsBits.Administrator),
  async execute(interaction) {
    const guildId = interaction.guild.id;
    const rr = config[guildId] && config[guildId].reactionRoles ? config[guildId].reactionRoles : null;
    if (!rr || !rr.emojiRoleMap || Object.keys(rr.emojiRoleMap).length === 0) {
      return interaction.reply({ content: 'Reaction role configuration is missing. Please run the setup flow first.', ephemeral: true });
    }
    // Build explanation message
    let description = 'React to this message to get the corresponding role.\n\n';
    for (const [emoji, roleId] of Object.entries(rr.emojiRoleMap)) {
      const label = rr.emojiLabels && rr.emojiLabels[emoji] ? rr.emojiLabels[emoji] : '';
      description += `${emoji} <@&${roleId}> \u2014 ${label}\n`;
    }
    const message = await interaction.reply({
      content: description,
      fetchReply: true
    });
    // React with each mapped emoji
    for (const emoji of Object.keys(rr.emojiRoleMap)) {
      try {
        await message.react(emoji);
      } catch (e) {
        console.error(`Failed to react with ${emoji}`, e);
      }
    }
    config[guildId].reactionRoles.messageId = message.id;
    fs.writeFileSync('./config.json', JSON.stringify(config, null, 2));
  }
};
