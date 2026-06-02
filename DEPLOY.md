# DEPLOYMENT GUIDE

## Quick Test (5 minutes) — ngrok

### 1. Start the bot locally
```bash
cd /Users/isakzvegelj/hotelbot

# Terminal 1: Start ollama
ollama run hotel-concierge

# Terminal 2: Start Flask app
python3 app.py
```
You should see: `Running on http://0.0.0.0:5000`

### 2. Install ngrok (if not installed)
```bash
# Download from https://ngrok.com/download
# Or with brew:
brew install ngrok/ngrok/ngrok
```

### 3. Create a public URL
```bash
ngrok http 5000
```
Output:
```
Session Status                online
Account                       Your Name (Plan: Free)
Version                       3.x.x
Region                        United States (us)
Web Interface                 http://127.0.0.1:4040
Forwarding                    https://abc1-23-45-67.ngrok-free.app -> http://localhost:5000
```

### 4. Share the HTTPS URL
Send `https://abc1-23-45-67.ngrok-free.app` to your testers. They can open it in any browser.

**Note:** Free ngrok URLs change each time you restart. For a permanent URL, sign up for a paid ngrok plan or use a cloud host.

---

## Persistent Deployment (Free/Cheap)

### Option A — PythonAnywhere (Free Tier)

1. Create account at https://www.pythonanywhere.com
2. Open **Bash** console
3. Upload your files via the **Files** tab or git:
   ```bash
   git clone <your-repo>
   cd hotelbot
   pip3 install --user -r requirements.txt
   ```
4. Create a **Web app**:
   - Source: Manual configuration
   - Python version: 3.11 or 3.12
   - WSGI configuration file: Edit to point to `app.py`
   ```
   import sys
   path = '/home/yourusername/hotelbot'
   if path not in sys.path:
       sys.path.insert(0, path)
   
   from app import app as application
   ```
5. Reload the web app. Your URL: `https://yourusername.pythonanywhere.com`

**Limits:** 100MB disk, 1 worker, sleeps after 5 mins inactivity (wakes on visit).

---

### Option B — Railway.app ($5/mo credit)

1. Sign up at https://railway.app
2. New Project → Deploy from GitHub repo
3. Add variables (optional):
   - None needed for local ollama, but Railway runs in cloud without ollama.
   - **Important:** This bot requires a running Ollama server. Railway only runs Python code, not Ollama.

**Not recommended** unless you also deploy Ollama separately (complex).

---

### Option C — Render (Free Tier)

Similar to Railway — cannot run Ollama. Not suitable.

---

### Option D — Self-Hosted VPS (€5-10/month)

**Recommended for production.**

1. Buy VPS (Hetzner, DigitalOcean, Linode, Vultr)
2. SSH into server
3. Install Ollama:
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ollama pull hotel-concierge
   ```
4. Deploy your code:
   ```bash
   git clone <your-repo>
   cd hotelbot
   pip3 install -r requirements.txt
   ```
5. Run with **systemd** service (auto-restart):

Create `/etc/systemd/system/hotelbot.service`:
```ini
[Unit]
Description=Hotel Bot Villa Adora
After=network.target

[Service]
Type=simple
User=root
WorkingDir=/home/youruser/hotelbot
ExecStart=/usr/bin/python3 /home/youruser/hotelbot/app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable hotelbot
sudo systemctl start hotelbot
sudo systemctl status hotelbot
```

6. Configure nginx reverse proxy + HTTPS (Let's Encrypt):

Install nginx:
```bash
apt install nginx certbot python3-certbot-nginx
```

Create `/etc/nginx/sites-available/hotelbot`:
```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```
```bash
ln -s /etc/nginx/sites-available/hotelbot /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d your-domain.com
```

Now your bot is live at `https://your-domain.com`.

---

## Multi-Server Architecture (Scalable)

If you want to separate concerns:

```
[User Browser] → [nginx] → [Flask App:5000] → [Ollama API:11434] → [SQLite]
                                   |
                                   └──→ [hotel.db]
```

Run Ollama on a separate port/container if needed. For a single hotel, one VPS is sufficient.

---

## Quick Validation Checklist

- [ ] `ollama run hotel-concierge` works (model loads)
- [ ] `python3 app.py` launches Flask without errors
- [ ] http://localhost:5000 shows the chat UI
- [ ] Bot answers: "What rooms do you have?" correctly
- [ ] Bot can extract booking details and ask for confirmation
- [ ] Saying "yes" writes to `hotel.db`
- [ ] `sqlite3 hotel.db "SELECT * FROM bookings;"` shows the booking

---

## FAQ

**Q: Do I need an API key?**  
A: No. Everything runs locally (Ollama + Flask).

**Q: Can I run this on Windows?**  
A: Yes. Use `python` instead of `python3`. Install Ollama for Windows.

**Q: What if Ollama crashes?**  
A: Use systemd to auto-restart both Ollama and Flask:
```ini
# /etc/systemd/system/ollama.service
[Unit]
Description=Ollama Service
After=network.target

[Service]
ExecStart=/usr/local/bin/ollama serve
Restart=always

[Install]
WantedBy=multi-user.target
```

**Q: Is the web interface mobile-friendly?**  
A: Yes — responsive design works on phones/tablets.

**Q: Where is the data stored?**  
A: Bookings in `hotel.db` (SQLite file). No external DB needed.

**Q: Can I change the bot's name/persona?**  
A: Edit `system_prompt` in `app.py` → `build_system_prompt()`.

---

## TL;DR — Fastest Path to Testing

```bash
# On your Mac
cd /Users/isakzvegelj/hotelbot
ollama run hotel-concierge  # keep running
python3 app.py             # another terminal
ngrok http 5000            # another terminal
# Send the ngrok HTTPS URL to testers
```

Done.
