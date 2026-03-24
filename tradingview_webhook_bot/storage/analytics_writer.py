"""
Daily Analytics Writer for Google Sheets
Adds/Updates "Daily Analytics" tab with daily breakdown.
"""

import gspread
import logging
import os
from datetime import datetime
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)


class AnalyticsWriter:
    TAB_NAME = "Daily Analytics"
    HEADER = [
        "Date", "Total Trades", "Total Qty", "Wins", "Losses",
        "Win Rate %", "Gross Profit", "Gross Loss", "Net PnL",
        "Running Capital", "Net DD %", "Worst DD %", "Notes"
    ]
    STARTING_CAPITAL = 10000.0

    def __init__(self, sheet_name=None, json_key=None):
        self.json_key = json_key or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE") or "/etc/tradingbot/service_account.json"
        if not os.path.exists(self.json_key):
            legacy = "/home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot/storage/service_account.json"
            if os.path.exists(legacy):
                self.json_key = legacy
        self.sheet_name = sheet_name or os.getenv("GOOGLE_SHEET_NAME") or "Trading_Bot_Ledger"
        self.spreadsheet = None
        self.analytics_ws = None
        self.trades_ws = None
        self._connect()

    def _connect(self):
        try:
            if not os.path.exists(self.json_key):
                logger.error("Service account not found: %s", self.json_key)
                return
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
            creds = Credentials.from_service_account_file(self.json_key, scopes=scopes)
            client = gspread.authorize(creds)
            self.spreadsheet = client.open(self.sheet_name)
            self.trades_ws = self.spreadsheet.worksheet("Trades")
            try:
                self.analytics_ws = self.spreadsheet.worksheet(self.TAB_NAME)
            except gspread.exceptions.WorksheetNotFound:
                self.analytics_ws = self.spreadsheet.add_worksheet(
                    title=self.TAB_NAME, rows=1000, cols=15
                )
                self.analytics_ws.append_row(self.HEADER)
                self.analytics_ws.format("A1:M1", {"textFormat": {"bold": True}})
                logger.info("Created Daily Analytics tab")
            logger.info("Analytics writer connected")
        except Exception as e:
            logger.error("Analytics connection error: %s", e)

    def rebuild_all_daily_analytics(self):
        if not self.trades_ws or not self.analytics_ws:
            logger.error("Sheets not connected")
            return None
        try:
            all_rows = self.trades_ws.get_all_values()
            if len(all_rows) <= 1:
                return None
            header_row = all_rows[0]
            if header_row[0].lower() in ("signal_id", "id", "signal id"):
                data_rows = all_rows[1:]
            else:
                data_rows = all_rows

            daily_data = {}
            for row in data_rows:
                if len(row) < 7:
                    continue
                try:
                    ts = row[1].strip()
                    dt = None
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S"):
                        try:
                            dt = datetime.strptime(ts, fmt)
                            break
                        except ValueError:
                            continue
                    if dt is None:
                        continue
                    ds = dt.strftime("%Y-%m-%d")
                    qty = float(row[4]) if row[4] else 0
                    pnl = float(row[6]) if row[6] else 0
                    if ds not in daily_data:
                        daily_data[ds] = []
                    daily_data[ds].append({"qty": qty, "pnl": pnl})
                except (ValueError, IndexError):
                    continue

            if not daily_data:
                return None

            sorted_dates = sorted(daily_data.keys())
            running_capital = self.STARTING_CAPITAL
            peak_capital = self.STARTING_CAPITAL
            worst_dd_pct = 0.0
            output_rows = []
            net_dd = 0.0

            for ds in sorted_dates:
                trades = daily_data[ds]
                total_trades = len(trades)
                total_qty = sum(t["qty"] for t in trades)
                gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
                gross_loss = sum(t["pnl"] for t in trades if t["pnl"] < 0)
                net_pnl = gross_profit + gross_loss
                wins = sum(1 for t in trades if t["pnl"] > 0)
                losses = sum(1 for t in trades if t["pnl"] < 0)
                wr = (wins / total_trades * 100) if total_trades > 0 else 0

                running_capital += net_pnl
                if running_capital > peak_capital:
                    peak_capital = running_capital

                net_dd = 0.0
                if running_capital < self.STARTING_CAPITAL:
                    net_dd = (self.STARTING_CAPITAL - running_capital) / self.STARTING_CAPITAL * 100

                if peak_capital > 0:
                    dd_fp = (peak_capital - running_capital) / peak_capital * 100
                    if dd_fp > worst_dd_pct:
                        worst_dd_pct = dd_fp

                output_rows.append([
                    ds, total_trades, round(total_qty, 4),
                    wins, losses, round(wr, 2),
                    round(gross_profit, 2), round(gross_loss, 2), round(net_pnl, 2),
                    round(running_capital, 2), round(net_dd, 2), round(worst_dd_pct, 2), ""
                ])

            self.analytics_ws.clear()
            self.analytics_ws.append_row(self.HEADER)

            total_t = sum(r[1] for r in output_rows)
            summary = [
                "TOTAL", total_t, round(sum(r[2] for r in output_rows), 4),
                sum(r[3] for r in output_rows), sum(r[4] for r in output_rows),
                round(sum(r[3] for r in output_rows) / max(total_t, 1) * 100, 2),
                round(sum(r[6] for r in output_rows), 2),
                round(sum(r[7] for r in output_rows), 2),
                round(sum(r[8] for r in output_rows), 2),
                round(running_capital, 2),
                round(net_dd, 2) if running_capital < self.STARTING_CAPITAL else 0,
                round(worst_dd_pct, 2), "Start: $10,000"
            ]
            self.analytics_ws.append_row(summary)
            self.analytics_ws.append_row([""] * 13)
            if output_rows:
                self.analytics_ws.append_rows(output_rows)

            try:
                self.analytics_ws.format("A1:M1", {"textFormat": {"bold": True}})
                self.analytics_ws.format("A2:M2", {
                    "textFormat": {"bold": True},
                    "backgroundColor": {"red": 0.9, "green": 0.95, "blue": 1.0}
                })
            except Exception:
                pass

            logger.info("Analytics: %d days, Capital: $%.2f", len(output_rows), running_capital)
            return {
                "days": len(output_rows), "total_trades": total_t,
                "net_pnl": summary[8], "running_capital": running_capital,
                "worst_dd": worst_dd_pct
            }
        except Exception as e:
            logger.error("Analytics rebuild failed: %s", e)
            import traceback
            traceback.print_exc()
            return None

    def update_today(self):
        return self.rebuild_all_daily_analytics()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    writer = AnalyticsWriter()
    result = writer.rebuild_all_daily_analytics()
    if result:
        print("=" * 60)
        print("ANALYTICS WRITTEN TO GOOGLE SHEETS")
        print("=" * 60)
        print("  Days tracked:    %d" % result["days"])
        print("  Total trades:    %d" % result["total_trades"])
        print("  Net PnL:         $%.2f" % result["net_pnl"])
        print("  Running Capital: $%.2f" % result["running_capital"])
        print("  Worst DD:        %.2f%%" % result["worst_dd"])
    else:
        print("Failed to write analytics")
