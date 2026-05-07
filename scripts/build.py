"""
Fetch price data from Yahoo Finance for a list of tickers and build a
self-contained HTML dashboard (index.html) with two line charts per ticker:
  - Left:  last ~3 months, daily close, with trailing 3-month moving average
  - Right: last 5 years, daily close, with trailing 3-month moving average

Run locally:
    pip install -r requirements.txt
    python scripts/build.py

Output:
    index.html  (committed by the GitHub Actions workflow)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

# (category, [(ticker, display_name), ...])
TICKER_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("US Stock Market", [
        ("VTSAX", "Vanguard Total Stock Market Index Admiral"),
    ]),
    ("US Large Cap Equity", [
        ("SPY",   "SPDR S&P 500 ETF Trust"),
        ("VFIAX", "Vanguard 500 Index Admiral"),
        ("VIGAX", "Vanguard Growth Index Admiral"),
        ("VGIAX", "Vanguard Growth and Income Admiral"),
        ("VLCAX", "Vanguard Large-Cap Index Admiral"),
        ("VVIAX", "Vanguard Value Index Admiral"),
        ("VDADX", "Vanguard Dividend Appreciation Index Admiral"),
        ("VHYAX", "Vanguard High Dividend Yield Index Admiral"),
        ("VFTAX", "Vanguard FTSE Social Index Admiral"),
    ]),
    ("US Mid Cap Equity", [
        ("VEXAX", "Vanguard Extended Market Index Admiral"),
        ("VIMAX", "Vanguard Mid-Cap Index Admiral"),
        ("VMGMX", "Vanguard Mid-Cap Growth Index Admiral"),
        ("VMVAX", "Vanguard Mid-Cap Value Index Admiral"),
    ]),
    ("US Small Cap Equity", [
        ("VSMAX", "Vanguard Small-Cap Index Admiral"),
        ("VSGAX", "Vanguard Small-Cap Growth Index Admiral"),
        ("VSIAX", "Vanguard Small-Cap Value Index Admiral"),
    ]),
    ("International Developed Equity", [
        ("VTMGX", "Vanguard Developed Markets Index Admiral"),
        ("VEUSX", "Vanguard European Stock Index Admiral"),
        ("VFWAX", "Vanguard FTSE All-World ex-US Index Admiral"),
        ("VPADX", "Vanguard Pacific Stock Index Admiral"),
        ("VTIAX", "Vanguard Total International Stock Index Admiral"),
        ("VFSAX", "Vanguard FTSE All-World ex-US Small-Cap Index Admiral"),
        ("VIAAX", "Vanguard International Dividend Appreciation Index Admiral"),
    ]),
    ("Emerging Markets Equity", [
        ("VEMAX", "Vanguard Emerging Markets Stock Index Admiral"),
        ("VWO",   "Vanguard FTSE Emerging Markets ETF"),
    ]),
    ("US Bonds", [
        ("VBTLX", "Vanguard Total Bond Market Index Admiral"),
        ("VBILX", "Vanguard Intermediate-Term Bond Index Admiral"),
        ("VBIRX", "Vanguard Short-Term Bond Index Admiral"),
        ("VBLAX", "Vanguard Long-Term Bond Index Admiral"),
    ]),
    ("US Government Bonds", [
        ("VTAPX", "Vanguard Short-Term Inflation-Protected Securities Idx Admiral"),
    ]),
    ("International Bonds", [
        ("VTABX", "Vanguard Total International Bond Index Admiral"),
    ]),
    ("Real Estate", [
        ("VGRLX", "Vanguard Global ex-US Real Estate Index Admiral"),
        ("VGSLX", "Vanguard Real Estate Index Admiral"),
    ]),
    ("Sector Equity", [
        ("VENAX", "Vanguard Energy Index Admiral"),
        ("VDE",   "Vanguard Energy ETF"),
        ("VFAIX", "Vanguard Financials Index Admiral"),
        ("VHCIX", "Vanguard Health Care Index Admiral"),
        ("VINAX", "Vanguard Industrials Index Admiral"),
        ("ITA",   "iShares U.S. Aerospace & Defense ETF"),
        ("VITAX", "Vanguard Information Technology Index Admiral"),
        ("VMIAX", "Vanguard Materials Index Admiral"),
        ("VTCAX", "Vanguard Communication Services Index Admiral"),
        ("VUIAX", "Vanguard Utilities Index Admiral"),
    ]),
    ("Money Market", [
        ("VMFXX", "Vanguard Federal Money Market"),
    ]),
]

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_HTML  = REPO_ROOT / "index.html"

# 3-month moving average ~= 63 US trading days
MA_WINDOW = 63


def fetch(symbol: str) -> dict | None:
    """Pull 5y daily history; derive 3m slice and MA."""
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="5y", interval="1d", auto_adjust=True)
    except Exception as e:
        print(f"  ERR {symbol}: {e}", file=sys.stderr)
        return None
    if hist.empty:
        print(f"  WARN: no data for {symbol}", file=sys.stderr)
        return None

    close = hist["Close"]
    ma = close.rolling(window=MA_WINDOW, min_periods=1).mean()

    cutoff = close.index.max() - pd.Timedelta(days=95)
    close_3m = close[close.index >= cutoff]
    ma_3m    = ma[ma.index >= cutoff]

    def pack(idx, series_close, series_ma):
        return {
            "dates": [d.strftime("%Y-%m-%d") for d in idx],
            "close": [round(float(v), 4) for v in series_close],
            "ma":    [round(float(v), 4) for v in series_ma],
        }

    return {
        "three_month": pack(close_3m.index, close_3m, ma_3m),
        "five_year":   pack(close.index, close, ma),
        "last_price":  round(float(close.iloc[-1]), 2),
        "last_date":   close.index[-1].strftime("%Y-%m-%d"),
        "change_3m_pct": round(float((close_3m.iloc[-1] / close_3m.iloc[0] - 1) * 100), 2) if len(close_3m) > 1 else 0.0,
        "change_5y_pct": round(float((close.iloc[-1]   / close.iloc[0]   - 1) * 100), 2) if len(close)    > 1 else 0.0,
    }


def build_payload() -> dict:
    tickers_out: dict[str, dict] = {}
    groups_out: list[dict] = []
    for category, items in TICKER_GROUPS:
        cat_tickers: list[str] = []
        for sym, name in items:
            print(f"Fetching {sym} ({name})...")
            data = fetch(sym)
            if data is None:
                continue
            data["name"] = name
            tickers_out[sym] = data
            cat_tickers.append(sym)
        if cat_tickers:
            groups_out.append({"name": category, "tickers": cat_tickers})
    return {
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "ma_window_days": MA_WINDOW,
        "groups": groups_out,
        "tickers": tickers_out,
    }


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Portfolio — Ticker Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  :root {
    --bg:#0f1216; --panel:#171b22; --border:#242a33;
    --text:#e7eaee; --muted:#8892a0; --up:#4ade80; --down:#f87171;
    --accent:#60a5fa; --accent-bg:#1a232f;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 24px;
    font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--text);
  }
  header { margin-bottom: 20px; }
  h1 { margin: 0 0 4px 0; font-size: 22px; font-weight: 600; }
  .sub { color: var(--muted); font-size: 13px; }
  .toc { display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0 24px; }
  .toc a {
    text-decoration: none; color: var(--accent); background: var(--accent-bg);
    padding: 5px 10px; border-radius: 6px; font-size: 12px;
    border: 1px solid var(--border);
  }
  .toc a:hover { background: #243042; }
  .group-head {
    margin: 28px 0 12px; padding-bottom: 6px;
    border-bottom: 1px solid var(--border);
    font-size: 16px; font-weight: 600; color: var(--text);
    display: flex; align-items: baseline; gap: 10px;
  }
  .group-head .count { color: var(--muted); font-size: 12px; font-weight: 400; }
  .card {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 16px; margin-bottom: 14px;
  }
  .card-head {
    display: flex; align-items: baseline; justify-content: space-between;
    margin-bottom: 10px; flex-wrap: wrap; gap: 8px;
  }
  .title-block .sym { font-size: 18px; font-weight: 600; }
  .title-block .nm  { color: var(--muted); font-size: 13px; margin-left: 8px; }
  .stats { display: flex; gap: 20px; font-size: 13px; }
  .stats .k { color: var(--muted); }
  .pos { color: var(--up); } .neg { color: var(--down); }
  .charts { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  @media (max-width: 900px) { .charts { grid-template-columns: 1fr; } }
  .chart { height: 280px; min-height: 280px; }
  .chart.loading {
    display: flex; align-items: center; justify-content: center;
    color: var(--muted); font-size: 12px;
  }
  footer { color: var(--muted); font-size: 12px; margin-top: 30px; }
  a { color: var(--accent); }
</style>
</head>
<body>
<header>
  <h1>Portfolio — Ticker Dashboard</h1>
  <div class="sub">
    Daily close with trailing 3-month moving average.
    Data via Yahoo Finance &middot; generated __GENERATED_AT__
  </div>
  <div id="toc" class="toc"></div>
</header>
<div id="cards"></div>
<footer>Source: Yahoo Finance. Rebuilt daily by GitHub Actions.</footer>

<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
const payload = JSON.parse(document.getElementById("payload").textContent);
const cards = document.getElementById("cards");
const toc   = document.getElementById("toc");

const layoutBase = {
  paper_bgcolor: "#171b22",
  plot_bgcolor:  "#171b22",
  font: { color: "#e7eaee", size: 11 },
  margin: { l: 48, r: 16, t: 28, b: 36 },
  xaxis: { gridcolor: "#242a33", linecolor: "#242a33", zerolinecolor: "#242a33" },
  yaxis: { gridcolor: "#242a33", linecolor: "#242a33", zerolinecolor: "#242a33", tickprefix: "$" },
  legend: { orientation: "h", y: -0.22, x: 0 },
  hovermode: "x unified",
};

function slug(s) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function mkTraces(d) {
  return [
    { x: d.dates, y: d.close, name: "Close", type: "scatter", mode: "lines",
      line: { color: "#60a5fa", width: 1.7 },
      hovertemplate: "%{x}<br>Close: $%{y:.2f}<extra></extra>" },
    { x: d.dates, y: d.ma, name: "3M avg", type: "scatter", mode: "lines",
      line: { color: "#f59e0b", width: 1.5, dash: "dot" },
      hovertemplate: "%{x}<br>3M avg: $%{y:.2f}<extra></extra>" },
  ];
}

function renderCard(sym, tk, container) {
  const card = document.createElement("div");
  card.className = "card";

  const chg3 = tk.change_3m_pct, chg5 = tk.change_5y_pct;
  const cls3 = chg3 >= 0 ? "pos" : "neg";
  const cls5 = chg5 >= 0 ? "pos" : "neg";
  const c3id = `c3m_${sym}`, c5id = `c5y_${sym}`;

  card.innerHTML = `
    <div class="card-head">
      <div class="title-block">
        <span class="sym">${sym}</span><span class="nm">${tk.name}</span>
      </div>
      <div class="stats">
        <div><span class="k">Last</span> $${tk.last_price.toFixed(2)} <span class="k">(${tk.last_date})</span></div>
        <div><span class="k">3M</span> <span class="${cls3}">${chg3 >= 0 ? "+" : ""}${chg3.toFixed(2)}%</span></div>
        <div><span class="k">5Y</span> <span class="${cls5}">${chg5 >= 0 ? "+" : ""}${chg5.toFixed(2)}%</span></div>
      </div>
    </div>
    <div class="charts">
      <div class="chart loading" id="${c3id}" data-sym="${sym}" data-range="three_month">Loading…</div>
      <div class="chart loading" id="${c5id}" data-sym="${sym}" data-range="five_year">Loading…</div>
    </div>
  `;
  container.appendChild(card);
}

// Lazy plot rendering — only kick off Plotly.newPlot when a chart scrolls into view.
const plotted = new Set();
function plotIfNeeded(el) {
  if (plotted.has(el.id)) return;
  plotted.add(el.id);
  const sym = el.dataset.sym;
  const range = el.dataset.range;
  const tk = payload.tickers[sym];
  if (!tk) return;
  const d = tk[range];
  const titleText = range === "three_month" ? "Last 3 months" : "Last 5 years";
  el.classList.remove("loading");
  el.textContent = "";
  Plotly.newPlot(el, mkTraces(d),
    { ...layoutBase, title: { text: titleText, font: { size: 13 }, x: 0.01 } },
    { displayModeBar: false, responsive: true });
}

const observer = new IntersectionObserver((entries) => {
  for (const ent of entries) {
    if (ent.isIntersecting) plotIfNeeded(ent.target);
  }
}, { rootMargin: "200px 0px" });

// Build TOC + groups + cards
for (const grp of payload.groups) {
  const id = "group-" + slug(grp.name);
  const link = document.createElement("a");
  link.href = "#" + id;
  link.textContent = `${grp.name} (${grp.tickers.length})`;
  toc.appendChild(link);

  const head = document.createElement("div");
  head.className = "group-head";
  head.id = id;
  head.innerHTML = `<span>${grp.name}</span><span class="count">${grp.tickers.length} ticker${grp.tickers.length === 1 ? "" : "s"}</span>`;
  cards.appendChild(head);

  for (const sym of grp.tickers) {
    renderCard(sym, payload.tickers[sym], cards);
  }
}

// Wire up the observer to every chart placeholder
for (const el of document.querySelectorAll(".chart")) observer.observe(el);
</script>
</body>
</html>
"""


def render(payload: dict) -> str:
    return (HTML_TEMPLATE
            .replace("__GENERATED_AT__", payload["generated_at"])
            .replace("__PAYLOAD__", json.dumps(payload, separators=(",", ":"))))


def main():
    payload = build_payload()
    if not payload["tickers"]:
        print("ERROR: no ticker data fetched", file=sys.stderr)
        sys.exit(1)
    OUT_HTML.write_text(render(payload), encoding="utf-8")
    print(f"Wrote {OUT_HTML}  ({len(payload['tickers'])} tickers across {len(payload['groups'])} groups)")


if __name__ == "__main__":
    main()
