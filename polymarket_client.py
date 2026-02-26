"""
polymarket_client.py - Polymarket Gamma + CLOB integration
Handles: market discovery, order book reading, order placement
"""
import logging
import time
import requests
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

from config import (
    GAMMA_API_URL, CLOB_HOST, CHAIN_ID,
    POLY_PRIVATE_KEY, POLY_API_KEY, POLY_API_SECRET, POLY_API_PASSPHRASE,
    ASSETS, MARKET_TYPES, MARKET_KEYWORDS,
)

logger = logging.getLogger(__name__)

# ── Lazy import py-clob-client ─────────────────────────────
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import (
        ApiCreds, OrderArgs, OrderType, BalanceAllowanceParams, AssetType
    )
    from py_clob_client.constants import BUY, SELL
    CLOB_AVAILABLE = True
except ImportError:
    CLOB_AVAILABLE = False
    logger.warning("py-clob-client not installed. Trading disabled.")


# ── Market Data Structures ─────────────────────────────────
class MarketInfo:
    """Represents an active Polymarket 5m/15m crypto market."""
    __slots__ = [
        "condition_id", "question", "slug",
        "asset", "direction", "market_type",
        "yes_token_id", "no_token_id",
        "close_time", "close_dt",
        "best_ask", "best_bid", "last_price",
        "open_time_str", "close_time_str"
    ]

    def __init__(self, raw: dict, asset: str, direction: str, market_type: str):
        self.condition_id = raw.get("conditionId", "")
        self.question     = raw.get("question", "")
        self.slug         = raw.get("slug", "")
        self.asset        = asset
        self.direction    = direction   # "UP" or "DOWN"
        self.market_type  = market_type # "5m" or "15m"

        # Parse tokens
        tokens = raw.get("tokens", [])
        self.yes_token_id = ""
        self.no_token_id  = ""
        for t in tokens:
            outcome = t.get("outcome", "").upper()
            if outcome == "YES":
                self.yes_token_id = t.get("token_id", "")
            elif outcome == "NO":
                self.no_token_id  = t.get("token_id", "")

        # Close time
        raw_end = raw.get("endDate") or raw.get("end_date_iso") or raw.get("end_date", "")
        try:
            self.close_dt = datetime.fromisoformat(raw_end.replace("Z", "+00:00"))
        except Exception:
            self.close_dt = None
        self.close_time = self.close_dt.timestamp() if self.close_dt else 0

        # Estimate open time (close - market_type duration)
        dur = 5 * 60 if market_type == "5m" else 15 * 60
        if self.close_dt:
            open_dt = datetime.fromtimestamp(self.close_time - dur, tz=timezone.utc)
            self.open_time_str  = open_dt.strftime("%b %d, %I:%M %p ET").replace(" 0", " ")
            self.close_time_str = self.close_dt.strftime("%I:%M %p ET").replace(" 0", " ")
        else:
            self.open_time_str  = "N/A"
            self.close_time_str = "N/A"

        # Prices (refreshed separately)
        self.best_ask  = float(raw.get("bestAsk", 1.0))
        self.best_bid  = float(raw.get("bestBid", 0.0))
        self.last_price = float(raw.get("lastTradePrice", 0.0))

    @property
    def seconds_to_close(self) -> float:
        return max(0, self.close_time - time.time())

    @property
    def market_label(self):
        dur = "5 Minutes" if self.market_type == "5m" else "15 Minutes"
        return f"{self.asset} Up or Down - {dur}"

    def is_expired(self) -> bool:
        return time.time() >= self.close_time


