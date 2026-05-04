"""
PolymarketExecutor V2 — live order execution via py_clob_client_v2.
Uses MarketOrderArgsV2 which handles decimal precision internally.
"""
import os, time, requests
from dotenv import load_dotenv
load_dotenv()

CLOB_HOST = "https://clob.polymarket.com"

_PRIVATE_KEY = (os.getenv("POLYMARKET_PRIVATE_KEY") or os.getenv("PRIVATE_KEY", ""))
_API_KEY     = (os.getenv("POLYMARKET_API_KEY")     or os.getenv("POLY_API_KEY", ""))
_API_SECRET  = (os.getenv("POLYMARKET_API_SECRET")  or os.getenv("POLY_API_SECRET", ""))
_API_PASS    = (os.getenv("POLYMARKET_API_PASSPHRASE") or os.getenv("POLY_API_PASSPHRASE", ""))
_FUNDER      = (os.getenv("POLYMARKET_FUNDER_ADDRESS") or
                os.getenv("POLY_FUNDER_ADDR", "0xec8de7FBab84518AeE23fc131aab93324a588CA3"))

SPREAD_LIMIT  = 0.08
PRICE_CEILING = 0.79


class PolymarketExecutor:

    def __init__(self):
        self._clob = self._build_client()

    def _build_client(self):
        from py_clob_client_v2 import ClobClient, ApiCreds
        if not _PRIVATE_KEY:
            raise RuntimeError("Missing PRIVATE_KEY in .env")
        creds = ApiCreds(api_key=_API_KEY, api_secret=_API_SECRET, api_passphrase=_API_PASS)
        return ClobClient(host=CLOB_HOST, chain_id=137, key=_PRIVATE_KEY,
                          creds=creds, signature_type=0)

    def get_balance(self) -> float:
        try:
            from py_clob_client_v2 import BalanceAllowanceParams, AssetType
            result = self._clob.get_balance_allowance(
                params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
            return round(int(result.get("balance", 0)) / 1_000_000, 2)
        except Exception as e:
            raise RuntimeError(f"get_balance failed: {e}")

    def ensure_allowance(self):
        try:
            from py_clob_client_v2 import BalanceAllowanceParams, AssetType
            p = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            r = self._clob.get_balance_allowance(params=p)
            print(f"  ✅ Allowance OK — balance: ${int(r.get('balance',0))/1e6:.2f}")
        except Exception as e:
            raise RuntimeError(f"ensure_allowance failed: {e}")

    def get_orderbook(self, token_id: str) -> dict:
        """Fetch orderbook via REST API — V2 SDK parsing is unreliable."""
        for attempt in range(3):
            try:
                r    = requests.get(f"{CLOB_HOST}/book",
                                    params={"token_id": token_id}, timeout=5)
                data = r.json()
                bids = sorted([float(b["price"]) for b in data.get("bids", [])], reverse=True)
                asks = sorted([float(a["price"]) for a in data.get("asks", [])])
                if bids and asks:
                    return {"bids": bids[:5], "asks": asks[:5],
                            "best_bid": bids[0], "best_ask": asks[0],
                            "spread": round(asks[0] - bids[0], 4)}
            except Exception as e:
                pass
            if attempt < 2:
                time.sleep(0.1)
        raise RuntimeError("[ABORT] orderbook empty after 3 retries — bid=None ask=None")

    def place_market_order(self, token_id: str, side: str, usdc_amount: float,
                           taker_price: float = None) -> dict:
        from py_clob_client_v2 import (MarketOrderArgsV2, OrderType,
                                        Side, PartialCreateOrderOptions)

        # Orderbook check
        book = self.get_orderbook(token_id)
        if book["spread"] > SPREAD_LIMIT:
            raise RuntimeError(f"[ABORT] spread {book['spread']} > {SPREAD_LIMIT}")
        if book["best_ask"] > PRICE_CEILING:
            raise RuntimeError(f"[ABORT] ASK ${book['best_ask']:.3f} > ${PRICE_CEILING} — too late")

        # Round maker (USDC, 2dp) and back-derive taker (shares, 4dp) to satisfy CLOB limits
        fill_price_pre = taker_price if taker_price is not None else None
        if fill_price_pre is None:
            # need first book fetch to know price; do a quick read
            try:
                _b = self.get_orderbook(token_id)
                fill_price_pre = _b.get("best_ask") or usdc_amount
            except Exception:
                fill_price_pre = usdc_amount
        if fill_price_pre and fill_price_pre > 0:
            shares_approx   = usdc_amount / fill_price_pre
            shares_rounded  = round(shares_approx, 4)
            actual_usdc     = round(shares_rounded * fill_price_pre, 2)
        else:
            actual_usdc = round(usdc_amount, 2)

        # Re-fetch for current bid/spread; price for FOK is caller-supplied or live ask
        time.sleep(0.1)
        book2    = self.get_orderbook(token_id)
        best_ask = book2["best_ask"]
        best_bid = book2["best_bid"]

        if best_ask > PRICE_CEILING:
            raise RuntimeError(f"[ABORT] ASK moved to ${best_ask:.3f} on second fetch")

        fill_price = taker_price if taker_price is not None else best_ask
        print(f"  ASK={best_ask:.3f} BID={best_bid:.3f} fill_price={fill_price:.3f} | ${actual_usdc:.2f} USDC")

        # Use MarketOrderArgsV2 — handles decimal precision internally
        try:
            poly_side = Side.BUY if side.upper() == "BUY" else Side.SELL
            bal       = self.get_balance()
            args      = MarketOrderArgsV2(
                token_id=token_id,
                amount=actual_usdc,
                side=poly_side,
                price=fill_price,
                user_usdc_balance=bal,
            )
            t0     = time.time()
            signed = self._clob.create_market_order(
                args, PartialCreateOrderOptions(tick_size="0.01"))
            resp   = self._clob.post_order(signed, OrderType.FOK)
            elapsed = round(time.time() - t0, 2)
        except Exception as e:
            err_str = str(e)
            # FOK "killed" means the book was too thin — not a hard error, return killed status
            if "fully filled" in err_str or "FOK" in err_str:
                order_id = ""
                try:
                    import re
                    m = re.search(r"'orderID':\s*'(0x[0-9a-fA-F]+)'", err_str)
                    if m:
                        order_id = m.group(1)
                except Exception:
                    pass
                return {
                    "order_id":       order_id,
                    "status":         "killed",
                    "fill_price":     fill_price,
                    "avg_fill_price": fill_price,
                    "best_bid":       best_bid,
                    "taker_price":    fill_price,
                    "usdc_amount":    actual_usdc,
                    "usdc_spent":     0.0,
                    "taking_amount":  "",
                    "shares_filled":  0.0,
                    "elapsed_s":      round(time.time() - t0, 2),
                    "raw":            {"error": err_str},
                }
            if ("timed out" in err_str or "Request exception" in err_str
                    or "status_code=None" in err_str):
                return {
                    "order_id":       "",
                    "status":         "timeout",
                    "fill_price":     fill_price,
                    "avg_fill_price": fill_price,
                    "best_bid":       best_bid,
                    "taker_price":    fill_price,
                    "usdc_amount":    actual_usdc,
                    "usdc_spent":     0.0,
                    "taking_amount":  "",
                    "shares_filled":  0.0,
                    "elapsed_s":      round(time.time() - t0, 2),
                    "raw":            {"error": err_str},
                }
            raise RuntimeError(f"Order submission failed: {e}")

        status        = resp.get("status", "unknown")
        taking_amount = resp.get("takingAmount", "")
        order_id      = resp.get("orderID", "")

        shares_filled = float(taking_amount) if taking_amount else 0.0

        return {
            "order_id":       order_id,
            "status":         status,
            "fill_price":     fill_price,
            "avg_fill_price": fill_price,
            "best_bid":       best_bid,
            "usdc_amount":    actual_usdc,
            "usdc_spent":     actual_usdc,
            "taking_amount":  taking_amount,
            "shares_filled":  shares_filled,
            "elapsed_s":      elapsed,
            "raw":            resp,
        }

    def redeem_position(self, slug: str, direction: str) -> dict:
        """Attempt early redemption of a winning position.

        py_clob_client_v2 has no redemption API; Polymarket auto-redeems
        within minutes of settlement. This method tries any available path
        and always returns a structured result so the caller can log and move on.
        """
        try:
            # Try via the CLOB client if a future SDK version adds the method.
            if hasattr(self._clob, "redeem_positions"):
                tx = self._clob.redeem_positions(slug=slug, side=direction)
                return {"success": True, "tx_hash": str(tx), "error": ""}
            # Fallback: Polymarket will auto-redeem; treat as non-fatal.
            return {
                "success": False,
                "tx_hash": "",
                "error": "redemption not supported by py_clob_client_v2 — Polymarket will auto-redeem",
            }
        except Exception as e:
            return {"success": False, "tx_hash": "", "error": str(e)}
