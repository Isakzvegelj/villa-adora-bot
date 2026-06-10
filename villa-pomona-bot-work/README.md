# Villa Pomona Bot — Digital Concierge

A Flask + OpenAI-powered virtual concierge for Villa Pomona Bled, a heritage villa boutique hotel in Bled, Slovenia.

## Features
- 🤖 AI-powered concierge (Nina) using Claude via OpenRouter
- 🏨 Room information and booking
- 🍳 Breakfast and dining info
- 🏔️ Local activities and experiences
- 🚐 Airport shuttle booking
- 🌿 Wellness info (sauna, massage, yoga)
- 🌐 Multi-language support (EN, SL, DE, IT, FR, ES, HR)
- 👤 Human agent handoff

## Setup

```bash
pip install -r requirements.txt
export LLM_API_KEY=your_openrouter_key
python app.py
```

## Deploy to Render
Connect this repo to Render. Set `LLM_API_KEY` as an environment variable.

## Tech Stack
- Python 3 + Flask
- OpenAI SDK → OpenRouter (Claude)
- SQLite for bookings
- Vanilla HTML/CSS/JS frontend