# ── Polymarket Client ──────────────────────────────────────
class PolymarketClient:

    def __init__(self):
        self._clob: Optional[Any] = None
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "PolymarketBot/1.0"

    def init_clob(self):
        """Initialize the CLOB trading client."""
        if not CLOB_AVAILABLE:
            raise RuntimeError("py-clob-client not installed")
        if self._clob:
            return
        creds = ApiCreds(
            api_key=POLY_API_KEY,
            api_secret=POLY_API_SECRET,
            api_passphrase=POLY_API_PASSPHRASE,
        )
        self._clob = ClobClient(
            host=CLOB_HOST,
            key=POLY_PRIVATE_KEY,
            chain_id=CHAIN_ID,
            creds=creds,
        )
        # Verify connection
        try:
            self._clob.get_ok()
            logger.info("✅ CLOB client connected")
        except Exception as e:
            raise RuntimeError(f"CLOB connection failed: {e}")

    # ── Market Discovery ───────────────────────────────────
    def _fetch_active_markets(self, limit: int = 200) -> List[dict]:
        """Fetch active (non-closed) markets from Gamma API."""
        try:
            resp = self._session.get(
                f"{GAMMA_API_URL}/markets",
                params={
                    "active":   "true",
                    "closed":   "false",
                    "archived": "false",
                    "limit":    limit,
                    "_order":   "endDate",
                    "_asc":     "true",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            # Gamma may return list directly or {data: [...]}
            if isinstance(data, list):
                return data
            return data.get("data", data.get("markets", []))
        except Exception as e:
            logger.error(f"Gamma API fetch error: {e}")
            return []

    def _classify_market(self, market: dict) -> Optional[tuple]:
        """
        Returns (asset, direction, market_type) if this is a matching
        5m/15m crypto up/down market, else None.
        """
        q = market.get("question", "").upper()
        slug = market.get("slug", "").lower()

        # Match asset
        matched_asset = None
        for asset in ASSETS:
            if asset in q or asset.lower() in slug:
                matched_asset = asset
                break
        if not matched_asset:
            return None

        # Match market type
        matched_type = None
        for mtype in MARKET_TYPES:
            for kw in MARKET_KEYWORDS.get(mtype, []):
                if kw.lower() in q.lower() or kw.lower() in slug:
                    matched_type = mtype
                    break
            if matched_type:
                break
        if not matched_type:
            return None

        # Must be an up/down market
        if "UP" not in q and "DOWN" not in q and "up" not in slug and "down" not in slug:
            return None

        # Check if still open and relevant close time
        raw_end = market.get("endDate") or market.get("end_date_iso", "")
        if not raw_end:
            return None
        try:
            close_dt = datetime.fromisoformat(raw_end.replace("Z", "+00:00"))
            remaining = close_dt.timestamp() - time.time()
            # Only care about markets closing in the future
            if remaining <= 0:
                return None
        except Exception:
            return None

        # Determine direction from question/slug
        if "UP" in q or "up" in slug:
            direction = "UP"
        else:
            direction = "DOWN"

        return (matched_asset, direction, matched_type)

    def scan_markets(self) -> List[MarketInfo]:
        """Scan and return all relevant active crypto 5m/15m markets."""
        raw_markets = self._fetch_active_markets()
        results = []
        seen_conditions = set()

        for m in raw_markets:
            classified = self._classify_market(m)
            if not classified:
                continue
            asset, direction, market_type = classified
            cid = m.get("conditionId", "")
            if cid in seen_conditions:
                continue
            seen_conditions.add(cid)
            try:
                info = MarketInfo(m, asset, direction, market_type)
                if info.seconds_to_close > 0 and info.yes_token_id:
                    results.append(info)
            except Exception as e:
                logger.debug(f"Market parse error: {e}")

        logger.info(f"Found {len(results)} active 5m/15m crypto markets")
        return results

    # ── Order Book ────────────────────────────────────────
    def get_best_ask(self, token_id: str) -> Optional[float]:
        """Get the best ask price for YES token from CLOB order book."""
        try:
            resp = self._session.get(
                f"{CLOB_HOST}/book",
                params={"token_id": token_id},
                timeout=10,
            )
            resp.raise_for_status()
            book = resp.json()
            asks = book.get("asks", [])
            if asks:
                return float(asks[0]["price"])
            return None
        except Exception as e:
            logger.debug(f"Order book fetch error: {e}")
            return None

    def get_orderbook_depth(self, token_id: str) -> dict:
        """Get full order book for spread/depth analysis."""
        try:
            resp = self._session.get(
                f"{CLOB_HOST}/book",
                params={"token_id": token_id},
                timeout=10,
            )
            resp.raise_for_status()
            book = resp.json()
            bids = [(float(b["price"]), float(b["size"])) for b in book.get("bids", [])[:5]]
            asks = [(float(a["price"]), float(a["size"])) for a in book.get("asks", [])[:5]]
            spread = asks[0][0] - bids[0][0] if (asks and bids) else None
            return {"bids": bids, "asks": asks, "spread": spread}
        except Exception as e:
            logger.debug(f"Orderbook depth error: {e}")
            return {"bids": [], "asks": [], "spread": None}

    # ── CLOB Balance ──────────────────────────────────────
    def get_usdc_balance(self) -> float:
        """Get current USDC balance from Polymarket."""
        try:
            self.init_clob()
            resp = self._clob.get_balance_allowance(
                BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            return float(resp.get("balance", 0)) / 1e6  # Convert from USDC units
        except Exception as e:
            logger.error(f"Balance fetch error: {e}")
            return 0.0

    # ── Order Execution ───────────────────────────────────
    def buy_yes(self, market: MarketInfo, price: float, size_usdc: float) -> dict:
        """
        Place a BUY order for YES token.
        Uses LIMIT order at price (maker = no fee, or slightly above = taker).
        size_usdc = USDC to spend, shares = size_usdc / price
        """
        self.init_clob()
        shares = round(size_usdc / price, 2)

        order_args = OrderArgs(
            token_id=market.yes_token_id,
            price=price,
            size=shares,
            side=BUY,
        )
        try:
            signed = self._clob.create_order(order_args)
            # GTC = Good Till Cancelled (stays in book = MAKER = no fee)
            resp = self._clob.post_order(signed, OrderType.GTC)
            logger.info(f"BUY order placed: {resp}")
            return {
                "order_id": resp.get("orderID", resp.get("id", "")),
                "status": resp.get("status", "unknown"),
                "price": price,
                "size": shares,
                "size_usdc": size_usdc,
            }
        except Exception as e:
            logger.error(f"BUY order failed: {e}")
            raise

    def sell_yes(self, market: MarketInfo, price: float, size_shares: float,
                 order_type: str = "GTC") -> dict:
        """
        Place a SELL order for YES token (cut-loss or take profit).
        For cut-loss, use FOK/IOC for immediate fill at any price.
        """
        self.init_clob()

        # For cut-loss, we want SELL at market (aggressively low ask)
        order_args = OrderArgs(
            token_id=market.yes_token_id,
            price=price,
            size=size_shares,
            side=SELL,
        )
        try:
            signed = self._clob.create_order(order_args)
            otype  = OrderType.FOK if order_type == "FOK" else OrderType.GTC
            resp   = self._clob.post_order(signed, otype)
            logger.info(f"SELL order placed: {resp}")
            return {
                "order_id": resp.get("orderID", resp.get("id", "")),
                "status": resp.get("status", "unknown"),
                "price": price,
                "size": size_shares,
            }
        except Exception as e:
            logger.error(f"SELL order failed: {e}")
            raise

    def check_market_resolved(self, condition_id: str) -> Optional[str]:
        """
        Check if market has resolved. Returns 'YES', 'NO', or None if pending.
        """
        try:
            resp = self._session.get(
                f"{GAMMA_API_URL}/markets",
                params={"condition_ids": condition_id},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            markets = data if isinstance(data, list) else data.get("data", [])
            if not markets:
                return None
            m = markets[0]
            if not m.get("closed"):
                return None
            # Check tokens to determine winner
            for t in m.get("tokens", []):
                price = float(t.get("price", 0))
                if price >= 0.99:
                    return t.get("outcome", "").upper()
            return None
        except Exception as e:
            logger.debug(f"Market resolve check error: {e}")
            return None


# ── Singleton ──────────────────────────────────────────────
poly_client = PolymarketClient()
