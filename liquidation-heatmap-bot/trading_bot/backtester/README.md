# Backtesting Pipeline

Production-quality Python backtesting system for TradingView signal analysis with parameter sweeps and walk-forward validation.

## Features

- ✅ TradingView CSV signal ingestion with flexible column naming
- ✅ Realistic trade execution (next-bar open fills, slippage, commissions)
- ✅ Stop-loss and take-profit with intra-bar high/low checks
- ✅ Fixed USD and risk-based position sizing
- ✅ Comprehensive performance metrics (Sharpe, profit factor, drawdown, win rate)
- ✅ Parameter grid search with artifact export
- ✅ Walk-forward out-of-sample validation
- ✅ Full test coverage with pytest

## Installation

Requires Python 3.8+ with pandas, numpy, and pytest:

```bash
pip install pandas numpy pytest
```

## Quick Start

### 1. Generate Test Data

```bash
python -m backtester.tests.generate_test_data
```

### 2. Run Single Backtest

```python
from backtester import load_tradingview_csv, Strategy, run_backtest, compute_metrics

# Load signals
df = load_tradingview_csv('data/signals.csv')

# Configure strategy
params = {
    'slippage_bps': 5,
    'commission_pct': 0.0002,
    'sl_pct': 0.01,
    'tp_pct': 0.02,
    'size_usd': 1000
}
strategy = Strategy(params)

# Run backtest
trades_df, equity_df = run_backtest(df, strategy, initial_capital=10000)
metrics = compute_metrics(trades_df, equity_df, 10000)

print(f"Total Trades: {metrics['total_trades']}")
print(f"Profit Factor: {metrics['profit_factor']:.2f}")
print(f"Sharpe Ratio: {metrics['sharpe']:.2f}")
```

### 3. Parameter Sweep (CLI)

```bash
# Single parameter set
python -m backtester.sweep \
    --input data/signals.csv \
    --params '{"slippage_bps":5,"commission_pct":0.0002,"sl_pct":0.01,"tp_pct":0.02,"size_usd":1000}' \
    --outdir backtest_artifacts/run1

# Grid search
python -m backtester.sweep \
    --input data/signals.csv \
    --grid params_grid.json \
    --outdir backtest_artifacts/ \
    --capital 10000
```

Example `params_grid.json`:
```json
{
  "slippage_bps": [1, 5],
  "commission_pct": [0.0002, 0.0005],
  "sl_pct": [0.005, 0.01],
  "tp_pct": [0.01, 0.02],
  "size_usd": [100, 500]
}
```

### 4. Walk-Forward Validation (CLI)

```bash
python -m backtester.walkforward \
    --input data/signals.csv \
    --params '{"slippage_bps":5,"commission_pct":0.0002,"sl_pct":0.01,"tp_pct":0.02,"size_usd":500}' \
    --train_days 60 \
    --test_days 10 \
    --outdir backtest_artifacts/wf \
    --capital 20000
```

## Input CSV Format

Expected TradingView export format (column names case-insensitive):

```csv
timestamp,open,high,low,close,volume,longSig,shortSig
2024-01-01 00:00:00,42000.0,42500.0,41800.0,42300.0,1000.0,1,0
2024-01-01 01:00:00,42300.0,42400.0,42100.0,42200.0,950.0,0,0
2024-01-01 02:00:00,42200.0,42300.0,41900.0,42000.0,1100.0,0,1
```

- `timestamp`: Datetime (converted to UTC if naive)
- `open, high, low, close`: OHLC prices
- `volume`: Trading volume
- `longSig`/`LongSig`: Long entry signal (1 or True)
- `shortSig`/`ShortSig`: Short entry signal (1 or True)

Signals are normalized to: `1` (long), `-1` (short), `0` (no signal)

## Output Artifacts

### Per-Run Artifacts (`backtest_artifacts/run_XXXX/`)

- **`trade_log.csv`**: Complete trade history
  ```
  decision_id,ts_open,ts_close,side,qty,entry_px,exit_px,pnl_usd,r_multiple,slippage_bps,fees_usd,exit_reason,...
  ```

- **`equity.csv`**: Equity curve over time
  ```
  timestamp,equity
  2024-01-01 00:00:00+00:00,10000.0
  2024-01-01 01:00:00+00:00,10015.5
  ```

