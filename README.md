# 🚀 Binance Futures Testnet Trading Bot

![Python](https://img.shields.io/badge/Python-3.8+-blue)
![CLI](https://img.shields.io/badge/CLI-Typer-green)
![UI](https://img.shields.io/badge/UI-Streamlit-red)
![API](https://img.shields.io/badge/API-Binance-yellow)
![Status](https://img.shields.io/badge/Status-Active-success)

---

## 📌 Overview
This project is a modular **Python-based trading bot** that interacts with the **Binance Futures Testnet (USDT-M)**.

It supports:
- Order placement (Market, Limit, Stop)
- CLI and UI interaction
- Strategy-based auto trading
- Logging, validation, and retry handling

---

## ✨ Features

### 🔹 Core Features
- Place **MARKET** and **LIMIT** orders
- Supports **BUY** and **SELL**
- CLI-based trading using Typer
- Input validation and error handling
- Logging of requests and responses

### 🔹 Advanced Features
- ✅ STOP-MARKET orders
- ✅ Retry mechanism (Tenacity)
- ✅ Interactive CLI (menu-driven)
- ✅ Streamlit dashboard
- ✅ EMA crossover trading strategy

---

## 🧱 Project Structure
```
trading_bot/
│
├── bot/
│   ├── client.py
│   ├── orders.py
│   ├── validators.py
│   ├── strategy.py
│   ├── retry.py
│   ├── logging_config.py
│
├── ui/
│   └── app.py
│
├── logs/
├── cli.py
├── interactive_cli.py
├── requirements.txt
├── README.md
```

---

## ⚙️ Setup Instructions

### 1️⃣ Clone Repository
```bash
git clone https://github.com/your-username/trading-bot.git
cd trading-bot
```

### 2️⃣ Create Virtual Environment (optional)
```bash
python -m venv venv
source venv/bin/activate     # Linux/Mac
venv\Scripts\activate        # Windows
```

### 3️⃣ Install Dependencies
```bash
pip install -r requirements.txt
```

---

## 🔐 Environment Setup

Create a `.env` file:

```env
API_KEY=your_testnet_api_key
API_SECRET=your_testnet_secret
```

Get keys from:
https://testnet.binancefuture.com

---

## ▶️ Usage

### 🔹 CLI (Typer)

#### MARKET Order
```bash
python cli.py trade --symbol BTCUSDT --side BUY --order-type MARKET --quantity 0.001
```

#### LIMIT Order
```bash
python cli.py trade --symbol BTCUSDT --side SELL --order-type LIMIT --quantity 0.001 --price 60000
```

#### STOP-MARKET Order
```bash
python cli.py trade --symbol BTCUSDT --side SELL --order-type STOP_MARKET --quantity 0.001 --stop 59000
```

---

### 🔹 Interactive CLI
```bash
python interactive_cli.py
```

---

### 🔹 Streamlit UI
```bash
streamlit run ui/app.py
```

---

## 📈 Trading Strategy

### EMA Crossover
- EMA(9) and EMA(21)

Logic:
- BUY → EMA9 > EMA21
- SELL → EMA9 < EMA21

---

## 📊 Logging

Logs are stored in:
```
logs/bot.log
```

Includes:
- API requests
- Responses
- Errors & retries

---

## ⚠️ Error Handling

Handles:
- Invalid inputs
- Missing API keys
- API failures
- Network issues

---

## 🧪 Example Output
```
📌 Order Summary:
BTCUSDT | BUY | MARKET | qty=0.001

✅ Order Successful!
Order ID: 123456
Status: FILLED
Executed Qty: 0.001
Avg Price: 59800
```

---

## 📌 Assumptions
- Valid Binance Futures Testnet account
- Correct API keys
- Stable internet connection

---

## 🚀 Future Improvements
- RSI + EMA strategy
- WebSocket live trading
- Backtesting engine
- Docker support
- Unit testing

---

## 👨‍💻 Author
Abhigyan Sharma

---

## 📜 License
For educational purposes only.