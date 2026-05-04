import os
from dotenv import load_dotenv
load_dotenv('/Users/saadmazouz/polymarket-agent/.env')
from py_clob_client_v2 import ClobClient

client = ClobClient(
    host="https://clob.polymarket.com",
    chain_id=137,
    key=os.getenv("PRIVATE_KEY"),
)
creds = client.create_or_derive_api_key()
print("POLY_API_KEY=" + creds.api_key)
print("POLY_API_SECRET=" + creds.api_secret)
print("POLY_API_PASSPHRASE=" + creds.api_passphrase)
