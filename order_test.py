"""
Quick $1 order test for V2 SDK - debug version
"""
import os, time, requests, json
from dotenv import load_dotenv
load_dotenv('/Users/saadmazouz/polymarket-agent/.env')

from py_clob_client_v2 import (ClobClient, ApiCreds, OrderArgs,
                                OrderType, Side, PartialCreateOrderOptions)

PRIVATE_KEY = os.getenv("PRIVATE_KEY") or os.getenv("POLYMARKET_PRIVATE_KEY")
API_KEY     = os.getenv("POLY_API_KEY") or os.getenv("POLYMARKET_API_KEY")
API_SECRET  = os.getenv("POLY_API_SECRET") or os.getenv("POLYMARKET_API_SECRET")
API_PASS    = os.getenv("POLY_API_PASSPHRASE") or os.getenv("POLYMARKET_API_PASSPHRASE")
FUNDER      = "0xec8de7FBab84518AeE23fc131aab93324a588CA3"

creds  = ApiCreds(api_key=API_KEY, api_secret=API_SECRET, api_passphrase=API_PASS)
client = ClobClient(host="https://clob.polymarket.com", chain_id=137,
                    key=PRIVATE_KEY, creds=creds,
                    signature_type=0)
print("✅ Client ready")

# Find next window
now  = time.time()
w_ts = int(now) - (int(now) % 300) + 300
slug = f"btc-updown-5m-{w_ts}"
print(f"Market: {slug}")

r      = requests.get("https://gamma-api.polymarket.com/markets", params={"slug": slug})
m      = r.json()[0]
ids    = json.loads(m.get("clobTokenIds", "[]"))
prices = json.loads(m.get("outcomePrices", "[]"))
token_id = ids[0]

# Get orderbook via REST
r2   = requests.get("https://clob.polymarket.com/book", params={"token_id": token_id})
book = r2.json()
asks = sorted([float(a["price"]) for a in book.get("asks", [])])
best_ask = asks[0] if asks else None
print(f"Best ask: ${best_ask}")

taker_price = min(round(best_ask + 0.02, 2), 0.97)
shares      = round(1.00 / taker_price, 4)
print(f"Price: {taker_price}, Shares: {shares}")

# Build order and inspect BEFORE sending
args = OrderArgs(token_id=token_id, price=taker_price, size=shares, side=Side.BUY)
opts = PartialCreateOrderOptions(tick_size="0.01")

print("\nBuilding signed order...")
signed = client.create_order(args, options=opts)
print("Signed order dict:", signed.order.dict() if hasattr(signed, 'order') else signed)

# Now post it
print("\nPosting...")
try:
    resp = client.post_order(signed, OrderType.FOK)
    print("✅ Response:", resp)
except Exception as e:
    print(f"❌ Error: {e}")
