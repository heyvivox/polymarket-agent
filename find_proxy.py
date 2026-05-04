
import os

from dotenv import load_dotenv

load_dotenv('/Users/saadmazouz/polymarket-agent/.env')

from py_clob_client.client import ClobClient

from py_clob_client.clob_types import ApiCreds

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

    signature_type=2,

)

print("Your signing address:", client.get_address())

print("Exchange address:", client.get_exchange_address())

print("Collateral address:", client.get_collateral_address())

