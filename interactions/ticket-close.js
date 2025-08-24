const config = require('../config.json');
const { sendTranscript } = require('../utils/transcript');

module.exports = {
  init(client) {
    client.on('interactionCreate', async interaction => {
      if (!interaction.isButton() || interaction.customId !== 'close_ticket') return;
      const channel = interaction.channel;
      const user = interaction.user;
      // Confirm close (ephemeral)
      await interaction.reply({ content: 'Are you sure you want to close this ticket? Click again to confirm.', flags: 64 });
      // Wait for confirmation (simulate with a second click for simplicity)
      let confirmed = false;
      const filter = i => i.user.id === user.id && i.customId === 'close_ticket';
      try {
        await interaction.channel.awaitMessageComponent({ filter, time: 10000 });
        confirmed = true;
      } catch (e) {
        confirmed = false;
      }
      if (confirmed) {
        // Log event
        const logChannel = channel.guild.channels.cache.get(config.logChannelId);
        if (logChannel) logChannel.send(`:lock: Ticket closed by ${user.tag} (${user.id}) in <#${channel.id}>`);
        client.emit('ticketClosed', { user: user.tag, channel: channel.name });
        // Send transcript to user and log channel, with metadata
        const meta = global.ticketMeta && global.ticketMeta[channel.id];
        await sendTranscript(channel, user, logChannel, client, meta, interaction.user);
        await channel.send('This ticket will be deleted in 3 seconds...');
        setTimeout(() => channel.delete(), 3000);
      }
    });
  }
};
