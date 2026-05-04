import os
from dotenv import load_dotenv
load_dotenv('/Users/saadmazouz/polymarket-agent/.env')

from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds, BalanceAllowanceParams, AssetType

FUNDER = os.getenv("POLY_FUNDER_ADDR", "0xec8de7FBab84518AeE23fc131aab93324a588CA3")

creds = ApiCreds(
    api_key=os.getenv("POLY_API_KEY"),
    api_secret=os.getenv("POLY_API_SECRET"),
    api_passphrase=os.getenv("POLY_API_PASSPHRASE"),
)

client = ClobClient(
    host="https://clob.polymarket.com",
    key=os.getenv("PRIVATE_KEY"),
    chain_id=137,
    creds=creds,
    signature_type=0,
)

params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)

print(f"Funder: {FUNDER}")
print("Checking balance/allowance...")
try:
    bal = client.get_balance_allowance(params=params)
    balance   = int(bal.get("balance",   0))
    allowance = int(bal.get("allowance", 0))
    print(f"  Balance  : ${balance/1e6:.2f} USDC")
    print(f"  Allowance: ${allowance/1e6:.2f} USDC")
except Exception as e:
    print(f"ERROR reading balance: {e}")

print("\nSetting max allowance...")
try:
    r = client.update_balance_allowance(params=params)
    print(f"✅ Done: {r}")
except Exception as e:
    print(f"❌ ERROR: {e}")
