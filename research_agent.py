"""
research_agent.py — Free-source research + Claude analysis for btc_agent improvements.

Sources: DuckDuckGo, Reddit (public JSON API), GitHub (unauthenticated).
Analysis: claude-haiku-3-5 via Anthropic SDK.
Output: ~/polymarket-agent/research_report.md
"""

import os, time, json, re, textwrap
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
import anthropic

load_dotenv()

REPO_DIR    = Path(__file__).parent
REPORT_PATH = REPO_DIR / "research_report.md"
BOT_PATH    = REPO_DIR / "btc_agent.py"

MAX_RESULTS    = 20
MIN_BODY_CHARS = 100
MAX_BODY_CHARS = 500

# ── Helpers ───────────────────────────────────────────────────────────────────

def truncate(text: str, n: int = MAX_BODY_CHARS) -> str:
    text = re.sub(r'\s+', ' ', text or "").strip()
    return text[:n] + "…" if len(text) > n else text

def dedup(results: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in results:
        url = r.get("url", "")
        if url and url not in seen:
            seen.add(url)
            out.append(r)
    return out

def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ── Source 1: DuckDuckGo ──────────────────────────────────────────────────────

def search_ddg(queries: list[str], max_per_query: int = 5) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    results = []
    ddgs = DDGS()
    for q in queries:
        try:
            log(f"  DDG: {q!r}")
            hits = ddgs.text(q, max_results=max_per_query)
            for h in hits or []:
                body = truncate(h.get("body", ""))
                if len(body) >= MIN_BODY_CHARS:
                    results.append({
                        "source": "DuckDuckGo",
                        "title":  h.get("title", ""),
                        "url":    h.get("href", ""),
                        "body":   body,
                    })
            time.sleep(1.2)
        except Exception as e:
            log(f"  DDG error ({q!r}): {e}")
    return results

# ── Source 2: Reddit ──────────────────────────────────────────────────────────

REDDIT_HEADERS = {"User-Agent": "research_agent/1.0 (educational)"}

def search_reddit(subreddits: list[str], terms: list[str], max_per: int = 3) -> list[dict]:
    results = []
    for sub in subreddits:
        for term in terms:
            url = f"https://www.reddit.com/r/{sub}/search.json"
            params = {"q": term, "restrict_sr": 1, "sort": "relevance", "limit": max_per, "t": "year"}
            try:
                log(f"  Reddit r/{sub}: {term!r}")
                r = requests.get(url, params=params, headers=REDDIT_HEADERS, timeout=10)
                if r.status_code != 200:
                    log(f"  Reddit {r.status_code} for r/{sub}")
                    continue
                for post in r.json().get("data", {}).get("children", []):
                    d = post["data"]
                    body = truncate(d.get("selftext", "") or d.get("title", ""))
                    if len(body) < MIN_BODY_CHARS:
                        body = truncate(d.get("title", "") + " " + d.get("selftext", ""))
                    if len(body) >= MIN_BODY_CHARS:
                        results.append({
                            "source": f"Reddit r/{sub}",
                            "title":  d.get("title", ""),
                            "url":    "https://reddit.com" + d.get("permalink", ""),
                            "body":   body,
                        })
                time.sleep(1.0)
            except Exception as e:
                log(f"  Reddit error (r/{sub}, {term!r}): {e}")
    return results

# ── Source 3: GitHub ──────────────────────────────────────────────────────────

GITHUB_HEADERS = {"Accept": "application/vnd.github.v3+json"}

def search_github(queries: list[str], max_per: int = 3) -> list[dict]:
    results = []
    for q in queries:
        try:
            log(f"  GitHub: {q!r}")
            r = requests.get(
                "https://api.github.com/search/repositories",
                params={"q": q, "sort": "stars", "per_page": max_per},
                headers=GITHUB_HEADERS,
                timeout=10,
            )
            if r.status_code == 403:
                log("  GitHub rate-limited — skipping remaining GitHub queries")
                break
            if r.status_code != 200:
                log(f"  GitHub {r.status_code}")
                continue
            for item in r.json().get("items", []):
                desc = item.get("description") or ""
                body = truncate(f"{item.get('full_name','')} — {desc}. Stars: {item.get('stargazers_count',0)}. Language: {item.get('language','?')}.")
                if len(body) >= MIN_BODY_CHARS:
                    results.append({
                        "source": "GitHub",
                        "title":  item.get("full_name", ""),
                        "url":    item.get("html_url", ""),
                        "body":   body,
                    })
            time.sleep(1.5)
        except Exception as e:
            log(f"  GitHub error ({q!r}): {e}")
    return results

# ── Collect & trim ────────────────────────────────────────────────────────────

def collect_results() -> list[dict]:
    all_results = []

    log("=== DuckDuckGo ===")
    all_results += search_ddg([
        "polymarket btc 5min bot strategy",
        "binary prediction market momentum filter",
        "polymarket trading edge 2024",
        "algotrading binary market win rate improvement",
    ])

    log("=== Reddit ===")
    all_results += search_reddit(
        subreddits=["Polymarket", "algotrading", "ethfinance"],
        terms=["polymarket bot", "btc binary", "prediction market edge"],
    )

    log("=== GitHub ===")
    all_results += search_github([
        "polymarket bot python",
        "btc updown prediction",
    ])

    all_results = dedup(all_results)
    log(f"Total unique results before trim: {len(all_results)}")
    return all_results[:MAX_RESULTS]

# ── Claude analysis ───────────────────────────────────────────────────────────

def build_prompt(results: list[dict], bot_code: str) -> str:
    snippets = []
    for i, r in enumerate(results, 1):
        snippets.append(
            f"[{i}] {r['source']} | {r['title']}\n"
            f"URL: {r['url']}\n"
            f"{r['body']}"
        )
    research_block = "\n\n".join(snippets)

    return textwrap.dedent(f"""
        ## Research findings ({len(results)} sources)

        {research_block}

        ---

        ## Current bot code (btc_agent.py — truncated to 8000 chars)

        ```python
        {bot_code[:8000]}
        ```

        ---

        Based on the research above and the bot code, provide specific, actionable improvements.
        Address each of these areas:
        1. Signal filters (delta threshold, score gate, confidence)
        2. Bet sizing (Kelly, zone boundaries, risk per trade)
        3. Entry timing (T-90s gate, momentum confirmation)
        4. Risk management (stop loss, drawdown, trailing stop)
        5. Win rate improvements (false-positive reduction, asymmetric bets)

        For each suggestion, cite the source number if applicable. Be technical and precise.
        Prioritize changes with highest expected impact on a live Polymarket BTC 5-min binary bot.
    """).strip()

def analyze_with_claude(results: list[dict], bot_code: str) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return "ERROR: ANTHROPIC_API_KEY not found in .env"

    client = anthropic.Anthropic(api_key=api_key)
    prompt = build_prompt(results, bot_code)

    log("Sending to Claude (haiku)…")
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=2000,
            system=(
                "You are a senior quant developer specialized in Polymarket binary prediction markets. "
                "Analyze the research findings and the provided bot code. Identify specific, actionable "
                "improvements the developer can make to their bot. Focus on: signal filters, bet sizing, "
                "entry timing, risk management, win rate improvement. Be technical and precise."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
    except Exception as e:
        return f"Claude API error: {e}"

# ── Report ────────────────────────────────────────────────────────────────────

def write_report(results: list[dict], analysis: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# BTC Agent Research Report",
        f"Generated: {now}",
        f"Sources collected: {len(results)}",
        "",
        "---",
        "",
        "## Sources Found",
        "",
    ]
    for i, r in enumerate(results, 1):
        lines += [
            f"### [{i}] {r['source']} — {r['title']}",
            f"**URL:** {r['url']}",
            f"> {r['body']}",
            "",
        ]

    lines += [
        "---",
        "",
        "## Claude Analysis & Improvement Suggestions",
        "",
        analysis,
        "",
    ]

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    log(f"Report saved → {REPORT_PATH}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    t0 = time.time()
    log("=== Research Agent starting ===")

    # Load bot code
    if BOT_PATH.exists():
        bot_code = BOT_PATH.read_text(encoding="utf-8")
        log(f"Loaded btc_agent.py ({len(bot_code):,} chars)")
    else:
        bot_code = "# btc_agent.py not found"
        log("WARNING: btc_agent.py not found")

    # Collect
    results = collect_results()
    log(f"Kept {len(results)} results for analysis")

    if not results:
        log("No results collected — check network / rate limits")

    # Analyze
    analysis = analyze_with_claude(results, bot_code)

    # Save
    write_report(results, analysis)

    elapsed = round(time.time() - t0, 1)
    log(f"=== Done in {elapsed}s ===")

    # Console summary
    print("\n" + "="*60)
    print("RESEARCH AGENT SUMMARY")
    print("="*60)
    print(f"Sources: {len(results)} results from DDG / Reddit / GitHub")
    print(f"Report : {REPORT_PATH}")
    print(f"Time   : {elapsed}s")
    print("-"*60)
    print("TOP SUGGESTIONS (first 1500 chars):")
    print(analysis[:1500])
    print("="*60)

if __name__ == "__main__":
    main()
