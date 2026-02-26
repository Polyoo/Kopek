"""
strategy.py - Core trading strategy engine

STRATEGY LOGIC:
──────────────────────────────────────────────────────────────
ENTRY:
  • Scan 5m and 15m BTC/ETH/SOL markets
  • Entry window: ≤ 2 min before close (5m), ≤ 5 min (15m)
  • Entry condition: YES ask price ≥ BUY_THRESHOLD (e.g. 97¢)
  • Binance momentum check: 1-min trend must align with direction
  • Order: LIMIT (GTC = maker = no fee)

CUT-LOSS TRIGGER (any one):
  1. Binance price drops > CUTLOSS_BINANCE_PCT% from entry (UP market)
     OR rises > CUTLOSS_BINANCE_PCT% from entry (DOWN market)
  2. Polymarket YES best bid drops below CUTLOSS_PM_PRICE

EXIT (Market Close):
  • Poll Gamma API after close_time until resolved
  • WIN: YES → $1.00  →  pnl = shares × (1 - buy_price)
  • LOSS: YES → $0.00 →  pnl = -size_usdc

FEE ESTIMATE:
  fee ≈ p × (1 - p) × 0.0016 (CLOB taker fee)
  At p=0.97: fee ≈ 0.97 × 0.03 × 0.0016 ≈ 0.000047 per share (negligible)
  Using LIMIT orders (GTC) → MAKER → fee = 0
──────────────────────────────────────────────────────────────
"""

import asyncio
import logging
import time
from typing import Optional, Set

from config import (
    BUY_THRESHOLD, ENTRY_SECONDS_5M, ENTRY_SECONDS_15M,
    TRADE_SIZE_USDC, CUTLOSS_PM_PRICE, CUTLOSS_BINANCE_PCT,
    MARKET_POLL_INTERVAL, POSITION_POLL_INTERVAL, OUTCOME_POLL_INTERVAL,
)
from polymarket_client import poly_client, MarketInfo
from binance_ws import binance_monitor
from trade_manager import TradeManager, Trade
import telegram_notif as tg

logger = logging.getLogger(__name__)


