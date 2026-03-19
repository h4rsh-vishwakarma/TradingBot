import subprocess
import csv
import re
import os
import pandas as pd

def export_to_csv():
    log_file = 'trading_audit_12h.csv'
    # Get logs from last 12 hours
    cmd = ['journalctl', '-u', 'trading_orchestrator', '--since', '12 hours ago', '--no-hostname']
    logs = subprocess.check_output(cmd).decode('utf-8')

    data = []
    for line in logs.split('\n'):
        if not line or "💓 Heartbeat" in line: continue
        parts = re.split(r'\s+', line, maxsplit=3)
        if len(parts) >= 4:
            timestamp = f"{parts[0]} {parts[1]}"
            message = parts[3]
            
            event_type = "GENERAL"
            if "Order Success" in message: event_type = "TRADE_SUCCESS"
            elif "Signal Received" in message: event_type = "SIGNAL_IN"
            elif "Safety Gate Block" in message or "Hybrid Risk Block" in message: event_type = "RISK_BLOCK"
            elif "Error" in message: event_type = "ERROR"

            data.append([timestamp, event_type, message])

    with open(log_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Timestamp', 'Event', 'Details'])
        writer.writerows(data)

    # Calculate Summary Metrics
    df = pd.DataFrame(data, columns=['Timestamp', 'Event', 'Details'])
    summary = {
        "total_signals": len(df[df['Event'] == 'SIGNAL_IN']),
        "trades": len(df[df['Event'] == 'TRADE_SUCCESS']),
        "blocks": len(df[df['Event'] == 'RISK_BLOCK']),
        "errors": len(df[df['Event'] == 'ERROR'])
    }
    return summary, log_file

if __name__ == "__main__":
    export_to_csv()
