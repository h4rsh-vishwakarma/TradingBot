"""
Create two backtest comparison sheets in Google Sheets:
1. "Backtest - With Safety" = Only actually executed trades (from Trades tab)
2. "Backtest - Without Safety" = All signals including blocked ones (Trades + Blocked Trades)
"""

import gspread
import logging
import os
from datetime import datetime
from google.oauth2.service_account import Credentials

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STARTING_CAPITAL = 10000.0


def connect():
    json_key = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE") or "/etc/tradingbot/service_account.json"
    if not os.path.exists(json_key):
        json_key = "/home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot/storage/service_account.json"
    sheet_name = os.getenv("GOOGLE_SHEET_NAME") or "Trading_Bot_Ledger"

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(json_key, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open(sheet_name)


def get_or_create_tab(spreadsheet, tab_name, cols=15):
    try:
        ws = spreadsheet.worksheet(tab_name)
        ws.clear()
        return ws
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=tab_name, rows=2000, cols=cols)
        return ws


def parse_trades(rows):
    """Parse trade rows into list of dicts. Rows: [ID, Time, Symbol, Action, Qty, Price, PnL, Indicator, Strategy]"""
    trades = []
    for row in rows:
        if len(row) < 7:
            continue
        try:
            ts = row[1].strip() if len(row) > 1 else ""
            dt = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S"):
                try:
                    dt = datetime.strptime(ts, fmt)
                    break
                except ValueError:
                    continue
            if dt is None:
                continue

            trades.append({
                "id": row[0] if len(row) > 0 else "",
                "timestamp": dt,
                "date": dt.strftime("%Y-%m-%d"),
                "time": dt.strftime("%H:%M:%S"),
                "symbol": row[2] if len(row) > 2 else "",
                "action": row[3].upper() if len(row) > 3 else "",
                "qty": float(row[4]) if len(row) > 4 and row[4] else 0,
                "price": float(row[5]) if len(row) > 5 and row[5] else 0,
                "pnl": float(row[6]) if len(row) > 6 and row[6] else 0,
                "indicator": row[7] if len(row) > 7 else "",
                "strategy": row[8] if len(row) > 8 else "",
                "status": "EXECUTED"
            })
        except (ValueError, IndexError):
            continue
    return trades


def parse_blocked(rows):
    """Parse blocked rows. Rows: [Timestamp, Symbol, Side, Strategy, Reason, Signal_ID]"""
    trades = []
    for row in rows:
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
            if dt is None:
                continue

            trades.append({
                "id": row[5] if len(row) > 5 else "",
                "timestamp": dt,
                "date": dt.strftime("%Y-%m-%d"),
                "time": dt.strftime("%H:%M:%S"),
                "symbol": row[1] if len(row) > 1 else "",
                "action": row[2].upper() if len(row) > 2 else "",
                "qty": 0,
                "price": 0,
                "pnl": 0,
                "indicator": "",
                "strategy": row[3] if len(row) > 3 else "",
                "status": "BLOCKED",
                "reason": row[4] if len(row) > 4 else ""
            })
        except (ValueError, IndexError):
            continue
    return trades


def compute_daily_summary(trades):
    """Group trades by date and compute daily metrics."""
    daily = {}
    for t in trades:
        ds = t["date"]
        if ds not in daily:
            daily[ds] = {"trades": [], "count": 0}
        daily[ds]["trades"].append(t)
        daily[ds]["count"] += 1

    running_capital = STARTING_CAPITAL
    peak_capital = STARTING_CAPITAL
    worst_dd = 0.0
    rows = []

    for ds in sorted(daily.keys()):
        day_trades = daily[ds]["trades"]
        total = len(day_trades)
        total_qty = sum(t["qty"] for t in day_trades)
        gross_profit = sum(t["pnl"] for t in day_trades if t["pnl"] > 0)
        gross_loss = sum(t["pnl"] for t in day_trades if t["pnl"] < 0)
        net_pnl = gross_profit + gross_loss
        wins = sum(1 for t in day_trades if t["pnl"] > 0)
        losses = sum(1 for t in day_trades if t["pnl"] < 0)
        blocked = sum(1 for t in day_trades if t.get("status") == "BLOCKED")
        executed = total - blocked
        wr = (wins / max(executed, 1)) * 100

        running_capital += net_pnl
        if running_capital > peak_capital:
            peak_capital = running_capital

        net_dd = 0.0
        if running_capital < STARTING_CAPITAL:
            net_dd = (STARTING_CAPITAL - running_capital) / STARTING_CAPITAL * 100

        if peak_capital > 0:
            dd_fp = (peak_capital - running_capital) / peak_capital * 100
            if dd_fp > worst_dd:
                worst_dd = dd_fp

        rows.append([
            ds, total, executed, blocked, round(total_qty, 4),
            wins, losses, round(wr, 2),
            round(gross_profit, 2), round(gross_loss, 2), round(net_pnl, 2),
            round(running_capital, 2), round(net_dd, 2), round(worst_dd, 2)
        ])

    return rows, running_capital, worst_dd


