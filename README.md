# Villa Adora Bled — Digital Concierge "Luka"

A hotel concierge bot with a web chat interface. It uses a cloud LLM API via OpenRouter and persists bookings in SQLite.

## Current Mode
- **Interface:** Web chat (Flask app at `/`)
- **LLM:** OpenRouter-compatible API
- **Data:** `hotel_data.py` for hotel facts/rooms/policies, `hotel.db` for bookings
- **Admin:** Simple booking viewer at `/admin`  

---

## Dev Quick Start

```bash
cd /Users/isakzvegelj/Documents/antigravity/villa-adora-bot
./run.sh
```

`run.sh` loads the OpenRouter API key from the macOS Keychain, starts the Flask app with the local virtualenv, and then opens an authenticated Cloudflare tunnel on demand.

## Admin & Staff Handoff
Staff can view recent bookings at `/admin`. For web testing, use the `/` chat UI. If you see no reply from the bot, the most common issues are:
- Keychain item `openrouter-api-key` missing or wrong user account
- Wrong local port: app listens on `5173`; `run.sh` now tunnels `5173`.

---

## File Structure

```
hotelbot/
├── bot.py              # CLI chat interface
├── app.py              # Flask web server
├── database.py         # SQLite booking operations
├── hotel_data.py       # Villa Adora Bled structured data
├── hotel.db            # SQLite database (auto-created)
├── requirements.txt    # Python dependencies
└── templates/
    └── index.html      # Web chat UI
```

---

## Villa Adora Bled at a Glance

| | |
|---|---|
| **Location** | Cesta svobode 35, 4260 Bled, Slovenia |
| **Phone** | +386 51 603 858 |
| **Suites** | Princess (€250), Luxury (€270), Penthouse (€300), Swan (€370), Island (€380), Prestige (€420) |
| **Check-in** | 14:00 - 21:00 |
| **Check-out** | 07:00 - 11:00 |
| **Breakfast** | €22 per person |
| **Parking** | Free private parking |
| **Pets** | Allowed on request |

---

## Web Deployment

To deploy on a VPS (5-10€/month):

```bash
# On your server
git clone <your-repo>
cd hotelbot
pip3 install -r requirements.txt

# Run with screen/tmux or as a service
python3 app.py --host 0.0.0.0 --port 5000
```

Configure reverse proxy (nginx) for HTTPS + domain:
```nginx
location / {
    proxy_pass http://localhost:5000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

---

## Multi-Language

**Current:** English only (recommended for consistency).  
**To add languages:** Extend `hotel_data.py` with translated fields and modify `hotel_data.py` → build system prompt with language selector.

---

## FAQ

**Q: Can I use a different model?**  
A: Yes — change `model='hotel-concierge'` to any ollama model in `bot.py` and `app.py` (line ~186/91).

**Q: Where are bookings stored?**  
A: SQLite database file: `hotel.db` (use `sqlite3 hotel.db` to inspect).

**Q: How do I reset bookings?**  
A: Delete `hotel.db` — it auto-recreates on next run.

**Q: Can I change hotel data?**  
A: Edit `hotel_data.py` — the bot reads from it on startup.

**Q: Do I need internet?**  
A: Only for ollama model download. After that, 100% local.

---

## Next Steps

- Add email confirmation (SMTP)  
- Add ICS calendar invite generation  
- Add admin dashboard to view bookings  
- Integrate payment gateway (Stripe)  
- Add WhatsApp via Twilio or WhatsApp Business API  

---

**Built for Villa Adora Bled** · Alpine Concierge · 2025
