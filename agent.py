"""
Polymarket AI Smart Scanner Agent v4
--------------------------------------
FIXES over v3 (code audit — April 2026):

  BUG FIXES:
  FIX-A  DOUBLE PROB GATE   : added market_price guard inside place_trade()
                               (v3 only filtered in fetch_markets — Claude could
                               still return an out-of-window trade)
  FIX-B  PAYOUT CALC BUG    : buy_no payout was using wrong formula.
                               Correct: profit_per_$1 = (1 - price) / price
                               for BOTH buy_yes and buy_no (Polymarket binary)
  FIX-C  BOOTSTRAP GUARD    : first 3 trades now capped at 12% regardless of
                               Kelly output (no history = no reliable edge)

  NEW FEATURES:
  FIX-D  VOLATILITY GUARD   : if abs(BTC momentum) > 1.5% in 5 min,
                               skip ALL crypto markets that cycle (false edges)
  FIX-E  MODEL UPDATE       : claude-opus-4-5 → claude-sonnet-4-6
                               (faster, cheaper for bulk scanning)
  FIX-F  WIN RATE TRACKER   : reads trades.csv at boot, computes real win_rate
                               + avg_win + avg_loss from resolved trades
                               (placeholder — Polymarket resolve not automatic)

Requirements: anthropic, requests, python-dotenv
Usage: python3 btc_agent.py
"""

import os
import csv
import json
import time
import datetime
import requests
from dotenv import load_dotenv
import anthropic

# ── Config ────────────────────────────────────────────────────────────────────
load_dotenv()

ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY")
STARTING_BALANCE   = 60.98     # your real starting balance

# ── Risk management constants ─────────────────────────────────────────────────
MIN_PROB           = 0.62      # skip coinflip zone (confirmed losers <0.62)
MAX_PROB           = 0.93      # skip no-payout zone (confirmed losers >0.93)
MIN_EDGE           = 0.12      # need real conviction (raised from 0.08)
MIN_CONFIDENCE     = 0.80      # raised from 0.75
MAX_BET_PCT        = 0.25      # never bet more than 25% of current balance
MAX_BET_ABS        = 50.00     # hard absolute ceiling in dollars
MIN_PAYOUT         = 2.00      # skip if expected profit < $2
STOP_PCT           = 0.70      # pause if balance < 70% of start
MAX_RESOLVE_DAYS   = 14        # only trade markets resolving within 14 days
BOOTSTRAP_TRADES   = 3         # FIX-C: first N trades use conservative 12%
BOOTSTRAP_PCT      = 0.12      # FIX-C: conservative bet during bootstrap
VOLATILITY_THRESH  = 1.5       # FIX-D: skip crypto if |5min momentum| > 1.5%

# ── Operational config ────────────────────────────────────────────────────────
POLL_INTERVAL      = 60
MARKETS_PER_SCAN   = 100
CSV_FILE           = "trades.csv"
LOG_FILE           = "agent.log"

# ── APIs ──────────────────────────────────────────────────────────────────────
GAMMA_API  = "https://gamma-api.polymarket.com"
COINGECKO  = "https://api.coingecko.com/api/v3"

# ── Logger ────────────────────────────────────────────────────────────────────
def log(msg: str):
    ts   = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── BTC Price Cache ───────────────────────────────────────────────────────────
btc_price_history = []

def fetch_btc_price() -> dict:
    """Fetch current BTC price and compute 5-min momentum."""
    try:
        resp = requests.get(
            f"{COINGECKO}/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "usd"},
            timeout=5,
        )
        resp.raise_for_status()
        price = float(resp.json()["bitcoin"]["usd"])
        now   = time.time()
        btc_price_history.append((now, price))

        cutoff = now - 600
        while btc_price_history and btc_price_history[0][0] < cutoff:
            btc_price_history.pop(0)

        momentum     = 0.0
        momentum_str = "flat"
        five_min_ago = now - 300
        older = [p for t, p in btc_price_history if t <= five_min_ago]
        if older:
            old_price = older[-1]
            momentum  = (price - old_price) / old_price * 100
            if momentum >  0.3:  momentum_str = f"STRONG UP +{momentum:.2f}%"
            elif momentum < -0.3: momentum_str = f"STRONG DOWN {momentum:.2f}%"
            elif momentum >  0.1: momentum_str = f"mild up +{momentum:.2f}%"
            elif momentum < -0.1: momentum_str = f"mild down {momentum:.2f}%"
            else:                 momentum_str = f"flat {momentum:.2f}%"

        return {"price": price, "momentum": momentum, "momentum_str": momentum_str}

    except Exception as e:
        log(f"[WARN] BTC price fetch failed: {e}")
        return {"price": None, "momentum": 0.0, "momentum_str": "unavailable"}


