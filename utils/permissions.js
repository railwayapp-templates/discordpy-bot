// Permission utilities for Z3dTickets
module.exports = {
  canManageTicket(member, supportRoleId) {
    return member.roles.cache.has(supportRoleId) || member.permissions.has('Administrator');
  }
};
