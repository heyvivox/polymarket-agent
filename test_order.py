import os, time, requests, json
from dotenv import load_dotenv
load_dotenv('/Users/saadmazouz/polymarket-agent/.env')
from py_clob_client_v2 import ClobClient, ApiCreds, MarketOrderArgsV2, OrderType, Side, PartialCreateOrderOptions

creds = ApiCreds(api_key=os.getenv("POLY_API_KEY"), api_secret=os.getenv("POLY_API_SECRET"), api_passphrase=os.getenv("POLY_API_PASSPHRASE"))
client = ClobClient(host="https://clob.polymarket.com", chain_id=137, key=os.getenv("PRIVATE_KEY"), creds=creds, signature_type=0)

now = time.time()
w_ts = int(now) - (int(now) % 300) + 300
slug = f"btc-updown-5m-{w_ts}"
print(f"Market: {slug}")
r = requests.get("https://gamma-api.polymarket.com/markets", params={"slug": slug})
m = r.json()[0]
ids = json.loads(m.get("clobTokenIds", "[]"))
token_id = ids[0]
r2 = requests.get("https://clob.polymarket.com/book", params={"token_id": token_id})
asks = sorted([float(a["price"]) for a in r2.json().get("asks", [])])
best_ask = asks[0]
print(f"best_ask={best_ask}")
args = MarketOrderArgsV2(token_id=token_id, amount=1.00, side=Side.BUY, price=best_ask, user_usdc_balance=13.52)
signed = client.create_market_order(args, PartialCreateOrderOptions(tick_size="0.01"))
try:
    resp = client.post_order(signed, OrderType.FOK)
    print("SUCCESS:", resp)
except Exception as e:
    print("ERROR:", e)
