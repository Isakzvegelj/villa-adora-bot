# RALPH.md - The Autonomous Engine

Ralph is the persistent, 24/7 background layer of Pi. While Pi is the personality and mind, Ralph is the hands and the clock.

## Responsibilities

1. **Gatekeeping the Inbox**: Monitor external inputs (Telegram, X, Email) and write them to `INBOX.md`.
2. **The Pulse**: Trigger a "Heartbeat" every 30-60 minutes to wake Pi up and process the current context.
3. **Execution**: Run background tasks that require long duration (scraping, downloading, processing) and report back to `memory/`.
4. **Connectivity**: Maintain the connection to the user's mobile device via Telegram.

## Integration

- **Trigger Command**: `/Users/isakzvegelj/.opencode/bin/opencode "Heartbeat: Check INBOX.md and HEARTBEAT.md. Execute pending tasks."`
- **Output Channel**: Responses meant for the user are written to `TELEGRAM_OUT.md`. Ralph will pick these up and send them.

## Current Status
- [ ] Daemon script implemented
- [ ] Telegram Bot connected
- [ ] Auto-heartbeat enabled
