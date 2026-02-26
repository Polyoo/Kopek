"""
trade_manager.py - Tracks open/closed trades, P&L, and balance
Persists state to trades.json for crash recovery
"""
import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
from config import TRADES_FILE

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    # Identifiers
    trade_id:       str
    condition_id:   str
    order_id:       str

    # Market info
    asset:          str    # BTC, ETH, SOL
    direction:      str    # UP, DOWN
    market_type:    str    # 5m, 15m
    market_label:   str    # "Feb 26, 11:35-11:40 AM ET"
    open_time_str:  str
    close_time_str: str

    # Order details
    buy_price:      float  # price per share (e.g. 0.98)
    shares:         float  # number of shares bought
    size_usdc:      float  # USDC spent

    # Polymarket token IDs
    yes_token_id:   str
    no_token_id:    str

    # Timing
    close_timestamp: float
    entry_time:      float

    # Binance reference
    binance_entry_price: float  # BTC/ETH/SOL price at entry

    # State
    status:         str    # "open", "cutloss", "win", "loss"
    sell_price:     Optional[float] = None
    pnl_usdc:       Optional[float] = None
    resolved_at:    Optional[float] = None
    cutloss_reason: Optional[str]   = None


class TradeManager:

    def __init__(self, starting_balance: float = 0.0):
        self.trades: Dict[str, Trade] = {}  # trade_id -> Trade
        self.balance: float = starting_balance
        self._trade_counter = 0
        self._load()

    def _load(self):
        """Load trades from disk."""
        if not os.path.exists(TRADES_FILE):
            return
        try:
            with open(TRADES_FILE, "r") as f:
                data = json.load(f)
            self.balance = data.get("balance", self.balance)
            self._trade_counter = data.get("counter", 0)
            for raw in data.get("trades", []):
                t = Trade(**raw)
                self.trades[t.trade_id] = t
            logger.info(f"Loaded {len(self.trades)} trades from disk")
        except Exception as e:
            logger.error(f"Trade load error: {e}")

    def _save(self):
        """Persist trades to disk."""
        try:
            data = {
                "balance":  self.balance,
                "counter":  self._trade_counter,
                "trades":   [asdict(t) for t in self.trades.values()],
            }
            with open(TRADES_FILE, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Trade save error: {e}")

    def _new_id(self) -> str:
        self._trade_counter += 1
        return f"T{self._trade_counter:04d}"

    # ── Open Trade ────────────────────────────────────────
    def open_trade(
        self,
        condition_id:        str,
        order_id:            str,
        asset:               str,
        direction:           str,
        market_type:         str,
        market_label:        str,
        open_time_str:       str,
        close_time_str:      str,
        buy_price:           float,
        shares:              float,
        size_usdc:           float,
        yes_token_id:        str,
        no_token_id:         str,
        close_timestamp:     float,
        binance_entry_price: float,
    ) -> Trade:
        trade = Trade(
            trade_id            = self._new_id(),
            condition_id        = condition_id,
            order_id            = order_id,
            asset               = asset,
            direction           = direction,
            market_type         = market_type,
            market_label        = market_label,
            open_time_str       = open_time_str,
            close_time_str      = close_time_str,
            buy_price           = buy_price,
            shares              = shares,
            size_usdc           = size_usdc,
            yes_token_id        = yes_token_id,
            no_token_id         = no_token_id,
            close_timestamp     = close_timestamp,
            entry_time          = time.time(),
            binance_entry_price = binance_entry_price,
            status              = "open",
        )
        # Deduct from balance (committed)
        self.balance -= size_usdc
        self.trades[trade.trade_id] = trade
        self._save()
        logger.info(f"Trade opened: {trade.trade_id} | {asset} {direction} {market_type} @ {buy_price}")
        return trade

    # ── Close Trade: Win ─────────────────────────────────
    def resolve_win(self, trade_id: str) -> Trade:
        """Market resolved YES = WIN. Payout = shares × 1.0."""
        t = self.trades[trade_id]
        t.sell_price  = 1.0
        t.pnl_usdc    = t.shares * (1.0 - t.buy_price)  # net profit
        t.status      = "win"
        t.resolved_at = time.time()
        self.balance += t.shares  # full payout
        self._save()
        logger.info(f"Trade WIN: {trade_id} | PnL: +{t.pnl_usdc:.4f} USDC")
        return t

    # ── Close Trade: Loss ─────────────────────────────────
    def resolve_loss(self, trade_id: str) -> Trade:
        """Market resolved NO = LOSS. Payout = 0."""
        t = self.trades[trade_id]
        t.sell_price  = 0.0
        t.pnl_usdc    = -(t.size_usdc)  # full loss of what we paid
        t.status      = "loss"
        t.resolved_at = time.time()
        # balance already reduced at entry, payout = 0
        self._save()
        logger.info(f"Trade LOSS: {trade_id} | PnL: {t.pnl_usdc:.4f} USDC")
        return t

    # ── Close Trade: Cut-Loss ─────────────────────────────
    def resolve_cutloss(self, trade_id: str, sell_price: float,
                        reason: str) -> Trade:
        """Cut-loss executed. Payout = shares × sell_price."""
        t = self.trades[trade_id]
        payout        = t.shares * sell_price
        t.sell_price  = sell_price
        t.pnl_usdc    = payout - t.size_usdc  # negative (loss)
        t.status      = "cutloss"
        t.resolved_at = time.time()
        t.cutloss_reason = reason
        self.balance  += payout
        self._save()
        logger.info(f"Trade CUTLOSS: {trade_id} | Sell@{sell_price} | PnL: {t.pnl_usdc:.4f}")
        return t

    # ── Getters ───────────────────────────────────────────
    def get_open_trades(self) -> List[Trade]:
        return [t for t in self.trades.values() if t.status == "open"]

    def get_open_by_condition(self, condition_id: str) -> Optional[Trade]:
        for t in self.trades.values():
            if t.condition_id == condition_id and t.status == "open":
                return t
        return None

    def already_traded(self, condition_id: str) -> bool:
        """Returns True if we already have/had a trade for this market."""
        return any(t.condition_id == condition_id for t in self.trades.values())

    def get_stats(self) -> dict:
        closed = [t for t in self.trades.values() if t.status != "open"]
        wins   = [t for t in closed if t.status == "win"]
        total_pnl = sum(t.pnl_usdc or 0 for t in closed)
        win_rate  = (len(wins) / len(closed) * 100) if closed else 0
        return {
            "total_trades": len(self.trades),
            "open":         len(self.get_open_trades()),
            "wins":         len(wins),
            "losses":       len([t for t in closed if t.status in ("loss", "cutloss")]),
            "win_rate":     win_rate,
            "total_pnl":    total_pnl,
            "balance":      self.balance,
        }

    def profit_cents_per_share(self, trade: Trade) -> float:
        """Calculate profit in cents per share."""
        sell = trade.sell_price or 0
        return (sell - trade.buy_price) * 100

    def set_balance(self, balance: float):
        self.balance = balance
        self._save()
