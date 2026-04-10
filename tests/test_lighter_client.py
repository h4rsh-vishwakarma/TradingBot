import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from tradingview_webhook_bot.core.orchestrator import Orchestrator
from tradingview_webhook_bot.exchange import lighter_client as lighter_module


class FakeApiClient:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class FakeOrderApi:
    def __init__(self, api_client=None):
        self.api_client = api_client

    async def order_book_details(self):
        market = SimpleNamespace(
            symbol="ETH-USDC",
            market_id=101,
            market_type="perp",
            status="active",
            size_decimals=4,
            supported_size_decimals=4,
            price_decimals=2,
            supported_price_decimals=2,
            quote_multiplier=1,
            min_base_amount="0.0010",
            min_quote_amount="5.0",
            last_trade_price="2500.50",
        )
        return SimpleNamespace(order_book_details=[market], spot_order_book_details=[])


class FakeResponse:
    def __init__(self, code=200, tx_hash="0xabc", message=None):
        self.code = code
        self.tx_hash = tx_hash
        self.message = message


class FakeSignerClient:
    ORDER_TIME_IN_FORCE_GOOD_TILL_TIME = 1

    def __init__(self, url, account_index, api_private_keys):
        self.url = url
        self.account_index = account_index
        self.api_private_keys = api_private_keys
        self.api_client = FakeApiClient()
        self.order_api = FakeOrderApi(self.api_client)
        self.market_order_calls = []
        self.stop_loss_calls = []
        self.take_profit_calls = []
        self.cancel_calls = []

    async def create_market_order_limited_slippage(self, **kwargs):
        self.market_order_calls.append(kwargs)
        created = SimpleNamespace(client_order_index=kwargs["client_order_index"])
        return created, FakeResponse(), None

    async def create_sl_order(self, **kwargs):
        self.stop_loss_calls.append(kwargs)
        return SimpleNamespace(), FakeResponse(), None

    async def create_tp_order(self, **kwargs):
        self.take_profit_calls.append(kwargs)
        return SimpleNamespace(), FakeResponse(), None

    async def cancel_all_orders(self, **kwargs):
        self.cancel_calls.append(kwargs)
        return SimpleNamespace(), FakeResponse(tx_hash="0xcancel"), None


class FakeAccountApi:
    def __init__(self, api_client=None):
        self.api_client = api_client

    async def account(self, by, value):
        return SimpleNamespace(to_dict=lambda: {
            "by": by,
            "value": value,
            "accounts": [{
                "available_balance": "1234.50",
                "positions": [{
                    "market_id": 101,
                    "symbol": "ETH-USDC",
                    "sign": 1,
                    "position": "0.0050",
                    "avg_entry_price": "2500.50",
                    "unrealized_pnl": "1.25",
                }],
            }],
        })


class FakeInfoApi:
    def __init__(self, api_client=None):
        self.api_client = api_client


class FakeLoopRunner:
    def __init__(self, name):
        self.name = name

    def run(self, coro, timeout=30):
        return asyncio.run(coro)

    def stop(self):
        return None


async def _fake_async_initialize(self):
    signer = FakeSignerClient(
        url=self.api_url,
        account_index=self.account_index,
        api_private_keys={self.api_key_index: self.api_private_key},
    )
    order_api = signer.order_api
    account_api = FakeAccountApi(order_api.api_client)
    info_api = FakeInfoApi(order_api.api_client)

    market = lighter_module.MarketSpec(
        symbol="ETH-USDC",
        market_id=101,
        market_type="perp",
        status="active",
        size_decimals=4,
        supported_size_decimals=4,
        price_decimals=2,
        supported_price_decimals=2,
        quote_multiplier=1,
        min_base_amount=Decimal("0.0010"),
        min_quote_amount=Decimal("5.0"),
        last_trade_price=Decimal("2500.50"),
    )
    by_symbol = {market.symbol: market}
    by_alias = {
        self._normalize_alias(alias): market
        for alias in self._aliases_for_symbol(market.symbol)
    }
    return signer, order_api, account_api, info_api, by_alias, by_symbol


def _build_test_client(monkeypatch, allow_real="true"):
    monkeypatch.setattr(lighter_module, "LIGHTER_SDK_AVAILABLE", True)
    monkeypatch.setattr(lighter_module, "_AsyncLoopRunner", FakeLoopRunner)
    monkeypatch.setattr(lighter_module.LighterClient, "_async_initialize", _fake_async_initialize)
    monkeypatch.setenv("LIGHTER_API_PRIVATE_KEY", "abc123")
    monkeypatch.setenv("ALLOW_REAL_TRADES", allow_real)
    monkeypatch.setenv("LIGHTER_ALLOW_REAL_TRADES", allow_real)
    monkeypatch.setenv("LIGHTER_API_URL", "https://testnet.zklighter.elliot.ai")
    return lighter_module.LighterClient()


def test_lighter_client_initializes_with_market_cache(monkeypatch):
    client = _build_test_client(monkeypatch)
    try:
        assert client.is_ready is True
        assert client.get_supported_markets() == ["ETH-USDC"]
        assert client.get_account_info()["data"]["value"] == str(client.account_index)
        assert client._resolve_market("ETHUSDT").market_id == 101
    finally:
        client.close()


