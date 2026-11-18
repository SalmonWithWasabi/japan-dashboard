"""
Japan Macro Dashboard
Question: Is Japan's inflation persistent enough for the Bank of Japan to keep
raising rates, and what does that mean for the yen?

Run:  python build_dashboard.py
Out:  data/*.csv  (raw data, kept between runs)
      docs/index.html  (the dashboard, served by GitHub Pages)
      docs/refresh_log.csv  (one line per run: time, series, status, latest obs)
"""

import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs_version
import requests

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"
DATA.mkdir(exist_ok=True)
DOCS.mkdir(exist_ok=True)

PLOTLY_JS = get_plotlyjs_version()  # load the plotly.js build that matches the Python package
START = "2010-01-01"  # display window: covers Abenomics, negative rates, 2024+ hikes
HEADERS = {}  # default python-requests User-Agent (FRED rejects some custom ones)

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
MOF_HIST = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv"
MOF_CURR = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"

# ---------------------------------------------------------------------------
# Series definitions. "source" = the original publisher; "via" = where we pull it.
# ---------------------------------------------------------------------------
SERIES = [
    dict(key="usdjpy", ylab="JPY per USD", fred="DEXJPUS", kind="fred",
         title="Exchange rate: yen per US dollar",
         units="JPY per USD (a rise = weaker yen)", freq="Daily", max_age_days=14,
         source="Board of Governors of the Federal Reserve System, H.10 release",
         via="FRED series DEXJPUS",
         check_url="https://www.federalreserve.gov/releases/h10/hist/dat00_ja.htm",
         transform="None (level, noon buying rates in New York)."),
    dict(key="callrate", ylab="% per year", fred="IRSTCI01JPM156N", kind="fred",
         title="Policy rate proxy: overnight call rate",
         units="Percent per year", freq="Monthly (average of daily rates)", max_age_days=150,
         source="Bank of Japan, uncollateralized overnight call rate (compiled by OECD)",
         via="FRED series IRSTCI01JPM156N",
         check_url="https://www.stat-search.boj.or.jp/",
         transform="None. The BOJ's policy target is this call rate, so it tracks the policy rate."),
    dict(key="jgb10", ylab="% per year", kind="mof",
         title="10-year JGB yield",
         units="Percent per year (semiannual compounding, constant maturity)", freq="Daily", max_age_days=14,
         source="Ministry of Finance Japan, JGB interest rates",
         via="MOF CSV files (jgbcme_all.csv + jgbcme.csv); fallback FRED IRLTLT01JPM156N (monthly)",
         check_url="https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/index.htm",
         transform="None (level)."),
    dict(key="cpi", ylab="% YoY", kind="cpi",
         title="Inflation: CPI, year over year",
         units="Percent change from 12 months earlier", freq="Monthly", max_age_days=100,
         source="Statistics Bureau of Japan (MIC), Consumer Price Index, Japan (national)",
         via="Statistics Bureau CSV files zmi2025aa.csv (2025 base) and zmi2020aa.csv (2020 base); "
             "2010–2020 history from OECD MEI via FRED (JPNCPIALLMINMEI), which republishes the same CPI",
         check_url="https://www.stat.go.jp/english/data/cpi/index.html",
         transform="YoY % = 100 × (index_t / index_t−12 − 1), computed within each base year and spliced: "
                   "2025-base from Jan 2026, 2020-base Jan 2021–Dec 2025, OECD before 2021. "
                   "Blue = all items (headline); orange = all items less fresh food (Japan’s ‘core’, from 2021). "
                   "Dashed line = BOJ 2% target.",
         ref_line=2.0),
    dict(key="gdp", ylab="% YoY", fred="JPNRGDPEXP", kind="fred",
         title="Real GDP growth, year over year",
         units="Percent change from the same quarter a year earlier", freq="Quarterly", max_age_days=240,
         source="Cabinet Office of Japan, National Accounts (real GDP, chained 2015 yen, seasonally adjusted)",
         via="FRED series JPNRGDPEXP",
         check_url="https://www.esri.cao.go.jp/en/sna/sokuhou/sokuhou_top.html",
         transform="Year-over-year % change of the level: 100 × (GDP_t / GDP_t−4 − 1).",
         yoy=4, ref_line=0.0),
    dict(key="unemp", ylab="% of labor force", fred="LRUNTTTTJPM156S", kind="fred",
         title="Unemployment rate",
         units="Percent of labor force, seasonally adjusted (age 15+)", freq="Monthly", max_age_days=100,
         source="Statistics Bureau of Japan, Labour Force Survey (compiled by OECD)",
         via="FRED series LRUNTTTTJPM156S",
         check_url="https://www.stat.go.jp/english/data/roudou/index.html",
         transform="None (level)."),
    dict(key="reer", ylab="Index, 2020 = 100", fred="RBJPBIS", kind="fred",
         title="Real effective exchange rate of the yen",
         units="Index, 2020 = 100 (a rise = stronger yen in real terms)", freq="Monthly", max_age_days=100,
         source="Bank for International Settlements, broad REER (CPI-based, trade-weighted)",
         via="FRED series RBJPBIS",
         check_url="https://data.bis.org/topics/EER",
         transform="None. Dashed line = average since 1994: below it, the yen is cheap in real terms "
                   "(relative PPP suggests eventual real appreciation).",
         avg_line=True),
]


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------
def get(url, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            r.raise_for_status()
            return r.content
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))


