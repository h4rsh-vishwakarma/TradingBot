from bot.client import get_client

client = get_client()
# Use the exact ID from your successful log
ORDER_ID = "12396152458" 

try:
    order = client.futures_get_order(symbol="BTCUSDT", orderId=ORDER_ID)
    print(f"✅ Order Found!")
    print(f"Status: {order['status']}")
    print(f"Price: {order['avgPrice']}")
    print(f"Executed Qty: {order['executedQty']}")
except Exception as e:
    print(f"❌ Order not found on this account: {e}")