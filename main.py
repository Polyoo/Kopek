"""
main.py - Polymarket 5m/15m Crypto Bot Entry Point

Run: python main.py
"""
import asyncio
import logging
import signal
import sys
import time

# ── Configure logging first ────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", mode="a"),
    ]
)
logger = logging.getLogger("main")

import config
from binance_ws import binance_monitor
from polymarket_client import poly_client
from trade_manager import TradeManager
from strategy import Strategy
import telegram_notif as tg


# ── Startup Validation ─────────────────────────────────────
def preflight():
    logger.info("Running preflight checks...")

    # Validate env vars
    try:
        config.validate()
        logger.info("✅ Config OK")
    except ValueError as e:
        logger.critical(f"Config error: {e}")
        sys.exit(1)

    # Test Telegram
    ok = tg._send("🔄 <b>Polymarket Bot</b> — preflight check...")
    if not ok:
        logger.critical("Telegram test failed — check BOT_TOKEN and CHAT_ID")
        sys.exit(1)
    logger.info("✅ Telegram OK")

    # Test Polymarket (no auth needed for Gamma read)
    markets = poly_client.scan_markets()
    logger.info(f"✅ Polymarket Gamma OK — {len(markets)} markets found")

    # Init CLOB (requires auth)
    try:
        poly_client.init_clob()
        logger.info("✅ CLOB client OK")
    except Exception as e:
        logger.critical(f"CLOB init failed: {e}")
        tg.notify_error(f"CLOB init failed: {e}\n\nCheck API keys in .env")
        sys.exit(1)

    # Fetch balance
    balance = poly_client.get_usdc_balance()
    logger.info(f"✅ USDC Balance: ${balance:.2f}")

    return balance


# ── Main Async Orchestrator ───────────────────────────────
async def run(balance: float):
    trade_manager = TradeManager(starting_balance=balance)

    # Sync balance with on-chain
    trade_manager.set_balance(balance)

    strategy = Strategy(trade_manager)

    # Send startup notification
    tg.notify_startup(
        assets        = config.ASSETS,
        market_types  = config.MARKET_TYPES,
        buy_threshold = config.BUY_THRESHOLD,
        trade_size    = config.TRADE_SIZE_USDC,
    )

    logger.info("="*50)
    logger.info("🤖 Polymarket Bot Running")
    logger.info(f"Assets: {config.ASSETS}")
    logger.info(f"Markets: {config.MARKET_TYPES}")
    logger.info(f"Buy threshold: {config.BUY_THRESHOLD*100:.0f}¢")
    logger.info(f"Trade size: ${config.TRADE_SIZE_USDC}")
    logger.info(f"Cut-loss PM: {config.CUTLOSS_PM_PRICE*100:.0f}¢")
    logger.info(f"Cut-loss Binance: {config.CUTLOSS_BINANCE_PCT*100:.2f}%")
    logger.info(f"Entry window 5m: {config.ENTRY_SECONDS_5M}s before close")
    logger.info(f"Entry window 15m: {config.ENTRY_SECONDS_15M}s before close")
    logger.info("="*50)

    # Allow Binance streams to warm up before trading
    logger.info("Waiting 10s for Binance streams to warm up...")
    await asyncio.sleep(10)

    # Run all loops concurrently
    tasks = [
        asyncio.create_task(binance_monitor.start(),         name="binance_ws"),
        asyncio.create_task(strategy.market_scanner_loop(),  name="scanner"),
        asyncio.create_task(strategy.position_monitor_loop(), name="positions"),
        asyncio.create_task(strategy.outcome_checker_loop(), name="outcomes"),
        asyncio.create_task(strategy.status_reporter_loop(), name="status"),
    ]

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Bot shutting down...")
    finally:
        binance_monitor.stop()
        stats = trade_manager.get_stats()
        tg._send(
            f"🛑 <b>Bot Stopped</b>\n"
            f"Trades: {stats['total_trades']} | "
            f"W: {stats['wins']} / L: {stats['losses']}\n"
            f"P&L: {stats['total_pnl']:+.4f} USDC\n"
            f"Balance: ${stats['balance']:.2f}"
        )


def handle_signal(signum, frame):
    logger.info(f"Received signal {signum}. Shutting down...")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT,  handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Preflight
    balance = preflight()

    # Run
    try:
        asyncio.run(run(balance))
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        tg.notify_error(f"FATAL ERROR: {e}")
        sys.exit(1)