class Strategy:

    def __init__(self, trade_manager: TradeManager):
        self.tm          = trade_manager
        self._active_markets: dict = {}   # condition_id -> MarketInfo
        self._pending_outcomes: Set[str] = set()  # condition_ids pending resolution
        self._last_scan   = 0.0
        self._last_status = 0.0

    # ── Entry Conditions ──────────────────────────────────

    def _get_entry_window(self, market_type: str) -> int:
        return ENTRY_SECONDS_5M if market_type == "5m" else ENTRY_SECONDS_15M

    def _should_enter(self, market: MarketInfo) -> tuple:
        """
        Returns (should_enter: bool, reason: str)
        Checks all entry conditions.
        """
        seconds_left = market.seconds_to_close

        # ── 1. Time window check ──
        window = self._get_entry_window(market.market_type)
        if seconds_left > window:
            return False, f"Too early: {seconds_left:.0f}s left (window={window}s)"
        if seconds_left <= 5:
            return False, "Too late (<5s): market about to close"

        # ── 2. Already traded this market? ──
        if self.tm.already_traded(market.condition_id):
            return False, "Already traded this market"

        # ── 3. Price threshold check ──
        ask = poly_client.get_best_ask(market.yes_token_id)
        if ask is None:
            return False, "Could not fetch order book"
        if ask < BUY_THRESHOLD:
            return False, f"Price too low: {ask:.2f} < {BUY_THRESHOLD:.2f}"
        if ask >= 1.0:
            return False, "Price at $1 — already resolved or invalid"

        # ── 4. Spread check ──
        book = poly_client.get_orderbook_depth(market.yes_token_id)
        if book["spread"] and book["spread"] > 0.05:
            return False, f"Spread too wide: {book['spread']:.3f}"

        # ── 5. Binance momentum check ──
        trend = binance_monitor.get_1min_trend(market.asset)
        if trend is not None:
            if market.direction == "UP" and trend < -0.002:
                return False, f"Binance {market.asset} dropping: {trend:.3%}"
            if market.direction == "DOWN" and trend > 0.002:
                return False, f"Binance {market.asset} rising: {trend:.3%}"

        # ── 6. Binance price available? ──
        binance_price = binance_monitor.get_price(market.asset)
        if binance_price is None:
            return False, f"Binance {market.asset} price not available yet"

        return True, f"✅ Entry OK | ask={ask:.3f} | {market.asset} trend={trend}"

    # ── Execute Buy ───────────────────────────────────────

    async def _execute_buy(self, market: MarketInfo):
        """Place a buy order and record the trade."""
        ask = poly_client.get_best_ask(market.yes_token_id)
        if ask is None or ask < BUY_THRESHOLD:
            logger.warning("Price moved before order — aborting")
            return

        binance_price = binance_monitor.get_price(market.asset) or 0.0

        logger.info(
            f"🟢 BUYING {market.asset} {market.direction} "
            f"{market.market_type} @ {ask:.3f} | "
            f"size=${TRADE_SIZE_USDC}"
        )

        # Place order
        try:
            order = poly_client.buy_yes(market, ask, TRADE_SIZE_USDC)
        except Exception as e:
            logger.error(f"Order failed: {e}")
            tg.notify_error(f"BUY ORDER FAILED: {e}")
            return

        # Record trade
        trade = self.tm.open_trade(
            condition_id        = market.condition_id,
            order_id            = order["order_id"],
            asset               = market.asset,
            direction           = market.direction,
            market_type         = market.market_type,
            market_label        = market.market_label,
            open_time_str       = market.open_time_str,
            close_time_str      = market.close_time_str,
            buy_price           = ask,
            shares              = order["size"],
            size_usdc           = TRADE_SIZE_USDC,
            yes_token_id        = market.yes_token_id,
            no_token_id         = market.no_token_id,
            close_timestamp     = market.close_time,
            binance_entry_price = binance_price,
        )

        # Set Binance reference price for cut-loss tracking
        binance_monitor.set_reference_price(market.asset)

        # Add to pending outcomes
        self._pending_outcomes.add(market.condition_id)

        # Telegram notification
        tg.notify_buy(
            asset        = market.asset,
            direction    = market.direction,
            market_type  = "5 Minutes" if market.market_type == "5m" else "15 Minutes",
            price        = ask,
            size         = TRADE_SIZE_USDC,
            market_label = market.market_label,
            open_time    = market.open_time_str,
            close_time   = market.close_time_str,
            balance      = self.tm.balance,
        )

    # ── Cut-Loss Logic ─────────────────────────────────────

    def _check_cutloss(self, trade: Trade) -> Optional[str]:
        """
        Returns cut-loss reason string if triggered, else None.
        Called for each open trade on every position poll.
        """
        # 1. Polymarket price drop
        ask = poly_client.get_best_ask(trade.yes_token_id)
        if ask is not None and ask < CUTLOSS_PM_PRICE:
            return f"Polymarket YES dropped to {ask:.2f} < threshold {CUTLOSS_PM_PRICE:.2f}"

        # 2. Binance adverse move
        change_pct = binance_monitor.get_change_pct(trade.asset)
        if change_pct is not None:
            if trade.direction == "UP" and change_pct <= -CUTLOSS_BINANCE_PCT:
                return (
                    f"Binance {trade.asset} dropped {change_pct:.3%} since entry "
                    f"(threshold: -{CUTLOSS_BINANCE_PCT:.2%})"
                )
            if trade.direction == "DOWN" and change_pct >= CUTLOSS_BINANCE_PCT:
                return (
                    f"Binance {trade.asset} rose {change_pct:.3%} since entry "
                    f"(threshold: +{CUTLOSS_BINANCE_PCT:.2%})"
                )
        return None

    async def _execute_cutloss(self, trade: Trade, reason: str):
        """Execute a cut-loss sell order."""
        logger.warning(f"⚠️ CUT LOSS: {trade.trade_id} | {reason}")

        # Get current best bid to sell into
        book = poly_client.get_orderbook_depth(trade.yes_token_id)
        bids = book.get("bids", [])
        # Sell at best bid, or 1¢ below ask (aggresive)
        sell_price = bids[0][0] if bids else 0.01
        sell_price = max(sell_price, 0.01)  # never sell for nothing

        try:
            # Reconstruct market info stub for sell order
            class _MarketStub:
                yes_token_id = trade.yes_token_id
                no_token_id  = trade.no_token_id
            poly_client.sell_yes(_MarketStub(), sell_price, trade.shares, order_type="FOK")
        except Exception as e:
            logger.error(f"Cut-loss sell failed: {e}")
            # Even if sell fails, record in trade for tracking
            sell_price = 0.0

        # Record in trade manager
        closed = self.tm.resolve_cutloss(trade.trade_id, sell_price, reason)

        # Clear Binance reference
        binance_monitor.clear_reference_price(trade.asset)
        self._pending_outcomes.discard(trade.condition_id)

        # Telegram
        tg.notify_cutloss(
            asset        = trade.asset,
            direction    = trade.direction,
            market_type  = "5 Minutes" if trade.market_type == "5m" else "15 Minutes",
            buy_price    = trade.buy_price,
            sell_price   = sell_price,
            loss         = closed.pnl_usdc,
            reason       = reason,
            balance      = self.tm.balance,
        )

    # ── Outcome Resolution ────────────────────────────────

    async def _check_outcomes(self):
        """
        After markets close, poll until resolved and send result notification.
        """
        resolved_ids = set()
        for trade in self.tm.get_open_trades():
            if trade.condition_id not in self._pending_outcomes:
                continue
            # Only start checking after close time
            if time.time() < trade.close_timestamp:
                continue
            # Check resolution
            outcome = poly_client.check_market_resolved(trade.condition_id)
            if outcome is None:
                continue  # Not resolved yet

            resolved_ids.add(trade.condition_id)
            binance_monitor.clear_reference_price(trade.asset)

            if outcome == "YES":
                closed = self.tm.resolve_win(trade.trade_id)
                profit_cents = self.tm.profit_cents_per_share(closed)
                tg.notify_outcome_win(
                    asset        = trade.asset,
                    direction    = trade.direction,
                    market_type  = "5 Minutes" if trade.market_type == "5m" else "15 Minutes",
                    buy_price    = trade.buy_price,
                    profit_cents = profit_cents,
                    market_label = trade.market_label,
                    open_time    = trade.open_time_str,
                    close_time   = trade.close_time_str,
                    balance      = self.tm.balance,
                )
            else:
                closed = self.tm.resolve_loss(trade.trade_id)
                loss_cents = abs(self.tm.profit_cents_per_share(closed))
                tg.notify_outcome_loss(
                    asset        = trade.asset,
                    direction    = trade.direction,
                    market_type  = "5 Minutes" if trade.market_type == "5m" else "15 Minutes",
                    buy_price    = trade.buy_price,
                    loss_cents   = loss_cents,
                    market_label = trade.market_label,
                    open_time    = trade.open_time_str,
                    close_time   = trade.close_time_str,
                    balance      = self.tm.balance,
                )

        self._pending_outcomes -= resolved_ids

    # ── Main Loop Tasks ───────────────────────────────────

    async def market_scanner_loop(self):
        """Continuously scan for new tradeable markets."""
        logger.info("Market scanner started")
        while True:
            try:
                markets = poly_client.scan_markets()
                for m in markets:
                    self._active_markets[m.condition_id] = m

                # Check each tracked market for entry
                for market in list(self._active_markets.values()):
                    if market.is_expired():
                        self._active_markets.pop(market.condition_id, None)
                        continue
                    if self.tm.already_traded(market.condition_id):
                        continue

                    ok, reason = self._should_enter(market)
                    if ok:
                        logger.info(f"Entry signal: {market.market_label} | {reason}")
                        await self._execute_buy(market)
                    else:
                        logger.debug(f"Skip {market.market_label}: {reason}")

            except Exception as e:
                logger.error(f"Scanner error: {e}")
                tg.notify_error(f"Scanner error: {e}")

            await asyncio.sleep(MARKET_POLL_INTERVAL)

    async def position_monitor_loop(self):
        """Monitor open positions for cut-loss conditions."""
        logger.info("Position monitor started")
        while True:
            try:
                for trade in self.tm.get_open_trades():
                    # Skip if market already closed (handled by outcome checker)
                    if time.time() >= trade.close_timestamp + 30:
                        continue
                    reason = self._check_cutloss(trade)
                    if reason:
                        await self._execute_cutloss(trade, reason)
            except Exception as e:
                logger.error(f"Position monitor error: {e}")

            await asyncio.sleep(POSITION_POLL_INTERVAL)

    async def outcome_checker_loop(self):
        """Poll for market resolutions after close time."""
        logger.info("Outcome checker started")
        while True:
            try:
                await self._check_outcomes()
            except Exception as e:
                logger.error(f"Outcome checker error: {e}")

            await asyncio.sleep(OUTCOME_POLL_INTERVAL)

    async def status_reporter_loop(self):
        """Send hourly status report to Telegram."""
        while True:
            await asyncio.sleep(3600)
            try:
                stats = self.tm.get_stats()
                tg.notify_status(
                    active_positions = stats["open"],
                    watched_markets  = len(self._active_markets),
                    total_trades     = stats["total_trades"],
                    win_rate         = stats["win_rate"],
                    total_pnl        = stats["total_pnl"],
                    balance          = stats["balance"],
                )
            except Exception as e:
                logger.error(f"Status reporter error: {e}")
