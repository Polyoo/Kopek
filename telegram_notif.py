"""
telegram_notif.py - Send Telegram notifications for all bot events
"""
import logging
import requests
from datetime import datetime
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _send(text: str) -> bool:
    """Send a raw message to Telegram."""
    try:
        resp = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        if not resp.ok:
            logger.error(f"Telegram error: {resp.text}")
            return False
        return True
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


def notify_buy(asset: str, direction: str, market_type: str,
               price: float, size: float, market_label: str,
               open_time: str, close_time: str, balance: float):
    """
    Notification when bot buys a position.

    Example:
    🟢 BUY | BTC Up or Down - 5 Minutes
    📅 Feb 26, 11:35–11:40 AM ET
    💰 98.0¢ / share | Size: $10.00
    💼 Balance: $20.18
    """
    emoji = "🟢"
    dir_str = f"{asset} {'📈 UP' if direction == 'UP' else '📉 DOWN'} or Down"
    msg = (
        f"{emoji} <b>BUY</b> | {dir_str} - {market_type}\n"
        f"📅 {market_label}\n"
        f"⏰ {open_time} → {close_time}\n"
        f"💰 {price*100:.1f}¢ / share | Size: <b>${size:.2f}</b>\n"
        f"💼 Balance: <b>${balance:.2f}</b>"
    )
    _send(msg)


def notify_cutloss(asset: str, direction: str, market_type: str,
                   buy_price: float, sell_price: float, loss: float,
                   reason: str, balance: float):
    """
    Notification when bot cuts loss.
    """
    msg = (
        f"🔴 <b>CUT LOSS</b> | {asset} {direction} - {market_type}\n"
        f"📉 Reason: {reason}\n"
        f"💸 Buy: {buy_price*100:.1f}¢ → Sell: {sell_price*100:.1f}¢\n"
        f"❌ Loss: <b>-{abs(loss)*100:.2f}¢</b> per share\n"
        f"💼 Balance: <b>${balance:.2f}</b>"
    )
    _send(msg)


def notify_outcome_win(asset: str, direction: str, market_type: str,
                       buy_price: float, profit_cents: float,
                       market_label: str, open_time: str, close_time: str,
                       balance: float):
    """
    Notification when position resolves as WIN.
    """
    msg = (
        f"✅ <b>WIN</b> | Buy {direction} {asset} Up or Down - {market_type}\n"
        f"📅 {market_label}\n"
        f"⏰ {open_time} → {close_time}\n"
        f"💰 {buy_price*100:.1f}¢ → $1.00\n"
        f"📈 Profit: <b>+{profit_cents:.2f}¢</b> per share\n"
        f"💼 Current Balance: <b>${balance:.2f}</b>"
    )
    _send(msg)


def notify_outcome_loss(asset: str, direction: str, market_type: str,
                        buy_price: float, loss_cents: float,
                        market_label: str, open_time: str, close_time: str,
                        balance: float):
    """
    Notification when position resolves as LOSS (expired NO).
    """
    msg = (
        f"❌ <b>LOSS</b> | Buy {direction} {asset} Up or Down - {market_type}\n"
        f"📅 {market_label}\n"
        f"⏰ {open_time} → {close_time}\n"
        f"💰 Paid: {buy_price*100:.1f}¢ → resolved $0.00\n"
        f"📉 Loss: <b>-{abs(loss_cents):.2f}¢</b> per share\n"
        f"💼 Current Balance: <b>${balance:.2f}</b>"
    )
    _send(msg)


def notify_startup(assets: list, market_types: list, buy_threshold: float,
                   trade_size: float):
    """Send startup notification."""
    msg = (
        f"🤖 <b>Polymarket Bot Started</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"📊 Assets: {', '.join(assets)}\n"
        f"⏱ Markets: {', '.join(market_types)}\n"
        f"🎯 Buy threshold: ≥ {buy_threshold*100:.0f}¢\n"
        f"💵 Trade size: ${trade_size:.2f} USDC\n"
        f"━━━━━━━━━━━━━━\n"
        f"✅ Monitoring active..."
    )
    _send(msg)


def notify_error(error_msg: str):
    """Send error notification."""
    _send(f"⚠️ <b>BOT ERROR</b>\n{error_msg[:500]}")


def notify_status(active_positions: int, watched_markets: int,
                  total_trades: int, win_rate: float,
                  total_pnl: float, balance: float):
    """Hourly status update."""
    sign = "+" if total_pnl >= 0 else ""
    msg = (
        f"📊 <b>Status Update</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"👁 Watching: {watched_markets} markets\n"
        f"📂 Open positions: {active_positions}\n"
        f"🔢 Total trades: {total_trades}\n"
        f"🏆 Win rate: {win_rate:.1f}%\n"
        f"💹 Total P&L: <b>{sign}{total_pnl:.4f} USDC</b>\n"
        f"💼 Balance: <b>${balance:.2f}</b>\n"
        f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    )
    _send(msg)
