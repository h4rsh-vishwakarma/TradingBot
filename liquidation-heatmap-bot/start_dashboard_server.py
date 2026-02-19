#!/usr/bin/env python3
"""
Simple HTTP server to serve trading bot dashboard and artifacts.
Serves files from backtest_artifacts directory.
"""

import http.server
import socketserver
import os
from pathlib import Path

PORT = 8080
DIRECTORY = "/home/ubuntu/trading_bot"

class MyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)
    
    def end_headers(self):
        # Add CORS headers to allow cross-origin requests
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        super().end_headers()

if __name__ == '__main__':
    os.chdir(DIRECTORY)
    
    with socketserver.TCPServer(("", PORT), MyHTTPRequestHandler) as httpd:
        print(f"✅ Server running at http://0.0.0.0:{PORT}")
        print(f"📁 Serving files from: {DIRECTORY}")
        print(f"🌐 Access dashboard at: http://13.236.143.201:{PORT}/live_dashboard.html")
        print(f"\n📊 Available endpoints:")
        print(f"   - /backtest_artifacts/trade_log.csv")
        print(f"   - /backtest_artifacts/equity.csv")
        print(f"   - /backtest_artifacts/trade_summary.csv")
        print(f"\nPress Ctrl+C to stop the server")
        
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\n🛑 Server stopped")