- **`metrics.json`**: Performance metrics
  ```json
  {
    "total_trades": 45,
    "net_pnl_usd": 156.30,
    "profit_factor": 1.42,
    "win_rate": 55.5,
    "sharpe": 0.92,
    "max_drawdown_pct": 8.3
  }
  ```

### Sweep Summary (`backtest_artifacts/summary.csv`)

Comparison of all parameter combinations sorted by profit factor and Sharpe ratio.

## Strategy Parameters

- **`slippage_bps`**: Slippage in basis points (e.g., `5` = 0.05%)
- **`commission_pct`**: Commission per trade as decimal (e.g., `0.0002` = 0.02%)
- **`sl_pct`**: Stop loss as percentage from entry (e.g., `0.01` = 1%)
- **`tp_pct`**: Take profit as percentage from entry (e.g., `0.02` = 2%)
- **`size_usd`**: Fixed position size in USD (for fixed sizing)
- **`risk_pct`**: Risk percentage of equity per trade (for risk-based sizing, requires `sl_pct`)
- **`enter_on`**: Entry timing - `'next_open'` (default) or `'same_bar'`

## Execution Rules

1. **Entry**: On signal change from 0→1 (long) or 0→-1 (short)
2. **Fill**: Next bar open by default (or same bar close if `enter_on='same_bar'`)
3. **Slippage**: Applied unfavorably on entry and exit
4. **Exit**: Stop loss OR take profit OR opposing signal OR end of data
5. **SL/TP**: Checked against intra-bar high/low (worst-case if both hit)
6. **Commissions**: Applied on both entry and exit

## Metrics

- **Profit Factor**: Gross profit / gross loss
- **Win Rate**: Percentage of winning trades
- **Sharpe Ratio**: Annualized risk-adjusted return (252 trading days)
- **Max Drawdown**: Largest equity peak-to-trough decline
- **R-Multiple**: Average risk-reward ratio (requires SL defined)
- **Trade Rate**: Average trades per day

### Validation Criteria

⚠️ **Statistical Significance**: Need ≥30 trades for reasonable power, ≥100 preferred

✅ **Live Deployment**: Requires profit_factor ≥1.2 AND Sharpe ≥0.8 on OOS validation

## Testing

Run the full test suite:

```bash
# All tests
pytest tests/test_backtester.py -v

# Quick smoke test
pytest tests/test_backtester.py -v -k "test_load_valid_csv or test_run_backtest_basic"

# With coverage
pytest tests/test_backtester.py --cov=backtester --cov-report=term-missing
```

## Architecture

```
backtester/
├── __init__.py           # Package exports
├── data_loader.py        # CSV loading and normalization
├── strategy.py           # Strategy configuration
├── executor.py           # Backtest execution engine
├── metrics.py            # Performance metrics
├── sweep.py              # Parameter grid search CLI
├── walkforward.py        # OOS walk-forward validation CLI
└── tests/
    ├── generate_test_data.py  # Synthetic data generator
    └── fixtures/              # Test data files
```

## Examples

### Custom Signal Strategy

```python
from backtester import Strategy

class VolatilityFilterStrategy(Strategy):
    def generate_signals(self, df):
        """Only trade signals during high volatility."""
        signals = df['signal'].copy()
        volatility = df['close'].pct_change().rolling(20).std()
        signals[volatility < 0.01] = 0  # Filter low volatility
        return signals

# Use custom strategy
params = {'slippage_bps': 5, 'commission_pct': 0.0002, 'sl_pct': 0.01, 'tp_pct': 0.02, 'size_usd': 1000}
strategy = VolatilityFilterStrategy(params)
trades, equity = run_backtest(df, strategy, 10000)
```

### Risk-Based Position Sizing

```python
params = {
    'slippage_bps': 5,
    'commission_pct': 0.0002,
    'sl_pct': 0.01,      # Required for risk-based sizing
    'tp_pct': 0.02,
    'risk_pct': 0.02     # Risk 2% of equity per trade
}
```

## Limitations

- No pyramiding (single position per signal)
- No trailing stops (fixed SL/TP only)
- No order book simulation (market orders only)
- No multi-asset support (single instrument per run)

## Future Enhancements

- Parameter optimization on train set in walk-forward
- Multi-timeframe signal aggregation
- Correlation analysis across parameter sets
- Monte Carlo simulation for robustness testing
- Integration with live trading bot event logs

## License

MIT License - See LICENSE file for details
