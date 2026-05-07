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

    return {
        "three_month": pack(close_3m.index, close_3m, ma_3m),
        "five_year":   pack(close_5y.index, close_5y, ma_5y),
        "last_price":  round(float(close.iloc[-1]), 2),
        "last_date":   close.index[-1].strftime("%Y-%m-%d"),
        "change_3m_pct": round(float((close_3m.iloc[-1] / close_3m.iloc[0] - 1) * 100), 2) if len(close_3m) > 1 else None,
        "change_5y_pct": round(float((close_5y.iloc[-1] / close_5y.iloc[0] - 1) * 100), 2) if len(close_5y) > 1 else None,
        "ytd_pct":  round(_ytd_pct(close), 2)              if _ytd_pct(close)            is not None else None,
        "y1_pct":   round(_pct_change_from_n_days(close,  365),  2) if _pct_change_from_n_days(close,  365)  is not None else None,
        "y5_pct":   round(_pct_change_from_n_days(close,  365*5), 2) if _pct_change_from_n_days(close, 365*5) is not None else None,
        "y10_pct":  round(_pct_change_from_n_days(close, 365*10), 2) if _pct_change_from_n_days(close, 365*10) is not None else None,
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
  .title-block .sym { font-size: 18px; font-weight: 600; }
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

  /* allocation table (allocation view) */
  .alloc-cat {
    display: flex; align-items: baseline; gap: 12px;
    margin: 26px 0 6px; padding-bottom: 6px; border-bottom: 1px solid var(--border);
  }
  .alloc-cat .name { font-size: 16px; font-weight: 600; }
  .alloc-cat .pct  { color: var(--accent); font-weight: 600; font-size: 14px; }
  .alloc-cat .pct.zero { color: var(--muted); font-weight: 400; }

  table.alloc { width: 100%; border-collapse: collapse; font-size: 14px; }
  table.alloc th, table.alloc td {
    padding: 14px 12px; text-align: left; border-bottom: 1px solid var(--border);
  }
  table.alloc th {
    color: var(--muted); font-weight: 500; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.06em;
  }
  table.alloc td.fund .sym { font-weight: 700; font-size: 15px; }
  table.alloc td.alloc {
    text-align: right; width: 110px; color: var(--muted); font-variant-numeric: tabular-nums;
  }
  table.alloc td.alloc.has-alloc { color: var(--text); font-weight: 600; }
  table.alloc td.num { font-variant-numeric: tabular-nums; }
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
  <button class="tab" data-target="view-alloc">Allocation</button>
</div>

<div id="view-charts" class="view active">
  <div id="toc" class="toc"></div>
  <div id="cards"></div>
</div>

<div id="view-alloc" class="view">
  <div id="alloc"></div>
  <div class="total-row">
    <span class="label">Total Allocation</span>
    <span class="value" id="totalAlloc">—</span>
  </div>
</div>

<footer>Source: Yahoo Finance. Rebuilt daily by GitHub Actions.</footer>

<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
const payload = JSON.parse(document.getElementById("payload").textContent);

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
        <span class="sym">${sym}</span><span class="nm">${tk.name}</span>
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

/* ---------- allocation view ---------- */
const alloc = document.getElementById("alloc");

function fmtER(v)   { return v == null ? "—" : `${v.toFixed(2)}%`; }
function fmtRet(v)  { return v == null ? "—" : `${v.toFixed(2)}%`; }

for (const grp of payload.groups) {
  const head = document.createElement("div");
  head.className = "alloc-cat";
  const zero = grp.allocation_pct === 0 ? " zero" : "";
  head.innerHTML = `
    <span class="name">${grp.name}</span>
    <span class="pct${zero}">${grp.allocation_pct}%</span>`;
  alloc.appendChild(head);

  const table = document.createElement("table");
  table.className = "alloc";
  table.innerHTML = `
    <thead>
      <tr>
        <th class="fund">Fund Name</th>
        <th>Expense Ratio</th>
        <th>5-yr Return</th>
        <th class="alloc" style="text-align:right">% Allocation</th>
      </tr>
    </thead>
    <tbody>
      ${grp.tickers.map(sym => {
        const tk = payload.tickers[sym];
        const allocCls = (tk.allocation_pct ?? 0) > 0 ? "alloc has-alloc" : "alloc";
        return `<tr>
          <td class="fund"><span class="sym">${sym}</span></td>
          <td class="num">${fmtER(tk.expense_ratio)}</td>
          <td class="num ${pctClass(tk.y5_pct)}">${fmtRet(tk.y5_pct)}</td>
          <td class="${allocCls}">${tk.allocation_pct ?? 0}%</td>
        </tr>`;
      }).join("")}
    </tbody>`;
  alloc.appendChild(table);
}
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
