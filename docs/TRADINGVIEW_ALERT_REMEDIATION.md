# TradingView Alert Remediation

EC2 can verify what the bot receives, but it cannot edit TradingView UI alerts directly.

## What the server can verify

Run:

```bash
python3 scripts/verify_tv_inventory.py
```

Status meanings:

- `READY`: local Pine artifact has long/short alertconditions and an embedded secret.
- `LIVE_VERIFIED`: signals are already reaching the bot from TradingView.
- `CONFIG_MISMATCH`: a local Pine artifact exists but is not standardized for a fresh TradingView alert rollout.
- `MISSING`: no local Pine artifact or live TradingView evidence was found.

## Standard JSON payload shape

Use JSON alerts, not plain text. The minimum safe shape is:

```json
{
  "secret": "<WEBHOOK_SECRET>",
  "strategy": "<STRATEGY_NAME>",
  "side": "BUY",
  "symbol": "ETHUSDT",
  "timeframe": "240",
  "price": 0,
  "exchange": "binance"
}
```

## Manual TradingView step

If a row is `CONFIG_MISMATCH` or `MISSING`, the TradingView alert itself still has to be created or updated in the TradingView UI. The server can audit and confirm receipt, but it cannot press the TradingView save button for you.