def fetch_fred(series_id):
    df = pd.read_csv(io.BytesIO(get(FRED_CSV.format(series_id))))
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")  # FRED uses "." for missing
    return df.dropna()


def parse_mof(raw):
    text = raw.decode("utf-8", errors="ignore")
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip().lower().startswith("date"))
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    df = df.rename(columns={df.columns[0]: "date"})
    col = next(c for c in df.columns if c.strip().upper() == "10Y")
    out = pd.DataFrame({
        "date": pd.to_datetime(df["date"], errors="coerce"),
        "value": pd.to_numeric(df[col], errors="coerce"),  # MOF uses "-" for missing
    })
    return out.dropna()


def fetch_mof_10y():
    hist = parse_mof(get(MOF_HIST))
    try:
        curr = parse_mof(get(MOF_CURR))
        hist = pd.concat([hist, curr]).drop_duplicates("date", keep="last")
    except Exception as e:  # current-month file can be briefly missing at month start
        print(f"  note: MOF current-month file not used ({e})")
    return hist.sort_values("date")


STAT_CPI = {  # newest base first; later bases win where they overlap
    "2025": "https://www.stat.go.jp/data/cpi/2025/csv/zmi2025aa.csv",
    "2020": "https://www.stat.go.jp/data/cpi/2020/csv/zmi2020aa.csv",
}


def parse_stat_cpi(raw):
    import csv
    rows = list(csv.reader(io.StringIO(raw.decode("cp932", errors="ignore"))))
    hdr = rows[0]
    i_all, i_core = hdr.index("総合"), hdr.index("生鮮食品を除く総合")
    data = [r for r in rows if r and len(r[0]) == 6 and r[0].isdigit()]
    df = pd.DataFrame({
        "date": pd.to_datetime([r[0] for r in data], format="%Y%m"),
        "all": pd.to_numeric([r[i_all] for r in data], errors="coerce"),
        "core": pd.to_numeric([r[i_core] for r in data], errors="coerce"),
    }).set_index("date").sort_index()
    return (100 * (df / df.shift(12) - 1)).dropna()  # YoY within one base year


def fetch_cpi():
    parts = []
    for base, url in STAT_CPI.items():
        try:
            parts.append(parse_stat_cpi(get(url)))
        except Exception as e:
            print(f"  CPI {base}-base file not used ({e})")
    if not parts:
        raise RuntimeError("no Statistics Bureau CPI file could be read")
    stat = parts[0]
    for older in parts[1:]:
        stat = stat.combine_first(older)  # newer base kept where both exist
    hist = fetch_fred("JPNCPIALLMINMEI").set_index("date")["value"]
    hist = (100 * (hist / hist.shift(12) - 1)).dropna()
    hist = hist[hist.index < stat.index.min()]
    out = pd.concat([pd.DataFrame({"all": hist}), stat]).sort_index()
    return out.rename(columns={"all": "value"}).reset_index().rename(columns={"index": "date"})


def fetch(s):
    if s["kind"] == "cpi":
        return fetch_cpi(), "Statistics Bureau + OECD history"
    if s["kind"] == "mof":
        try:
            return fetch_mof_10y(), "MOF"
        except Exception as e:
            print(f"  MOF failed ({e}); falling back to FRED IRLTLT01JPM156N")
            return fetch_fred("IRLTLT01JPM156N"), "FRED fallback (monthly)"
    return fetch_fred(s["fred"]), "FRED"


