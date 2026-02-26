#!/bin/bash
# ============================================================
# setup.sh - Termux / Linux setup for Polymarket Bot
# Run once: bash setup.sh
# ============================================================

echo "🤖 Polymarket Bot Setup"
echo "========================"

# ── Termux packages ────────────────────────────────────────
if command -v pkg &> /dev/null; then
    echo "📦 Detected Termux, installing system packages..."
    pkg update -y
    pkg install -y python python-pip git openssl libffi
else
    echo "📦 Linux detected..."
    # Ubuntu/Debian
    if command -v apt-get &> /dev/null; then
        sudo apt-get update
        sudo apt-get install -y python3 python3-pip git libssl-dev libffi-dev
    fi
fi

# ── Python virtual env ─────────────────────────────────────
echo ""
echo "🐍 Setting up Python environment..."
python -m venv venv 2>/dev/null || python3 -m venv venv

# Activate
source venv/bin/activate 2>/dev/null || source venv/Scripts/activate 2>/dev/null

# Upgrade pip
pip install --upgrade pip

# ── Install dependencies ───────────────────────────────────
echo ""
echo "📦 Installing Python packages..."
pip install -r requirements.txt

echo ""
echo "✅ Installation complete!"

# ── Setup .env ─────────────────────────────────────────────
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "📝 Created .env from .env.example"
    echo "   → Edit .env and fill in your API keys:"
    echo "      nano .env"
else
    echo "ℹ️  .env already exists — skipping"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 Next steps:"
echo "   1. nano .env          (fill in API keys)"
echo "   2. python main.py     (start the bot)"
echo ""
echo "📋 Key settings in .env:"
echo "   POLY_PRIVATE_KEY    - Your wallet private key"
echo "   POLY_API_KEY        - Polymarket CLOB API key"
echo "   TELEGRAM_BOT_TOKEN  - From @BotFather"
echo "   TELEGRAM_CHAT_ID    - Your chat ID"
echo "   TRADE_SIZE_USDC     - $ per trade (default: 10)"
echo "   BUY_THRESHOLD       - Min price to buy (default: 0.97)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📘 Get Polymarket API keys:"
echo "   https://docs.polymarket.com/developers/CLOB/clob-client"
echo "   Run: python get_api_keys.py  (after adding POLY_PRIVATE_KEY)"
