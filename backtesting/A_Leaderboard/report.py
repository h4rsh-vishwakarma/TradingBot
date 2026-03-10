import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'db.sqlite3')


def get_stars(sharpe, pf, profit):

    if profit <= 0:
        return "❌"

    if sharpe > 20 and pf > 2.5:
        return "⭐⭐⭐"

    if sharpe > 10 or pf > 1.8:
        return "⭐⭐"

    return "⭐"


def generate_report():

    if not os.path.exists(DB_PATH):
        print("❌ Database not found. Run ingest_csv.py first.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:

        cursor.execute("""
        SELECT strategy_name, net_profit, profit_factor, win_rate, max_dd, sharpe
        FROM metrics
        ORDER BY net_profit DESC
        """)

        rows = cursor.fetchall()

    except sqlite3.OperationalError:

        print("❌ metrics table does not exist.")
        conn.close()
        return

    if not rows:

        print("⚠️ No strategy data found.")
        conn.close()
        return

    print("=" * 60)
    print("🏆 TRADINGVIEW STRATEGY LEADERBOARD")
    print("=" * 60)
    print()

    for i, row in enumerate(rows):

        name, profit, pf, win, dd, sharpe = row
        stars = get_stars(sharpe, pf, profit)

        print(f"{i+1}. {name} {stars}")
        print(f"   💰 Net Profit: ${profit:,.2f}")
        print(f"   📊 Profit Factor: {pf}")
        print(f"   🎯 Win Rate: {win}%")
        print(f"   📉 Max Drawdown: ${dd:,.2f}")
        print(f"   ⚡ Sharpe: {sharpe}")
        print()

    print("-" * 40)
    print("📊 KEY INSIGHTS")
    print("-" * 40)

    cursor.execute("""
    SELECT strategy_name, sharpe
    FROM metrics
    ORDER BY sharpe DESC
    LIMIT 1
    """)

    res = cursor.fetchone()

    if res:
        print(f"✔ Highest Risk Adjusted Return (Sharpe): {res[0]} ({res[1]})")

    cursor.execute("""
    SELECT strategy_name, win_rate
    FROM metrics
    ORDER BY win_rate DESC
    LIMIT 1
    """)

    res = cursor.fetchone()

    if res:
        print(f"✔ Highest Win Rate: {res[0]} ({res[1]}%)")

    cursor.execute("""
    SELECT strategy_name, max_dd
    FROM metrics
    WHERE net_profit > 0
    ORDER BY max_dd ASC
    LIMIT 1
    """)

    res = cursor.fetchone()

    if res:
        print(f"✔ Safest Strategy (Lowest Drawdown): {res[0]} (${res[1]:,.2f})")

    conn.close()


if __name__ == "__main__":
    generate_report()