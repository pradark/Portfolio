# Portfolio — Ticker Dashboard

Self-updating dashboard showing two line charts per ticker:

- **Left**: last 3 months, daily close, with trailing 3-month moving average
- **Right**: last 5 years, daily close, with trailing 3-month moving average

Tickers tracked, by category:

- **US Stock Market**: VTSAX
- **US Large Cap Equity**: SPY, VFIAX, VIGAX, VGIAX, VLCAX, VVIAX, VDADX, VHYAX, VFTAX
- **US Mid Cap Equity**: VEXAX, VIMAX, VMGMX, VMVAX
- **US Small Cap Equity**: VSMAX, VSGAX, VSIAX
- **International Developed Equity**: VTMGX, VEUSX, VFWAX, VPADX, VTIAX, VFSAX, VIAAX
- **Emerging Markets Equity**: VEMAX, VWO
- **US Bonds**: VBTLX, VBILX, VBIRX, VBLAX
- **US Government Bonds**: VTAPX
- **International Bonds**: VTABX
- **Real Estate**: VGRLX, VGSLX
- **Sector Equity**: VENAX, VDE, VFAIX, VHCIX, VINAX, ITA, VITAX, VMIAX, VTCAX, VUIAX
- **Money Market**: VMFXX

Data comes from Yahoo Finance via the `yfinance` library. The workflow runs every weekday at 22:30 UTC (~1.5h after US market close) and can also be triggered manually from the Actions tab.

## Architecture

This repo is **private**. It builds the dashboard and deploys `index.html` to a separate **public** repo `pradark/portfolio-site`, whose Pages serves the live URL:

- Live dashboard: https://pradark.github.io/portfolio-site/
- Deploy mechanism: SSH deploy key. The workflow secret `SITE_DEPLOY_KEY` holds the private key; the matching public key is installed as a write-enabled deploy key on `pradark/portfolio-site`.

## One-time setup

1. Create a new **public** repo `pradark/portfolio-site` (no README/license).
2. On your Mac:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/portfolio-site-deploy -N "" -C "portfolio-site deploy"
   ```
3. Add the **public** key to `pradark/portfolio-site` → Settings → Deploy keys → **Add deploy key**, paste contents of `~/.ssh/portfolio-site-deploy.pub`, **check "Allow write access"**.
4. Add the **private** key to this repo → Settings → Secrets and variables → Actions → **New repository secret**, name `SITE_DEPLOY_KEY`, paste contents of `~/.ssh/portfolio-site-deploy` (the file without `.pub`).
5. On `pradark/portfolio-site` → Settings → Pages → Source: **Deploy from a branch**, branch `main`, folder `/ (root)`.
6. Trigger this repo's workflow once: Actions → Update dashboard → **Run workflow**. After it succeeds, the public site is live.
7. (Optional) Make this repo private: Settings → Danger Zone → Change repository visibility.

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
