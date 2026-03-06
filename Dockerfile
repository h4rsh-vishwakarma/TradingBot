FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y     build-essential     python3-dev     sqlite3     && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir     python-dotenv     pyTelegramBotAPI     python-binance     flask     pandas     requests     tenacity     psutil     google-auth     google-api-python-client     pydantic     ccxt     gspread     oauth2client

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH="/app:/app/tradingview_webhook_bot"

CMD ["python3", "tradingview_webhook_bot/main_enhanced.py"]
