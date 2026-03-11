import csv
import os
from datetime import datetime
from pathlib import Path

class BacktestIngestor:
    def __init__(self, base_path):
        self.import_dir = Path(base_path) / "backtesting" / "A_Leaderboard" / "backtest_imports"
        self.import_dir.mkdir(parents=True, exist_ok=True)

    def save_report(self, strategy_name, symbol, data):
        """Saves backtest metrics into a CSV file named after the strategy and symbol."""
        filename = f"{strategy_name}_{symbol}_LIVE_STATS.csv"
        filepath = self.import_dir / filename
        
        # Data preparation
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fieldnames = ["timestamp", "net_profit", "win_rate", "total_trades", "max_drawdown", "profit_factor"]
        
        row = {
            "timestamp": timestamp,
            "net_profit": data.get("net_profit", "0"),
            "win_rate": data.get("win_rate", "0"),
            "total_trades": data.get("total_trades", "0"),
            "max_drawdown": data.get("max_drawdown", "0"),
            "profit_factor": data.get("profit_factor", "0")
        }

        # Write to CSV (Append mode taaki history bani rahe)
        file_exists = os.path.isfile(filepath)
        with open(filepath, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
            
        return str(filepath)
