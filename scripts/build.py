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

TICKERS: dict[str, str] = {
    "SPY":   "SPDR S&P 500 ETF Trust",
    "VGIAX": "Vanguard Growth Index Admiral",
    "VTIAX": "Vanguard Total Intl Stock Index Admiral",
    "VDE":   "Vanguard Energy ETF",
    "ITA":   "iShares U.S. Aerospace & Defense ETF",
    "VWO":   "Vanguard FTSE Emerging Markets ETF",
}

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_HTML  = REPO_ROOT / "index.html"

# 3-month moving average ~= 63 US trading days
MA_WINDOW = 63


def fetch(symbol: str) -> dict | None:
    """Pull 5y daily history; derive 3m slice and MA."""
    t = yf.Ticker(symbol)
    hist = t.history(period="5y", interval="1d", auto_adjust=True)
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
    for sym, name in TICKERS.items():
        print(f"Fetching {sym} ({name})...")
        data = fetch(sym)
        if data is None:
            continue
        data["name"] = name
        tickers_out[sym] = data
    return {
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "ma_window_days": MA_WINDOW,
        "tickers": tickers_out,
    }


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Ticker Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  :root {
    --bg:#0f1216; --panel:#171b22; --border:#242a33;
    --text:#e7eaee; --muted:#8892a0; --up:#4ade80; --down:#f87171;
    --accent:#60a5fa;
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
  .card {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 16px; margin-bottom: 18px;
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
  .chart { height: 300px; }
  footer { color: var(--muted); font-size: 12px; margin-top: 10px; }
  a { color: var(--accent); }
</style>
</head>
<body>
<header>
  <h1>Ticker Dashboard</h1>
  <div class="sub">
    Daily close with trailing 3-month moving average.
    Data via Yahoo Finance &middot; generated __GENERATED_AT__
  </div>
</header>
<div id="cards"></div>
<footer>Source: Yahoo Finance. Rebuilt daily by GitHub Actions.</footer>

<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
const payload = JSON.parse(document.getElementById("payload").textContent);
const cards = document.getElementById("cards");

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

function renderOne(sym, tk) {
  const card = document.createElement("div");
  card.className = "card";

  const chg3 = tk.change_3m_pct, chg5 = tk.change_5y_pct;
  const cls3 = chg3 >= 0 ? "pos" : "neg";
  const cls5 = chg5 >= 0 ? "pos" : "neg";

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
      <div class="chart" id="c3m_${sym}"></div>
      <div class="chart" id="c5y_${sym}"></div>
    </div>
  `;
  cards.appendChild(card);

  const mkTraces = d => [
    { x: d.dates, y: d.close, name: "Close",      type: "scatter", mode: "lines",
      line: { color: "#60a5fa", width: 1.7 }, hovertemplate: "%{x}<br>Close: $%{y:.2f}<extra></extra>" },
    { x: d.dates, y: d.ma,    name: "3M avg",     type: "scatter", mode: "lines",
      line: { color: "#f59e0b", width: 1.5, dash: "dot" }, hovertemplate: "%{x}<br>3M avg: $%{y:.2f}<extra></extra>" },
  ];

  Plotly.newPlot(`c3m_${sym}`, mkTraces(tk.three_month),
    { ...layoutBase, title: { text: "Last 3 months", font: { size: 13 }, x: 0.01 } },
    { displayModeBar: false, responsive: true });

  Plotly.newPlot(`c5y_${sym}`, mkTraces(tk.five_year),
    { ...layoutBase, title: { text: "Last 5 years",  font: { size: 13 }, x: 0.01 } },
    { displayModeBar: false, responsive: true });
}

for (const [sym, tk] of Object.entries(payload.tickers)) {
  renderOne(sym, tk);
}
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
    print(f"Wrote {OUT_HTML}  ({len(payload['tickers'])} tickers)")


if __name__ == "__main__":
    main()
