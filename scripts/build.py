"""
Fetch price data from Yahoo Finance for a list of tickers and build a
self-contained HTML dashboard (index.html) with two tabs:

  Charts:     two line charts per ticker
              - left:  last ~3 months, daily close + 3-month moving average
              - right: last 5 years, daily close + 3-month moving average

  Allocation: table by category with expense ratio, YTD/1Y/5Y/10Y returns,
              and target % allocation (per the Guideline snapshot).

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

# Per-fund target allocation % from the Guideline custom-portfolio snapshot.
# Tickers not in this dict default to 0%. Sum across all funds = 100%.
FUND_ALLOCATION_PCT: dict[str, float] = {
    "VIGAX": 20,   # US Large Cap Equity
    "VVIAX": 30,   # US Large Cap Equity
    "VEUSX": 10,   # International Developed Equity
    "VEMAX": 10,   # Emerging Markets Equity
    "VBTLX": 10,   # US Bonds
    "VENAX": 10,   # Sector Equity
    "VINAX": 10,   # Sector Equity
}

# Expense ratio % by ticker (from the Guideline snapshot; ETFs added from prospectuses).
EXPENSE_RATIO: dict[str, float] = {
    "VTSAX": 0.04,
    "SPY":   0.09, "VFIAX": 0.04, "VIGAX": 0.05, "VGIAX": 0.23,
    "VLCAX": 0.05, "VVIAX": 0.05, "VDADX": 0.07, "VHYAX": 0.08, "VFTAX": 0.11,
    "VEXAX": 0.05, "VIMAX": 0.05, "VMGMX": 0.07, "VMVAX": 0.07,
    "VSMAX": 0.05, "VSGAX": 0.07, "VSIAX": 0.07,
    "VTMGX": 0.05, "VEUSX": 0.08, "VFWAX": 0.08, "VPADX": 0.09,
    "VTIAX": 0.09, "VFSAX": 0.16, "VIAAX": 0.16,
    "VEMAX": 0.13, "VWO":   0.07,
    "VBTLX": 0.04, "VBILX": 0.06, "VBIRX": 0.06, "VBLAX": 0.06,
    "VTAPX": 0.06, "VTABX": 0.10,
    "VGRLX": 0.12, "VGSLX": 0.13,
    "VENAX": 0.09, "VDE":   0.09, "VFAIX": 0.09, "VHCIX": 0.09, "VINAX": 0.09,
    "ITA":   0.40, "VITAX": 0.09, "VMIAX": 0.09, "VTCAX": 0.09, "VUIAX": 0.09,
    "VMFXX": 0.11,
}

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_HTML  = REPO_ROOT / "index.html"

# 3-month moving average ~= 63 US trading days
MA_WINDOW = 63


def _pct_change_from_n_days(close: pd.Series, days: int) -> float | None:
    """% change from the closing price ~n calendar days ago to the latest close."""
    if len(close) < 2:
        return None
    cutoff = close.index.max() - pd.Timedelta(days=days)
    older = close[close.index <= cutoff]
    if older.empty:
        return None
    return float((close.iloc[-1] / older.iloc[-1] - 1) * 100)


def _ytd_pct(close: pd.Series) -> float | None:
    """% change from first trading day of the current year to the latest close."""
    if close.empty:
        return None
    year = close.index.max().year
    yrs = close[close.index.year == year]
    if len(yrs) < 2:
        return None
    return float((yrs.iloc[-1] / yrs.iloc[0] - 1) * 100)


def fetch(symbol: str) -> dict | None:
    """Pull 10y daily history; derive 5y/3m chart slices, MA, and return windows."""
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="10y", interval="1d", auto_adjust=True)
    except Exception as e:
        print(f"  ERR {symbol}: {e}", file=sys.stderr)
        return None
    if hist.empty:
        print(f"  WARN: no data for {symbol}", file=sys.stderr)
        return None

    close = hist["Close"]
    ma = close.rolling(window=MA_WINDOW, min_periods=1).mean()

    # 5-year slice for the right-side chart
    cutoff_5y = close.index.max() - pd.Timedelta(days=365 * 5 + 5)
    close_5y = close[close.index >= cutoff_5y]
    ma_5y    = ma[ma.index    >= cutoff_5y]

    # 3-month slice for the left-side chart
    cutoff_3m = close.index.max() - pd.Timedelta(days=95)
    close_3m = close[close.index >= cutoff_3m]
    ma_3m    = ma[ma.index    >= cutoff_3m]

    def pack(idx, c, m):
        return {
            "dates": [d.strftime("%Y-%m-%d") for d in idx],
            "close": [round(float(v), 4) for v in c],
            "ma":    [round(float(v), 4) for v in m],
        }

    def maybe(v):
        return None if v is None else round(v, 2)

    return {
        "three_month": pack(close_3m.index, close_3m, ma_3m),
        "five_year":   pack(close_5y.index, close_5y, ma_5y),
        "last_price":  round(float(close.iloc[-1]), 2),
        "last_date":   close.index[-1].strftime("%Y-%m-%d"),
        "change_3m_pct": round(float((close_3m.iloc[-1] / close_3m.iloc[0] - 1) * 100), 2) if len(close_3m) > 1 else None,
        "change_5y_pct": round(float((close_5y.iloc[-1] / close_5y.iloc[0] - 1) * 100), 2) if len(close_5y) > 1 else None,
        "m1_pct":  maybe(_pct_change_from_n_days(close,  30)),
        "m3_pct":  maybe(_pct_change_from_n_days(close,  91)),
        "m6_pct":  maybe(_pct_change_from_n_days(close, 182)),
        "y1_pct":  maybe(_pct_change_from_n_days(close,  365)),
        "y5_pct":  maybe(_pct_change_from_n_days(close,  365 * 5)),
    }


def build_payload() -> dict:
    tickers_out: dict[str, dict] = {}
    groups_out: list[dict] = []
    for category, items in TICKER_GROUPS:
        cat_tickers: list[str] = []
        cat_alloc = 0.0
        for sym, name in items:
            print(f"Fetching {sym} ({name})...")
            data = fetch(sym)
            if data is None:
                continue
            data["name"] = name
            data["expense_ratio"] = EXPENSE_RATIO.get(sym)
            data["allocation_pct"] = FUND_ALLOCATION_PCT.get(sym, 0)
            tickers_out[sym] = data
            cat_tickers.append(sym)
            cat_alloc += data["allocation_pct"]
        if cat_tickers:
            groups_out.append({
                "name": category,
                "allocation_pct": cat_alloc,
                "tickers": cat_tickers,
            })
    return {
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "ma_window_days": MA_WINDOW,
        "groups": groups_out,
        "tickers": tickers_out,
        "total_allocation": sum(t.get("allocation_pct", 0) for t in tickers_out.values()),
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
  header { margin-bottom: 12px; }
  h1 { margin: 0 0 4px 0; font-size: 22px; font-weight: 600; }
  .sub { color: var(--muted); font-size: 13px; }

  /* tab bar */
  .tabs { display: flex; gap: 4px; margin: 16px 0 18px; border-bottom: 1px solid var(--border); }
  .tab {
    background: transparent; color: var(--muted); border: 0; cursor: pointer;
    padding: 10px 16px; font-size: 14px; font-weight: 500;
    border-bottom: 2px solid transparent; margin-bottom: -1px;
  }
  .tab:hover { color: var(--text); }
  .tab.active { color: var(--accent); border-bottom-color: var(--accent); }
  .view { display: none; }
  .view.active { display: block; }

  /* TOC pills (charts view) */
  .toc { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 24px; }
  .toc a {
    text-decoration: none; color: var(--accent); background: var(--accent-bg);
    padding: 5px 10px; border-radius: 6px; font-size: 12px; border: 1px solid var(--border);
  }
  .toc a:hover { background: #243042; }

  /* group head (charts view) */
  .group-head {
    margin: 28px 0 12px; padding-bottom: 6px; border-bottom: 1px solid var(--border);
    font-size: 16px; font-weight: 600; color: var(--text);
    display: flex; align-items: baseline; gap: 10px;
  }
  .group-head .count { color: var(--muted); font-size: 12px; font-weight: 400; }

  /* ticker card (charts view) */
  .card {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 16px; margin-bottom: 14px;
  }
  .card-head {
    display: flex; align-items: baseline; justify-content: space-between;
    margin-bottom: 10px; flex-wrap: wrap; gap: 8px;
  }
  .title-block .sym { font-size: 18px; font-weight: 600; color: var(--text); text-decoration: none; }
  .title-block a.sym:hover { color: var(--accent); text-decoration: underline; }
  .title-block .nm  { color: var(--muted); font-size: 13px; margin-left: 8px; }
  .stats { display: flex; gap: 20px; font-size: 13px; }
  .stats .k { color: var(--muted); }
  .pos { color: var(--up); } .neg { color: var(--down); }
  .charts { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  @media (max-width: 900px) { .charts { grid-template-columns: 1fr; } }
  .chart { height: 280px; min-height: 280px; }
  .chart.loading {
    display: flex; align-items: center; justify-content: center; color: var(--muted); font-size: 12px;
  }

  /* filter bar (performance view) */
  .filters {
    display: flex; gap: 14px; align-items: flex-end; flex-wrap: wrap;
    margin: 0 0 14px; padding: 12px 14px; background: var(--panel);
    border: 1px solid var(--border); border-radius: 10px;
  }
  .filter-group { display: flex; flex-direction: column; gap: 4px; }
  .filter-group label {
    color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
  }
  .filter-group select, .filter-group input {
    background: var(--bg); color: var(--text); border: 1px solid var(--border);
    border-radius: 6px; padding: 7px 9px; font: inherit;
  }
  .filter-group select { min-width: 180px; }
  .filter-group input  { width: 90px; }
  .filter-group select:focus, .filter-group input:focus {
    outline: none; border-color: var(--accent);
  }
  .reset-btn {
    background: transparent; color: var(--muted); border: 1px solid var(--border);
    border-radius: 6px; padding: 7px 14px; cursor: pointer;
    font: inherit;
  }
  .reset-btn:hover { color: var(--text); border-color: var(--text); }
  .alloc-status { color: var(--muted); font-size: 12px; margin: 0 4px 8px; }

  /* allocation table (performance view) */
  table.alloc { width: 100%; border-collapse: collapse; font-size: 14px; }
  table.alloc th, table.alloc td {
    padding: 12px 12px; text-align: left; border-bottom: 1px solid var(--border);
  }
  table.alloc thead th {
    color: var(--muted); font-weight: 500; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.06em;
    cursor: pointer; user-select: none; white-space: nowrap;
    position: sticky; top: 0; background: var(--bg); z-index: 1;
  }
  table.alloc thead th:hover { color: var(--text); }
  table.alloc thead th.num-h { text-align: right; }
  table.alloc thead th .arr {
    display: inline-block; width: 12px; opacity: 0.4; margin-left: 4px;
  }
  table.alloc thead th.sort-asc .arr,
  table.alloc thead th.sort-desc .arr {
    opacity: 1; color: var(--accent);
  }
  table.alloc td.cat { color: var(--muted); font-size: 12px; white-space: nowrap; }
  table.alloc td.fund .sym {
    font-weight: 700; font-size: 15px; display: block;
    color: var(--text); text-decoration: none;
  }
  table.alloc td.fund a.sym:hover { color: var(--accent); text-decoration: underline; }
  table.alloc td.fund .nm  { color: var(--muted); font-size: 12px; display: block; margin-top: 2px; }
  table.alloc td.num { text-align: right; font-variant-numeric: tabular-nums; }
  table.alloc tbody tr:hover { background: #1a1f27; }

  .total-row {
    display: flex; justify-content: space-between; align-items: baseline;
    margin-top: 28px; padding: 12px 14px; background: var(--panel);
    border: 1px solid var(--border); border-radius: 10px;
  }
  .total-row .label { font-weight: 600; }
  .total-row .value { font-size: 18px; font-weight: 600; color: var(--accent); }

  footer { color: var(--muted); font-size: 12px; margin-top: 30px; }
  a { color: var(--accent); }

  /* in-page modal for ticker pages */
  .modal { position: fixed; inset: 0; z-index: 1000; }
  .modal.hidden { display: none; }
  .modal-bg { position: absolute; inset: 0; background: rgba(0,0,0,0.72); }
  .modal-dialog {
    position: relative; margin: 4vh auto; width: min(1200px, 94vw); height: 88vh;
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    display: flex; flex-direction: column; overflow: hidden;
    box-shadow: 0 20px 60px rgba(0,0,0,0.5);
  }
  .modal-head {
    display: flex; align-items: center; gap: 14px; padding: 10px 14px;
    border-bottom: 1px solid var(--border); flex-shrink: 0;
  }
  .modal-head #modal-title { font-weight: 600; flex: 1; font-size: 14px; }
  .modal-head a.modal-newtab,
  .modal-head button.modal-close {
    color: var(--accent); background: transparent; border: 0; cursor: pointer;
    font: inherit; text-decoration: none; padding: 4px 8px; border-radius: 6px;
  }
  .modal-head a.modal-newtab:hover,
  .modal-head button.modal-close:hover { background: var(--accent-bg); }
  .modal-head button.modal-close { font-size: 22px; line-height: 1; padding: 0 10px; }
  .modal-body { flex: 1; min-height: 0; padding: 16px 18px; overflow-y: auto; }
  .stats-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 10px; margin-bottom: 16px;
  }
  .stat-tile {
    background: var(--bg); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 12px;
  }
  .stat-tile .lbl { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; }
  .stat-tile .val { font-size: 16px; font-weight: 600; margin-top: 2px; font-variant-numeric: tabular-nums; }
  .modal-chart { height: 320px; margin-bottom: 16px; }
  .modal-links { display: flex; gap: 12px; flex-wrap: wrap; padding-top: 12px; border-top: 1px solid var(--border); margin-top: 8px; }
  .modal-links a {
    color: var(--accent); text-decoration: none; font-size: 13px;
    padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px;
  }
  .modal-links a:hover { background: var(--accent-bg); }
</style>
</head>
<body>
<header>
  <h1>Portfolio — Ticker Dashboard</h1>
  <div class="sub">
    Daily close + 3-month moving average. Returns are computed from Yahoo Finance closing prices;
    expense ratios and target allocations are from your Guideline snapshot.
    Generated __GENERATED_AT__
  </div>
</header>

<div class="tabs">
  <button class="tab active" data-target="view-charts">Charts</button>
  <button class="tab" data-target="view-alloc">Performance</button>
</div>

<div id="view-charts" class="view active">
  <div id="toc" class="toc"></div>
  <div id="cards"></div>
</div>

<div id="view-alloc" class="view">
  <div id="alloc-filters" class="filters"></div>
  <div id="alloc-status" class="alloc-status"></div>
  <div id="alloc"></div>
  <div class="total-row">
    <span class="label">Total Allocation</span>
    <span class="value" id="totalAlloc">—</span>
  </div>
</div>

<footer>Source: Yahoo Finance. Rebuilt daily by GitHub Actions.</footer>

<!-- In-page modal: detail view rendered from local data (works for all tickers) -->
<div id="modal" class="modal hidden" aria-hidden="true">
  <div class="modal-bg"></div>
  <div class="modal-dialog" role="dialog" aria-labelledby="modal-title">
    <div class="modal-head">
      <span id="modal-title">—</span>
      <button class="modal-close" id="modal-close" type="button" aria-label="Close">×</button>
    </div>
    <div id="modal-body" class="modal-body"></div>
  </div>
</div>

<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
const payload = JSON.parse(document.getElementById("payload").textContent);

/* ---------- in-page ticker modal (rendered from local data) ---------- */
const modalEl    = document.getElementById("modal");
const modalBody  = document.getElementById("modal-body");
const modalTitle = document.getElementById("modal-title");

function fmtSignedPct(v) {
  if (v == null) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function tile(label, value, cls = "") {
  return `<div class="stat-tile">
    <div class="lbl">${label}</div>
    <div class="val ${cls}">${value}</div>
  </div>`;
}

function modalChartLayout(title) {
  return {
    paper_bgcolor: "#171b22", plot_bgcolor: "#171b22",
    font: { color: "#e7eaee", size: 11 },
    margin: { l: 56, r: 18, t: 30, b: 36 },
    xaxis: { gridcolor: "#242a33", linecolor: "#242a33", zerolinecolor: "#242a33" },
    yaxis: { gridcolor: "#242a33", linecolor: "#242a33", zerolinecolor: "#242a33", tickprefix: "$" },
    legend: { orientation: "h", y: -0.18, x: 0 },
    hovermode: "x unified",
    title: { text: title, font: { size: 14 }, x: 0.01 },
  };
}

function openTickerModal(sym /* string */) {
  const tk = payload.tickers[sym];
  if (!tk) return;
  const name = tk.name || "";
  modalTitle.textContent = `${sym} — ${name}`;

  // External links — multiple sources, user can pick whichever works for this ticker.
  const links = [
    ["Yahoo Finance",  `https://finance.yahoo.com/quote/${sym}/`],
    ["Stockanalysis",  `https://stockanalysis.com/quote/${sym}/`],
    ["TradingView",    `https://www.tradingview.com/symbols/${sym}/`],
    ["Google Finance", `https://www.google.com/finance/quote/${sym}`],
    ["Morningstar",    `https://www.morningstar.com/funds/xnas/${sym}/quote`],
  ];

  modalBody.innerHTML = `
    <div class="stats-grid">
      ${tile("Last Price",    `$${tk.last_price.toFixed(2)}`)}
      ${tile("As of",         tk.last_date)}
      ${tile("Expense Ratio", tk.expense_ratio == null ? "—" : `${tk.expense_ratio.toFixed(2)}%`)}
      ${tile("1-mo Return",   fmtSignedPct(tk.m1_pct), pctClass(tk.m1_pct))}
      ${tile("3-mo Return",   fmtSignedPct(tk.m3_pct), pctClass(tk.m3_pct))}
      ${tile("6-mo Return",   fmtSignedPct(tk.m6_pct), pctClass(tk.m6_pct))}
      ${tile("1-yr Return",   fmtSignedPct(tk.y1_pct), pctClass(tk.y1_pct))}
      ${tile("5-yr Return",   fmtSignedPct(tk.y5_pct), pctClass(tk.y5_pct))}
    </div>
    <div id="modal-chart-5y" class="modal-chart"></div>
    <div id="modal-chart-3m" class="modal-chart"></div>
    <div class="modal-links">
      <span style="color:var(--muted); font-size:12px; align-self:center;">View on:</span>
      ${links.map(([lbl, url]) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${lbl} ↗</a>`).join("")}
    </div>
  `;

  // Render charts (uses Plotly which is already loaded for the Charts tab)
  const c5 = document.getElementById("modal-chart-5y");
  const c3 = document.getElementById("modal-chart-3m");
  Plotly.newPlot(c5, mkTraces(tk.five_year),   modalChartLayout("Last 5 years"),  { displayModeBar: false, responsive: true });
  Plotly.newPlot(c3, mkTraces(tk.three_month), modalChartLayout("Last 3 months"), { displayModeBar: false, responsive: true });

  modalEl.classList.remove("hidden");
  modalEl.setAttribute("aria-hidden", "false");
}

function closeTickerModal() {
  modalEl.classList.add("hidden");
  modalEl.setAttribute("aria-hidden", "true");
  modalBody.innerHTML = "";
}

document.getElementById("modal-close").addEventListener("click", closeTickerModal);
document.querySelector(".modal-bg").addEventListener("click", closeTickerModal);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !modalEl.classList.contains("hidden")) closeTickerModal();
});

// Delegate clicks on any ticker link (a.sym) anywhere on the page.
document.body.addEventListener("click", (e) => {
  const a = e.target.closest("a.sym");
  if (!a) return;
  e.preventDefault();
  openTickerModal(a.textContent.trim());
});

/* ---------- tab switching ---------- */
for (const btn of document.querySelectorAll(".tab")) {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(b => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".view").forEach(v => v.classList.toggle("active", v.id === btn.dataset.target));
    // make sure charts that became visible get plotted
    if (btn.dataset.target === "view-charts") {
      requestAnimationFrame(() => {
        for (const el of document.querySelectorAll(".chart")) observer.observe(el);
      });
    }
  });
}

/* ---------- charts view ---------- */
const cards = document.getElementById("cards");
const toc   = document.getElementById("toc");

const layoutBase = {
  paper_bgcolor: "#171b22", plot_bgcolor: "#171b22",
  font: { color: "#e7eaee", size: 11 },
  margin: { l: 48, r: 16, t: 28, b: 36 },
  xaxis: { gridcolor: "#242a33", linecolor: "#242a33", zerolinecolor: "#242a33" },
  yaxis: { gridcolor: "#242a33", linecolor: "#242a33", zerolinecolor: "#242a33", tickprefix: "$" },
  legend: { orientation: "h", y: -0.22, x: 0 },
  hovermode: "x unified",
};

function slug(s) { return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""); }

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

function fmtPct(v, withPlus = true) {
  if (v == null) return "—";
  const sign = v >= 0 && withPlus ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}
function pctClass(v) { return v == null ? "" : (v >= 0 ? "pos" : "neg"); }

function renderCard(sym, tk, container) {
  const card = document.createElement("div");
  card.className = "card";
  const c3id = `c3m_${sym}`, c5id = `c5y_${sym}`;
  card.innerHTML = `
    <div class="card-head">
      <div class="title-block">
        <a class="sym" href="https://finance.yahoo.com/quote/${sym}/" data-name="${tk.name}" target="_blank" rel="noopener noreferrer">${sym}</a><span class="nm">${tk.name}</span>
      </div>
      <div class="stats">
        <div><span class="k">Last</span> $${tk.last_price.toFixed(2)} <span class="k">(${tk.last_date})</span></div>
        <div><span class="k">3M</span> <span class="${pctClass(tk.change_3m_pct)}">${fmtPct(tk.change_3m_pct)}</span></div>
        <div><span class="k">5Y</span> <span class="${pctClass(tk.change_5y_pct)}">${fmtPct(tk.change_5y_pct)}</span></div>
      </div>
    </div>
    <div class="charts">
      <div class="chart loading" id="${c3id}" data-sym="${sym}" data-range="three_month">Loading…</div>
      <div class="chart loading" id="${c5id}" data-sym="${sym}" data-range="five_year">Loading…</div>
    </div>`;
  container.appendChild(card);
}

const plotted = new Set();
function plotIfNeeded(el) {
  if (plotted.has(el.id)) return;
  plotted.add(el.id);
  const tk = payload.tickers[el.dataset.sym];
  if (!tk) return;
  const d = tk[el.dataset.range];
  const titleText = el.dataset.range === "three_month" ? "Last 3 months" : "Last 5 years";
  el.classList.remove("loading"); el.textContent = "";
  Plotly.newPlot(el, mkTraces(d),
    { ...layoutBase, title: { text: titleText, font: { size: 13 }, x: 0.01 } },
    { displayModeBar: false, responsive: true });
}

const observer = new IntersectionObserver((entries) => {
  for (const ent of entries) if (ent.isIntersecting) plotIfNeeded(ent.target);
}, { rootMargin: "200px 0px" });

for (const grp of payload.groups) {
  const id = "group-" + slug(grp.name);
  const link = document.createElement("a");
  link.href = "#" + id;
  link.textContent = `${grp.name} (${grp.tickers.length})`;
  toc.appendChild(link);

  const head = document.createElement("div");
  head.className = "group-head"; head.id = id;
  head.innerHTML = `<span>${grp.name}</span><span class="count">${grp.tickers.length} ticker${grp.tickers.length === 1 ? "" : "s"}</span>`;
  cards.appendChild(head);

  for (const sym of grp.tickers) renderCard(sym, payload.tickers[sym], cards);
}
for (const el of document.querySelectorAll(".chart")) observer.observe(el);

/* ---------- allocation view: single sortable table ---------- */
const alloc = document.getElementById("alloc");

function fmtER(v)   { return v == null ? "—" : `${v.toFixed(2)}%`; }
function fmtRet(v)  { return v == null ? "—" : `${v.toFixed(2)}%`; }

// Flatten all tickers into rows with their category attached.
// Default order = the order categories appear in payload.groups.
const allocRows = [];
let categoryOrder = 0;
for (const grp of payload.groups) {
  for (const sym of grp.tickers) {
    const tk = payload.tickers[sym];
    allocRows.push({
      sym, name: tk.name,
      category: grp.name,
      _category_ord: categoryOrder,
      expense_ratio: tk.expense_ratio,
      m1_pct: tk.m1_pct, m3_pct: tk.m3_pct, m6_pct: tk.m6_pct,
      y1_pct: tk.y1_pct, y5_pct: tk.y5_pct,
    });
  }
  categoryOrder++;
}

// Columns: { key, label, type, align, default_dir }
const ALLOC_COLS = [
  { key: "_category_ord", label: "Category",      type: "cat",  cls: "cat",  alignR: false, defaultDesc: false, sortKey: "_category_ord" },
  { key: "sym",           label: "Fund Name",     type: "fund", cls: "fund", alignR: false, defaultDesc: false, sortKey: "sym" },
  { key: "expense_ratio", label: "Expense Ratio", type: "num",  cls: "num",  alignR: true,  defaultDesc: false, sortKey: "expense_ratio" },
  { key: "m1_pct",        label: "1-mo",          type: "ret",  cls: "num",  alignR: true,  defaultDesc: true,  sortKey: "m1_pct" },
  { key: "m3_pct",        label: "3-mo",          type: "ret",  cls: "num",  alignR: true,  defaultDesc: true,  sortKey: "m3_pct" },
  { key: "m6_pct",        label: "6-mo",          type: "ret",  cls: "num",  alignR: true,  defaultDesc: true,  sortKey: "m6_pct" },
  { key: "y1_pct",        label: "1-yr",          type: "ret",  cls: "num",  alignR: true,  defaultDesc: true,  sortKey: "y1_pct" },
  { key: "y5_pct",        label: "5-yr",          type: "ret",  cls: "num",  alignR: true,  defaultDesc: true,  sortKey: "y5_pct" },
];

let sortKey = "_category_ord";   // default: keep category grouping
let sortDir = "asc";

// filter state
let fltSearch = "";
let fltSector = "";
let fltPeriod = "y1_pct";
let fltMin    = null;
let fltMax    = null;
let fltErMin  = null;
let fltErMax  = null;

const PERIOD_LABELS = {
  m1_pct: "1-mo", m3_pct: "3-mo", m6_pct: "6-mo",
  y1_pct: "1-yr", y5_pct: "5-yr",
};

function filteredRows() {
  const q = fltSearch.trim().toLowerCase();
  return allocRows.filter(r => {
    if (q) {
      const hay = `${r.sym} ${r.name} ${r.category}`.toLowerCase();
      // every whitespace-separated term must appear
      for (const term of q.split(/\s+/)) {
        if (!hay.includes(term)) return false;
      }
    }
    if (fltSector && r.category !== fltSector) return false;
    if (fltMin !== null || fltMax !== null) {
      const v = r[fltPeriod];
      if (v == null) return false;
      if (fltMin !== null && v < fltMin) return false;
      if (fltMax !== null && v > fltMax) return false;
    }
    if (fltErMin !== null || fltErMax !== null) {
      const v = r.expense_ratio;
      if (v == null) return false;
      if (fltErMin !== null && v < fltErMin) return false;
      if (fltErMax !== null && v > fltErMax) return false;
    }
    return true;
  });
}

function sortedRows() {
  const dirMul = sortDir === "asc" ? 1 : -1;
  const k = sortKey;
  const arr = filteredRows();
  arr.sort((a, b) => {
    const av = a[k], bv = b[k];
    // nulls always sort last regardless of direction
    const aN = av == null, bN = bv == null;
    if (aN && bN) return 0;
    if (aN) return 1;
    if (bN) return -1;
    let cmp;
    if (typeof av === "string") cmp = av.localeCompare(bv);
    else cmp = av - bv;
    if (cmp !== 0) return cmp * dirMul;
    // tiebreak: when sorting by category keep alphabetic by symbol
    return a.sym.localeCompare(b.sym);
  });
  return arr;
}

/* ---------- filter UI ---------- */
function buildFilterUI() {
  const sectorOpts = `<option value="">All sectors</option>` +
    payload.groups.map(g => `<option value="${g.name}">${g.name}</option>`).join("");
  const periodOpts = Object.entries(PERIOD_LABELS)
    .map(([k, label]) => `<option value="${k}"${k === fltPeriod ? " selected" : ""}>${label} return</option>`)
    .join("");

  const bar = document.getElementById("alloc-filters");
  bar.innerHTML = `
    <div class="filter-group" style="flex: 1; min-width: 220px;">
      <label for="flt-search">Search</label>
      <input id="flt-search" type="search" placeholder="ticker, fund name, or keyword" style="width: 100%;">
    </div>
    <div class="filter-group">
      <label for="flt-sector">Sector</label>
      <select id="flt-sector">${sectorOpts}</select>
    </div>
    <div class="filter-group">
      <label for="flt-period">Return period</label>
      <select id="flt-period">${periodOpts}</select>
    </div>
    <div class="filter-group">
      <label for="flt-min">Return Min %</label>
      <input id="flt-min" type="number" step="0.1" placeholder="any">
    </div>
    <div class="filter-group">
      <label for="flt-max">Return Max %</label>
      <input id="flt-max" type="number" step="0.1" placeholder="any">
    </div>
    <div class="filter-group">
      <label for="flt-er-min">Expense Min %</label>
      <input id="flt-er-min" type="number" step="0.01" placeholder="any">
    </div>
    <div class="filter-group">
      <label for="flt-er-max">Expense Max %</label>
      <input id="flt-er-max" type="number" step="0.01" placeholder="any">
    </div>
    <button id="flt-reset" class="reset-btn" type="button">Reset</button>
  `;

  document.getElementById("flt-search").addEventListener("input", (e) => {
    fltSearch = e.target.value; renderAllocTable();
  });
  document.getElementById("flt-sector").addEventListener("change", (e) => {
    fltSector = e.target.value; renderAllocTable();
  });
  document.getElementById("flt-period").addEventListener("change", (e) => {
    fltPeriod = e.target.value; renderAllocTable();
  });
  const onMinMax = () => {
    const mn = document.getElementById("flt-min").value.trim();
    const mx = document.getElementById("flt-max").value.trim();
    fltMin = mn === "" ? null : parseFloat(mn);
    fltMax = mx === "" ? null : parseFloat(mx);
    renderAllocTable();
  };
  const onErMinMax = () => {
    const mn = document.getElementById("flt-er-min").value.trim();
    const mx = document.getElementById("flt-er-max").value.trim();
    fltErMin = mn === "" ? null : parseFloat(mn);
    fltErMax = mx === "" ? null : parseFloat(mx);
    renderAllocTable();
  };
  document.getElementById("flt-min").addEventListener("input", onMinMax);
  document.getElementById("flt-max").addEventListener("input", onMinMax);
  document.getElementById("flt-er-min").addEventListener("input", onErMinMax);
  document.getElementById("flt-er-max").addEventListener("input", onErMinMax);
  document.getElementById("flt-reset").addEventListener("click", () => {
    fltSearch = ""; fltSector = ""; fltPeriod = "y1_pct";
    fltMin = null; fltMax = null;
    fltErMin = null; fltErMax = null;
    document.getElementById("flt-search").value = "";
    document.getElementById("flt-sector").value = "";
    document.getElementById("flt-period").value = "y1_pct";
    document.getElementById("flt-min").value = "";
    document.getElementById("flt-max").value = "";
    document.getElementById("flt-er-min").value = "";
    document.getElementById("flt-er-max").value = "";
    renderAllocTable();
  });
}

function updateAllocStatus(shown, total) {
  const status = document.getElementById("alloc-status");
  const filtersActive = fltSearch !== "" || fltSector !== "" || fltMin !== null || fltMax !== null
                        || fltErMin !== null || fltErMax !== null;
  if (!filtersActive) {
    status.textContent = `${total} fund${total === 1 ? "" : "s"}`;
  } else {
    const parts = [];
    if (fltSearch) parts.push(`search: "${fltSearch}"`);
    if (fltSector) parts.push(`sector: ${fltSector}`);
    if (fltMin !== null || fltMax !== null) {
      const lbl = PERIOD_LABELS[fltPeriod];
      const lo = fltMin !== null ? `${fltMin}%` : "any";
      const hi = fltMax !== null ? `${fltMax}%` : "any";
      parts.push(`${lbl} return ${lo}–${hi}`);
    }
    if (fltErMin !== null || fltErMax !== null) {
      const lo = fltErMin !== null ? `${fltErMin}%` : "any";
      const hi = fltErMax !== null ? `${fltErMax}%` : "any";
      parts.push(`expense ${lo}–${hi}`);
    }
    status.textContent = `Showing ${shown} of ${total} funds — filters: ${parts.join(", ")}`;
  }
}

function renderAllocTable() {
  const rows = sortedRows();
  updateAllocStatus(rows.length, allocRows.length);

  const thead = `
    <thead>
      <tr>
        ${ALLOC_COLS.map(c => {
          const sortCls = c.sortKey === sortKey ? (sortDir === "asc" ? "sort-asc" : "sort-desc") : "";
          const arr = c.sortKey === sortKey ? (sortDir === "asc" ? "▲" : "▼") : "";
          const align = c.alignR ? " num-h" : "";
          return `<th class="${align}${sortCls ? " " + sortCls : ""}" data-sort="${c.sortKey}">${c.label}<span class="arr">${arr}</span></th>`;
        }).join("")}
      </tr>
    </thead>`;

  const tbody = `
    <tbody>
      ${rows.map(r => `
        <tr>
          <td class="cat">${r.category}</td>
          <td class="fund"><a class="sym" href="https://finance.yahoo.com/quote/${r.sym}/" data-name="${r.name}" target="_blank" rel="noopener noreferrer">${r.sym}</a><span class="nm">${r.name}</span></td>
          <td class="num">${fmtER(r.expense_ratio)}</td>
          <td class="num ${pctClass(r.m1_pct)}">${fmtRet(r.m1_pct)}</td>
          <td class="num ${pctClass(r.m3_pct)}">${fmtRet(r.m3_pct)}</td>
          <td class="num ${pctClass(r.m6_pct)}">${fmtRet(r.m6_pct)}</td>
          <td class="num ${pctClass(r.y1_pct)}">${fmtRet(r.y1_pct)}</td>
          <td class="num ${pctClass(r.y5_pct)}">${fmtRet(r.y5_pct)}</td>
        </tr>`).join("")}
    </tbody>`;

  alloc.innerHTML = `<table class="alloc">${thead}${tbody}</table>`;

  // Wire up header clicks
  for (const th of alloc.querySelectorAll("thead th")) {
    th.addEventListener("click", () => {
      const k = th.dataset.sort;
      const col = ALLOC_COLS.find(c => c.sortKey === k);
      if (sortKey === k) {
        sortDir = sortDir === "asc" ? "desc" : "asc";
      } else {
        sortKey = k;
        sortDir = col.defaultDesc ? "desc" : "asc";
      }
      renderAllocTable();
    });
  }
}

buildFilterUI();
renderAllocTable();
document.getElementById("totalAlloc").textContent = `${payload.total_allocation}%`;
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