# ---------------------------------------------------------------------------
# Main refresh
# ---------------------------------------------------------------------------
def refresh():
    now = datetime.now(timezone.utc)
    log_rows, results = [], {}

    for s in SERIES:
        path = DATA / f"{s['key']}.csv"
        print(f"Fetching {s['key']} ...")
        try:
            df, used = fetch(s)
            if df.empty:
                raise ValueError("no observations returned")
            df.to_csv(path, index=False)  # overwrite only after a successful fetch
            status = f"OK ({used})"
        except Exception as e:
            status = f"FAILED: {e}"
            df = pd.read_csv(path, parse_dates=["date"]) if path.exists() else pd.DataFrame(columns=["date", "value"])
            print(f"  {status} -> using last saved data" if not df.empty else f"  {status}")
        results[s["key"]] = (df, status)
        last = df["date"].max() if not df.empty else None
        log_rows.append(dict(run_utc=now.strftime("%Y-%m-%d %H:%M:%S"), series=s["key"],
                             status=status, latest_obs=last.date() if last is not None else "",
                             latest_value=round(float(df.iloc[-1]["value"]), 4) if not df.empty else "",
                             n_obs=len(df)))

    ok = sum(r[1].startswith("OK") for r in results.values())
    log = pd.DataFrame(log_rows)
    log_path = DOCS / "refresh_log.csv"
    log.to_csv(log_path, mode="a", header=not log_path.exists(), index=False)
    print(log.to_string(index=False))

    meta = {"last_run_utc": now.isoformat(), "series_ok": ok, "series_total": len(SERIES)}
    if ok > 0:  # "successful refresh" = at least one series fetched fresh
        meta["last_success_utc"] = now.isoformat()
    else:
        old = DOCS / "meta.json"
        meta["last_success_utc"] = json.loads(old.read_text()).get("last_success_utc") if old.exists() else None
    (DOCS / "meta.json").write_text(json.dumps(meta, indent=2))

    build_html(results, meta)
    return ok


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def chart(s, df):
    full = df.copy().sort_values("date")
    if s.get("yoy"):
        full["value"] = 100 * (full["value"] / full["value"].shift(s["yoy"]) - 1)
        full = full.dropna()
    avg = full["value"].mean() if s.get("avg_line") else None
    show = full[full["date"] >= START]

    fig = go.Figure(go.Scatter(x=show["date"], y=show["value"], mode="lines",
                               line=dict(color="#1f4e79", width=2),
                               name="All items" if s["key"] == "cpi" else s["title"].split(":")[0]))
    if "core" in show.columns and show["core"].notna().any():
        fig.add_trace(go.Scatter(x=show["date"], y=show["core"], mode="lines",
                                 line=dict(color="#e07b00", width=2), name="Less fresh food (core)"))
    x_rng = [show["date"].min(), show["date"].max()]
    if s.get("ref_line") is not None:
        label = "BOJ 2% target" if s["key"] == "cpi" else f"{s['ref_line']:g}"
        fig.add_trace(go.Scatter(x=x_rng, y=[s["ref_line"]] * 2, mode="lines", name=label,
                                 line=dict(color="#c0504d", dash="dash", width=1.5)))
    if avg is not None:
        fig.add_trace(go.Scatter(x=x_rng, y=[avg] * 2, mode="lines",
                                 name=f"Average since {full['date'].min():%Y}: {avg:.1f}",
                                 line=dict(color="#c0504d", dash="dash", width=1.5)))
    fig.update_layout(height=320, margin=dict(l=50, r=20, t=10, b=40), template="simple_white",
                      yaxis_title=s.get("ylab", ""),
                      showlegend=len(fig.data) > 1, legend=dict(orientation="h", y=1.12))
    latest = show.iloc[-1] if not show.empty else None
    return fig, latest


