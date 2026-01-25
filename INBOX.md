# INBOX

New tasks and information from external sources appear here.
Clawd will process the "Current Queue" sequentially.

---
## 🚀 HIGH LEVEL GOALS
These are large projects. Clawd will break these down into small tasks.
- [ ] **Google Ultra AI Server**: Create a Discord bot to share AI subscription access.
- [ ] **Vila Adora Breakfast App**: Finalize backend and menu logic.
- [ ] **Polymarket Bot**: Optimize trade execution speed.
- [ ] **YouTube Engine**: Automate the export-to-upload pipeline.
- [ ] **Personal Brand**: Complete the 'Projects' section with descriptions.
- [ ] **Fuel App**: Implement the Apple Health data fetcher.

## 📝 CURRENT QUEUE
Small, actionable steps go here. Ralph triggers Clawd for each one.
- [ ] **Design Discord server logo** - Generate or source a logo for the server
- [ ] **Implement audio message processing** - Add Discord voice message transcription capability  
- [x] **Multi-user access system** - Designed restricted access model (see MULTI_USER_ACCESS_DESIGN.md)
- [x] **Model switching interface** - Enable model selection from Discord chat (Added !model command)
- [x] **Dashboard** - Created and accessible via serve_dashboard.py
- [x] **Task queue visibility** - Visible via INBOX.md and dashboard

## ✅ COMPLETED
- [x] Initial Ralph-Clawd integration setup.
- [x] Initial system check: Verified all project paths are accessible.
- [x] Fix ConfirmationModal field name bug (guestName vs primaryGuestName) in Vila Adora Breakfast App.
- [x] Fix item name display issue in confirmation modal in Vila Adora Breakfast App.
- [x] Remove console logging from production code in Vila Adora Breakfast App.
- [x] Initialize git repository for Vila Adora Breakfast App.
- [x] make sure the 401 error has proper handling.
  - ✓ Implemented axios interceptor for auto re-auth in Polymarket Bot.
  - ✓ Added SDK-level 401 detection in Polymarket Bot executor.
  - ✓ Verified system-level 401 detection in Ralph Daemon.
- [x] Generate a list of current blockers for Vila Adora Breakfast App.
- [x] Scaffold Google Ultra AI Server project.
  - ✓ Initialized project and installed discord.js.
  - ✓ Created index.js boilerplate and .env.example.
- [x] User identity confirmed: Call user "Isak"
- [x] Dashboard and status visibility confirmed working

- [x] **FIX: Discord heartbeat prompt concatenating into file path** - Investigated. Code is correct. Added debug logging.
- [x] want to be able to see inbox.md (Requested via Discord: zisak) - Added !inbox command as alias to !queue