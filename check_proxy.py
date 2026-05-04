import os, requests
from dotenv import load_dotenv
load_dotenv('/Users/saadmazouz/polymarket-agent/.env')
from py_clob_client_v2 import ClobClient, ApiCreds, BalanceAllowanceParams, AssetType

FUNDER = os.getenv("POLYMARKET_FUNDER_ADDRESS")

creds = ApiCreds(
    api_key=os.getenv("POLY_API_KEY"),
    api_secret=os.getenv("POLY_API_SECRET"),
    api_passphrase=os.getenv("POLY_API_PASSPHRASE"),
)

# Try with funder address
client = ClobClient(
    host="https://clob.polymarket.com",
    chain_id=137,
    key=os.getenv("PRIVATE_KEY"),
    creds=creds,
    funder=FUNDER,
)
print("Funder:", FUNDER)
bal = client.get_balance_allowance(params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
print("Balance with funder:", bal)

# Also check via Gamma API
r = requests.get("https://gamma-api.polymarket.com/public-profile",
                 params={"address": "0x69f195e5dc8663c536a34b9748d74340628c65ee"})
print("Profile:", r.json())
