import requests, time, json, os
from dotenv import load_dotenv
load_dotenv('/Users/saadmazouz/polymarket-agent/.env')

# Get current window token
now = time.time()
w_ts = int(now) - (int(now) % 300)
slug = f"btc-updown-5m-{w_ts}"
print("Slug:", slug)

r = requests.get("https://gamma-api.polymarket.com/markets", params={"slug": slug})
m = r.json()[0]
ids = json.loads(m.get("clobTokenIds", "[]"))
up_token = ids[0]
print("UP token:", up_token[:20], "...")

# Check orderbook via REST directly
r2 = requests.get(f"https://clob.polymarket.com/book", params={"token_id": up_token})
print("Book status:", r2.status_code)
print("Book response:", r2.text[:400])

# Try via V2 SDK
from py_clob_client_v2 import ClobClient, ApiCreds
creds = ApiCreds(
    api_key=os.getenv("POLY_API_KEY"),
    api_secret=os.getenv("POLY_API_SECRET"),
    api_passphrase=os.getenv("POLY_API_PASSPHRASE"),
)
client = ClobClient(host="https://clob.polymarket.com", chain_id=137,
                    key=os.getenv("PRIVATE_KEY"), creds=creds,
                    signature_type=0)

book = client.get_order_book(up_token)
print("\nSDK book bids:", getattr(book, "bids", None))
print("SDK book asks:", getattr(book, "asks", None))