def write_sheet(ws, title, daily_rows, running_capital, worst_dd):
    HEADER = [
        "Date", "Total Signals", "Executed", "Blocked", "Total Qty",
        "Wins", "Losses", "Win Rate %",
        "Gross Profit", "Gross Loss", "Net PnL",
        "Running Capital", "Net DD %", "Worst DD %"
    ]

    # Title row
    ws.append_row([title])

    # Summary
    if daily_rows:
        total_signals = sum(r[1] for r in daily_rows)
        total_exec = sum(r[2] for r in daily_rows)
        total_blocked = sum(r[3] for r in daily_rows)
        total_wins = sum(r[5] for r in daily_rows)
        total_losses = sum(r[6] for r in daily_rows)
        total_gp = sum(r[8] for r in daily_rows)
        total_gl = sum(r[9] for r in daily_rows)
        total_net = sum(r[10] for r in daily_rows)
        wr = round(total_wins / max(total_exec, 1) * 100, 2)
        net_dd = round((STARTING_CAPITAL - running_capital) / STARTING_CAPITAL * 100, 2) if running_capital < STARTING_CAPITAL else 0

        summary = [
            "TOTAL", total_signals, total_exec, total_blocked, "",
            total_wins, total_losses, wr,
            round(total_gp, 2), round(total_gl, 2), round(total_net, 2),
            round(running_capital, 2), net_dd, round(worst_dd, 2)
        ]
        ws.append_row(summary)

    ws.append_row([""])  # separator
    ws.append_row(HEADER)

    if daily_rows:
        ws.append_rows(daily_rows)

    # Format
    try:
        ws.format("A1:N1", {"textFormat": {"bold": True, "fontSize": 12}})
        ws.format("A2:N2", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 1.0}
        })
        ws.format("A4:N4", {"textFormat": {"bold": True}})
    except Exception:
        pass


def main():
    sp = connect()

    # Read Trades tab
    trades_ws = sp.worksheet("Trades")
    all_trades_raw = trades_ws.get_all_values()
    header = all_trades_raw[0] if all_trades_raw else []
    if header and header[0].lower() in ("signal_id", "id", "signal id"):
        trades_data = all_trades_raw[1:]
    else:
        trades_data = all_trades_raw
    executed_trades = parse_trades(trades_data)

    # Read Blocked Trades tab
    try:
        blocked_ws = sp.worksheet("Blocked Trades")
        blocked_raw = blocked_ws.get_all_values()
        bheader = blocked_raw[0] if blocked_raw else []
        if bheader and bheader[0].lower() in ("timestamp", "time"):
            blocked_data = blocked_raw[1:]
        else:
            blocked_data = blocked_raw
        blocked_trades = parse_blocked(blocked_data)
    except Exception:
        blocked_trades = []

    logger.info("Executed trades: %d, Blocked trades: %d", len(executed_trades), len(blocked_trades))

    # --- Sheet 1: With Safety Blocks (only executed trades) ---
    ws1 = get_or_create_tab(sp, "Backtest - With Safety")
    rows1, cap1, dd1 = compute_daily_summary(executed_trades)
    write_sheet(ws1, "BACKTEST: WITH SAFETY BLOCKS (Actual Bot Performance)", rows1, cap1, dd1)
    logger.info("Sheet 1 done: %d days, Capital: $%.2f, Worst DD: %.2f%%", len(rows1), cap1, dd1)

    # --- Sheet 2: Without Safety Blocks (all signals as if all executed) ---
    # Merge executed + blocked, sort by timestamp
    all_signals = executed_trades + blocked_trades
    all_signals.sort(key=lambda x: x["timestamp"])
    ws2 = get_or_create_tab(sp, "Backtest - Without Safety")
    rows2, cap2, dd2 = compute_daily_summary(all_signals)
    write_sheet(ws2, "BACKTEST: WITHOUT SAFETY BLOCKS (All Signals)", rows2, cap2, dd2)
    logger.info("Sheet 2 done: %d days, Capital: $%.2f, Worst DD: %.2f%%", len(rows2), cap2, dd2)

    print("=" * 70)
    print("BACKTEST SHEETS CREATED")
    print("=" * 70)
    print()
    print("Sheet 1: Backtest - With Safety")
    print("  Days: %d | Capital: $%.2f | Worst DD: %.2f%%" % (len(rows1), cap1, dd1))
    print()
    print("Sheet 2: Backtest - Without Safety")
    print("  Days: %d | Capital: $%.2f | Worst DD: %.2f%%" % (len(rows2), cap2, dd2))
    print("=" * 70)


if __name__ == "__main__":
    main()
