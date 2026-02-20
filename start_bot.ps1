# start_bot.ps1
echo "🚀 Launching Vibe Coder Trading System..."

# 1. Start Webhook Server (Port 5000)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "python -m core.webhook_server"

# 2. Start Signal Processor (The Executor)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "python -m core.signal_processor"

# 3. Start Reconciler (15s Audit Monitor)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "python -m core.reconciler"

# 4. Start Dashboard (UI)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "streamlit run ui.py"

echo "✅ All components are running in separate windows."