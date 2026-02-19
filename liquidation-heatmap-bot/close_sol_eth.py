#!/usr/bin/env python3
from binance_futures_adapter import BinanceFuturesAdapter

adapter = BinanceFuturesAdapter(
    api_key=dIuCO3DHfkmEsk0iLyGIIe9Vjjeeaycu0WHEIjaG5yz1qG1Fdq9pKb4dFBzzKoPI,
    api_secret=iRS1ME5Yq6bv2CytWD0oES38YMYetimNXQ78YaEpNAukWktR4XRYqtq4iKwQYsK7,
    testnet=True
)

print(= * 70)
print(CLOSING PROFITABLE SOL AND ETH POSITIONS)
print(= * 70)

positions = adapter.client.futures_position_information()

for pos in positions:
    amt = float(pos[positionAmt])
    pnl = float(pos[unRealizedProfit])
    symbol = pos[symbol]
    
    if abs(amt) > 0 and pnl > 0 and symbol in [SOLUSDT, ETHUSDT]:
        side_text = SELL if amt > 0 else BUY
        position_side = LONG if amt > 0 else SHORT
        
        print(f\n{symbol} {position_side})
        print(f Amount: {abs(amt)})
        print(f PnL: )
        print(f Closing with {side_text} market order...)
        
        order = adapter.client.futures_create_order(
            symbol=symbol,
            side=side_text,
            type=MARKET,
            quantity=abs(amt),
            reduceOnly=True
        )
        
        print(f SUCCESS - Order ID: {order[ orderId]})

print(\n + = * 70)
print(DONE - Positions Closed)
print(= * 70)
