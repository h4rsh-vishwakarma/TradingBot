#!/usr/bin/env python3
"""
top_strategies.py — CLI: Show top profitable strategies with TradingView webhook setup

Usage:
  python3 top_strategies.py                          # top 20 across all symbols
  python3 top_strategies.py --symbol FILUSDT         # filter by symbol
  python3 top_strategies.py --symbol FILUSDT LDOUSDT UNIUSDT
  python3 top_strategies.py --tier ALPHA++           # filter by tier
  python3 top_strategies.py --min-oos 0.25           # min OOS ROI
  python3 top_strategies.py --show-alert             # show TradingView alert format
  python3 top_strategies.py --top 5 --show-alert     # top 5 with alert format
"""
import csv, os, sys, argparse, textwrap

CSV_PATH = "/home/ubuntu/tradingview_webhook_bot/storage/reports/tournament_winners.csv"
WEBHOOK_SECRET = "squeeze_tradingview_cluster_2026_secure"
SERVER_IP = "15.207.152.119"
WEBHOOK_URL = f"http://{SERVER_IP}/webhook/tradingview"

# Strategy name → TradingView display name mapping
STRATEGY_TV_NAMES = {
    "Aggressive_Entry":    "10 Aggressive Entry",
    "Full_Momentum":       "21 Full Momentum",
    "Ichimoku_Trend_Pro":  "22 Ichimoku Trend Pro",
    "Ichimoku_MACD_Pro":   "23 Ichimoku MACD Pro",
    "Keltner_Breakout":    "24 Keltner Breakout",
    "MACD_Breakout":       "07 MACD Breakout",
    "Hybrid_SMC":          "Hybrid SMC [MarkitTick]",
    "SMC_LuxAlgo_WH":      "SMC Strategy [LuxAlgo] + Webhook",
    "BB_Squeeze_Break":    "BB Squeeze Break",
    "ML_Lorentzian":       "ML Lorentzian Classification",
    "EMA_Break_Momentum":  "03 EMA Break Momentum",
    "PSAR_Volume_Surge":   "44 PSAR Volume Surge 4h",
    "VWAP_Break_Entry":    "VWAP Break Entry [Live Trading]",
}

COLORS = {
    "ALPHA++": "\033[92m",  # green
    "ALPHA":   "\033[94m",  # blue
    "AVERAGE": "\033[93m",  # yellow
    "REJECT":  "\033[91m",  # red
    "RESET":   "\033[0m",
    "BOLD":    "\033[1m",
    "CYAN":    "\033[96m",
    "DIM":     "\033[2m",
}

def c(text, *color_keys):
    return "".join(COLORS.get(k,"") for k in color_keys) + str(text) + COLORS["RESET"]

def tv_name(strat):
    return STRATEGY_TV_NAMES.get(strat, strat.replace("_", " "))

def alert_format(strat, symbol):
    tv = tv_name(strat)
    return (
        f"{tv} | {symbol} - Webhook ({WEBHOOK_SECRET}): "
        f"order {{{{strategy.order.action}}}} @ {{{{strategy.order.contracts}}}} "
        f"filled on BINANCE:{symbol}.P. New strategy position is {{{{strategy.position_size}}}}"
    )

def load_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))

