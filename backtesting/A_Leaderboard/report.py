import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'db.sqlite3')

_SUSPECT_WIN_RATE_THRESHOLD = 65.0
_SUSPECT_PF_THRESHOLD = 5.0


def get_stars(sharpe, pf, profit):
    if profit <= 0:
        return "[LOSS]"
    if sharpe > 20 and pf > 2.5:
        return "[***]"
    if sharpe > 10 or pf > 1.8:
        return "[**]"
    return "[*]"


def generate_report():
    if not os.path.exists(DB_PATH):
        print("ERROR: Database not found. Run ingest_csv.py first.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute("""
        SELECT strategy_name, net_profit, profit_factor, win_rate, max_dd, sharpe, source, suspect
        FROM metrics
        ORDER BY net_profit DESC
        """)
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        print("ERROR: metrics table does not exist.")
        conn.close()
        return

    if not rows:
        print("WARNING: No strategy data found.")
        conn.close()
        return

    print("=" * 70)
    print("TRADINGVIEW STRATEGY LEADERBOARD")
    print("=" * 70)
    print(f"  Source legend: [TV] = tv_backtester  [PY] = python_backtester")
    print(f"  SUSPECT = win_rate > {_SUSPECT_WIN_RATE_THRESHOLD}% OR profit_factor > {_SUSPECT_PF_THRESHOLD}")
    print(f"  Suspect entries are BLOCKED from shortlist until re-validated via batch_backtest.py")
    print()

    suspect_list = []

    for i, row in enumerate(rows):
        name, profit, pf, win, dd, sharpe, source, suspect = row
        stars = get_stars(sharpe, pf, profit)
        src_tag = "[TV]" if source == "tv_backtester" else "[PY]"
        suspect_tag = " [SUSPECT -- SHORTLIST BLOCKED]" if suspect == "YES" else ""

        print(f"{i+1}. {src_tag} {name} {stars}{suspect_tag}")
        print(f"   Net Profit: ${profit:,.2f}")
        print(f"   Profit Factor: {pf}  |  Win Rate: {win}%  |  Max DD: ${dd:,.2f}  |  Sharpe: {sharpe}")
        if suspect == "YES":
            reasons = []
            if win > _SUSPECT_WIN_RATE_THRESHOLD:
                reasons.append(f"win_rate {win}% > {_SUSPECT_WIN_RATE_THRESHOLD}% (likely TV lookahead/compounding)")
            if pf > _SUSPECT_PF_THRESHOLD:
                reasons.append(f"profit_factor {pf} > {_SUSPECT_PF_THRESHOLD} (impossible for live trading)")
            print(f"   [!] Suspect reason: {'; '.join(reasons)}")
            suspect_list.append((name, win, pf, source))
        print()

    print("-" * 50)
    print("KEY INSIGHTS")
    print("-" * 50)

    cursor.execute("SELECT strategy_name, sharpe FROM metrics ORDER BY sharpe DESC LIMIT 1")
    res = cursor.fetchone()
    if res:
        print(f"  Highest Risk Adjusted Return (Sharpe): {res[0]} ({res[1]})")

    cursor.execute("SELECT strategy_name, win_rate FROM metrics ORDER BY win_rate DESC LIMIT 1")
    res = cursor.fetchone()
    if res:
        print(f"  Highest Win Rate: {res[0]} ({res[1]}%)")

    cursor.execute("SELECT strategy_name, max_dd FROM metrics WHERE net_profit > 0 ORDER BY max_dd ASC LIMIT 1")
    res = cursor.fetchone()
    if res:
        print(f"  Safest Strategy (Lowest Drawdown): {res[0]} (${res[1]:,.2f})")

    if suspect_list:
        print()
        print("=" * 70)
        print(f"[BLOCKED] SUSPECT ENTRIES -- NOT ELIGIBLE FOR SHORTLIST ({len(suspect_list)} total)")
        print("=" * 70)
        print("  These entries have metrics indicating TV backtester artifacts")
        print("  (infinite compounding, lookahead bias, insufficient slippage).")
        print("  Action: re-run through batch_backtest.py (15 bps, fixed_notional)")
        print("  before promoting to shortlist or approved manifest.")
        print()
        for name, wr, pf, src in suspect_list:
            print(f"  [{src}] {name}  WR={wr}%  PF={pf}")

    cursor.execute("SELECT COUNT(*) FROM metrics WHERE suspect='YES'")
    n_suspect = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM metrics WHERE suspect='NO'")
    n_clean = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM metrics WHERE source='python_backtester'")
    n_py = cursor.fetchone()[0]
    print()
    print(f"  Total: {len(rows)}  |  Clean: {n_clean}  |  Suspect (blocked): {n_suspect}  |  Python-validated: {n_py}")

    conn.close()


if __name__ == "__main__":
    generate_report()
