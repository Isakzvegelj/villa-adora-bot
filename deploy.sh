#!/bin/bash
# Quick deploy script for Villa Adora Bled Hotel Bot
# Usage: ./deploy.sh

set -e

echo "🏔️  Villa Adora Bled — Hotel Bot Deploy"
echo ""

# Check if ollama is installed
if ! command -v ollama &> /dev/null; then
    echo "❌ Ollama not found. Install from https://ollama.ai"
    exit 1
fi

# Pull model if not present
if ! ollama list | grep -q "hotel-concierge"; then
    echo "📥 Pulling hotel-concierge model..."
    ollama pull hotel-concierge
else
    echo "✅ Model hotel-concierge already loaded"
fi

# Install Python dependencies
echo "📦 Installing Python dependencies..."
pip3 install -q -r requirements.txt

# Initialize database
echo "🗄️  Initializing database..."
python3 -c "from database import init_db; init_db()"

# Start services
echo ""
echo "🚀 Starting services..."
echo ""
echo "1. Terminal ONE — Ollama (keep running):"
echo "   ollama run hotel-concierge"
echo ""
echo "2. Terminal TWO — Web server:"
echo "   python3 app.py"
echo ""
echo "3. Terminal THREE — Public URL (optional):"
echo "   ngrok http 5000"
echo ""
echo "✅ Setup complete!"
echo ""
echo "📱 Test locally: http://localhost:5000"
echo "📊 View bookings: http://localhost:5000/api/bookings"
echo ""
echo "📖 See DEPLOY.md for full deployment options (VPS, PythonAnywhere, etc.)"
