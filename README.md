# Japan Macro Dashboard

**Question:** Is Japan's inflation persistent enough for the Bank of Japan to keep raising rates, and what does that mean for the yen?

- `build_dashboard.py` fetches 7 series, saves them to `data/`, and writes `docs/index.html`.
- `.github/workflows/refresh.yml` runs it every day at 01:17 UTC and on demand.
- `docs/refresh_log.csv` records every run; `docs/meta.json` stores the last successful refresh time.

## Evidence
See `VERIFICATION.md` and the `evidence/` folder.

## Setup
1. Create a public GitHub repository and upload these files (keep the folder structure, including `.github/`).
2. Settings → Actions → General → Workflow permissions → "Read and write permissions" → Save.
3. Actions tab → "Refresh dashboard" → "Run workflow".
4. Settings → Pages → Source: "Deploy from a branch", Branch: `main`, folder `/docs` → Save.
5. Open `https://<your-username>.github.io/<repo-name>/`.

Run locally: `pip install -r requirements.txt && python build_dashboard.py`, then open `docs/index.html`.
