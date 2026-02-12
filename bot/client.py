from binance.client import Client
import os
from dotenv import load_dotenv
from .logging_config import logger

load_dotenv()

def get_client():
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    
    if not api_key or not api_secret:
        logger.error("API Keys missing in .env file!")
        raise ValueError("Missing API Keys")

    # Creating the client for Futures Testnet
    return Client(api_key, api_secret, testnet=True)