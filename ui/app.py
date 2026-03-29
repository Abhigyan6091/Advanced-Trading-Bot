import streamlit as st
from bot.orders import place_order
from bot.strategy import ema_strategy

st.title("📈 Trading Bot")

symbol = st.text_input("Symbol", "BTCUSDT")
side = st.selectbox("Side", ["BUY", "SELL"])
otype = st.selectbox("Type", ["MARKET", "LIMIT", "STOP_MARKET"])
qty = st.number_input("Quantity", 0.001)

price = st.number_input("Price", 0.0)
stop = st.number_input("Stop Price", 0.0)

if st.button("Place Order"):
    res = place_order(symbol, side, otype, qty, price, stop)
    st.write(res)

if st.button("Run EMA Strategy"):
    res = ema_strategy(symbol, qty)
    st.write(res)