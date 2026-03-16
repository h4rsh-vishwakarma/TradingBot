import subprocess
import csv
import re

def export_to_csv():
    # Command to get logs from last 12 hours
    cmd = ['journalctl', '-u', 'trading_orchestrator', '--since', '12 hours ago', '--no-hostname']
    logs = subprocess.check_output(cmd).decode('utf-8')

    with open('trading_audit_12h.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Timestamp', 'Level', 'Event', 'Details'])

        for line in logs.split('\n'):
            if not line: continue
            
            # Simple regex to split timestamp and message
            parts = re.split(r'\s+', line, maxsplit=3)
            if len(parts) >= 4:
                timestamp = f"{parts[0]} {parts[1]}"
                level = parts[2]
                message = parts[3]
                
                # Tag specific events for easier filtering in Excel
                event_type = "GENERAL"
                if "Order Success" in message: event_type = "TRADE_EXECUTION"
                elif "Signal Received" in message: event_type = "WEBHOOK_IN"
                elif "Safety Gate Block" in message: event_type = "RISK_BLOCK"
                elif "Error" in message: event_type = "ERROR"

                writer.writerow([timestamp, level, event_type, message])

    print("✅ Exported to trading_audit_12h.csv")

if __name__ == "__main__":
    export_to_csv()
