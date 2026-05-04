"""
BTC Agent Dashboard v4.0 — Compatible with btc_agent v1.6
Run: python3 dashboard_server.py
Open: http://localhost:5001
"""

import csv, json, os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

BTC_CSV   = "btc_trades.csv"
AGENT_LOG = "btc_agent.log"
STARTING  = 100.0
TARGET    = 1000.0
PORT      = 5001

def read_trades():
    if not os.path.exists(BTC_CSV): return []
    try:
        with open(BTC_CSV, "r", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except: return []

def read_log(n=60):
    if not os.path.exists(AGENT_LOG): return []
    try:
        with open(AGENT_LOG, "r", encoding="utf-8") as f:
            return [l.rstrip() for l in f.readlines()[-n:]]
    except: return []

def compute_stats(trades):
    empty = dict(
        balance=STARTING, session_pnl=0, pnl_pct=0,
        trades=0, wins=0, losses=0, win_rate=0,
        progress_pct=0, avg_token=0, total_bet=0,
        stop_pct=0, best=0, worst=0, avg_win=0, avg_loss=0,
        high_w=0, high_l=0, medium_w=0, medium_l=0,
    )
    if not trades: return empty

    def f(t, k, d=0):
        try: return float(t.get(k) or d)
        except: return d

    def won(t):
        return t.get("result","") == t.get("direction_bet","")

    wins   = sum(1 for t in trades if won(t))
    losses = len(trades) - wins
    bal    = f(trades[-1], "balance_after", STARTING)

    spnl_raw    = trades[-1].get("session_pnl","")
    session_pnl = float(spnl_raw) if spnl_raw else (bal - STARTING)
    pnl_pct     = session_pnl / STARTING * 100
    progress    = max((bal - STARTING) / (TARGET - STARTING) * 100, 0)

    tokens, bets, pnls = [], [], []
    zone_stats = {"high": [0,0], "medium": [0,0]}

    for t in trades:
        tp = f(t, "token_price")
        if tp: tokens.append(tp)
        bt = f(t, "bet_usd")
        if bt: bets.append(bt)
        pnl = f(t, "pnl_usd")
        pnls.append(pnl)

        zone = t.get("zone","").lower()
        if zone in zone_stats:
            zone_stats[zone][0 if won(t) else 1] += 1

    win_pnls  = [p for p in pnls if p > 0]
    loss_pnls = [abs(p) for p in pnls if p < 0]
    all_pnls  = [f(t,"pnl_usd") for t in trades]
    best  = max(all_pnls) if all_pnls else 0
    worst = min(all_pnls) if all_pnls else 0

    return dict(
        balance=round(bal,2),
        session_pnl=round(session_pnl,2),
        pnl_pct=round(pnl_pct,1),
        trades=len(trades), wins=wins, losses=losses,
        win_rate=round(wins/len(trades)*100,1) if trades else 0,
        progress_pct=round(min(progress,100),1),
        avg_token=round(sum(tokens)/len(tokens),3) if tokens else 0,
        total_bet=round(sum(bets),2),
        stop_pct=round(min(abs(session_pnl)/40*100,100),1) if session_pnl<0 else 0,
        best=round(best,2), worst=round(worst,2),
        avg_win=round(sum(win_pnls)/len(win_pnls),2) if win_pnls else 0,
        avg_loss=round(sum(loss_pnls)/len(loss_pnls),2) if loss_pnls else 0,
        high_w=zone_stats["high"][0], high_l=zone_stats["high"][1],
        medium_w=zone_stats["medium"][0], medium_l=zone_stats["medium"][1],
    )

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/data":
            trades = read_trades()
            body   = json.dumps({"stats": compute_stats(trades), "trades": trades[-100:], "logs": read_log()})
            self.send_response(200)
            self.send_header("Content-Type","application/json")
            self.send_header("Access-Control-Allow-Origin","*")
            self.end_headers()
            self.wfile.write(body.encode())
        elif path in ("/","/index.html"):
            self.send_response(200)
            self.send_header("Content-Type","text/html")
            self.end_headers()
            self.wfile.write(HTML.encode())
        else:
            self.send_response(404); self.end_headers()

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BTC Agent v1.6</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#0a0a0a;--s1:#111;--s2:#181818;--b1:#222;--b2:#2a2a2a;
  --g:#10b981;--g2:#059669;--r:#ef4444;--b:#3b82f6;--y:#f59e0b;--p:#8b5cf6;
  --t:#e2e8f0;--t2:#64748b;--t3:#334155;
  --mono:'JetBrains Mono',monospace;--sans:'Inter',sans-serif;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{background:var(--bg);color:var(--t);font-family:var(--sans);font-size:13px}
.shell{display:grid;grid-template-columns:260px 1fr;grid-template-rows:48px 1fr;height:100vh;overflow:hidden}
.topbar{grid-column:1/3;display:flex;align-items:center;justify-content:space-between;padding:0 20px;background:var(--s1);border-bottom:1px solid var(--b1)}
.sidebar{grid-column:1;overflow-y:auto;padding:14px 12px;border-right:1px solid var(--b1);display:flex;flex-direction:column;gap:14px}
.content{grid-column:2;overflow-y:auto;padding:14px 18px;display:flex;flex-direction:column;gap:12px}
::-webkit-scrollbar{width:3px;height:3px}
::-webkit-scrollbar-thumb{background:var(--b2);border-radius:2px}

/* topbar */
.logo{display:flex;align-items:center;gap:10px;font-family:var(--mono);font-size:14px;font-weight:500}
.logo-diamond{width:12px;height:12px;background:var(--g);transform:rotate(45deg);border-radius:1px;flex-shrink:0;animation:pulse 2s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
.logo em{color:var(--g);font-style:normal}
.vtag{font-size:10px;font-family:var(--mono);color:var(--t3);background:var(--s2);border:1px solid var(--b1);padding:2px 7px;border-radius:3px}
.tr{display:flex;align-items:center;gap:14px}
.live{display:flex;align-items:center;gap:5px;font-size:10px;font-family:var(--mono);color:var(--g);letter-spacing:.06em}
.ldot{width:5px;height:5px;border-radius:50%;background:var(--g);animation:blink 1.8s ease-in-out infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.1}}
.ts{font-size:10px;font-family:var(--mono);color:var(--t3)}

/* sidebar sections */
.slabel{font-size:9px;font-weight:500;text-transform:uppercase;letter-spacing:.12em;color:var(--t3);margin-bottom:6px}
.card{background:var(--s1);border:1px solid var(--b1);border-radius:8px;overflow:hidden}

/* balance block */
.bal-block{padding:14px}
.bal-num{font-family:var(--mono);font-size:34px;font-weight:500;line-height:1;letter-spacing:-.02em;margin-bottom:4px;transition:color .3s}
.bal-num.up{color:var(--g)}
.bal-num.dn{color:var(--r)}
.bal-pnl{font-size:12px;font-family:var(--mono);margin-bottom:14px}
.bal-pnl.up{color:var(--g)}
.bal-pnl.dn{color:var(--r)}
.brow{margin-bottom:8px}
.brow:last-child{margin-bottom:0}
.bmeta{display:flex;justify-content:space-between;font-size:9px;font-family:var(--mono);color:var(--t3);margin-bottom:4px}
.btrack{height:3px;background:var(--b1);border-radius:2px;overflow:hidden}
.bfill{height:100%;border-radius:2px;transition:width .8s ease}
.bfill.g{background:var(--g)}
.bfill.r{background:linear-gradient(90deg,var(--y),var(--r))}

/* stat pairs */
.spair{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--b1);border-radius:6px;overflow:hidden;border:1px solid var(--b1)}
.scell{background:var(--s1);padding:9px 10px}
.sclabel{font-size:9px;font-family:var(--mono);color:var(--t3);letter-spacing:.1em;text-transform:uppercase;margin-bottom:3px}
.scval{font-family:var(--mono);font-size:15px;font-weight:500;line-height:1}
.scsub{font-size:9px;color:var(--t3);margin-top:2px}

