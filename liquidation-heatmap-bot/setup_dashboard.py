#!/usr/bin/env python3
"""
Setup Live Trading Dashboard with existing Google Sheet
Run after manually creating sheet and sharing with service account
"""

import sys
from live_trading_dashboard import LiveTradingDashboard
from datetime import datetime, timezone

def setup_dashboard(sheet_id: str):
    """Initialize dashboard worksheets and test connection"""
    
    print("=" * 60)
    print("LIVE TRADING DASHBOARD SETUP")
    print("=" * 60)
    print(f"\nSheet ID: {sheet_id}")
    print(f"URL: https://docs.google.com/spreadsheets/d/{sheet_id}")
    
    print("\n✅ Service Account Email (for sharing):")
    print("   btc-layer@useful-field-474109-f0.iam.gserviceaccount.com")
    
    print("\n📝 Make sure you have:")
    print("   1. Created the Google Sheet")
    print("   2. Shared it with the service account (Editor access)")
    print("   3. Shared it with your supervisor (View/Editor access)")
    
    input("\nPress Enter to continue...")
    
    try:
        print("\nConnecting to dashboard...")
        dashboard = LiveTradingDashboard(sheet_id)
        
        print("✅ Connected successfully!")
        print("✅ Worksheets created/verified:")
        print("   - Decisions (trading signals and actions)")
        print("   - Orders (order placements)")
        print("   - Fills (trade executions)")
        print("   - Health (system status and equity)")
        print("   - Summary (key metrics overview)")
        
        print("\n📊 Inserting test data...")
        
        # Test health
        dashboard.insert_health({
            'ts': datetime.now(timezone.utc).isoformat(),
            'equity_usd': 1000.0,
            'pnl_realized_usd': 0.0,
            'pnl_unrealized_usd': 0.0,
            'positions_open': 0,
            'risk_used_pct': 0.0,
            'price_age_s': 1.5,
            'heatmap_age_s': 45,
            'ws_connected': True,
            'coinglass_ok': True
        })
        
        # Test decision
        dashboard.insert_decision({
            'ts': datetime.now(timezone.utc).isoformat(),
            'signal_dir': 'SHORT',
            'action': 'NO_TRADE',
            'signal_strength': 'WEAK',
            'S_long': 0.0,
            'S_short': 0.666,
            'votes': {'m1': 'SHORT', 'm2': 'SHORT', 'm3': 'NEUTRAL'},
            'cluster': {'distance_bps': 50},
            'costs': {'edge_bps': 2.5},
            'context': {
                'confidence': 0.5,
                'bias_reason': 'Test signal - Signal cooldown active',
                'price': 88350.0
            },
            'no_trade_reason': 'Signal cooldown active (test mode)'
        })
        
        print("✅ Test data inserted successfully!")
        print(f"\n🔗 View your dashboard: https://docs.google.com/spreadsheets/d/{sheet_id}")
        print("\n" + "=" * 60)
        print("NEXT STEPS:")
        print("=" * 60)
        print(f"1. Add to config.py:")
        print(f'   live_dashboard_key: str = "{sheet_id}"')
        print(f"\n2. Update observability hub to include dashboard emitter")
        print(f"\n3. Restart bot to start live updates")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Setup failed: {e}")
        print("\nTroubleshooting:")
        print("1. Verify sheet ID is correct")
        print("2. Ensure service account has Editor access to sheet")
        print("3. Check credentials.json exists and is valid")
        return False


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 setup_dashboard.py <SHEET_ID>")
        print("\nExample:")
        print("  python3 setup_dashboard.py 1ZeS5XS-SvnfTpmWQ5KNchV52b5f1X6qBqTWxnYQbBAQ")
        print("\nGet Sheet ID from URL:")
        print("  https://docs.google.com/spreadsheets/d/[SHEET_ID]/edit")
        sys.exit(1)
    
    sheet_id = sys.argv[1]
    success = setup_dashboard(sheet_id)
    sys.exit(0 if success else 1)
