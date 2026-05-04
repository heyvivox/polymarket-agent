import requests

PROXY = "0xee0dFa20d202fBe03FF903E55f6959b621fbd77A"

# Check trades to see recent activity
r = requests.get("https://data-api.polymarket.com/trades",
                 params={"user": PROXY, "limit": 5})
print("Recent trades:", r.json())

# Check positions
r2 = requests.get("https://data-api.polymarket.com/positions",
                  params={"user": PROXY})
print("Positions:", r2.json())
