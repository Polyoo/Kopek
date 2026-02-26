# 🤖 Polymarket 5m/15m Crypto Bot

Auto-trading bot for Polymarket BTC/ETH/SOL Up-or-Down markets.  
Monitors 5-minute and 15-minute markets, enters near close when price is ≥97¢,  
with Binance-based cut-loss and Telegram notifications.

---

## 📐 Strategy

```
ENTRY
  • Markets:  5-min & 15-min BTC / ETH / SOL Up-or-Down
  • Window:   ≤ 2 min before close (5m) | ≤ 5 min (15m)
  • Price:    YES ask ≥ 97¢ (configurable)
  • Filter:   Binance 1-min trend must not contradict direction
  • Order:    LIMIT GTC → MAKER → Zero fee

CUT-LOSS (either trigger)
  1. Binance drops 0.3%+ from entry price (UP market)
     or rises 0.3%+ (DOWN market)
  2. Polymarket YES bid drops below 80¢

EXIT
  • Market resolves YES → WIN  → profit ≈ 2–3¢ per share
  • Market resolves NO  → LOSS → total position value = 0
  • Cut-loss executed   → partial recovery

FEE ADVANTAGE
  • At 97-98¢, taker fee is ~0.05¢ per share (negligible)
  • LIMIT orders = MAKER = fee is ZERO
```

---

## 📊 Telegram Notifications

| Event | Example |
|-------|---------|
| Buy | 🟢 BUY \| BTC UP - 5 Minutes<br>📅 Feb 26, 11:35–11:40 AM ET<br>💰 98.0¢ / share \| $10.00 |
| Win | ✅ WIN \| Buy UP BTC - 5 Minutes<br>📈 Profit: **+1.89¢** per share<br>💼 Balance: $20.18 |
| Loss | ❌ LOSS \| Buy UP BTC - 5 Minutes<br>📉 Loss: -98.00¢<br>💼 Balance: $9.20 |
| Cut-loss | 🔴 CUT LOSS<br>📉 Binance BTC dropped -0.35%<br>💸 Buy: 98¢ → Sell: 83¢ |
| Status | 📊 Hourly summary with win rate & P&L |

---

## 📁 Project Structure

```
polymarket-bot/
├── main.py              # Entry point + orchestrator
├── config.py            # Environment config
├── strategy.py          # Core trading logic
├── polymarket_client.py # Gamma API + CLOB trading
├── binance_ws.py        # Binance real-time price feed
├── trade_manager.py     # Track trades & P&L (persisted to trades.json)
├── telegram_notif.py    # Telegram notifications
├── get_api_keys.py      # One-time key generation helper
├── setup.sh             # Install script (Termux/Linux)
├── requirements.txt
└── .env.example
```

---

## 🚀 Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/YOUR_USERNAME/polymarket-bot
cd polymarket-bot
bash setup.sh
```

### 2. Configure

```bash
nano .env
```

Fill in:
- `POLY_PRIVATE_KEY` — MetaMask/wallet private key (has USDC on Polygon)
- `TELEGRAM_BOT_TOKEN` — from @BotFather on Telegram
- `TELEGRAM_CHAT_ID` — your Telegram chat ID

### 3. Generate Polymarket API Keys (one-time)

```bash
python get_api_keys.py
# Paste output (KEY/SECRET/PASSPHRASE) into .env
```

### 4. Run

```bash
python main.py
```

---

## 📱 Termux (Android)

```bash
pkg install git python
git clone https://github.com/YOUR_USERNAME/polymarket-bot
cd polymarket-bot
bash setup.sh
nano .env
python get_api_keys.py
python main.py
```

To keep running after closing Termux:
```bash
# Install termux-services or use nohup:
nohup python main.py > bot.log 2>&1 &
echo "Bot PID: $!"
```

---

## ⚙️ Configuration (`.env`)

| Key | Default | Description |
|-----|---------|-------------|
| `BUY_THRESHOLD` | `0.97` | Minimum YES price to buy |
| `ENTRY_SECONDS_5M` | `120` | Seconds before close to enter 5m markets |
| `ENTRY_SECONDS_15M` | `300` | Seconds before close to enter 15m markets |
| `TRADE_SIZE_USDC` | `10.0` | USDC per trade |
| `CUTLOSS_PM_PRICE` | `0.80` | Cut-loss if Polymarket drops below this |
| `CUTLOSS_BINANCE_PCT` | `0.003` | Cut-loss on 0.3% Binance adverse move |
| `ASSETS` | `BTC,ETH,SOL` | Assets to trade |
| `MARKET_TYPES` | `5m,15m` | Market durations to watch |

---

## ⚠️ Risk Warning

- These are **binary prediction markets** — you can lose 100% of each trade
- The strategy requires very high probability (>98.6%) to be profitable long-term
- Past performance is not indicative of future results
- Not financial advice — trade at your own risk
- Check Polymarket ToS for your jurisdiction

---

## 📜 License

MIT