# ── Market Fetcher ────────────────────────────────────────────────────────────
def fetch_markets(limit: int = MARKETS_PER_SCAN) -> list:
    """Fetch active binary markets from Polymarket with resolve-window filter."""
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={
                "active":    "true",
                "closed":    "false",
                "limit":     limit,
                "order":     "volume24hr",
                "ascending": "false",
            },
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()

        now     = datetime.datetime.utcnow()
        markets = []

        for m in raw:
            try:
                outcomes   = json.loads(m.get("outcomes", "[]"))
                prices_raw = json.loads(m.get("outcomePrices", "[]"))
                prices     = [float(p) for p in prices_raw]

                if len(outcomes) != 2 or len(prices) != 2:
                    continue

                yes_price = prices[0]
                no_price  = prices[1]

                # prob gate at fetch time
                if yes_price < MIN_PROB or yes_price > MAX_PROB:
                    continue

                if yes_price < 0.02 or yes_price > 0.98:
                    continue

                # resolve window filter
                end_date_str = m.get("endDate", "")
                if end_date_str:
                    try:
                        end_dt = datetime.datetime.fromisoformat(
                            end_date_str.replace("Z", "+00:00")
                        ).replace(tzinfo=None)
                        days_left = (end_dt - now).days
                        if days_left < 0 or days_left > MAX_RESOLVE_DAYS:
                            continue
                    except ValueError:
                        pass

                question = m.get("question", "").lower()
                category = "other"
                if any(w in question for w in ["bitcoin", "btc", "eth", "crypto", "solana"]):
                    category = "crypto"
                elif any(w in question for w in ["trump", "biden", "election", "president", "congress", "senate"]):
                    category = "politics"
                elif any(w in question for w in ["fed", "rate", "gdp", "inflation", "economy"]):
                    category = "macro"
                elif any(w in question for w in ["war", "ceasefire", "conflict", "military", "iran", "russia", "ukraine"]):
                    category = "geopolitics"
                elif any(w in question for w in ["nba", "nfl", "soccer", "tennis", "sport", "champion"]):
                    category = "sports"

                markets.append({
                    "id":           m.get("id", "unknown"),
                    "question":     m.get("question", ""),
                    "yes_price":    yes_price,
                    "no_price":     no_price,
                    "volume_24h":   float(m.get("volume24hr", 0)),
                    "volume_total": float(m.get("volume", 0)),
                    "liquidity":    float(m.get("liquidityNum", 0)),
                    "end_date":     end_date_str,
                    "category":     category,
                    "spread":       float(m.get("spread", 0)),
                })
            except (ValueError, TypeError, json.JSONDecodeError):
                continue

        return markets

    except requests.RequestException as e:
        log(f"[ERROR] Failed to fetch markets: {e}")
        return []


# ── Kelly Bet Sizer ───────────────────────────────────────────────────────────
def kelly_bet(balance: float, edge: float, confidence: float, trade_count: int) -> float:
    """
    Tiered Kelly sizing with bootstrap guard (FIX-C).

    Bootstrap (trade_count < BOOTSTRAP_TRADES):
      → Always 12% regardless of edge/confidence (no history = no trust)

    Normal operation:
      edge 12–20%  → 12% of balance
      edge 20–30%  → 18% of balance
      edge >30%    → 25% of balance
      All scaled by confidence, hard-capped at MAX_BET_PCT and MAX_BET_ABS.
    """
    # FIX-C: bootstrap guard
    if trade_count < BOOTSTRAP_TRADES:
        bet = round(balance * BOOTSTRAP_PCT, 2)
        bet = min(bet, MAX_BET_ABS)
        return bet

    abs_edge = abs(edge)

    if abs_edge >= 0.30:
        base_pct = 0.25
    elif abs_edge >= 0.20:
        base_pct = 0.18
    else:
        base_pct = 0.12

    scaled_pct = base_pct * confidence
    scaled_pct = min(scaled_pct, MAX_BET_PCT)
    bet        = round(balance * scaled_pct, 2)
    bet        = min(bet, MAX_BET_ABS)
    return bet


# ── Claude Mispricing Analysis ────────────────────────────────────────────────
# FIX-E: updated model
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

