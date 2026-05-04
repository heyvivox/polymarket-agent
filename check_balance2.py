import requests

# Your proxy wallet address
PROXY = "0xee0dFa20d202fBe03FF903E55f6959b621fbd77A"

# Check via data API
r = requests.get(f"https://data-api.polymarket.com/value", params={"user": PROXY})
print("Data API:", r.json())

# Check pUSD balance via Polygon RPC
from web3 import Web3
w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))

# pUSD contract (new V2 collateral)
pUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
ABI = [{"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"type":"function"}]
contract = w3.eth.contract(address=Web3.to_checksum_address(pUSD), abi=ABI)
bal = contract.functions.balanceOf(Web3.to_checksum_address(PROXY)).call()
print(f"pUSD balance: ${bal/1e6:.2f}")

# Also check old USDC.e
usdc_e = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
contract2 = w3.eth.contract(address=Web3.to_checksum_address(usdc_e), abi=ABI)
bal2 = contract2.functions.balanceOf(Web3.to_checksum_address(PROXY)).call()
print(f"USDC.e balance: ${bal2/1e6:.2f}")
