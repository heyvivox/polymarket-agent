from typing import Optional
"""
BTC 5-Minute Auto-Trading Bot v2.1 — Real Polymarket Logic
Multi-user CLI edition: credentials stored encrypted per-user at ~/.polymarket_bot/
------------------------------------------------------------
WHY v2.0 DIDN'T WORK IN REAL LIFE:
  Dry run used estimated token prices ($0.56–$0.93).
  Real Polymarket BTC 5-min prices are always $0.44–$0.56.
  The entire token price filter was useless on real markets.

THE REAL EDGE (v2.1):
  Forget token price as a filter. Look at what BTC actually does.
  At T-10s, the window has been running for 4m50s.
  A large window delta (+0.05%+) almost never reverses in 10 seconds.
  Polymarket pricing is stale — the crowd doesn't have live Binance data.
  Your bot does. That gap is the edge.

TWO FILTERS ONLY:
  1. Window Delta |Δ%| >= 0.05% — BTC moved enough to be directional
  2. Score |score| >= 7          — 4-5 of 7 indicators agree on direction
  Both must be true. One alone is not enough.

BET SIZING:
  Always 25% of current balance when both filters pass.
  No zone classification. All real Polymarket tokens pay ~1:1.
  Compounding preserved — bet grows as balance grows.

WHY 0.05% DELTA THRESHOLD:
  From your own trade history:
  All losses  → window delta < 0.02% (flat market, noise)
  All big wins → window delta > 0.05% (real momentum)
  This threshold comes from your data, not theory.

RISK:
  Trades less frequently. Sideways BTC = 2-3hrs no trade. Normal.
  Strong trending day = large bets at peak balance. 25% cap is sacred.
  Paper trade minimum 2 weeks before real money.

Usage:
  python3 btc_agent.py           # DRY RUN (safe)
  python3 btc_agent.py --real    # REAL MONEY
  python3 btc_agent.py --force   # bypass session window
  python3 btc_agent.py --once    # single cycle
"""

import os, csv, sys, time, datetime, argparse, requests, json
from pathlib import Path

# Allow imports from src/
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv()

try:
    from polymarket_executor import PolymarketExecutor
    _EXECUTOR_AVAILABLE = True
except ImportError:
    _EXECUTOR_AVAILABLE = False

from src.terminal_ui import (
    print_startup_banner, print_status_dashboard,
    print_trade_log_header, print_trade_row, print_session_footer,
)

BOT_VERSION = "2.1"

# ── Credentials — overridden from UserConfig after wizard/login ───────────────
PRIVATE_KEY     = os.getenv("POLYMARKET_PRIVATE_KEY")     or os.getenv("PRIVATE_KEY", "")
POLY_API_KEY    = os.getenv("POLYMARKET_API_KEY")         or os.getenv("POLY_API_KEY", "")
POLY_API_SECRET = os.getenv("POLYMARKET_API_SECRET")      or os.getenv("POLY_API_SECRET", "")
POLY_API_PASS   = os.getenv("POLYMARKET_API_PASSPHRASE")  or os.getenv("POLY_API_PASSPHRASE", "")

# ── Config ────────────────────────────────────────────────────────────────────
STARTING_BANKROLL = 20.00    # $20 real test
TARGET_BANKROLL   = 100    # target double
SESSION_STOP_LOSS = 10.00    # stop if lose $10
MIN_BET           = 1.00
BET_PCT           = 0.20     # fallback for ghost trades
POLYMARKET_FEE    = 0.02     # 2% fee on gross winnings
SLIPPAGE_EST      = 0.005    # 0.5% slippage added to fill price
# ── Zone-based bet sizing ──────────────────────────────────────────────────────
BET_ZONE_HIGH_PCT  = 0.25    # HIGH zone bet fraction
BET_ZONE_MED_PCT   = 0.15    # MEDIUM zone bet fraction
SESSION_START_UTC = 14
SESSION_END_UTC   = 18

# ── THE TWO REAL FILTERS ──────────────────────────────────────────────────────
DELTA_THRESHOLD = 0.05   # from trade history: wins cluster above 0.05%, losses below 0.02%
SCORE_MIN       = 5.0    # |score| >= 5 — strong signal agreement
CONF_MIN        = 0.50
CONSEC_LOSS_CD  = 2      # cooldown after 2 consecutive losses
MIN_EV          = 0.05   # minimum expected value per dollar to enter a trade
KELLY_FRACTION  = 0.5    # use half Kelly — robust to model error
MAX_BET_PCT     = 0.20   # hard cap — never bet more than 20% of balance
SCALP_DELTA_MIN  = 0.15  # window must have moved ≥ 0.15% — near-certain direction
SCALP_ENTRY_TIME = 30    # only enter scalp between T-30s and T-10s
SCALP_BET_PCT    = 0.05  # small bet — 5% of balance (thin margin, high certainty)
SCALP_MIN_PRICE  = 0.88  # only scalp if market already pricing ≥ 0.88 (near-certain)

# ── Dynamic entry timing ──────────────────────────────────────────────────────
PRICE_CEILING  = 0.75   # max CLOB ask accepted — skips near-resolved markets
SCAN_INTERVAL  = 15     # default — overridden dynamically below
ENTRY_CUTOFF   = 15     # stop at T-15s — oracle lag is 3-7s, T-15s still safe

# ── APIs ──────────────────────────────────────────────────────────────────────
CLOB_HOST   = "https://clob.polymarket.com"
FUNDER_ADDR = (os.getenv("POLYMARKET_FUNDER_ADDRESS") or
               os.getenv("POLY_FUNDER_ADDR", "0xec8de7FBab84518AeE23fc131aab93324a588CA3"))
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"
GAMMA_HOST  = "https://gamma-api.polymarket.com"
BINANCE_API = "https://api.binance.com/api/v3"
GAMMA_API   = GAMMA_HOST      # alias used by new helpers
CLOB_API    = CLOB_HOST       # alias used by new helpers
CSV_FILE        = "btc_trades.csv"
SHADOW_CSV_FILE = "btc_shadow.csv"
LOG_FILE        = "btc_agent.log"
BALANCE_FILE    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "balance.json")

UTC = datetime.timezone.utc

def load_persisted_balance():
    """Return balance from balance.json, or None if file missing/corrupt."""
    try:
        with open(BALANCE_FILE) as f:
            return round(float(json.load(f)["balance"]), 2)
    except Exception:
        return None

def save_persisted_balance(balance: float):
    """Write current tracked balance to balance.json."""
    try:
        with open(BALANCE_FILE, "w") as f:
            json.dump({"balance": round(balance, 4)}, f)
    except Exception:
        pass

def _estimate_price_formula(window_pct: float) -> float:
    """Last-resort token price estimate when no real market data is available."""
    return round(min(0.75, 0.50 + abs(window_pct) * 3.0), 3)

def find_btc_5min_market(w_ts: int):
    """Search Gamma API for the BTC 5-min market matching this window. Returns dict or None."""
    try:
        r = requests.get(f"{GAMMA_API}/markets", params={
            "active": "true", "closed": "false",
            "limit": 100, "order": "endDate", "ascending": "true",
        }, timeout=8)
        if r.status_code != 200:
            return None
        keywords_5m = ("5 min", "5min", "5-min", "5 minute", "next 5", "5m ", "5m?", "five min")
        for m in r.json():
            q = (m.get("question") or "").lower()
            if not (("btc" in q or "bitcoin" in q) and any(k in q for k in keywords_5m)):
                continue
            try:
                end_ts = int(m.get("endDateIso") and
                             datetime.datetime.fromisoformat(
                                 m["endDateIso"].replace("Z", "+00:00")).timestamp()
                             or m.get("endDate", 0))
            except Exception:
                end_ts = int(m.get("endDate", 0))
            if abs(end_ts - (w_ts + 300)) > 90:
                continue
            # Parse clobTokenIds and outcomePrices
            tokens = m.get("clobTokenIds") or []
            if isinstance(tokens, str):
                try: tokens = json.loads(tokens)
                except Exception: tokens = []
            prices = m.get("outcomePrices") or []
            if isinstance(prices, str):
                try: prices = json.loads(prices)
                except Exception: prices = []
            return {
                "market_id":       m.get("id", ""),
                "question":        m.get("question", ""),
                "end_date":        end_ts,
                "liquidity":       float(m.get("liquidity") or 0),
                "volume_24h":      float(m.get("volume24hr") or 0),
                "token_id_yes":    tokens[0] if len(tokens) > 0 else None,
                "token_id_no":     tokens[1] if len(tokens) > 1 else None,
                "gamma_yes_price": float(prices[0]) if len(prices) > 0 else None,
                "gamma_no_price":  float(prices[1]) if len(prices) > 1 else None,
            }
    except Exception as e:
        log(f"[WARN] find_btc_5min_market: {e}")
    return None

def fetch_clob_ask(token_id: str):
    """Return the BUY-side ask price for a token from the CLOB API, or None."""
    try:
        r = requests.get(f"{CLOB_API}/price",
                         params={"token_id": token_id, "side": "BUY"}, timeout=5)
        if r.status_code == 200:
            return float(r.json()["price"])
    except Exception:
        pass
    return None

