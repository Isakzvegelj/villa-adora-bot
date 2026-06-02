# Villa Adora Bled — Digital Concierge "Luka"

A multi-language-capable hotel concierge bot powered by Ollama and SQLite, featuring a web chat interface.

## Features

✅ **Real-time chat** via web browser or terminal  
✅ **SQLite bookings** — persists to `hotel.db`  
✅ **Villa Adora Bled data** — rooms, policies, amenities, experiences  
✅ **Function calling** — extracts booking details automatically  
✅ **Confirmation flow** — user confirms before booking  
✅ **Web interface** — responsive chat UI (Flask)  

---

## Quick Start

### 1. Install Ollama & Pull Model

```bash
# Install from https://ollama.ai
ollama pull hotel-concierge  # your custom model
```

### 2. Install Python Dependencies

```bash
cd /Users/isakzvegelj/hotelbot
pip3 install -r requirements.txt
```

### 3. Run the Bot

**Option A — Terminal (CLI)**

```bash
python3 bot.py
```

**Option B — Web Interface**

```bash
python3 app.py
# Then open http://localhost:5000 in your browser
```

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
