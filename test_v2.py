import os
from dotenv import load_dotenv
load_dotenv('/Users/saadmazouz/polymarket-agent/.env')
from py_clob_client_v2 import ClobClient, ApiCreds, BalanceAllowanceParams, AssetType

creds = ApiCreds(
    api_key=os.getenv("POLY_API_KEY"),
    api_secret=os.getenv("POLY_API_SECRET"),
    api_passphrase=os.getenv("POLY_API_PASSPHRASE"),
)
client = ClobClient(
    host="https://clob.polymarket.com",
    chain_id=137,
    key=os.getenv("PRIVATE_KEY"),
    creds=creds,
)
print("Connection:", client.get_ok())
bal = client.get_balance_allowance(params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
print("Balance:", bal)