/* zone breakdown */
.zrows{padding:0}
.zrow{display:flex;align-items:center;gap:8px;padding:9px 12px;border-bottom:1px solid var(--b1)}
.zrow:last-child{border-bottom:none}
.zdot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.zname{font-size:10px;font-family:var(--mono);color:var(--t);min-width:56px}
.zpct{font-size:9px;color:var(--t3);min-width:28px}
.zbar-wrap{flex:1;height:2px;background:var(--b1);border-radius:1px;overflow:hidden}
.zbar{height:100%;border-radius:1px;transition:width .6s ease}
.zwl{font-size:9px;font-family:var(--mono);min-width:40px;text-align:right}

/* extremes */
.egrid{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.ec{background:var(--s1);border:1px solid var(--b1);border-radius:6px;padding:8px 10px}
.eclabel{font-size:9px;font-family:var(--mono);color:var(--t3);letter-spacing:.1em;text-transform:uppercase;margin-bottom:3px}
.ecval{font-size:14px;font-family:var(--mono);font-weight:500}

/* compounding indicator */
.compound-card{background:var(--s1);border:1px solid var(--b1);border-radius:8px;padding:12px 14px}
.compound-label{font-size:9px;font-family:var(--mono);color:var(--t3);text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px}
.compound-row{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.compound-key{font-size:10px;color:var(--t2)}
.compound-val{font-size:11px;font-family:var(--mono);font-weight:500;color:var(--t)}

/* metric strip */
.mstrip{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}
.mc{background:var(--s1);border:1px solid var(--b1);border-radius:8px;padding:12px 14px;position:relative;overflow:hidden;transition:border-color .2s}
.mc:hover{border-color:var(--b2)}
.mc::after{content:'';position:absolute;bottom:0;left:0;right:0;height:2px;opacity:0;transition:opacity .3s}
.mc:hover::after{opacity:1}
.mcg::after{background:var(--g)}.mcr::after{background:var(--r)}.mcb::after{background:var(--b)}.mcy::after{background:var(--y)}.mcp::after{background:var(--p)}
.mlabel{font-size:9px;font-family:var(--mono);letter-spacing:.1em;color:var(--t3);text-transform:uppercase;margin-bottom:7px}
.mval{font-family:var(--mono);font-size:22px;font-weight:500;line-height:1;margin-bottom:4px}
.msub{font-size:9px;color:var(--t3)}

/* charts */
.crow{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.cc{background:var(--s1);border:1px solid var(--b1);border-radius:8px;overflow:hidden}
.ch{display:flex;align-items:center;justify-content:space-between;padding:9px 12px;border-bottom:1px solid var(--b1)}
.ct{font-size:9px;font-family:var(--mono);letter-spacing:.1em;color:var(--t3);text-transform:uppercase}
.cbadge{font-size:9px;font-family:var(--mono);color:var(--t3);background:var(--s2);padding:2px 7px;border-radius:3px}
.cb{padding:12px;height:170px;position:relative}
canvas{display:block;width:100%!important;height:100%!important}

/* table */
.tc{background:var(--s1);border:1px solid var(--b1);border-radius:8px;overflow:hidden}
.tscroll{max-height:200px;overflow-y:auto}
table{width:100%;border-collapse:collapse}
th{font-size:8px;font-family:var(--mono);letter-spacing:.1em;color:var(--t3);text-transform:uppercase;font-weight:500;padding:7px 10px;text-align:left;background:var(--s2);border-bottom:1px solid var(--b1);position:sticky;top:0;z-index:1}
td{padding:7px 10px;font-size:11px;font-family:var(--mono);border-bottom:1px solid var(--b1);color:var(--t2)}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(255,255,255,.015)}
.chip{display:inline-flex;align-items:center;font-size:9px;font-weight:500;padding:2px 6px;border-radius:3px}
.chip-up{color:var(--g);background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.15)}
.chip-down{color:var(--r);background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.15)}
.chip-high{color:var(--g);background:rgba(16,185,129,.06);border:1px solid rgba(16,185,129,.12)}
.chip-medium{color:var(--b);background:rgba(59,130,246,.06);border:1px solid rgba(59,130,246,.12)}
.wc{color:var(--g);font-weight:500}.lc{color:var(--r);font-weight:500}

