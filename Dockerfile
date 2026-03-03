FROM python:3.12-slim

WORKDIR /app

# Combine system deps and clean up in ONE layer
RUN apt-get update && apt-get install -y \
    gcc \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install heavy requirements separately to leverage cache
COPY requirements.txt .
RUN pip install --no-cache-dir pandas==2.2.0 numpy==1.26.4
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p storage

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "tradingview_webhook_bot.tradingview_webhook_server:app"]
