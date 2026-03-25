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


    # ======= BACKTEST SHEETS (auto-update on every trade) =======

    BACKTEST_WITH_HEADER = [
        "Date", "Total Signals", "Executed", "Blocked", "Total Qty",
        "Wins", "Losses", "Win Rate %",
        "Gross Profit", "Gross Loss", "Net PnL",
        "Running Capital", "Net DD %", "Worst DD %"
    ]

    def _get_or_create_tab(self, tab_name):
        try:
            ws = self.spreadsheet.worksheet(tab_name)
            ws.clear()
            return ws
        except gspread.exceptions.WorksheetNotFound:
            return self.spreadsheet.add_worksheet(title=tab_name, rows=2000, cols=15)

    def _parse_blocked_trades(self):
        try:
            blocked_ws = self.spreadsheet.worksheet("Blocked Trades")
            rows = blocked_ws.get_all_values()
            header = rows[0] if rows else []
            data = rows[1:] if header and header[0].lower() in ("timestamp", "time") else rows
            trades = []
            for row in data:
                if len(row) < 5:
                    continue
                try:
                    ts = row[0].strip()
                    dt = None
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S"):
                        try:
                            dt = datetime.strptime(ts, fmt)
                            break
                        except ValueError:
                            continue
                    if not dt:
                        continue
                    trades.append({
                        "date": dt.strftime("%Y-%m-%d"),
                        "qty": 0, "pnl": 0, "status": "BLOCKED"
                    })
                except (ValueError, IndexError):
                    continue
            return trades
        except Exception:
            return []

    def _parse_executed_trades(self):
        try:
            rows = self.trades_ws.get_all_values()
            header = rows[0] if rows else []
            data = rows[1:] if header and header[0].lower() in ("signal_id", "id", "signal id") else rows
            trades = []
            for row in data:
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
                    if not dt:
                        continue
                    trades.append({
                        "date": dt.strftime("%Y-%m-%d"),
                        "qty": float(row[4]) if row[4] else 0,
                        "pnl": float(row[6]) if row[6] else 0,
                        "status": "EXECUTED"
                    })
                except (ValueError, IndexError):
                    continue
            return trades
        except Exception:
            return []

    def _compute_daily(self, trades):
        daily = {}
        for t in trades:
            ds = t["date"]
            if ds not in daily:
                daily[ds] = []
            daily[ds].append(t)

        running = self.STARTING_CAPITAL
        peak = self.STARTING_CAPITAL
        worst_dd = 0.0
        rows = []

        for ds in sorted(daily.keys()):
            day = daily[ds]
            total = len(day)
            executed = sum(1 for t in day if t["status"] == "EXECUTED")
            blocked = sum(1 for t in day if t["status"] == "BLOCKED")
            total_qty = sum(t["qty"] for t in day)
            gp = sum(t["pnl"] for t in day if t["pnl"] > 0)
            gl = sum(t["pnl"] for t in day if t["pnl"] < 0)
            net = gp + gl
            wins = sum(1 for t in day if t["pnl"] > 0)
            losses = sum(1 for t in day if t["pnl"] < 0)
            wr = (wins / max(executed, 1)) * 100

            running += net
            if running > peak:
                peak = running
            net_dd = max(0, (self.STARTING_CAPITAL - running) / self.STARTING_CAPITAL * 100)
            dd_fp = max(0, (peak - running) / peak * 100) if peak > 0 else 0
            if dd_fp > worst_dd:
                worst_dd = dd_fp

            rows.append([
                ds, total, executed, blocked, round(total_qty, 4),
                wins, losses, round(wr, 2),
                round(gp, 2), round(gl, 2), round(net, 2),
                round(running, 2), round(net_dd, 2), round(worst_dd, 2)
            ])
        return rows, running, worst_dd

    def _write_backtest_tab(self, tab_name, title, daily_rows, running, worst_dd):
        ws = self._get_or_create_tab(tab_name)
        # Build all rows first, then write in one batch to avoid column shifting
        all_data = []
        # Row 1: Title (pad to 14 cols)
        title_row = [title] + [""] * 13
        all_data.append(title_row)
        # Row 2: Summary
        if daily_rows:
            ts = sum(r[1] for r in daily_rows)
            te = sum(r[2] for r in daily_rows)
            tb = sum(r[3] for r in daily_rows)
            tw = sum(r[5] for r in daily_rows)
            tl = sum(r[6] for r in daily_rows)
            tgp = sum(r[8] for r in daily_rows)
            tgl = sum(r[9] for r in daily_rows)
            tn = sum(r[10] for r in daily_rows)
            wr = round(tw / max(te, 1) * 100, 2)
            nd = round((self.STARTING_CAPITAL - running) / self.STARTING_CAPITAL * 100, 2) if running < self.STARTING_CAPITAL else 0
            all_data.append(["TOTAL", ts, te, tb, "", tw, tl, wr, round(tgp,2), round(tgl,2), round(tn,2), round(running,2), nd, round(worst_dd,2)])
        else:
            all_data.append(["TOTAL"] + ["0"] * 13)
        # Row 3: Empty separator (14 cols)
        all_data.append([""] * 14)
        # Row 4: Header
        all_data.append(self.BACKTEST_WITH_HEADER)
        # Row 5+: Daily data
        if daily_rows:
            all_data.extend(daily_rows)
        # Write all at once using update (A1 based)
        ws.update(range_name=f"A1:N{len(all_data)}", values=all_data)
        # Format
        try:
            ws.format("A1:N1", {"textFormat": {"bold": True, "fontSize": 12}})
            ws.format("A2:N2", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 1.0}})
            ws.format("A4:N4", {"textFormat": {"bold": True}})
        except Exception:
            pass

    def rebuild_backtest_sheets(self):
        if not self.spreadsheet:
            return
        try:
            executed = self._parse_executed_trades()
            blocked = self._parse_blocked_trades()

            # With Safety = only executed
            r1, c1, d1 = self._compute_daily(executed)
            self._write_backtest_tab("Backtest - With Safety", "BACKTEST: WITH SAFETY BLOCKS (Actual Bot Performance)", r1, c1, d1)

            # Without Safety = executed + blocked
            all_signals = executed + blocked
            all_signals.sort(key=lambda x: x["date"])
            r2, c2, d2 = self._compute_daily(all_signals)
            self._write_backtest_tab("Backtest - Without Safety", "BACKTEST: WITHOUT SAFETY BLOCKS (All Signals)", r2, c2, d2)

            logger.info("Backtest sheets updated: WithSafety=%d days, WithoutSafety=%d days", len(r1), len(r2))
        except Exception as e:
            logger.warning("Backtest sheets update failed: %s", e)

    def update_today(self):
        result = self.rebuild_all_daily_analytics()
        # Backtest sheets are heavier — throttle to every 5 min
        import time as _time
        now = _time.time()
        if not hasattr(self, '_last_backtest_update'):
            self._last_backtest_update = 0
        if now - self._last_backtest_update > 300:
            self.rebuild_backtest_sheets()
            self._last_backtest_update = now
        return result


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
