# Portfolio — Ticker Dashboard

Self-updating dashboard showing two line charts per ticker:

- **Left**: last 3 months, daily close, with trailing 3-month moving average
- **Right**: last 5 years, daily close, with trailing 3-month moving average

Tickers tracked:

- `SPY` — SPDR S&P 500 ETF Trust
- `VGIAX` — Vanguard Growth Index Admiral
- `VTIAX` — Vanguard Total Intl Stock Index Admiral
- `VDE` — Vanguard Energy ETF
- `ITA` — iShares U.S. Aerospace & Defense ETF
- `VWO` — Vanguard FTSE Emerging Markets ETF

Data comes from Yahoo Finance via the `yfinance` library. The workflow runs every weekday at 22:30 UTC (~1.5h after US market close) and can also be triggered manually from the Actions tab.

## Enable GitHub Pages (one-time)

1. Repo → **Settings → Pages** → Source: **GitHub Actions**.
2. Go to the **Actions** tab → pick **Update dashboard** → **Run workflow** once to do the first real data fetch.

Live URL: https://pradark.github.io/Portfolio/

## Local preview

```bash
pip install -r requirements.txt
python scripts/build.py
# open index.html in a browser
```

## Customizing tickers

Edit the `TICKERS` dict at the top of `scripts/build.py` and commit. The next workflow run picks up the change.

## Changing the schedule

Edit the `cron` expression in `.github/workflows/update.yml` (UTC).
