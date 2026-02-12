import streamlit as st
from bot.client import get_client
from bot.orders import place_futures_order

st.set_page_config(page_title="Binance Futures Bot", page_icon="📈")

st.title("🚀 Binance Futures Trader")
st.subheader("Testnet Environment")

# Sidebar for Account Info
with st.sidebar:
    st.header("Account Status")
    try:
        client = get_client()
        acc = client.futures_account()
        st.success("Connected to Testnet")
        st.metric("Wallet Balance", f"{acc['totalWalletBalance']} USDT")
    except Exception as e:
        st.error(f"Connection Error: {e}")

# Main Trading Form
with st.form("order_form"):
    col1, col2 = st.columns(2)
    with col1:
        symbol = st.text_input("Symbol", value="BTCUSDT")
        side = st.selectbox("Side", ["BUY", "SELL"])
    with col2:
        order_type = st.selectbox("Order Type", ["MARKET", "LIMIT"])
        quantity = st.number_input("Quantity", min_value=0.001, step=0.001, format="%.3f")

    price = None
    if order_type == "LIMIT":
        price = st.number_input("Limit Price", min_value=1.0)

    submit = st.form_submit_button("Place Order")

if submit:
    with st.spinner("Executing order..."):
        result = place_futures_order(client, symbol, side, order_type, quantity, price)
        
        if result:
            st.balloons()
            st.success(f"Order Placed! ID: {result['orderId']}")
            st.json(result) # Shows full API response to the recruiter
        else:
            st.error("Order Failed. Check logs for details.")