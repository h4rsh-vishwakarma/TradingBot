import pandas as pd
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class BacktestEngine:
    def __init__(self):
        # 📂 Path set to the internal bot directory for portable deployment
        self.backtest_dir = Path(__file__).resolve().parent / "A_Leaderboard" / "backtest_imports"
        self.min_win_rate = 0.54  # 54% safety threshold for the Hybrid Gate

    def find_best_matching_file(self, strategy_id, symbol):
        """
        🔍 SUPER FUZZY Matcher
        Matches Strategy (SMC) and Base Symbol (ETH, BTC) 
        even if the filename has 'Strategy', 'BINANCE', 'USDH2026', spaces, or dashes.
        """
        try:
            if not self.backtest_dir.exists():
                logger.error(f"❌ Backtest directory missing: {self.backtest_dir}")
                return None

            all_files = list(self.backtest_dir.glob("*.csv"))
            if not all_files:
                logger.error(f"❌ No CSV files found in: {self.backtest_dir}")
                return None

            # --- SUPER FUZZY CLEANING ---
            # 1. Strategy cleanup (SMC_Lux -> smclux)
            clean_sid = str(strategy_id).lower().replace("strategy", "").replace("_", "").replace("-", "").replace(" ", "").strip()
            
            # 2. Base Symbol Extraction (BTCUSDT -> btc)
            raw_sym = str(symbol).lower()
            base_symbol = raw_sym.replace("usdt", "").replace("usd", "").split("_")[0][:3]

            matches = []
            for f in all_files:
                # Filename cleanup for matching (LuxAlgo - SMC -> luxalgosmc)
                fname_clean = f.name.lower().replace("_", "").replace("-", "").replace(" ", "")
                
                # Check if BOTH core strategy key and base symbol exist in the cleaned filename
                if clean_sid in fname_clean and base_symbol in fname_clean:
                    matches.append(f)

            if matches:
                # Sort by modification time to get the absolute latest backtest report
                matches.sort(key=os.path.getmtime)
                latest_match = matches[-1]
                logger.info(f"🎯 Dynamic Match Found: {latest_match.name}")
                return latest_match

            logger.warning(f"🔦 No file found matching Strategy: {clean_sid} and Base: {base_symbol}")
            return None
        except Exception as e:
            logger.error(f"❌ Mapper Search Error: {e}")
            return None

    def get_strategy_confidence(self, strategy_id, symbol):
        """
        📊 Historical Confidence (CSV Logic)
        Extracts win rate from TV exports. Updates BT WinRate for notification.
        """
        try:
            latest_file = self.find_best_matching_file(strategy_id, symbol)

            if not latest_file:
                # Neutral fallback if no backtest file exists for this specific pair
                return 0.51  

            df = pd.read_csv(latest_file)
            if df.empty: return 0.5

            # Detect PnL/Profit column across different TV export formats
            pnl_col = None
            possible_cols = ['profit', 'net profit', 'trade p/l', 'pnl', 'result', 'profit/loss']
            for col in df.columns:
                if any(x in col.lower() for x in possible_cols):
                    pnl_col = col
                    break

            if not pnl_col:
                logger.error(f"❌ No PnL column detected in {latest_file.name}")
                return 0.5

            # Calculation: (Winning Trades / Total Trades)
            wins = len(df[df[pnl_col] > 0])
            total = len(df)
            
            win_rate = wins / total if total > 0 else 0.5
            return win_rate

        except Exception as e:
            logger.error(f"❌ Error parsing CSV {strategy_id}: {e}")
            return 0.5

    def get_live_confidence(self, ledger):
        """
        📈 Live Ledger Confidence (Real-time Performance)
        Checks recent live trade history from the Ledger.
        """
        try:
            if not hasattr(ledger, 'get_daily_pnl_events'):
                return 0.6 # Optimistic default for new bot sessions

            history = ledger.get_daily_pnl_events()
            if not history or len(history) == 0:
                return 0.6  # Default start score

            # Focus on the last 5 trades to capture current market fit
            recent_trades = history[-5:]
            wins = len([x for x in recent_trades if x.get('pnl', 0) > 0])
            
            live_rate = wins / len(recent_trades)
            return live_rate
        except Exception as e:
            logger.error(f"❌ Live Ledger Scoring Error: {e}")
            return 0.6

    def validate_signal(self, strategy_id, symbol, ledger):
        """
        🚀 THE HYBRID GATEKEEPER
        Weights: 60% Historical Backtest | 40% Live Ledger Performance
        """
        bt_win_rate = self.get_strategy_confidence(strategy_id, symbol)
        live_win_rate = self.get_live_confidence(ledger)

        # Hybrid Scoring Logic
        hybrid_score = (bt_win_rate * 0.6) + (live_win_rate * 0.4)

        if hybrid_score >= self.min_win_rate:
            logger.info(f"⚖️ HYBRID PASS: {hybrid_score:.2f} (BT: {bt_win_rate:.2f} | Live: {live_win_rate:.2f})")
            return True, hybrid_score
        else:
            logger.warning(f"⚖️ HYBRID REJECT: {hybrid_score:.2f} (BT: {bt_win_rate:.2f} | Live: {live_win_rate:.2f})")
            return False, hybrid_score