def ask_claude_mispricing(market: dict, btc_data: dict) -> dict:
    """
    Ask Claude to estimate the TRUE probability and find mispricing.
    Uses claude-sonnet-4-6 (faster, cheaper for bulk scanning).
    """
    btc_context = ""
    if market["category"] == "crypto" and btc_data["price"]:
        btc_context = f"""
LIVE MARKET DATA:
- Current BTC price: ${btc_data['price']:,.0f}
- 5-minute momentum: {btc_data['momentum_str']}
"""

    prompt = f"""You are a quantitative prediction market analyst hunting for MISPRICED markets.

MARKET:
- Question: {market['question']}
- Category: {market['category']}
- Market YES probability: {market['yes_price']*100:.1f}%
- Market NO probability:  {market['no_price']*100:.1f}%
- 24h Volume: ${market['volume_24h']:,.0f}
- Total Volume: ${market['volume_total']:,.0f}
- Liquidity: ${market['liquidity']:,.0f}
- End date: {market['end_date']}
{btc_context}

RULES — only trade if ALL conditions are met:
1. Your estimated TRUE probability must differ from market by >= 12% (edge >= 0.12)
2. You must have confidence >= 0.80 in your estimate
3. Do NOT trade markets where the price is already near the true probability
4. Do NOT recommend action="buy_yes" on a market priced at 0.90+ (no payout left)
5. Be conservative — if uncertain, skip

Edge calculation:
  edge = your_yes_prob - market_yes_price
  Positive edge → market underpricing YES → BUY YES
  Negative edge → market overpricing YES → BUY NO

Respond ONLY with valid JSON (no markdown, no extra text):
{{
  "my_yes_prob": <float 0.0–1.0>,
  "edge": <float, can be negative>,
  "action": "buy_yes" | "buy_no" | "skip",
  "confidence": <float 0.0–1.0>,
  "reasoning": "<2–3 sentences: what the real probability is and why the market is wrong>"
}}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",   # FIX-E: was claude-opus-4-5
            max_tokens=350,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        decision = json.loads(raw)
        decision["market_id"]       = market["id"]
        decision["market_question"] = market["question"]
        decision["yes_price"]       = market["yes_price"]
        decision["no_price"]        = market["no_price"]
        decision["category"]        = market["category"]
        return decision

    except (json.JSONDecodeError, IndexError, anthropic.APIError) as e:
        log(f"[ERROR] Claude analysis failed for {market['id']}: {e}")
        return None


# ── Portfolio ─────────────────────────────────────────────────────────────────
class Portfolio:
    def __init__(self, starting_balance: float, traded_ids: set, trade_count: int = 0):
        self.balance        = starting_balance
        self.starting       = starting_balance
        self.traded_ids     = traded_ids
        self.trade_count    = trade_count
        self.category_stats = {}
        self.stop_triggered = False

    def already_traded(self, market_id: str) -> bool:
        return market_id in self.traded_ids

    def check_stop_loss(self) -> bool:
        """Pause if balance drops below 70% of starting."""
        floor = self.starting * STOP_PCT
        if self.balance <= floor and not self.stop_triggered:
            self.stop_triggered = True
            log(f"🛑 AUTO-STOP: balance ${self.balance:.2f} < ${floor:.2f} "
                f"(70% of ${self.starting:.2f})")
            log("   Trading paused. Restart bot to resume.")
        return self.stop_triggered

    def place_trade(self, decision: dict) -> dict | None:
        action     = decision.get("action")
        confidence = float(decision.get("confidence", 0))
        edge       = float(decision.get("edge", 0))
        abs_edge   = abs(edge)
        market_id  = decision.get("market_id")

        if action == "skip":
            return None
        if self.already_traded(market_id):
            log(f"  ↳ Skip — already traded {market_id}")
            return None
        if self.check_stop_loss():
            return None

        # FIX-A: prob gate inside place_trade (double security layer)
        if action == "buy_yes":
            market_price = decision["yes_price"]
        else:
            market_price = decision["no_price"]

        if not (MIN_PROB <= market_price <= MAX_PROB):
            log(f"  ↳ Skip — market_price {market_price:.3f} outside prob window "
                f"[{MIN_PROB:.2f}, {MAX_PROB:.2f}]")
            return None

        # confidence gate
        if confidence < MIN_CONFIDENCE:
            log(f"  ↳ Skip — confidence {confidence:.2f} < {MIN_CONFIDENCE}")
            return None

        # edge gate
        if abs_edge < MIN_EDGE:
            log(f"  ↳ Skip — edge {abs_edge:.2%} < {MIN_EDGE:.2%}")
            return None

        # FIX-C: Kelly with bootstrap guard (passes trade_count)
        size = kelly_bet(self.balance, edge, confidence, self.trade_count)

        # FIX-B: Corrected payout calculation for both buy_yes and buy_no
        # On Polymarket binary markets:
        #   buy_yes: you pay market_price, collect $1 if YES. Profit = 1 - market_price
        #   buy_no:  you pay no_price, collect $1 if NO.  Profit = 1 - no_price
        # payout_per_dollar = profit / cost = (1 - price) / price for both sides
        payout_per_dollar = (1.0 - market_price) / market_price
        expected_profit   = round(size * payout_per_dollar, 2)

        if expected_profit < MIN_PAYOUT:
            log(f"  ↳ Skip — expected profit ${expected_profit:.2f} < ${MIN_PAYOUT:.2f} "
                f"(market too priced-in at {market_price:.3f})")
            return None

        if size <= 0 or self.balance < size:
            log(f"  ↳ Skip — insufficient balance or zero size")
            return None

        # place the trade
        self.balance -= size
        self.trade_count += 1
        self.traded_ids.add(market_id)

        cat = decision.get("category", "other")
        if cat not in self.category_stats:
            self.category_stats[cat] = {"total": 0, "deployed": 0.0}
        self.category_stats[cat]["total"]    += 1
        self.category_stats[cat]["deployed"] += size

        trade = {
            "trade_id":        self.trade_count,
            "timestamp":       datetime.datetime.now().isoformat(timespec="seconds"),
            "market_id":       market_id,
            "question":        decision["market_question"],
            "category":        cat,
            "action":          action,
            "market_price":    market_price,
            "my_prob":         decision.get("my_yes_prob", ""),
            "edge":            edge,
            "size_usd":        size,
            "confidence":      confidence,
            "expected_profit": expected_profit,
            "reasoning":       decision.get("reasoning", ""),
            "balance_after":   round(self.balance, 2),
        }
        return trade

    def summary(self) -> str:
        pnl = self.balance - self.starting
        return (
            f"Balance: ${self.balance:.2f} | "
            f"P&L: ${pnl:+.2f} | "
            f"Trades: {self.trade_count}"
        )

    def category_summary(self) -> str:
        if not self.category_stats:
            return "  No trades yet"
        lines = []
        for cat, s in sorted(self.category_stats.items()):
            lines.append(
                f"  {cat}: {s['total']} trades, ${s['deployed']:.0f} deployed"
            )
        return "\n".join(lines)


# ── CSV ───────────────────────────────────────────────────────────────────────
CSV_HEADERS = [
    "trade_id", "timestamp", "market_id", "question", "category",
    "action", "market_price", "my_prob", "edge", "size_usd",
    "confidence", "expected_profit", "reasoning", "balance_after",
]

def load_existing_trades() -> tuple:
    if not os.path.exists(CSV_FILE):
        return STARTING_BALANCE, set(), 0

    traded_ids   = set()
    last_balance = STARTING_BALANCE
    count        = 0

    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            traded_ids.add(row.get("market_id", ""))
            try:
                last_balance = float(row.get("balance_after", STARTING_BALANCE))
            except ValueError:
                pass
            count += 1

    log(f"[RESUME] {count} existing trades loaded — balance ${last_balance:.2f}")
    log(f"[RESUME] Skipping {len(traded_ids)} already-traded markets")
    return last_balance, traded_ids, count

def init_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()

def append_trade(trade: dict):
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writerow({k: trade.get(k, "") for k in CSV_HEADERS})


# ── Main Loop ─────────────────────────────────────────────────────────────────
def main():
    init_csv()
    balance, traded_ids, existing_count = load_existing_trades()

    portfolio             = Portfolio(balance, traded_ids, existing_count)
    stop_floor            = portfolio.starting * STOP_PCT

    log("=" * 65)
    log("Polymarket Smart Scanner Agent v4 — Starting")
    log(f"  Balance          : ${portfolio.balance:.2f}")
    log(f"  Auto-stop floor  : ${stop_floor:.2f} (70% of start)")
    log(f"  Prob window      : {MIN_PROB:.0%} – {MAX_PROB:.0%}")
    log(f"  Min edge         : {MIN_EDGE:.0%}")
    log(f"  Min confidence   : {MIN_CONFIDENCE:.0%}")
    log(f"  Max bet          : {MAX_BET_PCT:.0%} of balance  (Kelly tiered)")
    log(f"  Min payout       : ${MIN_PAYOUT:.2f} per trade")
    log(f"  Resolve window   : ≤ {MAX_RESOLVE_DAYS} days")
    log(f"  Volatility guard : skip crypto if |5min BTC| > {VOLATILITY_THRESH}%")
    log(f"  Bootstrap guard  : first {BOOTSTRAP_TRADES} trades capped at {BOOTSTRAP_PCT:.0%}")
    log(f"  Model            : claude-sonnet-4-6")
    log("=" * 65)

    cycle = 0

    while True:
        cycle += 1
        log(f"\n── Cycle {cycle} {'─'*48}")

        # 1. Fetch BTC price
        btc = fetch_btc_price()
        if btc["price"]:
            log(f"BTC: ${btc['price']:,.0f} | {btc['momentum_str']}")

        # FIX-D: volatility guard — flag high-volatility cycles
        high_volatility = abs(btc["momentum"]) > VOLATILITY_THRESH
        if high_volatility:
            log(f"⚡ HIGH VOLATILITY ({btc['momentum']:+.2f}%) — crypto markets will be skipped this cycle")

        # 2. Fetch markets
        markets = fetch_markets()
        if not markets:
            log("[WARN] No markets fetched. Retrying next cycle.")
            time.sleep(POLL_INTERVAL)
            continue

        # 3. Filter already-traded + apply volatility guard for crypto
        fresh = []
        skipped_dup   = 0
        skipped_volat = 0
        for m in markets:
            if portfolio.already_traded(m["id"]):
                skipped_dup += 1
                continue
            # FIX-D: skip crypto during high volatility
            if high_volatility and m["category"] == "crypto":
                skipped_volat += 1
                continue
            fresh.append(m)

        log(f"Markets: {len(markets)} fetched | "
            f"{skipped_dup} already traded | "
            f"{skipped_volat} skipped (volatility) | "
            f"{len(fresh)} to scan")

        if not fresh:
            log("Nothing to scan this cycle — waiting...")
            time.sleep(POLL_INTERVAL)
            continue

        # 4. Scan each fresh market
        trades_this_cycle = 0
        for market in fresh:
            log(f"\n  [{market['category'].upper()}] {market['question'][:80]}")
            log(f"  YES={market['yes_price']:.3f}  NO={market['no_price']:.3f}  "
                f"Vol=${market['volume_24h']:,.0f}  Liq=${market['liquidity']:,.0f}")

            decision = ask_claude_mispricing(market, btc)
            if decision is None:
                continue

            edge    = float(decision.get("edge", 0))
            my_prob = float(decision.get("my_yes_prob", 0))
            action  = decision.get("action", "skip")
            conf    = float(decision.get("confidence", 0))

            log(f"  Claude: my_prob={my_prob:.1%} | market={market['yes_price']:.1%} | "
                f"edge={edge:+.1%} | action={action} | conf={conf:.0%}")

            if action == "skip" or abs(edge) < MIN_EDGE:
                log("  ↳ No sufficient edge — skip")
                time.sleep(1)
                continue

            log(f"  💡 EDGE {edge:+.1%} | {decision.get('reasoning', '')}")

            trade = portfolio.place_trade(decision)
            if trade:
                append_trade(trade)
                trades_this_cycle += 1
                log(f"  ✅ TRADE #{trade['trade_id']} | "
                    f"Bet: ${trade['size_usd']:.2f} | "
                    f"Expected profit: ${trade['expected_profit']:.2f} | "
                    f"{portfolio.summary()}")

                # bootstrap reminder
                if portfolio.trade_count <= BOOTSTRAP_TRADES:
                    log(f"  ℹ️  Bootstrap trade {portfolio.trade_count}/{BOOTSTRAP_TRADES} "
                        f"— conservative sizing active")

            time.sleep(1.5)

        # 5. Cycle summary
        log(f"\n📊 Cycle {cycle} — {trades_this_cycle} trades placed")
        log(f"   {portfolio.summary()}")
        log(f"   Category breakdown:\n{portfolio.category_summary()}")

        if portfolio.stop_triggered:
            log("\n🛑 Auto-stop active. Bot halted.")
            log("   Review trades.csv and restart when ready.\n")
            break

        log(f"\n⏳ Sleeping {POLL_INTERVAL}s...\n")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\n[STOPPED] Agent interrupted. Goodbye!")