def get_real_token_prices(market: dict, direction: str, window_pct: float) -> dict:
    """Return token prices with SLIPPAGE_EST applied. Priority: CLOB > Gamma > formula."""
    slippage = SLIPPAGE_EST
    tid_yes  = market.get("token_id_yes")
    tid_no   = market.get("token_id_no")

    # Priority 1 — CLOB live ask
    if tid_yes and tid_no:
        clob_yes = fetch_clob_ask(tid_yes)
        clob_no  = fetch_clob_ask(tid_no)
        if clob_yes is not None and clob_no is not None:
            yes_ask = round(clob_yes + slippage, 4)
            no_ask  = round(clob_no  + slippage, 4)
            log(f"  💹 CLOB prices — YES: ${clob_yes:.3f}+slip=${yes_ask:.3f} | "
                f"NO: ${clob_no:.3f}+slip=${no_ask:.3f}")
            token_price = yes_ask if direction == "up" else no_ask
            return {"token_price": token_price, "price_source": "clob",
                    "yes_ask": yes_ask, "no_ask": no_ask}

    # Priority 2 — Gamma probability
    g_yes = market.get("gamma_yes_price")
    g_no  = market.get("gamma_no_price")
    if g_yes is not None and g_no is not None:
        yes_ask = round(g_yes + slippage, 4)
        no_ask  = round(g_no  + slippage, 4)
        log(f"  💹 Gamma prices — YES: ${g_yes:.3f}+slip=${yes_ask:.3f} | "
            f"NO: ${g_no:.3f}+slip=${no_ask:.3f}")
        token_price = yes_ask if direction == "up" else no_ask
        return {"token_price": token_price, "price_source": "gamma",
                "yes_ask": yes_ask, "no_ask": no_ask}

    # Priority 3 — formula fallback
    est = _estimate_price_formula(window_pct)
    yes_ask = no_ask = round(est + slippage, 4)
    log(f"  [WARN] No real prices — using formula estimate ${est:.3f}+slip=${yes_ask:.3f}")
    token_price = yes_ask
    return {"token_price": token_price, "price_source": "estimated",
            "yes_ask": yes_ask, "no_ask": no_ask}

def check_polymarket_resolution(market_id: str):
    """Return 'up', 'down', or None based on Polymarket settlement."""
    try:
        r = requests.get(f"{GAMMA_API}/markets/{market_id}", timeout=8)
        if r.status_code != 200:
            return None
        m = r.json()
        if not m.get("closed"):
            return None
        prices = m.get("outcomePrices") or []
        if isinstance(prices, str):
            try: prices = json.loads(prices)
            except Exception: return None
        if prices and float(prices[0]) >= 0.99:
            return "up"
        if prices and float(prices[0]) <= 0.01:
            return "down"
    except Exception:
        pass
    return None

def utcnow():
    return datetime.datetime.now(UTC)

def from_ts(ts):
    return datetime.datetime.fromtimestamp(ts, UTC)

def log(msg: str):
    ts   = utcnow().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def parse_args():
    p = argparse.ArgumentParser(description="BTC Agent v2.1")
    p.add_argument("--paper",      action="store_true", help="Paper trading mode (default)")
    p.add_argument("--real",       action="store_true", help="Live trading — requires CONFIRM prompt")
    p.add_argument("--setup",      action="store_true", help="Re-run the setup wizard")
    p.add_argument("--reset",      action="store_true", help="Delete local encrypted config")
    p.add_argument("--status",     action="store_true", help="Print stats and exit")
    p.add_argument("--force",      action="store_true", help="Bypass session window check")
    p.add_argument("--once",       action="store_true", help="Run a single cycle then exit")
    p.add_argument("--max-trades", type=int, default=0)
    return p.parse_args()


def _apply_config(cfg) -> None:
    """Override module-level credential globals with values from UserConfig."""
    global PRIVATE_KEY, POLY_API_KEY, POLY_API_SECRET, POLY_API_PASS, FUNDER_ADDR
    if cfg.polymarket_private_key:
        PRIVATE_KEY = cfg.polymarket_private_key
    if cfg.polymarket_api_key:
        POLY_API_KEY = cfg.polymarket_api_key
    if cfg.polymarket_api_secret:
        POLY_API_SECRET = cfg.polymarket_api_secret
    if cfg.polymarket_api_passphrase:
        POLY_API_PASS = cfg.polymarket_api_passphrase
    if cfg.polymarket_funder_address:
        FUNDER_ADDR = cfg.polymarket_funder_address
    if cfg.anthropic_api_key:
        os.environ["ANTHROPIC_API_KEY"] = cfg.anthropic_api_key