/* log */
.lcard{background:var(--s1);border:1px solid var(--b1);border-radius:8px;overflow:hidden}
.lterm{background:#070707;padding:10px 12px;max-height:180px;overflow-y:auto;font-family:var(--mono);font-size:10px;line-height:1.9;color:var(--t3)}
.ll{white-space:pre-wrap;word-break:break-all}
.ll.win{color:var(--g)}.ll.loss{color:var(--r)}.ll.trade{color:var(--y);font-weight:500}
.ll.skip{color:#1e1e1e}.ll.warn{color:var(--y);opacity:.7}.ll.stop{color:var(--r);font-weight:500}
.ll.head{color:#1a1a1a}.ll.info{color:var(--b)}
.empty{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:28px;gap:6px;color:var(--t3);font-size:11px;font-family:var(--mono)}
</style>
</head>
<body>
<div class="shell">

<header class="topbar">
  <div class="logo">
    <div class="logo-diamond"></div>
    BTC<em>AGENT</em>
    <span class="vtag">v1.6</span>
  </div>
  <div class="tr">
    <div class="live"><div class="ldot"></div>LIVE</div>
    <span class="ts" id="ts">—</span>
  </div>
</header>

<aside class="sidebar">

  <div>
    <div class="slabel">Balance</div>
    <div class="card">
      <div class="bal-block">
        <div class="bal-num" id="balNum">$100.00</div>
        <div class="bal-pnl" id="balPnl">+$0.00 · +0.0%</div>
        <div class="brow">
          <div class="bmeta"><span>$100 start</span><span>$1000 target</span></div>
          <div class="btrack"><div class="bfill g" id="progBar" style="width:0%"></div></div>
        </div>
        <div class="brow">
          <div class="bmeta"><span>Session stop loss</span><span id="stopPct">0%</span></div>
          <div class="btrack"><div class="bfill r" id="stopBar" style="width:0%"></div></div>
        </div>
      </div>
      <div class="spair">
        <div class="scell"><div class="sclabel">Win Rate</div><div class="scval" id="sWR" style="color:var(--g)">—</div><div class="scsub" id="sWL">0W / 0L</div></div>
        <div class="scell"><div class="sclabel">Trades</div><div class="scval" id="sTrades" style="color:var(--t)">0</div><div class="scsub">this session</div></div>
        <div class="scell"><div class="sclabel">Avg Win</div><div class="scval" id="sAvgW" style="color:var(--g)">—</div><div class="scsub">per win</div></div>
        <div class="scell"><div class="sclabel">Avg Loss</div><div class="scval" id="sAvgL" style="color:var(--r)">—</div><div class="scsub">per loss</div></div>
      </div>
    </div>
  </div>

  <div>
    <div class="slabel">Zone Breakdown</div>
    <div class="card">
      <div class="zrows">
        <div class="zrow">
          <div class="zdot" style="background:var(--g)"></div>
          <span class="zname">HIGH</span>
          <span class="zpct">25%</span>
          <div class="zbar-wrap"><div class="zbar" id="zb-high" style="width:0%;background:var(--g)"></div></div>
          <span class="zwl" id="zw-high" style="color:var(--g)">0/0</span>
        </div>
        <div class="zrow">
          <div class="zdot" style="background:var(--b)"></div>
          <span class="zname">MEDIUM</span>
          <span class="zpct">15%</span>
          <div class="zbar-wrap"><div class="zbar" id="zb-medium" style="width:0%;background:var(--b)"></div></div>
          <span class="zwl" id="zw-medium" style="color:var(--b)">0/0</span>
        </div>
      </div>
    </div>
  </div>

  <div>
    <div class="slabel">Compounding Status</div>
    <div class="compound-card">
      <div class="compound-label">Next trade bet size</div>
      <div class="compound-row">
        <div class="compound-key">HIGH zone (25%)</div>
        <div class="compound-val" id="nextHigh">$25.00</div>
      </div>
      <div class="compound-row">
        <div class="compound-key">MEDIUM zone (15%)</div>
        <div class="compound-val" id="nextMed">$15.00</div>
      </div>
      <div class="compound-row" style="margin-bottom:0;border-top:1px solid var(--b1);padding-top:6px;margin-top:2px">
        <div class="compound-key" style="color:var(--t3)">vs start ($100)</div>
        <div class="compound-val" id="compoundDiff" style="color:var(--t3)">+$0</div>
      </div>
    </div>
  </div>

  <div>
    <div class="slabel">Trade Extremes</div>
    <div class="egrid">
      <div class="ec"><div class="eclabel">Best</div><div class="ecval" id="eBest" style="color:var(--g)">—</div></div>
      <div class="ec"><div class="eclabel">Worst</div><div class="ecval" id="eWorst" style="color:var(--r)">—</div></div>
      <div class="ec"><div class="eclabel">Avg Token</div><div class="ecval" id="eToken" style="color:var(--b)">—</div></div>
      <div class="ec"><div class="eclabel">Deployed</div><div class="ecval" id="eDep" style="color:var(--p)">$0</div></div>
    </div>
  </div>

</aside>

<main class="content">

  <div class="mstrip">
    <div class="mc mcg">
      <div class="mlabel">Session P&L</div>
      <div class="mval" id="mPnl" style="color:var(--g)">+$0.00</div>
      <div class="msub" id="mPct">+0.0% from $100</div>
    </div>
    <div class="mc mcg">
      <div class="mlabel">Win Rate</div>
      <div class="mval" id="mWR" style="color:var(--g)">—</div>
      <div class="msub" id="mWRsub">no trades yet</div>
    </div>
    <div class="mc mcb">
      <div class="mlabel">Total Trades</div>
      <div class="mval" id="mTrades" style="color:var(--t)">0</div>
      <div class="msub">this session</div>
    </div>
    <div class="mc mcy">
      <div class="mlabel">Progress</div>
      <div class="mval" id="mProg" style="color:var(--y)">0%</div>
      <div class="msub">to $1000 target</div>
    </div>
    <div class="mc mcp">
      <div class="mlabel">Stop Used</div>
      <div class="mval" id="mStop" style="color:var(--p)">0%</div>
      <div class="msub">of $40 session limit</div>
    </div>
  </div>

  <div class="crow">
    <div class="cc">
      <div class="ch"><span class="ct">Balance Curve</span><span class="cbadge" id="cBalBadge">0 pts</span></div>
      <div class="cb"><canvas id="cBal"></canvas></div>
    </div>
    <div class="cc">
      <div class="ch"><span class="ct">P&L Per Trade</span><span class="cbadge" id="cDistBadge">0 trades</span></div>
      <div class="cb"><canvas id="cDist"></canvas></div>
    </div>
  </div>

  <div class="tc">
    <div class="ch"><span class="ct">Recent Trades</span><span class="cbadge" id="tBadge">0 trades</span></div>
    <div class="tscroll" id="tBody">
      <div class="empty"><span>◎</span><span>Waiting for first trade…</span></div>
    </div>
  </div>

  <div class="lcard">
    <div class="ch"><span class="ct">Agent Log</span><span class="cbadge">last 60 lines</span></div>
    <div class="lterm" id="lterm"><div class="ll">waiting for output…</div></div>
  </div>

</main>
</div>

<script>
const $ = id => document.getElementById(id);
const dpr = devicePixelRatio || 1;

function setupC(id) {
  const c = $(id);
  const W = c.offsetWidth, H = c.offsetHeight;
  c.width = W * dpr; c.height = H * dpr;
  const ctx = c.getContext('2d');
  ctx.scale(dpr, dpr);
  return {ctx, W, H};
}

function drawEmpty(ctx, W, H, msg) {
  ctx.fillStyle = '#1e1e1e';
  ctx.font = '10px JetBrains Mono,monospace';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(msg, W/2, H/2);
}

function drawBal(trades) {
  const {ctx, W, H} = setupC('cBal');
  const pts = [100, ...trades.map(t => parseFloat(t.balance_after) || 100)];
  if (pts.length < 2) { drawEmpty(ctx, W, H, 'need 2+ trades'); return; }
  const pad = {l:36,r:10,t:10,b:22};
  const cw = W-pad.l-pad.r, ch = H-pad.t-pad.b;
  const minV = Math.min(...pts)*.994, maxV = Math.max(...pts)*1.006, rng = maxV-minV||1;
  const sx = i => pad.l + i/(pts.length-1)*cw;
  const sy = v => pad.t + ch - (v-minV)/rng*ch;

  [minV,(minV+maxV)/2,maxV].forEach(v => {
    const y = sy(v);
    ctx.beginPath(); ctx.strokeStyle='#181818'; ctx.lineWidth=1;
    ctx.setLineDash([2,4]); ctx.moveTo(pad.l,y); ctx.lineTo(W-pad.r,y); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle='#334155'; ctx.font='8px JetBrains Mono,monospace';
    ctx.textAlign='right'; ctx.fillText('$'+v.toFixed(0), pad.l-4, y+3);
  });

  ctx.beginPath(); ctx.strokeStyle='#1a1a1a'; ctx.lineWidth=1;
  ctx.setLineDash([3,5]);
  ctx.moveTo(pad.l, sy(100)); ctx.lineTo(W-pad.r, sy(100)); ctx.stroke();
  ctx.setLineDash([]);

  const last = pts[pts.length-1];
  const lc = last >= 100 ? '#10b981' : '#ef4444';
  const grad = ctx.createLinearGradient(0,pad.t,0,H-pad.b);
  grad.addColorStop(0, last>=100?'rgba(16,185,129,.1)':'rgba(239,68,68,.1)');
  grad.addColorStop(1,'rgba(0,0,0,0)');

  ctx.beginPath();
  pts.forEach((v,i) => i===0?ctx.moveTo(sx(i),sy(v)):ctx.lineTo(sx(i),sy(v)));
  ctx.lineTo(sx(pts.length-1),H-pad.b); ctx.lineTo(sx(0),H-pad.b);
  ctx.closePath(); ctx.fillStyle=grad; ctx.fill();

  ctx.beginPath();
  pts.forEach((v,i) => i===0?ctx.moveTo(sx(i),sy(v)):ctx.lineTo(sx(i),sy(v)));
  ctx.strokeStyle=lc; ctx.lineWidth=1.5; ctx.lineJoin='round'; ctx.stroke();

  trades.forEach((t,i) => {
    const won = t.result === t.direction_bet;
    ctx.beginPath(); ctx.arc(sx(i+1), sy(parseFloat(t.balance_after)||100), 3,0,Math.PI*2);
    ctx.fillStyle=won?'#10b981':'#ef4444'; ctx.strokeStyle='#0a0a0a';
    ctx.lineWidth=1; ctx.fill(); ctx.stroke();
  });

  if (trades.length) {
    ctx.fillStyle='#334155'; ctx.font='8px JetBrains Mono,monospace'; ctx.textAlign='center';
    const step = Math.max(1, Math.floor(trades.length/4));
    trades.forEach((t,i) => {
      if (i%step===0||i===trades.length-1)
        ctx.fillText((t.timestamp||'').slice(11,16), sx(i+1), H-pad.b+14);
    });
  }
}

function drawPnl(trades) {
  const {ctx, W, H} = setupC('cDist');
  if (!trades.length) { drawEmpty(ctx,W,H,'no trades yet'); return; }
  const pnls = trades.map(t => parseFloat(t.pnl_usd)||0);
  const pad = {l:36,r:10,t:10,b:22};
  const cw=W-pad.l-pad.r, ch=H-pad.t-pad.b;
  const maxA = Math.max(...pnls.map(Math.abs),1);
  const bw = Math.max(4, Math.min(22,(cw/pnls.length)-2));
  const mid = pad.t+ch/2;

  ctx.beginPath(); ctx.strokeStyle='#1e1e1e'; ctx.lineWidth=1;
  ctx.moveTo(pad.l,mid); ctx.lineTo(W-pad.r,mid); ctx.stroke();
  ctx.fillStyle='#334155'; ctx.font='8px JetBrains Mono,monospace'; ctx.textAlign='right';
  ctx.fillText('+$'+maxA.toFixed(0),pad.l-4,pad.t+9);
  ctx.fillText('$0',pad.l-4,mid+3);
  ctx.fillText('-$'+maxA.toFixed(0),pad.l-4,H-pad.b);

  pnls.forEach((p,i) => {
    const x = pad.l+(i/pnls.length)*cw+(cw/pnls.length-bw)/2;
    const bh = Math.abs(p)/maxA*(ch/2);
    const zone = (trades[i]?.zone||'').toLowerCase();
    let c = p>=0 ? (zone==='medium'?'#3b82f6':'#10b981') : '#ef4444';
    ctx.fillStyle=c; ctx.globalAlpha=.85;
    p>=0?ctx.fillRect(x,mid-bh,bw,bh):ctx.fillRect(x,mid,bw,bh);
    ctx.globalAlpha=1;
    if (bh>12) {
      ctx.fillStyle='#0a0a0a'; ctx.font='bold 7px JetBrains Mono,monospace'; ctx.textAlign='center';
      const lbl=(p>=0?'+':'')+p.toFixed(1);
      p>=0?ctx.fillText(lbl,x+bw/2,mid-bh+9):ctx.fillText(lbl,x+bw/2,mid+bh-3);
    }
  });
}

function logCls(l) {
  if (l.includes('✅ WIN')) return 'win';
  if (l.includes('❌ LOSS')) return 'loss';
  if (l.includes('HIGH zone')||l.includes('MEDIUM zone')||l.includes('TRADE')) return 'trade';
  if (l.includes('SKIP')) return 'skip';
  if (l.includes('WARN')||l.includes('⚠️')) return 'warn';
  if (l.includes('STOP')||l.includes('🛑')) return 'stop';
  if (l.includes('===')||l.includes('───')) return 'head';
  if (l.includes('Fetching')||l.includes('BTC:')) return 'info';
  return '';
}

async function update() {
  try {
    const {stats:s, trades, logs} = await fetch('/api/data').then(r=>r.json());
    $('ts').textContent = new Date().toLocaleTimeString();

    // Balance sidebar
    const bn = $('balNum');
    bn.textContent = '$'+s.balance.toFixed(2);
    bn.className = 'bal-num '+(s.session_pnl>=0?'up':'dn');
    const bp = $('balPnl');
    bp.textContent = (s.session_pnl>=0?'+':'')+s.session_pnl.toFixed(2)+' · '+(s.pnl_pct>=0?'+':'')+s.pnl_pct.toFixed(1)+'%';
    bp.className = 'bal-pnl '+(s.session_pnl>=0?'up':'dn');
    $('progBar').style.width = s.progress_pct+'%';
    $('stopBar').style.width = s.stop_pct+'%';
    $('stopPct').textContent = s.stop_pct.toFixed(0)+'%';

    // Stats
    const wr=$('sWR');
    wr.textContent = s.trades>0?s.win_rate+'%':'—';
    wr.style.color = s.win_rate>=70?'var(--g)':s.win_rate>50?'var(--y)':'var(--r)';
    $('sWL').textContent = s.wins+'W / '+s.losses+'L';
    $('sTrades').textContent = s.trades;
    $('sAvgW').textContent = s.avg_win>0?'+$'+s.avg_win.toFixed(2):'—';
    $('sAvgL').textContent = s.avg_loss>0?'-$'+s.avg_loss.toFixed(2):'—';

    // Zone breakdown
    const total = s.trades||1;
    [['high',s.high_w,s.high_l,'var(--g)'],['medium',s.medium_w,s.medium_l,'var(--b)']].forEach(([z,w,l,c])=>{
      $('zb-'+z).style.width = ((w+l)/total*100)+'%';
      const el=$('zw-'+z); el.textContent=w+'/'+l; el.style.color=c;
    });

    // Compounding status — live next bet sizes
    const nextH = (s.balance * 0.25).toFixed(2);
    const nextM = (s.balance * 0.15).toFixed(2);
    const diffH = ((s.balance*0.25)-(100*0.25)).toFixed(2);
    $('nextHigh').textContent = '$'+nextH;
    $('nextMed').textContent  = '$'+nextM;
    $('compoundDiff').textContent = (parseFloat(diffH)>=0?'+':'')+diffH+' vs start';
    $('compoundDiff').style.color = parseFloat(diffH)>=0?'var(--g)':'var(--r)';

    // Extremes
    $('eBest').textContent  = s.best>0?'+$'+s.best.toFixed(2):'—';
    $('eWorst').textContent = s.worst<0?'-$'+Math.abs(s.worst).toFixed(2):'—';
    $('eToken').textContent = s.avg_token>0?'$'+s.avg_token:'—';
    $('eDep').textContent   = '$'+s.total_bet.toFixed(0);

    // Top metrics
    const mp=$('mPnl');
    mp.textContent=(s.session_pnl>=0?'+':'')+s.session_pnl.toFixed(2);
    mp.style.color=s.session_pnl>=0?'var(--g)':'var(--r)';
    $('mPct').textContent=(s.pnl_pct>=0?'+':'')+s.pnl_pct.toFixed(1)+'% from $100';
    const mwr=$('mWR');
    mwr.textContent=s.trades>0?s.win_rate+'%':'—';
    mwr.style.color=s.win_rate>=70?'var(--g)':s.win_rate>50?'var(--y)':'var(--r)';
    $('mWRsub').textContent=s.wins+' wins / '+s.losses+' losses';
    $('mTrades').textContent=s.trades;
    $('mProg').textContent=s.progress_pct.toFixed(1)+'%';
    $('mStop').textContent=s.stop_pct.toFixed(0)+'%';

    // Charts
    $('cBalBadge').textContent=trades.length+' pts';
    $('cDistBadge').textContent=trades.length+' trades';
    drawBal(trades); drawPnl(trades);

    // Table
    $('tBadge').textContent=trades.length+' trades';
    const tb=$('tBody');
    if (!trades.length) {
      tb.innerHTML='<div class="empty"><span>◎</span><span>waiting for first trade…</span></div>';
    } else {
      const rows=[...trades].reverse().slice(0,30).map(t=>{
        const won=t.result===t.direction_bet;
        const pnl=parseFloat(t.pnl_usd)||0;
        const zone=(t.zone||'').toLowerCase();
        const dir=t.direction_bet||'';
        const ts=(t.timestamp||'').slice(11,16);
        const bp=parseFloat(t.bet_pct)||0;
        return '<tr>'+
          '<td style="color:var(--t3)">#'+t.trade_id+'</td>'+
          '<td>'+ts+'</td>'+
          '<td><span class="chip chip-'+(zone||'high')+'">'+zone.toUpperCase()+'</span></td>'+
          '<td><span class="chip chip-'+dir+'">'+dir.toUpperCase()+'</span></td>'+
          '<td>'+(parseFloat(t.token_price)||0).toFixed(3)+'</td>'+
          '<td>$'+(parseFloat(t.bet_usd)||0).toFixed(2)+' <span style="color:var(--t3);font-size:9px">('+bp.toFixed(1)+'%)</span></td>'+
          '<td class="'+(won?'wc':'lc')+'">'+(won?'WIN':'LOSS')+'</td>'+
          '<td class="'+(pnl>=0?'wc':'lc')+'">'+(pnl>=0?'+':'')+pnl.toFixed(2)+'</td>'+
          '<td style="color:var(--t)">$'+(parseFloat(t.balance_after)||0).toFixed(2)+'</td>'+
          '</tr>';
      }).join('');
      tb.innerHTML='<table><thead><tr>'+
        '<th>#</th><th>Time</th><th>Zone</th><th>Dir</th><th>Token</th><th>Bet</th><th>Result</th><th>P&L</th><th>Balance</th>'+
        '</tr></thead><tbody>'+rows+'</tbody></table>';
    }

    // Log
    const lt=$('lterm');
    lt.innerHTML=logs.length
      ?logs.map(l=>'<div class="ll '+logCls(l)+'">'+l.replace(/&/g,'&amp;').replace(/</g,'&lt;')+'</div>').join('')
      :'<div class="ll">waiting for output…</div>';
    lt.scrollTop=lt.scrollHeight;

  } catch(e){
    $('ts').textContent='ERR '+new Date().toLocaleTimeString();
  }
}

update();
setInterval(update, 3000);
window.addEventListener('resize',()=>{clearTimeout(window._rt);window._rt=setTimeout(update,150)});
</script>
</body>
</html>"""

if __name__ == "__main__":
    print(f"BTC Agent Dashboard v4.0 — compatible v1.6")
    print(f"→ http://localhost:{PORT}")
    print(f"  {BTC_CSV} + {AGENT_LOG}")
    print(f"  Ctrl+C to stop\n")
    server = HTTPServer(("localhost", PORT), Handler)
    try: server.serve_forever()
    except KeyboardInterrupt: print("\nStopped.")