def test_lighter_client_executes_market_order_with_scaled_amount(monkeypatch):
    client = _build_test_client(monkeypatch, allow_real="true")
    try:
        result = client.execute_futures_order(
            symbol="ETHUSDT",
            side="BUY",
            quantity=0.123456,
            price=2500.50,
            signal_id="sig-001",
        )

        assert result["status"] == "SUCCESS"
        assert result["exchange"] == "lighter"
        assert result["avg_price"] == 2500.5

        call = client.signer.market_order_calls[0]
        assert call["market_index"] == 101
        assert call["base_amount"] == 1234
        assert call["is_ask"] is False
        assert call["max_slippage"] == client.max_slippage
    finally:
        client.close()


def test_lighter_client_rejects_below_minimum_without_raising(monkeypatch):
    client = _build_test_client(monkeypatch, allow_real="true")
    try:
        result = client.execute_futures_order(
            symbol="ETHUSDT",
            side="BUY",
            quantity=0.0005,
            price=2500.50,
            signal_id="sig-small",
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "permanent"
        assert "below Lighter minimum" in result["msg"]
        assert client.signer.market_order_calls == []
    finally:
        client.close()


def test_lighter_client_reports_balance_positions_and_reduce_only_close(monkeypatch):
    client = _build_test_client(monkeypatch, allow_real="true")
    try:
        assert client.get_account_balance() == 1234.5
        positions = client.get_open_positions()
        assert positions[0]["symbol"] == "ETHUSDT"
        assert positions[0]["quantity"] == 0.005
        assert positions[0]["unrealizedProfit"] == 1.25

        closed = client.close_all_positions()
        assert closed[0]["status"] == "SUCCESS"
        close_call = client.signer.market_order_calls[0]
        assert close_call["reduce_only"] is True
        assert close_call["is_ask"] is True
    finally:
        client.close()


def test_orchestrator_executes_lighter_via_normalized_client_contract(monkeypatch):
    monkeypatch.setenv("POSITION_SIZE_MODE", "fixed")
    monkeypatch.setenv("ALLOWED_EXCHANGES", "lighter")

    orch = Orchestrator.__new__(Orchestrator)
    orch.idempotency = MagicMock()
    orch.idempotency.is_seen.return_value = False
    orch.telegram = MagicMock()
    orch.sheets_logger = MagicMock()
    orch.webhook_secret = "test_secret"
    orch._thread_pool = SimpleNamespace(submit=lambda fn: fn())
    orch._is_duplicate_signal = lambda *args, **kwargs: False
    orch._is_symbol_in_cooldown = lambda *args, **kwargs: False
    orch._is_candle_locked = lambda *args, **kwargs: False
    orch.require_approval_manifest = False
    orch._notify_signal_decision = Orchestrator._notify_signal_decision.__get__(orch, Orchestrator)
    orch.check_safety_gate = lambda *args, **kwargs: (True, "Safe")
    orch.exchange_lighter = MagicMock()
    orch.exchange_lighter.get_mark_price.return_value = 2500.5
    orch.exchange_lighter.place_stop_loss.return_value = {"status": "SKIPPED", "msg": "test"}
    orch.exchange_lighter.execute_futures_order.return_value = {
        "status": "SUCCESS",
        "avg_price": 2500.5,
        "exchange": "lighter",
    }
    orch.exchange_hl = None
    orch.exchange_binance = MagicMock()
    orch.exchange_binance.get_mainnet_mark_price.return_value = 2500.5
    orch.ledger = MagicMock()
    before_pos = SimpleNamespace(realized_pnl=0.0, daily_realized_pnl=0.0)
    orch.ledger.get_position.return_value = SimpleNamespace(
        realized_pnl=0.0,
        daily_realized_pnl=0.0,
        model_copy=lambda deep=False: before_pos,
    )
    orch.ledger.apply_fill.return_value = SimpleNamespace(
        quantity=0.5,
        realized_pnl=10.0,
        daily_realized_pnl=10.0,
    )
    orch.analytics = MagicMock()
    orch.circuit_breaker = None
    orch.processed_count = 0
    orch.MAX_QTY = {"ETHUSDT": 1.0}
    orch._mark_symbol_traded = MagicMock()
    orch._set_candle_lock = MagicMock()
    orch._persist_exec_lock = MagicMock()
    orch.allow_real = True
    orch.max_notional = 2000.0
    orch.daily_loss_limit = -50.0
    orch.ledger_path = "/tmp/test_lighter_ledger.json"
    orch.dlq_path = "/tmp/test_lighter_orchestrator_dlq.jsonl"

    event = {
        "signal_id": "SIG-LIGHTER-001",
        "payload": {
            "exchange": "lighter",
            "strategy": "LighterStrategy",
            "symbol": "ETHUSDT",
            "action": "BUY",
            "price": 2500.5,
            "quantity": 0.5,
            "secret": "test_secret",
        },
    }

    assert orch.handle_signal(event) is True
    orch.exchange_lighter.execute_futures_order.assert_called_once_with(
        "ETHUSDT",
        "BUY",
        0.5,
        price=2500.5,
        signal_id="SIG-LIGHTER-001",
    )
    assert orch.telegram.send.call_args.kwargs["title"] == "Trade Success"
