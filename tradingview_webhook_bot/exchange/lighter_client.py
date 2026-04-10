"""
Lighter.xyz exchange client bridged into the synchronous orchestrator.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    from lighter import AccountApi, InfoApi, OrderApi, SignerClient

    LIGHTER_SDK_AVAILABLE = True
except ImportError:
    LIGHTER_SDK_AVAILABLE = False
    logger.warning("lighter-sdk not installed. Run: pip install lighter-sdk")

SYMBOL_MAP = {
    "ETHUSDT": "ETH-USDC",
    "BTCUSDT": "BTC-USDC",
    "SOLUSDT": "SOL-USDC",
    "LINKUSDT": "LINK-USDC",
    "AAVEUSDT": "AAVE-USDC",
    "UNIUSDT": "UNI-USDC",
}
REVERSE_SYMBOL_MAP = {v: k for k, v in SYMBOL_MAP.items()}


@dataclass(frozen=True)
class MarketSpec:
    symbol: str
    market_id: int
    market_type: str
    status: str
    size_decimals: int
    supported_size_decimals: int
    price_decimals: int
    supported_price_decimals: int
    quote_multiplier: int
    min_base_amount: Decimal
    min_quote_amount: Decimal
    last_trade_price: Optional[Decimal]


class _AsyncLoopRunner:
    def __init__(self, name: str):
        self._ready = threading.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._jobs: "queue.Queue[tuple[Any, concurrent.futures.Future] | None]" = queue.Queue()
        self._thread = threading.Thread(target=self._bootstrap, name=name, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=10):
            raise RuntimeError("Timed out starting Lighter event loop thread")

    def _bootstrap(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            while True:
                job = self._jobs.get()
                if job is None:
                    break
                coro, result_future = job
                if result_future.cancelled():
                    continue
                try:
                    result = loop.run_until_complete(coro)
                except Exception as exc:
                    result_future.set_exception(exc)
                else:
                    result_future.set_result(result)
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    def run(self, coro, timeout: float = 30):
        if not self._loop or not self._thread.is_alive():
            raise RuntimeError("Lighter event loop is not available")
        future: concurrent.futures.Future = concurrent.futures.Future()
        self._jobs.put((coro, future))
        return future.result(timeout=timeout)

    def stop(self):
        if not self._loop:
            return
        self._jobs.put(None)
        self._thread.join(timeout=5)


class LighterClient:
    """Lighter.xyz exchange client with a synchronous interface."""

    def __init__(self):
        if not LIGHTER_SDK_AVAILABLE:
            raise ImportError("lighter-sdk not installed")

        self.api_url = os.getenv("LIGHTER_API_URL", "https://testnet.lighter.xyz")
        self.account_index = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "0"))
        self.api_key_index = int(os.getenv("LIGHTER_API_KEY_INDEX", "4"))
        self.private_key = os.getenv("LIGHTER_PRIVATE_KEY", "")
        self.api_private_key = os.getenv("LIGHTER_API_PRIVATE_KEY", self.private_key)
        # Lighter-specific override; falls back to global ALLOW_REAL_TRADES
        lighter_override = os.getenv("LIGHTER_ALLOW_REAL_TRADES", "").strip().lower()
        if lighter_override in ("true", "false"):
            self.allow_real = lighter_override == "true"
        else:
            self.allow_real = os.getenv("ALLOW_REAL_TRADES", "false").lower() == "true"
        self.max_slippage = float(os.getenv("LIGHTER_MAX_SLIPPAGE", "0.01"))
        self.is_testnet = "testnet" in self.api_url.lower()

        if not self.api_private_key:
            raise ValueError("LIGHTER_API_PRIVATE_KEY not set in env_vars")

        if self.private_key and not self.private_key.startswith("0x"):
            self.private_key = "0x" + self.private_key
        if not self.api_private_key.startswith("0x"):
            self.api_private_key = "0x" + self.api_private_key

        self.client = None
        self.signer = None
        self.order_api = None
        self.account_api = None
        self.info_api = None
        self._market_by_alias: Dict[str, MarketSpec] = {}
        self._market_by_symbol: Dict[str, MarketSpec] = {}
        self._loop_runner: Optional[_AsyncLoopRunner] = None
        self._closed = False

        try:
            self._loop_runner = _AsyncLoopRunner("lighter-sdk")
            (
                self.signer,
                self.order_api,
                self.account_api,
                self.info_api,
                self._market_by_alias,
                self._market_by_symbol,
            ) = self._loop_runner.run(self._async_initialize(), timeout=30)
            # client=signer for trading; None means read-only mode
            self.client = self.signer

            mode = "TESTNET" if self.is_testnet else "MAINNET"
            logger.info(
                "Connected to Lighter [%s] | Account: %d | Markets: %d",
                mode,
                self.account_index,
                len(self._market_by_symbol),
            )
        except Exception:
            self.close()
            raise

    @property
    def is_ready(self) -> bool:
        """True if REST API is available (even without signer)."""
        return self.order_api is not None

    @property
    def can_trade(self) -> bool:
        """True only when signer (L2 key) is valid and real trades enabled."""
        return self.signer is not None and self.allow_real

    async def _async_initialize(self):
        """Initialize REST API (read-only) and optionally the signer (trading).

        Split into 2 phases so market price / account balance work even when
        the signing key is the wrong format (L2 40-byte key required).
        """
        import lighter as _lighter_mod
        # Phase 1: REST-only clients (always needed)
        rest_api_client = _lighter_mod.ApiClient(
            configuration=_lighter_mod.Configuration(host=self.api_url)
        )
        order_api = _lighter_mod.OrderApi(rest_api_client)
        account_api = AccountApi(rest_api_client)
        info_api = InfoApi(rest_api_client)
        market_by_alias, market_by_symbol = await self._async_load_market_cache(order_api)

        # Phase 2: Signer (trading) — fail gracefully with clear message
        api_keys = {self.api_key_index: self.api_private_key}
        signer = SignerClient.__new__(SignerClient)
        try:
            SignerClient.__init__(
                signer,
                url=self.api_url,
                account_index=self.account_index,
                api_private_keys=api_keys,
            )
            logger.info("Lighter signer initialized (trading enabled)")
        except Exception as sign_err:
            signer = None
            err_str = str(sign_err)
            if "invalid private key length" in err_str:
                logger.warning(
                    "⚠️ Lighter signer DISABLED — API key is wrong format (32-byte ETH key, "
                    "need 40-byte Lighter L2 key). Generate one at: "
                    "https://testnet.zklighter.elliot.ai -> Account -> API Keys. "
                    "Market data and paper trades still work."
                )
            else:
                logger.warning("⚠️ Lighter signer DISABLED: %s", sign_err)

        return signer, order_api, account_api, info_api, market_by_alias, market_by_symbol

    async def _async_load_market_cache(self, order_api):
        details = await order_api.order_book_details()
        raw_markets = list(getattr(details, "order_book_details", []) or [])
        if not raw_markets:
            raw_markets = list(getattr(details, "spot_order_book_details", []) or [])

        active_perps = [
            market
            for market in raw_markets
            if getattr(market, "market_type", "perp") == "perp"
            and getattr(market, "status", "active") == "active"
        ]
        selected_markets = active_perps or raw_markets

        by_alias: Dict[str, MarketSpec] = {}
        by_symbol: Dict[str, MarketSpec] = {}
        for market in selected_markets:
            spec = MarketSpec(
                symbol=str(market.symbol).upper(),
                market_id=int(market.market_id),
                market_type=str(getattr(market, "market_type", "perp")),
                status=str(getattr(market, "status", "active")),
                size_decimals=int(getattr(market, "size_decimals", getattr(market, "supported_size_decimals", 0))),
                supported_size_decimals=int(getattr(market, "supported_size_decimals", getattr(market, "size_decimals", 0))),
                price_decimals=int(getattr(market, "price_decimals", getattr(market, "supported_price_decimals", 0))),
                supported_price_decimals=int(getattr(market, "supported_price_decimals", getattr(market, "price_decimals", 0))),
                quote_multiplier=int(getattr(market, "quote_multiplier", 1) or 1),
                min_base_amount=self._parse_decimal(getattr(market, "min_base_amount", "0")),
                min_quote_amount=self._parse_decimal(getattr(market, "min_quote_amount", "0")),
                last_trade_price=self._safe_decimal(getattr(market, "last_trade_price", None)),
            )
            by_symbol[spec.symbol] = spec
            for alias in self._aliases_for_symbol(spec.symbol):
                by_alias[self._normalize_alias(alias)] = spec
        return by_alias, by_symbol

    def _run_async(self, coro, timeout: float = 30):
        if not self._loop_runner:
            raise RuntimeError("Lighter async runner not initialized")
        return self._loop_runner.run(coro, timeout=timeout)

    @staticmethod
    def _normalize_alias(symbol: str) -> str:
        return str(symbol or "").upper().replace("-", "").replace("/", "").replace("_", "")

    @staticmethod
    def _aliases_for_symbol(symbol: str):
        symbol = str(symbol or "").upper()
        base, _, quote = symbol.partition("-")
        aliases = {
            symbol,
            symbol.replace("-", ""),
        }
        if base:
            aliases.add(base)
        if quote == "USDC":
            aliases.add(f"{base}USDT")
            aliases.add(f"{base}USD")
            aliases.add(f"{base}USDC")
        # Handle bare base names like "ETH", "BTC", "SOL" from Lighter
        # by also adding common quote variants so ETHUSDT resolves to ETH
        if not quote:
            aliases.add(f"{base}USDT")
            aliases.add(f"{base}USD")
            aliases.add(f"{base}USDC")
            aliases.add(f"{base}-USDC")
            aliases.add(f"{base}-USDT")
        mapped = REVERSE_SYMBOL_MAP.get(symbol)
        if mapped:
            aliases.add(mapped)
        return aliases

    @staticmethod
    def _parse_decimal(value: Any) -> Decimal:
        return Decimal(str(value or "0"))

    @staticmethod
    def _safe_decimal(value: Any) -> Optional[Decimal]:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None

    @staticmethod
    def _quantize_down(value: Decimal, decimals: int) -> Decimal:
        quantum = Decimal("1").scaleb(-decimals)
        return value.quantize(quantum, rounding=ROUND_DOWN)

    def _resolve_market(self, symbol: str) -> MarketSpec:
        candidates = [str(symbol or "").upper()]
        mapped_symbol = SYMBOL_MAP.get(candidates[0])
        if mapped_symbol:
            candidates.insert(0, mapped_symbol)

        for candidate in candidates:
            market = self._market_by_alias.get(self._normalize_alias(candidate))
            if market:
                return market

        self.refresh_market_cache()
        for candidate in candidates:
            market = self._market_by_alias.get(self._normalize_alias(candidate))
            if market:
                return market

        available = ", ".join(sorted(self._market_by_symbol.keys())[:10])
        raise ValueError(
            f"Unsupported Lighter market for symbol={symbol}. Cached markets: {available or 'none'}"
        )

    def _normalize_base_amount(self, quantity: float, market: MarketSpec) -> tuple[int, Decimal]:
        qty_decimal = self._parse_decimal(quantity)
        normalized_qty = self._quantize_down(qty_decimal, market.supported_size_decimals)
        if normalized_qty <= 0:
            raise ValueError(f"Quantity must be positive for {market.symbol}")
        if market.min_base_amount > 0 and normalized_qty < market.min_base_amount:
            raise ValueError(
                f"Quantity {normalized_qty} is below Lighter minimum {market.min_base_amount} for {market.symbol}"
            )

        units = int(
            (normalized_qty * (Decimal(10) ** market.size_decimals)).to_integral_value(rounding=ROUND_DOWN)
        )
        if units <= 0:
            raise ValueError(f"Scaled quantity is zero for {market.symbol}")
        return units, normalized_qty

    def _normalize_price_units(self, price: float, market: MarketSpec) -> tuple[int, Decimal]:
        price_decimal = self._parse_decimal(price)
        normalized_price = self._quantize_down(price_decimal, market.supported_price_decimals)
        if normalized_price <= 0:
            raise ValueError(f"Price must be positive for {market.symbol}")

        price_units = int(
            (normalized_price * (Decimal(10) ** market.price_decimals)).to_integral_value(rounding=ROUND_DOWN)
        )
        if price_units <= 0:
            raise ValueError(f"Scaled price is zero for {market.symbol}")
        return price_units, normalized_price

    @staticmethod
    def _client_order_index(seed: Optional[str]) -> int:
        raw = seed or str(time.time_ns())
        digest = hashlib.sha256(raw.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") & ((1 << 48) - 1)

    async def _async_market_order(
        self,
        market: MarketSpec,
        is_buy: bool,
        base_amount: int,
        signal_id: Optional[str],
        reduce_only: bool = False,
    ):
        return await self.signer.create_market_order_limited_slippage(
            market_index=market.market_id,
            client_order_index=self._client_order_index(signal_id),
            base_amount=base_amount,
            max_slippage=self.max_slippage,
            is_ask=not is_buy,
            reduce_only=reduce_only,
        )

    async def _async_trigger_order(
        self,
        order_fn,
        market: MarketSpec,
        quantity_units: int,
        trigger_price_units: int,
        execution_price_units: int,
        is_ask: bool,
        signal_id: Optional[str],
    ):
        return await order_fn(
            market_index=market.market_id,
            client_order_index=self._client_order_index(signal_id),
            base_amount=quantity_units,
            trigger_price=trigger_price_units,
            price=execution_price_units,
            is_ask=is_ask,
            reduce_only=True,
        )

    async def _async_refresh_market_cache(self):
        self._market_by_alias, self._market_by_symbol = await self._async_load_market_cache(self.order_api)
        return self._market_by_symbol

    def refresh_market_cache(self):
        if not self.is_ready:
            return {}
        self._run_async(self._async_refresh_market_cache(), timeout=30)
        return self._market_by_symbol

    def market_order(self, symbol, is_buy, size, price=None, signal_id=None):
        side = "BUY" if is_buy else "SELL"
        return self.execute_futures_order(symbol, side, size, price=price, signal_id=signal_id)

    def execute_futures_order(self, symbol, side, quantity, price=None, order_type="MARKET", signal_id=None):
        try:
            market = self._resolve_market(symbol)
            reference_price = self._safe_decimal(price) or market.last_trade_price or Decimal("0")
            quantity_units, normalized_qty = self._normalize_base_amount(quantity, market)
            notional = normalized_qty * reference_price
            if market.min_quote_amount > 0 and reference_price > 0 and notional < market.min_quote_amount:
                return {
                    "status": "FAILED",
                    "reason": "permanent",
                    "msg": (
                        f"Notional {notional} is below Lighter minimum "
                        f"{market.min_quote_amount} for {market.symbol}"
                    ),
                    "exchange": "lighter",
                }
        except Exception as exc:
            return {
                "status": "FAILED",
                "reason": "permanent",
                "msg": str(exc),
                "exchange": "lighter",
            }

        if order_type != "MARKET":
            return {
                "status": "FAILED",
                "reason": "permanent",
                "msg": f"Lighter only supports MARKET orders from the orchestrator path, got {order_type}",
                "exchange": "lighter",
            }

        if not self.signer and self.allow_real:
            logger.warning(
                "Lighter signer not available — falling back to paper mode. "
                "Provide a valid 40-byte L2 API key in LIGHTER_PRIVATE_KEY."
            )
        if not self.signer or not self.allow_real:
            sim_id = f"LIGHTER_PAPER_{signal_id or int(time.time())}"
            logger.info(
                "PAPER TRADE [Lighter]: %s %s %s @ %s",
                side,
                normalized_qty,
                market.symbol,
                reference_price,
            )
            return {
                "status": "SUCCESS",
                "orderId": sim_id,
                "avg_price": float(reference_price),
                "paper": True,
                "exchange": "lighter",
                "symbol": market.symbol,
                "market_id": market.market_id,
                "reference_price": float(reference_price),
                "order_type_used": "MARKET",
                "estimated_fee_bps": float(os.getenv("LIGHTER_TAKER_FEE_BPS", "4.0")),
            }

        try:
            logger.info("Executing %s %s %s on Lighter", side, normalized_qty, market.symbol)
            created_order, response, err = self._run_async(
                self._async_market_order(
                    market=market,
                    is_buy=side.upper() == "BUY",
                    base_amount=quantity_units,
                    signal_id=signal_id,
                    reduce_only=False,
                ),
                timeout=30,
            )
            if err:
                return {
                    "status": "FAILED",
                    "reason": "permanent",
                    "msg": str(err),
                    "exchange": "lighter",
                }
            if response and getattr(response, "code", None) == 200:
                logger.info("Lighter order accepted: tx_hash=%s", getattr(response, "tx_hash", ""))
                return {
                    "status": "SUCCESS",
                    "orderId": getattr(response, "tx_hash", str(signal_id or "")),
                    "avg_price": float(reference_price),
                    "exchange": "lighter",
                    "symbol": market.symbol,
                    "market_id": market.market_id,
                    "client_order_index": getattr(created_order, "client_order_index", None),
                    "tx_hash": getattr(response, "tx_hash", None),
                    "reference_price": float(reference_price),
                    "order_type_used": "MARKET",
                    "estimated_fee_bps": float(os.getenv("LIGHTER_TAKER_FEE_BPS", "4.0")),
                }
            return {
                "status": "FAILED",
                "reason": "permanent",
                "msg": getattr(response, "message", "Empty result") if response else "Empty result",
                "exchange": "lighter",
            }
        except Exception as exc:
            logger.error("Lighter execution error: %s", exc)
            return {
                "status": "FAILED",
                "reason": "permanent",
                "msg": str(exc),
                "exchange": "lighter",
            }

    def place_stop_loss(self, symbol, side, quantity, entry_price, sl_pct=3.0, signal_id=None):
        if not self.allow_real:
            return {"status": "SKIPPED", "msg": "Paper mode"}

        market = self._resolve_market(symbol)
        quantity_units, _ = self._normalize_base_amount(quantity, market)
        stop_side_is_ask = side.upper() == "BUY"
        trigger_price = (
            entry_price * (1 - sl_pct / 100)
            if side.upper() == "BUY"
            else entry_price * (1 + sl_pct / 100)
        )
        execution_price = (
            trigger_price * (1 - self.max_slippage)
            if stop_side_is_ask
            else trigger_price * (1 + self.max_slippage)
        )

        try:
            trigger_price_units, trigger_price_decimal = self._normalize_price_units(trigger_price, market)
            execution_price_units, _ = self._normalize_price_units(execution_price, market)
            _, response, err = self._run_async(
                self._async_trigger_order(
                    order_fn=self.signer.create_sl_order,
                    market=market,
                    quantity_units=quantity_units,
                    trigger_price_units=trigger_price_units,
                    execution_price_units=execution_price_units,
                    is_ask=stop_side_is_ask,
                    signal_id=f"{signal_id or ''}:sl",
                ),
                timeout=30,
            )
            if err:
                return {"status": "FAILED", "msg": str(err)}
            if response and getattr(response, "code", None) == 200:
                logger.info("Lighter SL: %s @ %s", market.symbol, trigger_price_decimal)
                return {"status": "SUCCESS", "stopPrice": float(trigger_price_decimal)}
            return {"status": "FAILED", "msg": getattr(response, "message", "Empty result")}
        except Exception as exc:
            logger.error("Lighter SL error: %s", exc)
            return {"status": "FAILED", "msg": str(exc)}

    def place_take_profit(self, symbol, side, quantity, entry_price, tp_pct=5.0, signal_id=None):
        if not self.allow_real:
            return {"status": "SKIPPED", "msg": "Paper mode"}

        market = self._resolve_market(symbol)
        quantity_units, _ = self._normalize_base_amount(quantity, market)
        tp_side_is_ask = side.upper() == "BUY"
        trigger_price = (
            entry_price * (1 + tp_pct / 100)
            if side.upper() == "BUY"
            else entry_price * (1 - tp_pct / 100)
        )
        execution_price = (
            trigger_price * (1 - self.max_slippage)
            if tp_side_is_ask
            else trigger_price * (1 + self.max_slippage)
        )

        try:
            trigger_price_units, trigger_price_decimal = self._normalize_price_units(trigger_price, market)
            execution_price_units, _ = self._normalize_price_units(execution_price, market)
            _, response, err = self._run_async(
                self._async_trigger_order(
                    order_fn=self.signer.create_tp_order,
                    market=market,
                    quantity_units=quantity_units,
                    trigger_price_units=trigger_price_units,
                    execution_price_units=execution_price_units,
                    is_ask=tp_side_is_ask,
                    signal_id=f"{signal_id or ''}:tp",
                ),
                timeout=30,
            )
            if err:
                return {"status": "FAILED", "msg": str(err)}
            if response and getattr(response, "code", None) == 200:
                logger.info("Lighter TP: %s @ %s", market.symbol, trigger_price_decimal)
                return {"status": "SUCCESS", "tpPrice": float(trigger_price_decimal)}
            return {"status": "FAILED", "msg": getattr(response, "message", "Empty result")}
        except Exception as exc:
            logger.error("Lighter TP error: %s", exc)
            return {"status": "FAILED", "msg": str(exc)}

    def _account_payload(self) -> Dict[str, Any]:
        info = self.get_account_info() or {}
        data = info.get("data", {}) if isinstance(info, dict) else {}
        accounts = data.get("accounts", []) if isinstance(data, dict) else []
        return accounts[0] if accounts else data

    @staticmethod
    def _external_symbol_for_market(symbol: str) -> str:
        symbol = str(symbol or "").upper()
        mapped = REVERSE_SYMBOL_MAP.get(symbol)
        if mapped:
            return mapped
        base = symbol.split("-", 1)[0].replace("USDC", "").replace("USD", "")
        return f"{base}USDT" if base else symbol

    def get_open_positions(self):
        """Return Lighter open positions normalized to the bot exchange schema."""
        try:
            account = self._account_payload()
            positions = account.get("positions", []) if isinstance(account, dict) else []
            open_positions = []
            for pos in positions or []:
                if not isinstance(pos, dict):
                    continue
                raw_qty = self._safe_decimal(pos.get("position"))
                if raw_qty is None:
                    continue
                sign = int(pos.get("sign") or 1)
                qty = raw_qty if sign >= 0 else -raw_qty
                if abs(qty) <= Decimal("0"):
                    continue
                market_symbol = str(pos.get("symbol") or "").upper()
                symbol = self._external_symbol_for_market(market_symbol)
                entry = self._safe_decimal(pos.get("avg_entry_price")) or Decimal("0")
                unrealized = self._safe_decimal(pos.get("unrealized_pnl")) or Decimal("0")
                open_positions.append({
                    "exchange": "lighter",
                    "symbol": symbol,
                    "market_symbol": market_symbol,
                    "market_id": int(pos.get("market_id") or 0),
                    "positionAmt": float(qty),
                    "quantity": float(qty),
                    "side": "LONG" if qty > 0 else "SHORT",
                    "entryPrice": float(entry),
                    "entry_price": float(entry),
                    "unrealizedProfit": float(unrealized),
                    "unrealized_pnl": float(unrealized),
                })
            return open_positions
        except Exception as exc:
            logger.error("Lighter position fetch failed: %s", exc)
            return []

    def cancel_open_orders(self, symbol: Optional[str] = None) -> bool:
        """Cancel open Lighter orders. Lighter SDK cancel-all is account-wide."""
        if not self.allow_real:
            logger.info("Lighter cancel_open_orders skipped in paper mode")
            return True
        try:
            _, response, err = self._run_async(
                self.signer.cancel_all_orders(
                    time_in_force=SignerClient.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                    timestamp_ms=int(time.time() * 1000),
                ),
                timeout=30,
            )
            if err:
                logger.error("Lighter cancel all failed: %s", err)
                return False
            logger.critical("Lighter: All open orders cancelled: %s", getattr(response, "tx_hash", response))
            return True
        except Exception as exc:
            logger.error("Lighter cancel all failed: %s", exc)
            return False

    def close_position(self, symbol: str, quantity: Optional[float] = None, signal_id: Optional[str] = None):
        """Close a Lighter position with a reduce-only market order."""
        market = self._resolve_market(symbol)
        positions = self.get_open_positions()
        target = None
        external_symbol = self._external_symbol_for_market(market.symbol)
        for pos in positions:
            if pos.get("symbol") == external_symbol or pos.get("market_symbol") == market.symbol:
                target = pos
                break
        if not target:
            return {"exchange": "lighter", "symbol": external_symbol, "status": "SKIPPED", "msg": "No open position"}

        position_qty = Decimal(str(target.get("quantity", 0)))
        close_qty = Decimal(str(abs(quantity))) if quantity else abs(position_qty)
        quantity_units, normalized_qty = self._normalize_base_amount(float(close_qty), market)
        close_is_buy = position_qty < 0

        if not self.allow_real:
            return {
                "exchange": "lighter",
                "symbol": external_symbol,
                "status": "SUCCESS",
                "paper": True,
                "side": "BUY" if close_is_buy else "SELL",
                "qty": float(normalized_qty),
                "action": "close_position",
            }

        try:
            created_order, response, err = self._run_async(
                self._async_market_order(
                    market=market,
                    is_buy=close_is_buy,
                    base_amount=quantity_units,
                    signal_id=signal_id or f"close:{external_symbol}:{time.time_ns()}",
                    reduce_only=True,
                ),
                timeout=30,
            )
            if err:
                return {"exchange": "lighter", "symbol": external_symbol, "status": "FAILED", "msg": str(err)}
            if response and getattr(response, "code", None) == 200:
                return {
                    "exchange": "lighter",
                    "symbol": external_symbol,
                    "status": "SUCCESS",
                    "side": "BUY" if close_is_buy else "SELL",
                    "qty": float(normalized_qty),
                    "tx_hash": getattr(response, "tx_hash", None),
                    "client_order_index": getattr(created_order, "client_order_index", None),
                }
            return {
                "exchange": "lighter",
                "symbol": external_symbol,
                "status": "FAILED",
                "msg": getattr(response, "message", "Empty result") if response else "Empty result",
            }
        except Exception as exc:
            logger.error("Lighter close position failed: %s", exc)
            return {"exchange": "lighter", "symbol": external_symbol, "status": "FAILED", "msg": str(exc)}

    def close_all_positions(self):
        closed = []
        cancel_ok = self.cancel_open_orders()
        if not cancel_ok:
            closed.append({"exchange": "lighter", "action": "cancel_all", "status": "FAILED"})
        for pos in self.get_open_positions():
            closed.append(self.close_position(
                pos.get("symbol") or pos.get("market_symbol"),
                signal_id=f"kill:{pos.get('symbol')}:{time.time_ns()}",
            ))
        if not closed:
            closed.append({"exchange": "lighter", "action": "close_all_positions", "status": "SKIPPED", "msg": "No open positions"})
        return closed

    def get_account_info(self):
        if not self.is_ready:
            return None
        try:
            account = self._run_async(
                self.account_api.account(by="index", value=str(self.account_index)),
                timeout=30,
            )
            return {"account_index": self.account_index, "data": account.to_dict() if account else {}}
        except Exception as exc:
            logger.error("Lighter account error: %s", exc)
            return None

    def get_supported_markets(self):
        if not self._market_by_symbol and self.is_ready:
            self.refresh_market_cache()
        return sorted(self._market_by_symbol.keys())


    def get_mark_price(self, symbol: str) -> Optional[float]:
        """Return live mark/last-trade price for a symbol."""
        if not self.is_ready:
            return None
        try:
            market = self._resolve_market(symbol)
            # Try last_trade_price from market spec first
            if market.last_trade_price and market.last_trade_price > 0:
                return float(market.last_trade_price)
            # Refresh and retry
            self.refresh_market_cache()
            market = self._resolve_market(symbol)
            if market.last_trade_price and market.last_trade_price > 0:
                return float(market.last_trade_price)
        except Exception as exc:
            logger.debug("Lighter get_mark_price error for %s: %s", symbol, exc)
        # Try fetching from orderbook via info_api
        try:
            async def _fetch_price(mid):
                ob = await self.order_api.order_book(market_id=mid)
                # Use mid-price from asks/bids
                asks = getattr(ob, "asks", []) or []
                bids = getattr(ob, "bids", []) or []
                if asks and bids:
                    best_ask = self._safe_decimal(getattr(asks[0], "price", None))
                    best_bid = self._safe_decimal(getattr(bids[0], "price", None))
                    if best_ask and best_bid and best_ask > 0 and best_bid > 0:
                        return float((best_ask + best_bid) / 2)
                return None
            market = self._resolve_market(symbol)
            return self._run_async(_fetch_price(market.market_id), timeout=10)
        except Exception as exc2:
            logger.debug("Lighter orderbook price fetch failed for %s: %s", symbol, exc2)
        return None

    def get_account_balance(self) -> Optional[float]:
        """Return available USDC balance for the account."""
        if not self.is_ready:
            return None
        try:
            info = self.get_account_info()
            if not info:
                return None
            data = info.get("data", {})
            # account data is nested inside data["accounts"][0]
            accounts_list = data.get("accounts", [])
            acct = accounts_list[0] if accounts_list else data
            # Try top-level balance fields
            for key in ("available_balance", "free_collateral", "usdc_balance", "equity", "cross_asset_value"):
                val = acct.get(key) if isinstance(acct, dict) else None
                if val is not None:
                    try:
                        f = float(val)
                        if f > 0:
                            return f
                    except (TypeError, ValueError):
                        pass
            # Try USDC from asset list
            assets = (acct.get("assets", []) if isinstance(acct, dict) else None) or data.get("assets", [])
            for asset in assets:
                if isinstance(asset, dict):
                    sym = asset.get("symbol", "")
                    if sym in ("USDC", "USD"):
                        try:
                            bal = float(asset.get("balance", 0) or 0)
                            locked = float(asset.get("locked_balance", 0) or 0)
                            return max(0.0, bal - locked)
                        except (TypeError, ValueError):
                            pass
            return None
        except Exception as exc:
            logger.debug("Lighter get_account_balance error: %s", exc)
            return None

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            signer_api_client = getattr(self.signer, "api_client", None) if self.signer else None
            rest_api_client = getattr(self.order_api, "api_client", None) if self.order_api else None
            if self.signer and hasattr(self.signer, "close"):
                self._run_async(self.signer.close(), timeout=10)
            elif signer_api_client:
                self._run_async(signer_api_client.close(), timeout=10)
            if rest_api_client and rest_api_client is not signer_api_client:
                self._run_async(rest_api_client.close(), timeout=10)
        except Exception as exc:
            logger.debug("Lighter client close warning: %s", exc)
        finally:
            if self._loop_runner:
                self._loop_runner.stop()
                self._loop_runner = None
            self.client = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from dotenv import load_dotenv

    load_dotenv("/etc/tradingbot/env_vars")
    try:
        client = LighterClient()
        print("Connected!")
        print("Markets:", client.get_supported_markets())
        client.allow_real = False
        print("Paper trade:", client.execute_futures_order("ETHUSDT", "BUY", 0.01, 2000))
    except Exception as exc:
        print(f"Error: {exc}")