def build_html(results, meta):
    tokyo, chicago = ZoneInfo("Asia/Tokyo"), ZoneInfo("America/Chicago")
    succ = meta.get("last_success_utc")
    if succ:
        t = datetime.fromisoformat(succ)
        refresh_txt = (f"{t:%Y-%m-%d %H:%M} UTC · {t.astimezone(tokyo):%Y-%m-%d %H:%M} Tokyo · "
                       f"{t.astimezone(chicago):%Y-%m-%d %H:%M} Chicago")
    else:
        refresh_txt = "never"

    cards, first = [], True
    for s in SERIES:
        df, status = results[s["key"]]
        if df.empty:
            cards.append(f"<div class='card'><h2>{s['title']}</h2><p class='bad'>No data: {status}</p></div>")
            continue
        fig, latest = chart(s, df)
        html = fig.to_html(full_html=False, include_plotlyjs=False,
                           default_width="100%", default_height="320px", config={"responsive": True})
        first = False
        age = (pd.Timestamp.now() - df["date"].max()).days
        stale = f" <span class='bad'>(no new data for {age} days)</span>" if age > s["max_age_days"] else ""
        ok_cls = "ok" if status.startswith("OK") else "bad"
        cards.append(f"""
<div class='card'>
  <h2>{s['title']}</h2>
  <p class='latest'>Latest: <b>{latest['value']:.2f}</b> · observation date <b>{latest['date']:%Y-%m-%d}</b>{stale}</p>
  {html}
  <table class='meta'>
    <tr><td>Units</td><td>{s['units']}</td></tr>
    <tr><td>Frequency</td><td>{s['freq']}</td></tr>
    <tr><td>Source</td><td>{s['source']}</td></tr>
    <tr><td>Retrieved via</td><td>{s['via']}</td></tr>
    <tr><td>Transformation</td><td>{s['transform']}</td></tr>
    <tr><td>Sample shown</td><td>{START[:4]} to latest</td></tr>
    <tr><td>Last fetch</td><td class='{ok_cls}'>{status}</td></tr>
  </table>
</div>""")

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Japan Macro Dashboard</title>
<script src="https://cdn.plot.ly/plotly-{PLOTLY_JS}.min.js" charset="utf-8"></script>
<style>
 body {{ font-family: Arial, sans-serif; margin: 0; background: #f7f7f5; color: #222; }}
 header {{ background: #1f4e79; color: #fff; padding: 20px 32px; }}
 header h1 {{ margin: 0 0 6px; font-size: 26px; }}
 header p {{ margin: 4px 0; font-size: 15px; }}
 .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; padding: 24px 32px; }}
 .card {{ min-width: 0; overflow: hidden; background: #fff; border: 1px solid #ddd; border-radius: 6px; padding: 16px 18px; }}
 .card .plotly-graph-div {{ width: 100% !important; }}
 .card h2 {{ font-size: 18px; margin: 0 0 4px; }}
 .latest {{ margin: 0 0 6px; font-size: 14px; }}
 table.meta {{ font-size: 12.5px; border-collapse: collapse; width: 100%; margin-top: 6px; }}
 table.meta td {{ border-top: 1px solid #eee; padding: 3px 6px; vertical-align: top; }}
 table.meta td:first-child {{ color: #666; width: 110px; }}
 .ok {{ color: #2e7d32; }} .bad {{ color: #c62828; }}
 @media (max-width: 1100px) {{ .grid {{ grid-template-columns: minmax(0, 1fr); }} }}
 footer {{ padding: 0 32px 24px; font-size: 13px; color: #555; }}
</style></head><body>
<header>
 <h1>Japan Macro Dashboard</h1>
 <p><b>Question:</b> Is Japan's inflation persistent enough for the Bank of Japan to keep raising rates, and what does that mean for the yen?</p>
 <p><b>Last successful refresh:</b> {refresh_txt} &nbsp;|&nbsp; series updated this run: {meta['series_ok']}/{meta['series_total']}</p>
 <p style="opacity:.85">The refresh time is when this page last pulled data. Each chart shows its own <i>latest observation date</i>, which depends on the publisher's release calendar.</p>
</header>
<div class="grid">{''.join(cards)}</div>
<footer>
 Exchange-rate conventions: USD/JPY is quoted as yen per dollar (up = yen depreciates). The REER index rises when the yen strengthens.
 Refresh log: <a href="refresh_log.csv">refresh_log.csv</a>. Updated automatically every day by GitHub Actions.
</footer>
<script>window.addEventListener('load', () => document.querySelectorAll('.plotly-graph-div').forEach(d => Plotly.Plots.resize(d)));</script>
</body></html>"""
    (DOCS / "index.html").write_text(page, encoding="utf-8")
    print(f"Wrote {DOCS / 'index.html'}")


if __name__ == "__main__":
    ok = refresh()
    sys.exit(0 if ok > 0 else 1)
