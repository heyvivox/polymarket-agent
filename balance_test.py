from web3 import Web3

# Polygon RPC
w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))

# Your MetaMask wallet address (public, not private key)
# Replace with your actual 0x address
WALLET = "0xYOUR_WALLET_ADDRESS_HERE"

# USDC.e contract on Polygon
USDC_CONTRACT = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
ABI = [{"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"type":"function"}]

contract = w3.eth.contract(address=USDC_CONTRACT, abi=ABI)
balance = contract.functions.balanceOf(Web3.to_checksum_address(WALLET)).call()
print(f"USDC balance: ${balance / 1e6:.2f}")
