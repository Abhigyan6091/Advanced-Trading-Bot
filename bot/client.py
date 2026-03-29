import os
from binance.client import Client
from dotenv import load_dotenv

load_dotenv()

def get_client():
    api_key = os.getenv("API_KEY")
    api_secret = os.getenv("API_SECRET")

    if not api_key or not api_secret:
        raise ValueError("Missing API keys in .env")

    client = Client(api_key, api_secret)
    client.FUTURES_URL = "https://testnet.binancefuture.com"
    return client