def main():
    parser = argparse.ArgumentParser(description="Top profitable strategies from tournament")
    parser.add_argument("--symbol", nargs="+", default=[], help="Filter by symbol(s)")
    parser.add_argument("--tier", choices=["ALPHA++","ALPHA","AVERAGE"], default=None)
    parser.add_argument("--min-oos", type=float, default=0.10, help="Min OOS ROI %/day (default 0.10)")
    parser.add_argument("--top", type=int, default=20, help="Show top N results")
    parser.add_argument("--show-alert", action="store_true", help="Show TradingView alert format")
    parser.add_argument("--all", action="store_true", help="Show all tiers")
    args = parser.parse_args()

    rows = load_csv(CSV_PATH)

    # Filter
    filtered = []
    for r in rows:
        sym = r.get("Symbol","")
        tier = r.get("Tier","")
        oos = float(r.get("OOS_Daily_ROI_%",0) or 0)
        is_roi = float(r.get("Daily_ROI_%",0) or 0)

        if args.symbol and sym not in args.symbol:
            continue
        if args.tier and tier != args.tier:
            continue
        if not args.all and tier not in ("ALPHA++","ALPHA"):
            continue
        if oos < args.min_oos:
            continue
        filtered.append(r)

    # Sort by OOS desc
    filtered.sort(key=lambda x: -float(x.get("OOS_Daily_ROI_%",0) or 0))
    filtered = filtered[:args.top]

    if not filtered:
        print(c("No strategies found with given filters.", "RESET"))
        print(f"  Try: python3 top_strategies.py --min-oos 0.05")
        sys.exit(0)

    print()
    print(c("═" * 90, "BOLD"))
    title = "  🏆 TOP PROFITABLE STRATEGIES"
    if args.symbol:
        title += f"  [{', '.join(args.symbol)}]"
    print(c(title, "BOLD", "CYAN"))
    print(c(f"  Source: {CSV_PATH}", "DIM"))
    print(c("═" * 90, "BOLD"))
    print()

    # Header
    print(c(f"{'#':<4}{'Symbol':<12}{'Strategy':<28}{'Tier':<12}{'OOS ROI':<11}{'IS ROI':<10}{'Win%':<8}{'GDD%':<9}{'OOS Sharpe'}", "BOLD"))
    print(c("-" * 90, "DIM"))

    for i, r in enumerate(filtered, 1):
        sym    = r.get("Symbol","?")
        strat  = r.get("Strategy","?")
        tier   = r.get("Tier","?")
        oos    = float(r.get("OOS_Daily_ROI_%",0) or 0)
        is_roi = float(r.get("Daily_ROI_%",0) or 0)
        wr     = r.get("Win_Rate_%","?")
        gdd    = r.get("Gross_DD_%","?")
        oos_sh = r.get("OOS_Sharpe","?")

        tier_color = "ALPHA++" if tier == "ALPHA++" else ("ALPHA" if tier == "ALPHA" else "RESET")
        tier_colored = c(f"{tier:<12}", tier_color, "BOLD") if tier in ("ALPHA++","ALPHA") else f"{tier:<12}"

        print(f"{c(str(i)+'.',  'DIM'):<7}{c(sym,'BOLD'):<20}{strat[:27]:<28}{tier_colored}{c('%.3f%%'%oos,'BOLD'):<20}{is_roi:<10.3f}{str(wr)+'%':<8}{str(gdd)+'%':<9}{oos_sh}")

    print(c("-" * 90, "DIM"))
    print(c(f"  Total: {len(filtered)} strategies shown", "DIM"))
    print()

    # TradingView Alert Format
    if args.show_alert:
        print(c("═" * 90, "BOLD"))
        print(c("  📋 TRADINGVIEW ALERT FORMAT — Copy-paste into TradingView Alert > Message", "BOLD", "CYAN"))
        print(c("  Webhook URL: " + WEBHOOK_URL, "DIM"))
        print(c("═" * 90, "BOLD"))
        print()
        seen = set()
        for r in filtered:
            strat = r.get("Strategy","?")
            sym   = r.get("Symbol","?")
            oos   = float(r.get("OOS_Daily_ROI_%",0) or 0)
            tier  = r.get("Tier","?")
            key   = (strat, sym)
            if key in seen: continue
            seen.add(key)

            tv = tv_name(strat)
            alert = alert_format(strat, sym)
            print(c(f"  [{tier}] {sym} — {strat}  (OOS: {oos:.3f}%/day)", "BOLD"))
            print(c(f"  TradingView Script Name: ", "DIM") + c(tv, "CYAN"))
            print(c(f"  Alert Message:", "DIM"))
            print(c("  ┌─────────────────────────────────────────────────────────────────────────────────┐", "DIM"))
            for line in textwrap.wrap(alert, 80):
                print(c("  │ ", "DIM") + line)
            print(c("  └─────────────────────────────────────────────────────────────────────────────────┘", "DIM"))
            print()

    # Summary by symbol
    if not args.symbol:
        from collections import defaultdict
        by_sym = defaultdict(list)
        for r in filtered:
            by_sym[r["Symbol"]].append(float(r.get("OOS_Daily_ROI_%",0) or 0))

        print(c("  📊 Summary by Symbol:", "BOLD"))
        sym_summary = sorted(by_sym.items(), key=lambda x: -sum(x[1]))
        for sym, oos_list in sym_summary[:10]:
            best = max(oos_list)
            count = len(oos_list)
            bar = "█" * int(best * 30)
            print(f"    {c(sym,'BOLD'):<20} {count} strategies  best OOS: {c('%.3f%%/day' % best,'BOLD')}  {c(bar,'CYAN')}")
        print()

if __name__ == "__main__":
    main()
