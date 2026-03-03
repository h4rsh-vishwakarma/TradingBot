import smtplib
from email.mime.text import MIMEText
import os

class EmailNotifier:
    def __init__(self):
        self.enabled = os.getenv("EMAIL_SENDER") is not None
        
    def send_critical_alert(self, subject, message):
        if not self.enabled: return
        
        msg = MIMEText(message)
        msg['Subject'] = f"🚨 CRITICAL: {subject}"
        msg['From'] = os.getenv("EMAIL_SENDER")
        msg['To'] = os.getenv("EMAIL_RECEIVER")

        try:
            with smtplib.SMTP(os.getenv("SMTP_SERVER"), int(os.getenv("SMTP_PORT"))) as server:
                server.starttls()
                server.login(os.getenv("EMAIL_SENDER"), os.getenv("EMAIL_PASSWORD"))
                server.send_message(msg)
                print("✅ Email Alert Sent!")
        except Exception as e:
            print(f"❌ Email Failed: {e}")