def _print_status_and_exit(cfg) -> None:
    """Print balance, win rate, and last 5 trades from CSV, then exit."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    mode_str = "[green]PAPER[/green]"
    balance  = cfg.paper_balance

    console.print(f"\n[bold]Mode:[/bold] {mode_str}  "
                  f"[bold]Paper balance:[/bold] ${balance:.2f}  "
                  f"[bold]Real balance:[/bold] ${cfg.real_balance:.2f}\n")

    if not os.path.exists(CSV_FILE):
        console.print("[yellow]No trade history found.[/yellow]")
        sys.exit(0)

    import csv as _csv
    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        rows = list(_csv.DictReader(f))

    if not rows:
        console.print("[yellow]No trades recorded yet.[/yellow]")
        sys.exit(0)

    wins   = sum(1 for r in rows if r.get("result") == r.get("direction_bet"))
    total  = len(rows)
    wr     = wins / total if total else 0

    console.print(f"[bold]Total trades:[/bold] {total}  [bold]Win rate:[/bold] {wr:.1%}\n")

    table = Table(title="Last 5 Trades", border_style="dim")
    for col in ("timestamp", "direction_bet", "result", "pnl_net", "balance_after"):
        table.add_column(col, style="cyan" if col == "pnl_net" else "")

    for row in rows[-5:]:
        pnl = row.get("pnl_net", "")
        try:
            pnl_f  = float(pnl)
            pnl_s  = f"[green]+${pnl_f:.4f}[/green]" if pnl_f >= 0 else f"[red]${pnl_f:.4f}[/red]"
        except ValueError:
            pnl_s = pnl
        table.add_row(
            row.get("timestamp", ""),
            row.get("direction_bet", "").upper(),
            row.get("result", "").upper(),
            pnl_s,
            f"${float(row.get('balance_after', 0)):.2f}",
        )

    console.print(table)
    sys.exit(0)

def in_session_window():
    return SESSION_START_UTC <= utcnow().hour < SESSION_END_UTC

# ── Window ────────────────────────────────────────────────────────────────────
def get_window():
    now      = time.time()
    w_ts     = int(now) - (int(now) % 300)
    close    = w_ts + 300
    return {
        "window_ts":  w_ts,
        "close_time": close,
        "secs_left":  close - now,
        "open_dt":    from_ts(w_ts),
        "close_dt":   from_ts(close),
        "slug":       f"btc-updown-5m-{w_ts}",
    }

# ── Polymarket ────────────────────────────────────────────────────────────────
class PolymarketClient:
    def __init__(self):
        self.headers = {
            "POLY-API-KEY":        POLY_API_KEY,
            "POLY-API-SECRET":     POLY_API_SECRET,
            "POLY-API-PASSPHRASE": POLY_API_PASS,
            "Content-Type":        "application/json",
        }
        self._clob = None  # initialized once on first use

    def _get_clob(self):
        if self._clob is None:
            self._clob = self._make_clob_client()
            log("🔌 CLOB client initialized")
        return self._clob

    def get_market(self, slug):
        try:
            r = requests.get(f"{GAMMA_HOST}/markets",
                             params={"slug": slug}, timeout=8)
            if r.status_code == 200:
                d = r.json()
                return d[0] if d else None
        except Exception as e:
            log(f"[ERROR] Market: {e}")
        return None

    def get_real_prices(self, slug):
        """Get real UP/DOWN token prices from Polymarket."""
        try:
            market = self.get_market(slug)
            if not market: return None
            outcomes   = json.loads(market.get("outcomes", "[]"))
            prices_raw = json.loads(market.get("outcomePrices", "[]"))
            prices     = [float(p) for p in prices_raw]
            result     = {}
            for i, o in enumerate(outcomes):
                k = o.lower()
                if k in ("up", "higher"):   result["up"]   = prices[i]
                elif k in ("down", "lower"): result["down"] = prices[i]
            return result if "up" in result and "down" in result else None
        except Exception as e:
            log(f"[ERROR] Prices: {e}")
            return None

    def get_token_ids(self, slug):
        try:
            market = self.get_market(slug)
            if not market: return None
            raw = market.get("clobTokenIds")
            if not raw: return None
            ids      = json.loads(raw) if isinstance(raw, str) else raw
            outcomes = json.loads(market.get("outcomes", "[]"))
            result   = {}
            for i, o in enumerate(outcomes):
                k = o.lower()
                if k in ("up", "higher"):    result["up"]   = ids[i]
                elif k in ("down", "lower"): result["down"] = ids[i]
            # Fallback: if outcome names don't match known keywords, assume ids[0]=up
            if not result and len(ids) >= 2:
                result = {"up": ids[0], "down": ids[1]}
            return result if "up" in result and "down" in result else None
        except Exception as e:
            log(f"[ERROR] Token IDs: {e}")
        return None

    def _make_clob_client(self):
        from py_clob_client_v2.client import ClobClient
        from py_clob_client_v2.clob_types import ApiCreds
        creds = ApiCreds(api_key=POLY_API_KEY,
                         api_secret=POLY_API_SECRET,
                         api_passphrase=POLY_API_PASS)
        return ClobClient(host=CLOB_HOST, key=PRIVATE_KEY,
                          chain_id=137, creds=creds,
                          signature_type=0)

    def ensure_allowance(self):
        """Check USDC allowance for CTF Exchange; set it if zero. Call at real-mode startup."""
        try:
            from py_clob_client_v2.clob_types import BalanceAllowanceParams, AssetType
            client = self._get_clob()
            result = client.get_balance_allowance(
                params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
            allowance = int(result.get("allowance", 0))
            balance   = int(result.get("balance",   0))
            log(f"💳 Wallet — balance: ${balance/1e6:.2f} USDC | "
                f"allowance: ${allowance/1e6:.2f} USDC")
            if allowance < balance:
                log("⚙️  Allowance < balance — setting max allowance now...")
                client.update_balance_allowance(
                    params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
                log("✅ Allowance set — orders can now be placed")
            else:
                log("✅ Allowance OK")
        except Exception as e:
            log(f"[WARN] ensure_allowance failed: {e} — continuing anyway")

    def warm_up(self):
        """Pre-initialize CLOB client so place_order fires instantly. Call early in each window."""
        try:
            self._get_clob()
        except Exception as e:
            log(f"[WARN] warm_up failed: {e}")

    def place_order(self, token_id, amount_usdc, price, direction):
        try:
            from py_clob_client_v2.clob_types import OrderArgs, OrderType
            from py_clob_client_v2.order_builder.constants import BUY

            client = self._get_clob()

            # Bid above the ask to become a taker and fill immediately.
            # Without this, we're a maker bid sitting below the ask — nobody fills us
            # in the 5 seconds before close, order gets voided at resolution.
            taker_price = min(round(price + 0.05, 4), 0.97)
            shares = round(amount_usdc / price, 2)  # maker amount: max 2 dp per CLOB spec
            log(f"  💱 Market price: ${price:.4f} | Taker bid: ${taker_price:.4f} | Shares: {shares}")
            args   = OrderArgs(token_id=token_id, price=taker_price,
                               size=shares, side=BUY)
            t0     = time.time()
            signed = client.create_order(args)
            resp   = client.post_order(signed, OrderType.GTC)
            elapsed = time.time() - t0
            status  = resp.get("status", "?")
            taken   = resp.get("takingAmount", "")
            log(f"  📋 Order in {elapsed:.1f}s | status={status} | takingAmount={taken or '(unfilled)'}")
            if status == "live" and not taken:
                log("  ⚠️  Order is maker-only (sitting in book) — may not fill before close")
            return resp
        except Exception as e:
            err = str(e)
            if "allowance" in err or "balance" in err.lower():
                log(f"[ERROR] Place order — allowance/balance issue: {e}")
                log("   → Run set_allowance.py or restart with --real to auto-fix")
            elif "invalid signature" in err.lower():
                log(f"[ERROR] Place order — signature rejected: {e}")
                log("   → Check PRIVATE_KEY and POLY_FUNDER_ADDR in .env")
            else:
                log(f"[ERROR] Place order: {e}")
            return None

    def get_result(self, slug):
        try:
            time.sleep(5)
            market = self.get_market(slug)
            if market and market.get("resolved"):
                return market.get("winner", "").lower() or None
        except Exception as e:
            log(f"[ERROR] Result: {e}")
        return None

    def get_balance(self):
        """
        Fetch USDC balance from Polymarket.
        Uses /balance-allowance with asset_type=COLLATERAL (official endpoint).
        Falls back to Data API /value endpoint.
        """
        # Method 1 — py-clob-client with signature_type=0 (deposit wallet / EOA)
        try:
            from py_clob_client_v2.client import ClobClient as _ClobClient
            from py_clob_client_v2.clob_types import ApiCreds as _ApiCreds, BalanceAllowanceParams as _BAP, AssetType as _AT
            _creds = _ApiCreds(api_key=POLY_API_KEY, api_secret=POLY_API_SECRET, api_passphrase=POLY_API_PASS)
            _client = _ClobClient(host=CLOB_HOST, key=PRIVATE_KEY, chain_id=137,
                                  creds=_creds, signature_type=0)
            bal = _client.get_balance_allowance(params=_BAP(asset_type=_AT.COLLATERAL))
            raw = float(bal.get("balance", 0))
            if raw > 0:
                return round(raw / 1_000_000, 2)  # USDC has 6 decimals
        except Exception as e:
            log(f"[DEBUG] py-clob balance: {e}")

        # Method 2 — Data API portfolio value (public endpoint)
        try:
            # Need wallet address derived from private key
            from eth_account import Account
            acct = Account.from_key(PRIVATE_KEY)
            wallet = acct.address
            r = requests.get(
                f"https://data-api.polymarket.com/value",
                params={"user": wallet},
                timeout=8
            )
            if r.status_code == 200:
                data = r.json()
                # Response: {"cash": "16.26", "bets": "0.00", "equity_total": "16.26"}
                for key in ["cash", "balance", "USDC"]:
                    if key in data:
                        val = float(data[key])
                        if val >= 0:
                            return val
        except Exception as e:
            log(f"[DEBUG] data-api value: {e}")

        return 0.0

# ── Binance ───────────────────────────────────────────────────────────────────
def fetch_candles(limit=30):
    try:
        r = requests.get(f"{BINANCE_API}/klines",
                         params={"symbol":"BTCUSDT","interval":"1m","limit":limit},
                         timeout=8)
        r.raise_for_status()
        return [{"close": float(c[4]), "volume": float(c[5]),
                 "open": float(c[1])} for c in r.json()]
    except Exception as e:
        log(f"[ERROR] Candles: {e}")
        return []

def fetch_price():
    try:
        r = requests.get(f"{BINANCE_API}/ticker/price",
                         params={"symbol":"BTCUSDT"}, timeout=8)
        r.raise_for_status()
        return float(r.json()["price"])
    except Exception as e:
        log(f"[ERROR] Price: {e}")
        return None

def fetch_window_open(w_ts):
    try:
        r = requests.get(f"{BINANCE_API}/klines",
                         params={"symbol":"BTCUSDT","interval":"1m",
                                 "startTime":w_ts*1000,"limit":1},
                         timeout=8)
        r.raise_for_status()
        d = r.json()
        return float(d[0][1]) if d else None
    except Exception as e:
        log(f"[ERROR] Window open: {e}")
        return None

def fetch_live_polymarket_ask(token_id: str, executor_obj) -> Optional[float]:
    """
    Return the real-time best CLOB ask price for a token, or None if unavailable.
    Uses the executor's get_orderbook() so it reads the live Polymarket CLOB —
    not the Gamma display probability. Fast (<1s); safe to call every 15s.
    """
    if not executor_obj or not token_id:
        return None
    try:
        book = executor_obj.get_orderbook(token_id)
        return book.get("best_ask")
    except Exception:
        return None

def fetch_binance_result(w_ts):
    try:
        time.sleep(3)
        r = requests.get(f"{BINANCE_API}/klines",
                         params={"symbol":"BTCUSDT","interval":"5m",
                                 "startTime":w_ts*1000,"limit":1},
                         timeout=8)
        r.raise_for_status()
        d = r.json()
        if d: return "up" if float(d[0][4]) >= float(d[0][1]) else "down"
    except Exception as e:
        log(f"[ERROR] Binance result: {e}")
    return None

# ── TA — 7 indicators ─────────────────────────────────────────────────────────
def ema(values, period):
    if len(values) < period: return []
    k = 2/(period+1)
    r = [sum(values[:period])/period]
    for v in values[period:]:
        r.append(v*k + r[-1]*(1-k))
    return r

def rsi(closes, period=14):
    if len(closes) < period+1: return 50.0
    gains = [max(closes[i]-closes[i-1],0) for i in range(1,len(closes))]
    losses= [max(closes[i-1]-closes[i],0) for i in range(1,len(closes))]
    ag = sum(gains[-period:])/period
    al = sum(losses[-period:])/period
    if al == 0: return 100.0
    return 100-(100/(1+ag/al))

def analyze(candles, cur_price, window_open, ticks):
    if not candles or not cur_price or not window_open:
        return {"score":0,"confidence":0,"direction":"skip","window_pct":0}

    closes  = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]
    score   = 0

    # 1. Window Delta (weight 1–7) — THE DOMINANT SIGNAL
    window_pct = (cur_price - window_open) / window_open * 100
    if   abs(window_pct) > 0.10: w = 7
    elif abs(window_pct) > 0.02: w = 5
    elif abs(window_pct) > 0.005: w = 3
    elif abs(window_pct) > 0.001: w = 1
    else: w = 0
    score += w if window_pct > 0 else -w

    # 2. Micro Momentum (weight 2)
    if len(closes) >= 2:
        score += 2 if closes[-1] > closes[-2] else -2

    # 3. Acceleration (weight 1.5)
    if len(closes) >= 3:
        m1 = closes[-1]-closes[-2]
        m2 = closes[-2]-closes[-3]
        score += 1.5 if (m1-m2) > 0 else -1.5

    # 4. EMA 9/21 (weight 1)
    if len(closes) >= 21:
        e9  = ema(closes, 9)
        e21 = ema(closes, 21)
        if e9 and e21:
            score += 1 if e9[-1] > e21[-1] else -1

    # 5. RSI (weight 2)
    rv = rsi(closes)
    if   rv > 75: score += 2
    elif rv < 25: score -= 2

    # 6. Volume Surge (weight 1)
    if len(volumes) >= 6:
        recent = sum(volumes[-3:])/3
        prior  = sum(volumes[-6:-3])/3
        if prior > 0 and recent >= prior*1.5:
            score += 1 if closes[-1] > closes[-2] else -1

    # 7. Tick Trend (weight 2)
    if len(ticks) >= 5:
        up_t = sum(1 for i in range(1,len(ticks)) if ticks[i] > ticks[i-1])
        dn_t = sum(1 for i in range(1,len(ticks)) if ticks[i] < ticks[i-1])
        tot  = up_t+dn_t
        t_mv = (ticks[-1]-ticks[0])/ticks[0]*100
        if tot > 0 and abs(t_mv) > 0.005 and max(up_t,dn_t)/tot >= 0.60:
            score += 2 if up_t > dn_t else -2

    raw_conf = min(abs(score) / 7.0, 1.0)
    conf     = round(0.50 + raw_conf * 0.30, 4)   # maps 0→0.50, 1→0.80 — no TA signal is certainty
    direction = "up" if score > 0 else ("down" if score < 0 else "skip")
    return {"score":score,"confidence":conf,"direction":direction,"window_pct":window_pct}

def compute_ev(q: float, p: float) -> float:
    """
    Expected value per dollar risked.
    q = our probability estimate (from TA confidence)
    p = market price (real CLOB ask)
    EV = q(1 - p) - (1 - q)p
    Positive EV = edge in our favor.
    """
    return round(q * (1 - p) - (1 - q) * p, 4)

def kelly_bet(balance: float, q: float, p: float) -> tuple:
    """
    Half-Kelly position sizing.
    f* = (q - p) / (1 - p)
    Scaled by KELLY_FRACTION, capped at MAX_BET_PCT.
    Returns (bet_amount, kelly_pct, raw_kelly_pct).
    """
    if p >= 1.0 or p <= 0.0:
        return 0.0, 0.0, 0.0
    raw_f    = (q - p) / (1 - p)
    if raw_f <= 0:
        return 0.0, 0.0, raw_f
    scaled_f = min(raw_f * KELLY_FRACTION, MAX_BET_PCT)
    bet      = round(balance * scaled_f, 2)
    bet      = max(bet, MIN_BET)
    return bet, scaled_f, raw_f

# ── Session ───────────────────────────────────────────────────────────────────
class Session:
    def __init__(self, starting, real_mode=False, target=None, stop_loss=None):
        self.balance         = starting
        self.starting        = starting
        self.session_pnl     = 0.0
        self.wins            = 0
        self.losses          = 0
        self.peak            = starting
        self.consec_losses   = 0
        self.cooldown_active = False
        self.real_mode       = real_mode
        self.target          = target    or TARGET_BANKROLL
        self.stop_loss       = stop_loss or SESSION_STOP_LOSS
        self.total_fees      = 0.0

    def stopped(self):
        stop = getattr(self, 'stop_loss', SESSION_STOP_LOSS)
        if self.session_pnl <= -stop:
            log(f"🛑 SESSION STOP — P&L ${self.session_pnl:.2f} ≤ −${stop:.2f}")
            return True
        if self.peak > self.starting and self.balance < self.peak * 0.85:
            log(f"🛑 TRAILING STOP — balance ${self.balance:.2f} < 85% of peak ${self.peak:.2f} (${self.peak * 0.85:.2f})")
            return True
        return False

    def target_hit(self):
        target = getattr(self, 'target', TARGET_BANKROLL)
        return self.balance >= target

    def record_win(self, bet, token_price):
        gross_profit  = round(bet / token_price - bet, 4)
        fee           = round(gross_profit * POLYMARKET_FEE, 4)
        net_profit    = round(gross_profit - fee, 4)
        self.balance     += net_profit
        self.session_pnl += net_profit
        self.total_fees  += fee
        self.wins        += 1
        self.peak         = max(self.peak, self.balance)
        self.consec_losses = 0
        self.cooldown_active = False
        return (net_profit, gross_profit, fee)

    def record_loss(self, loss):
        self.balance     -= loss
        self.session_pnl -= loss
        self.losses      += 1
        self.consec_losses += 1
        if self.consec_losses >= CONSEC_LOSS_CD:
            self.cooldown_active = True
            log(f"⚠️  {CONSEC_LOSS_CD} consecutive losses — cooldown active")
        return -loss

    def win_rate(self):
        t = self.wins+self.losses
        return self.wins/t if t > 0 else 0

    def summary(self):
        mode = "🔴 REAL" if self.real_mode else "📋 DRY RUN"
        return (f"[{mode}] Balance: ${self.balance:.2f} | "
                f"P&L: ${self.session_pnl:+.2f} | "
                f"W/L: {self.wins}/{self.losses} | "
                f"Win rate: {self.win_rate():.0%} | "
                f"Fees: ${self.total_fees:.3f}")

    def progress(self):
        return max((self.balance-self.starting)/(self.target-self.starting)*100, 0)

# ── CSV ───────────────────────────────────────────────────────────────────────
CSV_HEADERS = [
    "trade_id","timestamp","window_ts","direction_bet",
    "window_pct","score","confidence","ev","token_price","zone",
    "kelly_pct","raw_kelly","bet_usd","bet_pct","result","result_source",
    "pnl_net","balance_after","session_pnl","win_rate_so_far","real_mode",
    "mode",            # "live"=FOK fill via executor | "real_gtc"=GTC | "paper"=simulated
    "avg_fill_price",  # actual CLOB fill price (live only)
    "usdc_spent",      # actual USDC out of wallet (live only)
    "real_balance_after",  # on-chain wallet balance after settlement (live only)
    # New Polymarket price tracking columns
    "real_token_price","estimated_token_price","price_source",
    "yes_ask","no_ask","polymarket_liquidity",
    "pnl_gross","fee_deducted","resolution_source","polymarket_market_id",
]

SHADOW_HEADERS = [
    "window_id","timestamp","window_ts","skip_reason",
    "direction","window_pct","score","confidence","token_price",
    "ghost_bet","ghost_pnl","ghost_result","would_have","delta_ok","score_ok",
]

def init_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE,"w",newline="",encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_HEADERS).writeheader()

def append_trade(trade):
    with open(CSV_FILE,"a",newline="",encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=CSV_HEADERS).writerow(
            {k: trade.get(k,"") for k in CSV_HEADERS})

def init_shadow_csv():
    if not os.path.exists(SHADOW_CSV_FILE):
        with open(SHADOW_CSV_FILE,"w",newline="",encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=SHADOW_HEADERS).writeheader()

def append_shadow(shadow):
    with open(SHADOW_CSV_FILE,"a",newline="",encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=SHADOW_HEADERS).writerow(
            {k: shadow.get(k,"") for k in SHADOW_HEADERS})

# ── Main ──────────────────────────────────────────────────────────────────────
def fetch_shadow_result(w_ts, direction, bet, token_price, skip_reason, score, window_pct, confidence, shadow_count):
    """Fetch what would have happened on a skipped window."""
    actual = fetch_binance_result(w_ts)
    if actual is None:
        return None

    won          = (direction == actual)
    ghost_pnl    = round(bet/token_price - bet, 2) if won else -bet
    would_have   = "WIN" if won else "LOSS"
    delta_ok     = abs(window_pct) >= DELTA_THRESHOLD
    score_ok     = abs(score) >= SCORE_MIN

    log(f"  👻 GHOST [{would_have}] — {direction.upper()} | Actual: {actual.upper()} | "
        f"Ghost P&L: ${ghost_pnl:+.2f} | Reason skipped: {skip_reason}")

    return {
        "window_id":    shadow_count,
        "timestamp":    utcnow().isoformat(timespec="seconds"),
        "window_ts":    w_ts,
        "skip_reason":  skip_reason,
        "direction":    direction,
        "window_pct":   round(window_pct, 5),
        "score":        score,
        "confidence":   round(confidence, 3),
        "token_price":  round(token_price, 3),
        "ghost_bet":    round(bet, 2),
        "ghost_pnl":    round(ghost_pnl, 4),
        "ghost_result": actual,
        "would_have":   would_have,
        "delta_ok":     delta_ok,
        "score_ok":     score_ok,
    }

def main():
    args      = parse_args()
    real_mode = args.real

    # ── Setup wizard / login ──────────────────────────────────────────────────
    from src.setup_wizard import handle_reset, run_wizard
    from src.config_manager import CONFIG_BASE, UserConfig

    if args.reset:
        handle_reset()
        return

    existing_users = (
        [d.name for d in CONFIG_BASE.iterdir() if d.is_dir()]
        if CONFIG_BASE.exists() else []
    )
    needs_wizard = (not existing_users) or args.setup

    cfg = run_wizard(force=args.setup, version=BOT_VERSION) if needs_wizard else run_wizard(force=False, version=BOT_VERSION)
    if cfg is None:
        log("[ERROR] Login failed — exiting.")
        return

    _apply_config(cfg)

    if args.status:
        _print_status_and_exit(cfg)

    from rich.console import Console as _Console
    _con = _Console()

    # ── REAL mode CONFIRM gate ────────────────────────────────────────────────
    if real_mode:
        balance_display = cfg.real_balance or STARTING_BANKROLL
        _con.print(
            f"\n[bold red]⚠  REAL MONEY MODE — Your balance: ${balance_display:.2f}[/bold red]\n"
            f"[red]Real USDC will be spent. Type CONFIRM to proceed.[/red]"
        )
        answer = input("  → ").strip()
        if answer != "CONFIRM":
            _con.print("[yellow]Aborted.[/yellow]")
            return


    init_csv()
    init_shadow_csv()

    poly     = PolymarketClient()
    executor = None   # PolymarketExecutor — set below if LIVE_TRADING=true

    # ── Balance: prefer balance.json over API (API misses unredeemed tokens) ─
    if real_mode:
        persisted = load_persisted_balance()
        if persisted and persisted > 0:
            starting = persisted
            log(f"💰 Balance loaded from balance.json: ${starting:.2f} USDC")
        else:
            log("💰 Auto-detecting Polymarket balance...")
            detected = poly.get_balance()
            if detected and detected > 0:
                starting = round(detected, 2)
                log(f"💰 Balance detected: ${starting:.2f} USDC")
            else:
                starting = STARTING_BANKROLL
                log(f"[WARN] Could not detect balance — using ${STARTING_BANKROLL:.2f}")
        poly.ensure_allowance()
    else:
        starting = cfg.paper_balance if cfg.paper_balance > 0 else STARTING_BANKROLL

    # ── Live trading executor ─────────────────────────────────────────────
    if real_mode and LIVE_TRADING:
        if not _EXECUTOR_AVAILABLE:
            log("[ERROR] polymarket_executor.py not found — cannot enable live trading")
            return
        try:
            executor = PolymarketExecutor()
            live_bal = executor.get_balance()
            if live_bal < 5.0:
                log(f"[ABORT] Wallet balance ${live_bal:.2f} < $5.00 minimum — aborting")
                return
            executor.ensure_allowance()
            persisted = load_persisted_balance()
            if persisted and persisted >= live_bal:
                starting = persisted
                log(f"💳 Live balance from balance.json: ${starting:.2f} (API: ${live_bal:.2f})")
            else:
                starting = live_bal
                log(f"💳 Live balance synced on startup: ${live_bal:.2f}")
            # ── WARNING BANNER ────────────────────────────────────────────
            log("!" * 65)
            log("!   ⚠️  LIVE TRADING ACTIVE — REAL USDC WILL BE SPENT   !")
            log(f"!   Wallet  : {FUNDER_ADDR}")
            log(f"!   Balance : ${live_bal:.2f} USDC")
            log("!   Ctrl+C NOW to abort")
            log("!" * 65)
            for i in range(5, 0, -1):
                log(f"  ⏳ Starting live trading in {i}s...")
                time.sleep(1)
        except Exception as e:
            log(f"[ERROR] Executor init failed: {e} — aborting")
            return
    elif real_mode:
        log("[INFO] LIVE_TRADING=false — using paper mode with real balance tracking")
        log("       Set LIVE_TRADING=true in .env to enable real orders via FOK executor")

    # Scale target and stop loss
    # (also runs for dry run so progress bar works correctly)
    # Auto-scale target and stop loss from real balance
    real_target    = round(starting * 2.0,  2)   # target  = 2× balance
    real_stop_loss = round(starting * 0.40, 2)   # stop    = −40% of balance

    session = Session(starting, real_mode, target=real_target, stop_loss=real_stop_loss)
    print_status_dashboard(
        "REAL" if real_mode else "PAPER",
        cfg.username,
        session.balance,
        0.0, 0.0, 0,
    )

    if not in_session_window() and not args.force:
        log(f"⏰ Outside session window ({SESSION_START_UTC}:00–{SESSION_END_UTC}:00 UTC)")
        log(f"   Use --force to bypass")
        return

    mode_str = "🔴 REAL MONEY" if real_mode else "📋 DRY RUN — No real trades"
    log("="*65)
    log(f"BTC Agent v2.1 — {mode_str}")
    log(f"  Balance       : ${session.balance:.2f}  {'← auto-detected from Polymarket' if real_mode else ''}")
    log(f"  Target        : ${real_target:.2f}  (2× balance)")
    log(f"  Session stop  : −${real_stop_loss:.2f}  (−40% of balance)")
    log(f"  Session window: {SESSION_START_UTC}:00–{SESSION_END_UTC}:00 UTC")
    log(f"")
    log(f"  FILTER 1 — Window Delta : |Δ%| ≥ {DELTA_THRESHOLD}%")
    log(f"  FILTER 2 — Score gate   : |score| ≥ {SCORE_MIN:.0f}")
    log(f"  BET SIZING  — HIGH ($0.45–$0.69) {BET_ZONE_HIGH_PCT*100:.0f}% | MEDIUM ($0.70–$0.94) {BET_ZONE_MED_PCT*100:.0f}%")
    log(f"  Entry gate  — T≤90s only")
    log(f"  Scalp mode  — T-{SCALP_ENTRY_TIME}s, Δ ≥ {SCALP_DELTA_MIN}%, price ≥ ${SCALP_MIN_PRICE}")
    log("┌─────────────────────────────────────┐")
    log("│  BTC Agent — Fix Validation         │")
    log("│  Token zone floor : $0.45           │")
    log("│  Entry gate       : T≤90s only      │")
    log("│  Payout math      : tokens × $1.00  │")
    log("│  Balance source   : balance.json    │")
    log("│  Phantom guard    : ON              │")
    log("└─────────────────────────────────────┘")
    log(f"  Cooldown    — {CONSEC_LOSS_CD} consecutive losses → skip 1 window")
    if real_mode:
        log(f"  ⚠️  REAL TRADES WILL BE PLACED AUTOMATICALLY")
    log("="*65)

    traded_windows       = set()
    trade_count          = 0
    shadow_count         = [0]
    open_position_shares = 0.0   # shares held between fill and settlement
    shadow_saved   = [0.0]
    shadow_missed  = [0.0]

    print_trade_log_header()
    while True:
        if not in_session_window() and not args.force:
            log(f"\n⏰ Session ended — {SESSION_END_UTC}:00 UTC"); break
        if session.stopped(): break
        if session.target_hit():
            log(f"🎯 TARGET HIT! ${session.balance:.2f}"); break
        if args.max_trades > 0 and trade_count >= args.max_trades: break

        w = get_window()
        log(f"\n{'─'*55}")
        log(f"Window: {w['open_dt'].strftime('%H:%M')} → {w['close_dt'].strftime('%H:%M')} UTC "
            f"| {w['secs_left']:.0f}s left | {w['slug']}")

        if w["window_ts"] in traded_windows:
            time.sleep(max(w["close_time"]-time.time()+3, 3)); continue

        if session.cooldown_active:
            log(f"  ⏸ COOLDOWN — window skipped")
            session.cooldown_active = False
            traded_windows.add(w["window_ts"])
            time.sleep(max(w["close_time"]-time.time()+3, 3)); continue

        # ── Find matching Polymarket 5-min BTC market ─────────────────────────
        pm_market = find_btc_5min_market(w["window_ts"])
        if pm_market:
            log(f"  📍 PM market: {pm_market['question']} | "
                f"Liq: ${pm_market['liquidity']:,.0f} | Vol24h: ${pm_market['volume_24h']:,.0f}")
        else:
            log("  [WARN] No matching Polymarket 5-min BTC market found")

        # ── Fetch data immediately at window start, then scan continuously ───────
        if real_mode:
            poly.warm_up()   # initialize CLOB client before first scan

        log("📡 Fetching Binance + Polymarket data...")
        candles              = fetch_candles()
        cur_price            = fetch_price()
        window_open          = fetch_window_open(w["window_ts"])
        real_prices          = poly.get_real_prices(w["slug"])
        prefetched_token_ids = poly.get_token_ids(w["slug"]) if real_mode else None

        if not candles or not cur_price or not window_open:
            log("[WARN] Missing data — skipping")
            time.sleep(max(w["close_time"]-time.time()+5, 5)); continue

        log(f"BTC: ${cur_price:,.2f} | Window open: ${window_open:,.2f}")
        if real_prices:
            log(f"  💹 Polymarket — UP: ${real_prices.get('up',0):.3f} | DOWN: ${real_prices.get('down',0):.3f}")
        if prefetched_token_ids:
            log(f"  🪙 Token IDs ready")

        # ── Scanning loop: polls every SCAN_INTERVAL until T-ENTRY_CUTOFF ──────
        # Fires the instant Δ ✓ AND score ✓ AND CLOB ask ≤ PRICE_CEILING.
        log(f"🔍 Scanning window from T-{w['secs_left']:.0f}s...")

        tick_prices      = []
        entry_sig        = None
        entry_ask        = None
        entry_tstr       = ""
        exit_reason      = "cutoff"   # overwritten to "odds_gone" if ceiling breaks the loop
        ask_open             = None       # first live ask seen this window (ask momentum baseline)
        ask_low              = None       # lowest ask seen this window
        ask_momentum_blocked = False      # latched True if ask dips >$0.05 below ask_open
        _logged_block        = False      # log the block message only once per window
        had_valid_signal     = False      # True once delta+score+T≤90 all pass in same tick
        window_scan_start    = time.time()

        while time.time() < w["close_time"] - ENTRY_CUTOFF:
            p = fetch_price()
            if p:
                cur_price = p
                tick_prices.append(p)

            sig        = analyze(candles, cur_price, window_open, tick_prices)
            direction  = sig["direction"]
            score      = sig["score"]
            window_pct = sig["window_pct"]
            time_left  = w["close_time"] - time.time()

            # Fetch live CLOB ask for the current signal direction
            live_ask = None
            if direction != "skip":
                if executor and prefetched_token_ids and direction in prefetched_token_ids:
                    live_ask = fetch_live_polymarket_ask(
                        prefetched_token_ids[direction], executor
                    )
                # Paper-mode / no-executor fallback: use Gamma probability price
                if live_ask is None and real_prices and direction in real_prices:
                    live_ask = real_prices[direction]

            ask_str = f"${live_ask:.3f}" if live_ask is not None else "n/a"
            log(f"  📊 T-{time_left:.0f}s | Δ {window_pct:+.4f}% | "
                f"score {score:+.1f} | ask {ask_str}")

            # Track first ask seen this window as the momentum baseline
            if live_ask is not None and ask_open is None:
                ask_open = live_ask

            # Update ask_low and latch block flag if ask dips >$0.05 below open
            if live_ask is not None:
                if ask_low is None:
                    ask_low = live_ask
                else:
                    ask_low = min(ask_low, live_ask)
                if ask_open is not None and (ask_open - ask_low) > 0.05:
                    ask_momentum_blocked = True

            delta_ok = abs(window_pct) >= DELTA_THRESHOLD
            score_ok = abs(score)      >= SCORE_MIN
            price_ok = live_ask is not None and live_ask <= PRICE_CEILING
            dir_ok   = direction != "skip"

            # ── Secondary: ask-momentum trigger ──────────────────────────────
            ASK_MOMENTUM_RISE   = 0.07
            ASK_MOMENTUM_SCORE  = 7
            ASK_MOMENTUM_CEIL   = 0.80
            ASK_MOMENTUM_MIN_S  = 60

            elapsed_s    = time.time() - window_scan_start
            ask_rise     = (live_ask - ask_open) if (live_ask is not None and ask_open is not None) else 0.0
            momentum_ok  = (
                dir_ok
                and ask_open is not None
                and ask_rise >= ASK_MOMENTUM_RISE
                and abs(score) >= ASK_MOMENTUM_SCORE
                and live_ask <= ASK_MOMENTUM_CEIL
                and elapsed_s >= ASK_MOMENTUM_MIN_S
                and not ask_momentum_blocked
            )

            if momentum_ok and entry_sig is None and time_left <= 90:
                entry_tstr = f"T-{time_left:.0f}s"
                log(f"  ✅ ASK MOMENTUM ENTRY — ask rose ${ask_open:.3f} → ${live_ask:.3f} "
                    f"(+${ask_rise:.2f}) | score {score:+.1f} | "
                    f"delta below threshold but market confirming direction")
                entry_sig = sig
                entry_ask = live_ask
                break

            # Log once if momentum would fire but is blocked by dip
            if (ask_momentum_blocked and not momentum_ok
                    and dir_ok and ask_open is not None
                    and ask_rise >= ASK_MOMENTUM_RISE
                    and abs(score) >= ASK_MOMENTUM_SCORE
                    and live_ask is not None and live_ask <= ASK_MOMENTUM_CEIL
                    and elapsed_s >= ASK_MOMENTUM_MIN_S):
                if not _logged_block:
                    ask_dip = ask_open - ask_low if ask_low is not None else 0.0
                    log(f"  ⛔ ASK MOMENTUM BLOCKED — ask dipped "
                        f"${ask_open:.3f} → ${ask_low:.3f} "
                        f"(-${ask_dip:.2f} from open, max dip $0.05)")
                _logged_block = True

            if delta_ok and score_ok and price_ok and dir_ok and time_left <= 90:
                entry_tstr = f"T-{time_left:.0f}s"
                log(f"  ✅ ENTRY TRIGGERED — {entry_tstr} | "
                    f"ask {ask_str} ≤ ${PRICE_CEILING} ceiling")
                entry_sig = sig
                entry_ask = live_ask
                break

            # Hold-off reason (only log if direction is known to reduce noise)
            if dir_ok:
                if not delta_ok:
                    log(f"  ⏳ Waiting — delta {window_pct:+.4f}% below threshold")
                elif not score_ok:
                    log(f"  ⏳ Waiting — score {score:+.1f} below threshold")
                elif not price_ok:
                    log(f"  ⛔ ODDS GONE — ask {ask_str} > ${PRICE_CEILING}")
                    exit_reason = "odds_gone"
                    break   # market has priced in the move; no point waiting
                elif time_left > 90:
                    log(f"  ⏳ Too early — T-{time_left:.0f}s (entry only after T-90s). Waiting...")
                else:
                    had_valid_signal = True   # delta+score+price+time all passed

            remaining = w["close_time"] - ENTRY_CUTOFF - time.time()
            if remaining <= 0:
                break
            # Dynamic scan interval — slower early, faster near the close
            time_left_now = w["close_time"] - time.time()
            if time_left_now > 180:
                poll_interval = 15
            elif time_left_now > 90:
                poll_interval = 10
            else:
                poll_interval = 5    # critical window — scan every 5s
            time.sleep(min(poll_interval, max(remaining - 0.1, 0)))

        # ── Near-expiry scalp check (T-30s to T-10s) ─────────────────────────
        scalp_fired = False
        if entry_sig is None:
            time_left_now = w["close_time"] - time.time()
            if 10 <= time_left_now <= SCALP_ENTRY_TIME:
                scalp_sig   = analyze(candles, cur_price, window_open, tick_prices)
                scalp_dir   = scalp_sig["direction"]
                scalp_delta = abs(scalp_sig["window_pct"])
                if scalp_dir != "skip" and scalp_delta >= SCALP_DELTA_MIN:
                    scalp_price = None
                    if pm_market:
                        scalp_pinfo = get_real_token_prices(pm_market, scalp_dir, scalp_sig["window_pct"])
                        scalp_price = scalp_pinfo["token_price"]
                    if scalp_price and scalp_price >= SCALP_MIN_PRICE:
                        scalp_bet = max(round(session.balance * SCALP_BET_PCT, 2), MIN_BET)
                        scalp_ev  = compute_ev(0.97, scalp_price)
                        log(f"\n  🎯 SCALP ENTRY — T-{time_left_now:.0f}s | "
                            f"Δ {scalp_sig['window_pct']:+.4f}% | "
                            f"price ${scalp_price:.4f} | EV {scalp_ev:+.4f}")
                        if scalp_ev > 0:
                            entry_sig   = scalp_sig
                            entry_ask   = scalp_price
                            entry_tstr  = f"SCALP T-{time_left_now:.0f}s"
                            token_price = scalp_price
                            bet         = scalp_bet
                            bet_pct     = SCALP_BET_PCT * 100
                            kelly_pct   = SCALP_BET_PCT
                            raw_kelly   = SCALP_BET_PCT
                            zone_label  = f"SCALP 5% (Δ={scalp_delta:.3f}%)"
                            scalp_fired = True
                            log(f"  Scalp bet: ${scalp_bet:.2f} | Expected net: ~${round(scalp_bet/scalp_price - scalp_bet, 4):.4f}")
                        else:
                            log(f"  ⏭ Scalp skipped — EV {scalp_ev:+.4f} ≤ 0 at price ${scalp_price:.4f}")

        # ── No qualifying entry → determine skip reason + ghost trade ─────────
        if entry_sig is None and not scalp_fired:
            sig        = analyze(candles, cur_price, window_open, tick_prices)
            direction  = sig["direction"]
            score      = sig["score"]
            window_pct = sig["window_pct"]
            confidence = sig["confidence"]
            token_price = 0.50
            if real_prices and direction in real_prices:
                token_price = real_prices[direction]

            _exit_msg = (f"odds gone — ask > ${PRICE_CEILING}"
                         if exit_reason == "odds_gone"
                         else f"T-{ENTRY_CUTOFF}s cutoff reached")
            log(f"\n🎯 SIGNAL (no entry — {_exit_msg}):")
            log(f"  Direction   : {direction.upper()}")
            log(f"  Window Δ    : {window_pct:+.4f}%  [threshold: ±{DELTA_THRESHOLD}%]")
            log(f"  Score       : {score:+.1f}  [threshold: ±{SCORE_MIN:.0f}]")
            log(f"  Confidence  : {confidence:.0%}")
            log(f"  Token price : ${token_price:.3f}")

            if direction == "skip":
                skip_reason = "no direction"
                log(f"  ⏭ SKIP — no direction")
            elif abs(window_pct) < DELTA_THRESHOLD:
                skip_reason = f"delta {window_pct:+.4f}% < {DELTA_THRESHOLD}%"
                log(f"  ⏭ SKIP — Δ {window_pct:+.4f}% < {DELTA_THRESHOLD}% — flat market, no edge")
            elif abs(score) < SCORE_MIN:
                skip_reason = f"score {score:+.1f} < {SCORE_MIN:.0f}"
                log(f"  ⏭ SKIP — score {score:+.1f} < |{SCORE_MIN:.0f}| — weak signal")
            else:
                skip_reason = f"ask > ${PRICE_CEILING:.2f} ceiling (T-{ENTRY_CUTOFF}s)"
                log(f"  ⏭ SKIP — ask above ${PRICE_CEILING:.2f} ceiling at T-{ENTRY_CUTOFF}s cutoff")

            traded_windows.add(w["window_ts"])
            ghost_bet = max(round(session.balance * BET_PCT, 2), MIN_BET)
            ttc = w["close_time"] - time.time()
            if ttc > 0: time.sleep(ttc + 2)
            # Only log ghost when filters + T≤90 were all valid at some point this window
            if not had_valid_signal:
                continue
            shadow_count[0] += 1
            print_trade_row(
                utcnow().strftime("%H:%M:%S"),
                direction, score, confidence, 0.0, "SKIP", 0.0, session.balance,
            )
            ghost = fetch_shadow_result(w["window_ts"], direction, ghost_bet,
                                        token_price, skip_reason,
                                        score, window_pct, confidence, shadow_count[0])
            if ghost:
                append_shadow(ghost)
                if ghost["would_have"] == "WIN": shadow_missed[0] += ghost["ghost_pnl"]
                else: shadow_saved[0] += abs(ghost["ghost_pnl"])
            continue

        # ── Entry confirmed — lock signal values ──────────────────────────────
        direction   = entry_sig["direction"]
        confidence  = entry_sig["confidence"]
        score       = entry_sig["score"]
        window_pct  = entry_sig["window_pct"]
        # Initialize EV/Kelly defaults (scalp path may have already set bet/zone_label)
        ev         = 0.0
        kelly_pct  = 0.0
        raw_kelly  = 0.0
        # entry_ask is the price at time of entry — use it for all P&L calculation
        token_price           = entry_ask if entry_ask is not None else _estimate_price_formula(window_pct)
        estimated_token_price = _estimate_price_formula(window_pct)

        # Fetch current prices for logging/audit only — do NOT use for P&L
        if pm_market:
            price_info   = get_real_token_prices(pm_market, direction, window_pct)
            price_source = price_info["price_source"]
            yes_ask      = price_info["yes_ask"]
            no_ask       = price_info["no_ask"]
            pm_liquidity = pm_market.get("liquidity", 0)
            log(f"  ℹ️  Audit price at log time: ${price_info['token_price']:.4f} [{price_source}]  (entry was ${token_price:.4f})")
        else:
            price_source = "estimated"
            yes_ask      = None
            no_ask       = None
            pm_liquidity = 0

        log(f"\n🎯 SIGNAL (entered {entry_tstr}):")
        log(f"  Direction   : {direction.upper()}")
        log(f"  Window Δ    : {window_pct:+.4f}%  [threshold: ±{DELTA_THRESHOLD}%]")
        log(f"  Score       : {score:+.1f}  [threshold: ±{SCORE_MIN:.0f}]")
        log(f"  Confidence  : {confidence:.0%}")
        log(f"  Token live  : ${token_price:.3f} [{price_source}] "
            f"(estimated: ${estimated_token_price:.3f})")
        if yes_ask is not None:
            log(f"  YES ask     : ${yes_ask:.3f} | NO ask: ${no_ask:.3f}")
        if pm_liquidity:
            log(f"  PM liquidity: ${pm_liquidity:,.0f}")
        log(f"  Fill ceiling: ${PRICE_CEILING:.2f}")

        if not scalp_fired:
            # ── Zone-based bet sizing ($0.45–$0.69 HIGH 25% | $0.70–$0.94 MED 15%) ──
            if 0.45 <= token_price <= 0.69:
                zone_pct   = BET_ZONE_HIGH_PCT
                zone_label = f"HIGH ({BET_ZONE_HIGH_PCT*100:.0f}%) — token ${token_price:.3f}"
            elif 0.70 <= token_price <= 0.94:
                zone_pct   = BET_ZONE_MED_PCT
                zone_label = f"MEDIUM ({BET_ZONE_MED_PCT*100:.0f}%) — token ${token_price:.3f}"
            else:
                log(f"  ⏭ SKIP — token ${token_price:.3f} outside bet zones ($0.45–$0.94)")
                print_trade_row(
                    utcnow().strftime("%H:%M:%S"),
                    direction, score, confidence, 0.0, "SKIP", 0.0, session.balance,
                )
                traded_windows.add(w["window_ts"])
                ghost_bet = max(round(session.balance * BET_PCT, 2), MIN_BET)
                ttc = w["close_time"] - time.time()
                if ttc > 0: time.sleep(ttc + 2)
                shadow_count[0] += 1
                ghost = fetch_shadow_result(w["window_ts"], direction, ghost_bet,
                                            token_price,
                                            f"token ${token_price:.3f} outside zones ($0.45–$0.94)",
                                            score, window_pct, confidence, shadow_count[0])
                if ghost:
                    append_shadow(ghost)
                    if ghost["would_have"] == "WIN": shadow_missed[0] += ghost["ghost_pnl"]
                    else: shadow_saved[0] += abs(ghost["ghost_pnl"])
                continue
            bet       = max(round(session.balance * zone_pct, 2), MIN_BET)
            bet_pct   = round(zone_pct * 100, 1)
            kelly_pct = zone_pct    # CSV compatibility
            raw_kelly = zone_pct    # CSV compatibility
            ev        = compute_ev(confidence, token_price)
            log(f"  EV          : {ev:+.4f}  (q={confidence:.3f}, p={token_price:.4f})")
        else:
            ev = compute_ev(0.97, token_price)   # scalp uses near-certainty q, not TA confidence
            log(f"  EV (scalp)  : {ev:+.4f}  (q=0.97, p={token_price:.4f})")

        # ── ALL FILTERS PASSED — TRADE ────────────────────────────────────────
        expected_profit = round(bet/token_price - bet, 2)

        gross_expected = round(bet / token_price - bet, 4)
        fee_expected   = round(gross_expected * POLYMARKET_FEE, 4)
        net_expected   = round(gross_expected - fee_expected, 4)

        log(f"\n  ✅ TRADE — filters + ceiling passed")
        log(f"  Zone        : {zone_label} — token ${token_price:.3f} [{price_source}]")
        log(f"  Δ {window_pct:+.4f}% ≥ {DELTA_THRESHOLD}% ✓ | Score {score:+.1f} ≥ {SCORE_MIN:.0f} ✓")
        log(f"  Bet         : ${bet:.2f}  ({bet_pct:.1f}% of ${session.balance:.2f}  — ½ Kelly)")
        log(f"  Raw Kelly   : {raw_kelly*100:.1f}%  →  scaled to {kelly_pct*100:.1f}%")
        log(f"  Gross profit: ${gross_expected:.4f}  if win")
        log(f"  PM fee (2%) : −${fee_expected:.4f}")
        log(f"  Net profit  : ${net_expected:.4f}  if win")
        log(f"  Direction   : {direction.upper()}")

        # ── ORDER EXECUTION ───────────────────────────────────────────────────
        order_id   = ""
        trade_mode = "paper"

        # BUG-1 FIX: log which branch executes so it's always visible in the log
        _branch = "live" if executor is not None else ("real_gtc" if real_mode else "paper")
        log(f"  📍 BRANCH: {_branch}")

        live_fill_data = None
        live_res       = None

        if executor is not None:
            # ── LIVE path: FOK order via PolymarketExecutor ──────────────────
            token_ids = prefetched_token_ids
            if not (token_ids and direction in token_ids):
                log("  ❌ No token IDs — skipping")
                traded_windows.add(w["window_ts"]); continue

            # Sync session balance with real wallet right before the bet
            try:
                live_bal        = executor.get_balance()
                # Use ONLY confirmed liquid USDC — never add unredeemed token positions.
                # open_position_shares are not liquid until Polymarket auto-redeems them.
                if live_bal < session.balance:
                    session.balance = round(live_bal, 2)   # accept real losses
                # If live_bal > session.balance: phantom from unredeemed tokens — ignore
                effective_bal   = session.balance
                # bet already computed from ½ Kelly sizing above — recompute on synced balance
                bet             = max(round(session.balance * kelly_pct, 2), MIN_BET)
                bet_pct         = bet / session.balance * 100
                expected_profit = round(bet / token_price - bet, 2)
                drift = round(live_bal - session.balance, 2)
                drift_note = f" | phantom drift +${drift:.2f}" if drift > 0.10 else ""
                log(f"  💰 Re-sync: liquid USDC ${live_bal:.2f} | tracked ${session.balance:.2f}{drift_note} | bet ${bet:.2f}")
            except Exception as e:
                log(f"  [WARN] Balance re-sync failed: {e} — using cached ${session.balance:.2f}")

            log(f"  📤 Placing LIVE order (FOK)...")
            try:
                # Pre-submission slippage guard — abort if ask moved >$0.03 since entry
                try:
                    sub_book = executor.get_orderbook(token_ids[direction])
                    sub_ask  = sub_book["best_ask"]
                except Exception:
                    sub_ask  = entry_ask
                slip = sub_ask - entry_ask
                if slip > 0.03:
                    log(f"  ⛔ ABORTED — ask slipped ${entry_ask:.2f} → ${sub_ask:.2f} (+${slip:.2f}) between entry and submission")
                    traded_windows.add(w["window_ts"])
                    time.sleep(max(w["close_time"]-time.time()+3, 3)); continue
                fok_price = min(sub_ask, PRICE_CEILING)
                live_res = executor.place_market_order(token_ids[direction], "BUY", bet,
                                                       taker_price=fok_price)
                order_id = live_res["order_id"]

                if live_res["status"] == "killed":
                    log(f"  ⚠️  FOK killed — book too thin at taker_price={live_res['taker_price']} "
                        f"(orderID={order_id[:20] if order_id else 'none'})")
                    traded_windows.add(w["window_ts"])
                    time.sleep(max(w["close_time"]-time.time()+3, 3)); continue

                if live_res["status"] == "timeout":
                    log(f"  ⚠️  FOK timed out — network issue, order state unknown, skipping window")
                    traded_windows.add(w["window_ts"])
                    time.sleep(max(w["close_time"]-time.time()+3, 3)); continue

                if live_res["status"] == "no_asks":
                    log(f"  ⚠️  No asks in book — token illiquid, skipping window "
                        f"({live_res['raw'].get('error', '')})")
                    traded_windows.add(w["window_ts"])
                    time.sleep(max(w["close_time"]-time.time()+3, 3)); continue

                if live_res["status"] == "ceiling":
                    log(f"  ⚠️  Price ceiling exceeded at submit — "
                        f"ask ${live_res['best_ask']:.3f} > ${PRICE_CEILING:.2f} (moved since entry)")
                    traded_windows.add(w["window_ts"])
                    time.sleep(max(w["close_time"]-time.time()+3, 3)); continue

                trade_mode           = "live"
                live_fill_data       = (live_res["shares_filled"], live_res["usdc_spent"])
                open_position_shares = live_res["shares_filled"]  # track until settlement
                log(f"  📋 status={live_res['status']} | "
                    f"avg_fill={live_res['avg_fill_price']:.4f} | "
                    f"shares={live_res['shares_filled']:.4f} | "
                    f"spent=${live_res['usdc_spent']:.2f} | "
                    f"elapsed={live_res['elapsed_s']}s | "
                    f"orderID={order_id[:20]}...")

                # Anchor session.balance to real wallet immediately after fill.
                # post_trade_balance = wallet USDC ~4s after fill (shares bought, USDC deducted).
                # This prevents the internal balance from being over-estimated for the next bet.
                post_fill_bal = live_res.get("post_trade_balance")
                if post_fill_bal is not None:
                    # Effective balance = wallet USDC + shares × $1 (payout pending)
                    effective_bal = round(post_fill_bal + open_position_shares, 2)
                    estimated     = session.balance
                    drift         = abs(effective_bal - estimated)
                    if drift > 0.50:
                        log(f"  💰 REAL P&L: ${live_res['real_pnl']:+.2f} | "
                            f"Real balance: ${post_fill_bal:.2f} "
                            f"+ ${open_position_shares:.2f} position = ${effective_bal:.2f} | "
                            f"Bot estimate was: ${estimated:.2f}")
                        log(f"  ⚠️ DRIFT DETECTED: bot estimated ${estimated:.2f}, "
                            f"real is ${effective_bal:.2f}, correcting")
                    else:
                        log(f"  💰 Real wallet after fill: ${post_fill_bal:.2f} "
                            f"+ ${open_position_shares:.2f} position = ${effective_bal:.2f}")
                    session.balance = effective_bal
                    session.peak    = max(session.peak, effective_bal)
                if live_res["status"] not in ("matched", "filled") and not live_res["taking_amount"]:
                    log(f"  ⚠️  status={live_res['status']} — order may not have filled")
            except Exception as e:
                log(f"  [ERROR] Live order failed: {e}")
                traded_windows.add(w["window_ts"])
                time.sleep(max(w["close_time"]-time.time()+3, 3)); continue

        elif real_mode:
            # ── REAL-GTC path: old PolymarketClient (LIVE_TRADING=false) ────
            token_ids = prefetched_token_ids
            if token_ids and direction in token_ids:
                log(f"  📤 Placing order (GTC)...")
                result = poly.place_order(token_ids[direction], bet, token_price, direction)
                if not result:
                    log("  ❌ Order failed — skipping")
                    traded_windows.add(w["window_ts"])
                    time.sleep(max(w["close_time"]-time.time()+3, 3)); continue
                log(f"  ✅ Order placed!")
                trade_mode = "real_gtc"
            else:
                log("  ❌ No token IDs — skipping")
                traded_windows.add(w["window_ts"]); continue
        # else: paper — no order placed, trade_mode stays "paper"

        # Wait for close
        ttc = w["close_time"]-time.time()
        if ttc > 0: time.sleep(ttc+2)

        # Get result
        log("📊 Checking result...")
        actual            = None
        result_source     = "binance"
        resolution_source = "binance"

        # Try Polymarket resolution first if we have a market
        if pm_market and pm_market.get("market_id"):
            pm_res = check_polymarket_resolution(pm_market["market_id"])
            if pm_res:
                actual            = pm_res
                result_source     = "polymarket"
                resolution_source = "polymarket"
                log(f"  ✅ Resolution from Polymarket: {actual.upper()}")

        if not actual and real_mode:
            actual = poly.get_result(w["slug"])
            if actual:
                result_source     = "polymarket"
                resolution_source = "polymarket"

        if not actual:
            actual            = fetch_binance_result(w["window_ts"])
            result_source     = "binance"
            resolution_source = "binance"

        if not actual:
            log("[WARN] No result — skipping"); continue

        traded_windows.add(w["window_ts"])

        won = (direction == actual)
        pnl_gross = 0.0
        fee_deducted = 0.0
        if won:
            fill_bet      = live_fill_data[1] if live_fill_data else bet
            fill_tp       = (live_fill_data[1] / live_fill_data[0]) if (live_fill_data and live_fill_data[0]) else token_price
            pnl_net, pnl_gross, fee_deducted = session.record_win(fill_bet, fill_tp)
            pnl = pnl_net
            tokens_bought = round(fill_bet / fill_tp, 4) if fill_tp > 0 else 0
            payout        = round(tokens_bought * 1.00, 4)
            log(f"\n✅ WIN | {direction.upper()} | Actual: {actual.upper()} | "
                f"+${pnl_net:+.4f} | tokens: {tokens_bought:.4f} @ ${fill_tp:.4f} | "
                f"payout: ${payout:.4f} | fee: −${fee_deducted:.4f}")
            print_trade_row(
                utcnow().strftime("%H:%M:%S"),
                direction, score, confidence, bet, "WIN", pnl_net, session.balance,
            )

            # Immediately redeem the winning position so USDC arrives in the wallet
            if trade_mode == "live" and executor:
                log("💸 Redeeming winning position...")
                redeem = executor.redeem_position(w["slug"], direction)
                if redeem["success"]:
                    log(f"✅ Redeemed — tx: {redeem['tx_hash'][:20]}...")
                else:
                    log(f"  ⚠️ Redemption failed (Polymarket will auto-redeem): {redeem['error']}")
        else:
            loss_amt = live_fill_data[1] if live_fill_data else bet
            pnl      = session.record_loss(loss_amt)
            log(f"\n❌ LOSS | {direction.upper()} | Actual: {actual.upper()} | P&L: ${pnl:+.4f}")
            print_trade_row(
                utcnow().strftime("%H:%M:%S"),
                direction, score, confidence, loss_amt, "LOSS", pnl, session.balance,
            )

        # FIX B: re-anchor balance to real on-chain wallet after every live settlement.
        real_balance_after = ""
        if trade_mode == "live":
            try:
                real_bal = executor.get_balance()
                real_balance_after = round(real_bal, 4)
                # Position has resolved; clear it and use raw wallet balance.
                open_position_shares = 0.0
                drift = real_bal - session.balance
                if drift > 0.50:
                    log(f"💰 Wallet sync: bot ${session.balance:.2f} | real ${real_bal:.2f}"
                        f"  (unredeemed tokens: +${drift:.2f} — not counting)")
                elif drift < -0.10:
                    log(f"💰 Wallet sync: bot ${session.balance:.2f} | real ${real_bal:.2f}"
                        f"  ⚠️ DRIFT ${abs(drift):.2f} — correcting down")
                    session.balance = real_bal
                    session.peak    = max(session.peak, real_bal)
                else:
                    log(f"💰 Wallet sync: bot ${session.balance:.2f} | real ${real_bal:.2f}")
            except Exception as e:
                log(f"  [WARN] Wallet sync failed: {e}")

        if real_mode:
            save_persisted_balance(session.balance)
            log(f"💾 balance.json updated → ${session.balance:.2f}")

        trade_count += 1
        log(f"📊 {session.summary()}")
        log(f"🎯 Progress: {session.progress():.1f}%  (${session.balance:.2f} / ${TARGET_BANKROLL:.0f})")

        append_trade({
            "trade_id":              trade_count,
            "timestamp":             utcnow().isoformat(timespec="seconds"),
            "window_ts":             w["window_ts"],
            "direction_bet":         direction,
            "window_pct":            round(window_pct, 5),
            "score":                 score,
            "confidence":            round(confidence, 3),
            "ev":                    round(ev, 4),
            "token_price":           round(token_price, 4),
            "zone":                  zone_label,
            "kelly_pct":             round(kelly_pct * 100, 2),
            "raw_kelly":             round(raw_kelly * 100, 2),
            "bet_usd":               bet,
            "bet_pct":               round(bet_pct, 1),
            "result":                actual,
            "result_source":         result_source,
            "pnl_net":               round(pnl, 4),
            "balance_after":         round(session.balance, 4),
            "session_pnl":           round(session.session_pnl, 4),
            "win_rate_so_far":       round(session.win_rate(), 3),
            "real_mode":             real_mode,
            "mode":                  trade_mode,
            "avg_fill_price":        round(live_res["avg_fill_price"], 6) if live_res else "",
            "usdc_spent":            round(live_res["usdc_spent"], 4)     if live_res else "",
            "real_balance_after":    real_balance_after,
            # new columns
            "real_token_price":      round(token_price, 4),
            "estimated_token_price": round(estimated_token_price, 4),
            "price_source":          price_source,
            "yes_ask":               round(yes_ask, 4) if yes_ask is not None else "",
            "no_ask":                round(no_ask,  4) if no_ask  is not None else "",
            "polymarket_liquidity":  round(pm_liquidity, 2) if pm_liquidity else "",
            "pnl_gross":             round(pnl_gross, 4),
            "fee_deducted":          round(fee_deducted, 4),
            "resolution_source":     resolution_source,
            "polymarket_market_id":  pm_market["market_id"] if pm_market else "",
        })

        if args.once: break
        time.sleep(3)

    # ── Save updated balance back to config ──────────────────────────────────
    if real_mode:
        cfg.save_balances(real=session.balance)
    else:
        cfg.save_balances(paper=session.balance)

    # Final summary
    log("\n"+"="*65)
    log("SESSION COMPLETE")
    log(f"  Mode        : {'🔴 REAL MONEY' if real_mode else '📋 DRY RUN'}")
    log(f"  Balance     : ${session.balance:.2f}")
    log(f"  P&L         : ${session.session_pnl:+.2f}")
    log(f"  Trades      : {session.wins+session.losses}")
    log(f"  Win rate    : {session.win_rate():.1%}")
    log(f"  Peak        : ${session.peak:.2f}")
    log(f"  Total fees  : ${session.total_fees:.4f} (2% on wins, real simulation)")
    log("="*65)
    print_session_footer()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\n[STOPPED] Bot interrupted. Goodbye!")
        print_session_footer()