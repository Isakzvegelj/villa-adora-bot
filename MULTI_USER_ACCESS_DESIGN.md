# Multi-User Access Design for Ralph/Clawd

## Overview
Design a restricted access model that allows Isak to share Ralph/Clawd with other users while maintaining security and privacy boundaries.

## Current Architecture
- Ralph: Discord bot daemon running 24/7
- Clawd: AI assistant accessed via OpenCode
- Configuration: ralph_config.json (contains API keys, channel bindings)
- INBOX.md: Task queue shared across all users
- Memory files: Session history and context

## Security Concerns
1. **API Keys**: Currently stored in ralph_config.json
2. **Private Context**: MEMORY.md contains personal information
3. **File Access**: All users could theoretically access Isak's private files
4. **Cost Control**: API usage should be tracked per user

## Proposed Multi-User Access Model

### Tier 1: Read-Only Guest Access
**Use Case:** Friends/colleagues who want to see what Clawd can do

**Permissions:**
- View status (!status)
- View public queue (!queue shows only PUBLIC tasks)
- Cannot trigger Clawd execution
- Cannot modify configuration

**Implementation:**
- Add `guest_users` list to config
- Filter INBOX.md to show only tasks tagged with [PUBLIC]
- Reject execution commands from non-admin users

### Tier 2: Restricted User Access
**Use Case:** Trusted collaborators working on specific projects

**Permissions:**
- All Read-Only permissions
- Execute tasks in their own isolated workspace
- Add tasks to shared public queue
- Use their own API keys (no access to Isak's keys)

**Implementation:**
- Add `trusted_users` list to config
- Create per-user workspaces: `/Users/isakzvegelj/clawd/users/{username}/`
- Each user gets their own INBOX, memory files
- Shared public queue in main INBOX.md
- User-specific API key storage

### Tier 3: Admin Access (Isak only)
**Permissions:**
- Full system access
- Modify configuration
- Access all workspaces
- Manage user permissions
- View all logs

**Implementation:**
- `admin_users` list in config (starts with Isak's Discord ID)
- All commands available

## Implementation Checklist

### Phase 1: Basic Access Control
- [ ] Add user role system to ralph_config.json
- [ ] Implement permission checks in command handlers
- [ ] Filter INBOX.md display based on user role
- [ ] Add !whoami command to show current user's permissions

### Phase 2: Workspace Isolation
- [ ] Create user workspace directory structure
- [ ] Implement workspace switching for Clawd
- [ ] Separate per-user API key storage
- [ ] Per-user task queues

### Phase 3: Shared Resources
- [ ] Public task queue system
- [ ] Shared project directories with ACLs
- [ ] Usage tracking and quotas

### Phase 4: Advanced Features
- [ ] Audit logging for all commands
- [ ] Web interface for permission management
- [ ] Cost tracking per user
- [ ] Rate limiting

## Configuration Schema

```json
{
  "discord_token": "...",
  "channel_id": "...",
  "users": {
    "123456789": {
      "name": "Isak",
      "role": "admin",
      "workspace": "/Users/isakzvegelj/clawd",
      "api_keys": {...}
    },
    "987654321": {
      "name": "Guest",
      "role": "guest",
      "workspace": null,
      "api_keys": {}
    }
  },
  "default_role": "guest"
}
```

## Commands for User Management

- `!adduser @user [guest|trusted|admin]` - Grant access
- `!removeuser @user` - Revoke access
- `!listusers` - Show all users and their roles
- `!whoami` - Show your permissions
- `!switchworkspace [user]` - Admin-only: switch context

## Security Best Practices

1. **Never share API keys between users**
2. **Log all sensitive operations**
3. **Use Discord user IDs (not names) for authentication**
4. **Implement rate limiting to prevent abuse**
5. **Regular audits of user access**

## Next Steps

1. Get feedback from Isak on the proposed tiers
2. Decide if workspace isolation is needed immediately
3. Start with Phase 1 (basic access control)
4. Test with one trusted user before broader rollout

---
Created: 2026-01-25
Status: Design Draft - Awaiting Review
