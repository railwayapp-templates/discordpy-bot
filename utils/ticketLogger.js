// Ticket event logger for Z3dTickets
const fs = require('fs');
const path = require('path');
const LOG_PATH = path.join(__dirname, '../logs/tickets.json');

function logTicketEvent(event) {
  let logs = [];
  if (fs.existsSync(LOG_PATH)) {
    logs = JSON.parse(fs.readFileSync(LOG_PATH, 'utf8'));
  }
  logs.push(event);
  fs.writeFileSync(LOG_PATH, JSON.stringify(logs, null, 2));
}

module.exports = { logTicketEvent };
