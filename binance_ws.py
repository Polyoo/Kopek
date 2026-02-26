"""
binance_ws.py - Real-time Binance price feed via WebSocket
Tracks BTC, ETH, SOL prices for cut-loss logic
"""
import asyncio
import json
import logging
import time
import websockets
from typing import Callable, Dict, Optional

from config import ASSETS, ASSET_SYMBOLS, BINANCE_WS_BASE

logger = logging.getLogger(__name__)


class BinancePriceMonitor:
    """
    Subscribes to Binance aggTrade streams for configured assets.
    Maintains latest price and 1-minute price history for trend detection.
    """

    def __init__(self):
        self.prices: Dict[str, float] = {}          # Latest price per asset
        self.price_at_buy: Dict[str, float] = {}    # Reference price when trade was entered
        self.price_history: Dict[str, list] = {}    # Last 60 ticks per asset
        self._running = False
        self._callbacks: list = []                  # Cut-loss alert callbacks

    @property
    def running(self):
        return self._running

    def get_price(self, asset: str) -> Optional[float]:
        return self.prices.get(asset)

    def set_reference_price(self, asset: str):
        """Call this when a trade is entered to record reference price."""
        if asset in self.prices:
            self.price_at_buy[asset] = self.prices[asset]
            logger.info(f"Reference price set for {asset}: ${self.prices[asset]:.2f}")

    def clear_reference_price(self, asset: str):
        self.price_at_buy.pop(asset, None)

    def get_change_pct(self, asset: str) -> Optional[float]:
        """
        Returns price change % since trade entry.
        Positive = price went up, Negative = price went down.
        """
        current = self.prices.get(asset)
        ref = self.price_at_buy.get(asset)
        if current is None or ref is None or ref == 0:
            return None
        return (current - ref) / ref

    def register_cutloss_callback(self, callback: Callable):
        """
        Register a callback to be called when cut-loss conditions are met.
        callback(asset, direction, change_pct)
        """
        self._callbacks.append(callback)

    def _check_cutloss(self, asset: str):
        """Internal: check if cut-loss should be triggered."""
        from config import CUTLOSS_BINANCE_PCT
        change = self.get_change_pct(asset)
        if change is None:
            return
        # Will be filtered by direction in strategy.py
        if abs(change) >= CUTLOSS_BINANCE_PCT:
            for cb in self._callbacks:
                try:
                    cb(asset, change)
                except Exception as e:
                    logger.error(f"Cut-loss callback error: {e}")

    def _process_tick(self, asset: str, price: float):
        """Update price state and check conditions."""
        self.prices[asset] = price
        history = self.price_history.setdefault(asset, [])
        history.append((time.time(), price))
        # Keep last 120 ticks (~2 min at 1/sec)
        if len(history) > 120:
            history.pop(0)
        # Check cut-loss trigger
        self._check_cutloss(asset)

    def get_1min_trend(self, asset: str) -> Optional[float]:
        """
        Returns price change % over last ~60 seconds.
        Useful for momentum check before entering trade.
        """
        history = self.price_history.get(asset, [])
        if len(history) < 10:
            return None
        now = time.time()
        one_min_ago = now - 60
        old_ticks = [p for t, p in history if t <= one_min_ago]
        if not old_ticks:
            return None
        old_price = old_ticks[-1]
        current = self.prices.get(asset)
        if not current or old_price == 0:
            return None
        return (current - old_price) / old_price

    async def _stream_asset(self, asset: str, symbol: str):
        """Maintain WebSocket connection for a single asset."""
        stream_url = f"{BINANCE_WS_BASE}/{symbol.lower()}@aggTrade"
        while self._running:
            try:
                logger.info(f"Connecting Binance WS: {symbol}")
                async with websockets.connect(
                    stream_url,
                    ping_interval=20,
                    ping_timeout=10
                ) as ws:
                    logger.info(f"✅ Binance {symbol} stream connected")
                    async for raw in ws:
                        if not self._running:
                            break
                        data = json.loads(raw)
                        price = float(data.get("p", 0))
                        if price > 0:
                            self._process_tick(asset, price)

            except websockets.exceptions.ConnectionClosed:
                logger.warning(f"Binance {symbol} WS closed, reconnecting...")
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Binance {symbol} WS error: {e}")
                await asyncio.sleep(5)

    async def start(self):
        """Start WebSocket streams for all configured assets."""
        self._running = True
        tasks = []
        for asset in ASSETS:
            symbol = ASSET_SYMBOLS.get(asset)
            if symbol:
                tasks.append(self._stream_asset(asset, symbol))
        logger.info(f"Starting Binance price monitor for: {ASSETS}")
        await asyncio.gather(*tasks)

    def stop(self):
        self._running = False


# ── Singleton ──────────────────────────────────────────────
binance_monitor = BinancePriceMonitor()
