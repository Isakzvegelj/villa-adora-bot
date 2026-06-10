# DEPLOYMENT NOTES

This repo is configured for web-mode operation only.

- Entrypoint: `app.py` (Flask chat UI at `/` and admin at `/admin`)
- Data: `hotel_data.py` for hotel facts; `hotel.db` for bookings
- Run: `./run.sh` starts the local app and opens an authenticated Cloudflare tunnel
- Online URL: `https://villa-adora-bot.onrender.com`
- Env/api key: backend uses OpenRouter via `LLM_BASE_URL` / `LLM_MODEL` with the credential loaded from the macOS Keychain
