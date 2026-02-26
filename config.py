"""
config.py - Load and validate all environment variables
"""
import os
from dotenv import load_dotenv

load_dotenv()

# --- POLYMARKET ---
POLY_PRIVATE_KEY    = os.getenv("POLY_PRIVATE_KEY", "")
POLY_API_KEY        = os.getenv("POLY_API_KEY", "")
POLY_API_SECRET     = os.getenv("POLY_API_SECRET", "")
POLY_API_PASSPHRASE = os.getenv("POLY_API_PASSPHRASE", "")

# Polymarket API endpoints
GAMMA_API_URL = "https://gamma-api.polymarket.com"
CLOB_HOST     = "https://clob.polymarket.com"
CHAIN_ID      = 137  # Polygon mainnet

# --- TELEGRAM ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# --- STRATEGY ---
BUY_THRESHOLD       = float(os.getenv("BUY_THRESHOLD", "0.97"))
ENTRY_SECONDS_5M    = int(os.getenv("ENTRY_SECONDS_5M", "120"))    # 2 min
ENTRY_SECONDS_15M   = int(os.getenv("ENTRY_SECONDS_15M", "300"))   # 5 min
TRADE_SIZE_USDC     = float(os.getenv("TRADE_SIZE_USDC", "10.0"))
CUTLOSS_PM_PRICE    = float(os.getenv("CUTLOSS_PM_PRICE", "0.80"))
CUTLOSS_BINANCE_PCT = float(os.getenv("CUTLOSS_BINANCE_PCT", "0.003"))

# Assets & market types
_assets       = os.getenv("ASSETS", "BTC,ETH,SOL").upper()
_market_types = os.getenv("MARKET_TYPES", "5m,15m").lower()
ASSETS        = [a.strip() for a in _assets.split(",")]
MARKET_TYPES  = [m.strip() for m in _market_types.split(",")]

# --- BINANCE WebSocket streams ---
BINANCE_WS_BASE = "wss://stream.binance.com:9443/ws"

ASSET_SYMBOLS = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
}

# Keyword patterns to match Polymarket market questions
# e.g. "Will BTC go up or down in the next 5 minutes?"
MARKET_KEYWORDS = {
    "5m":  ["5 minute", "5-minute", "5min", "next 5"],
    "15m": ["15 minute", "15-minute", "15min", "next 15"],
}

# Polling intervals (seconds)
MARKET_POLL_INTERVAL    = 20   # How often to scan for new markets
POSITION_POLL_INTERVAL  = 5    # How often to check open positions
OUTCOME_POLL_INTERVAL   = 10   # How often to check resolved markets

# File paths
TRADES_FILE = "trades.json"
LOG_FILE    = "bot.log"

def validate():
    missing = []
    for key in ["POLY_PRIVATE_KEY", "POLY_API_KEY", "POLY_API_SECRET",
                "POLY_API_PASSPHRASE", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]:
        if not globals()[key]:
            missing.append(key)
    if missing:
        raise ValueError(f"Missing required config: {', '.join(missing)}")
