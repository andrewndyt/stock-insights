#!/usr/bin/env python3
"""
Builds report.html from data/latest.json — a single self-contained file with no
external requests (no CDN, no web fonts), so it renders identically as a
committed artefact, an emailed attachment, or a Cowork artifact.

Design decisions, per the ui-ux-pro-max pass:
  * Dark default with a light toggle. Both themes are defined as token sets and
    contrast-checked, not one inverted from the other.
  * Series colours are the dataviz reference palette already used by the
    existing Weekly Insights artifact, so the two look like one system.
  * The recommended "Exaggerated Minimalism" style was deliberately rejected —
    oversized editorial type is wrong for a table of 99 rows. The typography
    recommendation (dashboard/data/technical, tabular figures) was kept.
  * Tabular numerals throughout so columns do not jitter between sorts.
  * Colour never carries meaning alone: gate status has a text label as well as
    a colour, and every chart segment is listed in an accessible table.
"""

import json
import html

DATA_FILE = "data/latest.json"
OUT_FILE = "report.html"

# dataviz reference palette — light, then dark
SERIES = {
    "C": ("#2a78d6", "#3987e5"),
    "A": ("#eb6834", "#d95926"),
    "N": ("#1baf7a", "#199e70"),
    "S": ("#eda100", "#c98500"),
    "L": ("#4a3aa7", "#9085e9"),
    "I": ("#e87ba4", "#d55181"),
    "M": ("#008300", "#008300"),
}
COMP_NAMES = {
    "C": "Current quarterly earnings",
    "A": "Annual earnings growth",
    "N": "New high / proximity to 52w high",
    "S": "Supply — relative volume",
    "L": "Leader vs laggard — relative strength",
    "I": "Institutional sponsorship",
    "M": "Market direction",
}

CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --space-1:4px;--space-2:8px;--space-3:12px;--space-4:16px;--space-5:24px;--space-6:32px;
  --r:8px;--r-sm:5px;
  --bg:#141413;--surface:#1a1a19;--surface-2:#222221;--border:#33322f;
  /* --fg-subtle is used for small uppercase labels on both --surface and
     --surface-2, so it is chosen to clear 4.5:1 against the darker of the two,
     not just the lighter. Verified, not eyeballed. */
  --fg:#f5f4ef;--fg-muted:#a8a59a;--fg-subtle:#96938a;
  --pass:#4ade80;--fail:#f0a4a4;--warn:#e0b341;--ring:#3987e5;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 4px 12px rgba(0,0,0,.25);
}
html.light{
  --bg:#f4f3ee;--surface:#fcfcfb;--surface-2:#f0efe9;--border:#dcdad2;
  --fg:#1c1b19;--fg-muted:#5c5a52;--fg-subtle:#67645d;
  --pass:#0f7a3d;--fail:#b3261e;--warn:#8a6100;--ring:#2a78d6;
  --shadow:0 1px 2px rgba(0,0,0,.06),0 4px 12px rgba(0,0,0,.05);
}
html{background:var(--bg);-webkit-text-size-adjust:100%}
body{
  margin:0;padding:var(--space-5);background:var(--bg);color:var(--fg);
  font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  font-size:15px;line-height:1.5;
  font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1;
}
.num,td.num,th.num{font-variant-numeric:tabular-nums;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.9em}
.wrap{max-width:1360px;margin:0 auto}
h1{font-size:1.5rem;font-weight:650;margin:0;letter-spacing:-.01em}
h2{font-size:1.05rem;font-weight:600;margin:var(--space-6) 0 var(--space-3);
  letter-spacing:-.005em}
p{margin:0 0 var(--space-3)}
.sub{color:var(--fg-muted);font-size:.85rem;margin-top:var(--space-1)}
header{display:flex;justify-content:space-between;align-items:flex-start;
  gap:var(--space-4);flex-wrap:wrap;margin-bottom:var(--space-5)}
button{font:inherit;cursor:pointer;color:var(--fg);background:var(--surface);
  border:1px solid var(--border);border-radius:var(--r-sm);
  padding:var(--space-2) var(--space-3);min-height:36px;
  transition:background .18s ease,border-color .18s ease}
button:hover{background:var(--surface-2)}
button:focus-visible{outline:2px solid var(--ring);outline-offset:2px}
.actions{display:flex;gap:var(--space-2);flex-wrap:wrap}
.tiles{display:grid;gap:var(--space-3);
  grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.tile{background:var(--surface);border:1px solid var(--border);
  border-radius:var(--r);padding:var(--space-3) var(--space-4);box-shadow:var(--shadow)}
.tile .k{font-size:.7rem;text-transform:uppercase;letter-spacing:.07em;
  color:var(--fg-subtle);font-weight:600}
.tile .v{font-size:1.5rem;font-weight:650;margin-top:var(--space-1);line-height:1.15}
.tile .d{font-size:.78rem;color:var(--fg-muted);margin-top:2px}
.card{background:var(--surface);border:1px solid var(--border);
  border-radius:var(--r);padding:var(--space-4);box-shadow:var(--shadow)}
.legend{display:flex;flex-wrap:wrap;gap:var(--space-2);margin-bottom:var(--space-4)}
.legend button{display:inline-flex;align-items:center;gap:var(--space-2);
  font-size:.8rem;padding:var(--space-1) var(--space-3)}
.legend button[aria-pressed=false]{opacity:.4}
.legend .sw{width:11px;height:11px;border-radius:2px;flex:none}
.bars{display:flex;flex-direction:column;gap:var(--space-2)}
.barrow{display:grid;grid-template-columns:70px 1fr 54px;gap:var(--space-3);
  align-items:center}
.barrow .tk{font-weight:600;font-size:.85rem}
.track{display:flex;height:22px;border-radius:var(--r-sm);overflow:hidden;
  background:var(--surface-2)}
.seg{height:100%;transition:width .2s ease}
.tot{text-align:right;font-weight:650;font-size:.88rem}
.tablewrap{overflow-x:auto;border:1px solid var(--border);border-radius:var(--r);
  background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:.85rem}
th,td{padding:var(--space-2) var(--space-3);text-align:right;white-space:nowrap;
  border-bottom:1px solid var(--border)}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}
thead th{position:sticky;top:0;background:var(--surface-2);z-index:1;
  font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;
  color:var(--fg-subtle);font-weight:650;cursor:pointer;user-select:none}
thead th:focus-visible{outline:2px solid var(--ring);outline-offset:-2px}
thead th[aria-sort=descending]::after{content:" \\2193";color:var(--fg)}
thead th[aria-sort=ascending]::after{content:" \\2191";color:var(--fg)}
tbody tr:hover{background:var(--surface-2)}
tbody tr:last-child td{border-bottom:none}
.badge{display:inline-block;padding:1px var(--space-2);border-radius:99px;
  font-size:.7rem;font-weight:650;border:1px solid currentColor}
.badge.p{color:var(--pass)}
.badge.f{color:var(--fail)}
.flag{color:var(--warn);font-size:.72rem}
details{margin-top:var(--space-3)}
summary{cursor:pointer;font-weight:600;padding:var(--space-2) 0}
summary:focus-visible{outline:2px solid var(--ring);outline-offset:2px}
.notes li{margin-bottom:var(--space-2)}
.caveat{border-left:3px solid var(--warn);padding-left:var(--space-3);
  color:var(--fg-muted);font-size:.88rem}
footer{margin-top:var(--space-6);padding-top:var(--space-4);
  border-top:1px solid var(--border);color:var(--fg-subtle);font-size:.78rem}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);
  white-space:nowrap}
@media(max-width:600px){
  body{padding:var(--space-3)}
  .barrow{grid-template-columns:56px 1fr 46px}
}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""


def fmt(v, dp=1, suffix="", dash="—"):
    if v is None:
        return dash
    try:
        if isinstance(v, str):
            return html.escape(v)
        return f"{float(v):,.{dp}f}{suffix}"
    except (TypeError, ValueError):
        return dash


def cap(v):
    if not v:
        return "—"
    v = float(v)
    for div, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if v >= div:
            return f"{v/div:.2f}{unit}"
    return f"{v:,.0f}"


def build(d: dict) -> str:
    stocks = d["stocks"]
    passers = [s for s in stocks if s["gate_pass"]]
    m = d["market_direction"]
    top15 = passers[:15]
    top8 = passers[:8]

    # ---- stat tiles ----
    tiles = []
    for sym in ("SPY", "QQQ", "IWM"):
        ix = m["indexes"].get(sym, {})
        above = [n for n, k in (("20", "sma20_pct"), ("50", "sma50_pct"), ("200", "sma200_pct"))
                 if ix.get(k) is not None and ix[k] > 0]
        tiles.append((sym, fmt(ix.get("score")),
                      ("above " + "/".join(above) + "-day" if above else "below all averages")))
    tiles.append(("Market direction M", fmt(m["score"]),
                  "average of the three indexes"))
    tiles.append(("Universe", str(d["universe_size"]), "names scored"))
    tiles.append(("Passed gate", f'{d["gate_pass_count"]}/{d["universe_size"]}',
                  "within 25% of high, above 200-day"))
    tile_html = "".join(
        f'<div class="tile"><div class="k">{html.escape(k)}</div>'
        f'<div class="v num">{v}</div><div class="d">{html.escape(dd)}</div></div>'
        for k, v, dd in tiles)

    # ---- stacked component bars ----
    legend = "".join(
        f'<button type="button" aria-pressed="true" data-c="{c}">'
        f'<span class="sw" style="background:{SERIES[c][1]}"></span>{c} — '
        f'{html.escape(COMP_NAMES[c])}</button>' for c in "CANSLIM" if c in SERIES)

    if top15:
        bars = "".join(
            f'<div class="barrow"><span class="tk">{html.escape(s["ticker"])}</span>'
            f'<div class="track" data-row="{html.escape(s["ticker"])}"></div>'
            f'<span class="tot num">{s["total"]:.1f}</span></div>' for s in top15)
        chart_note = (f"Top {len(top15)} gate-passing names. Each bar is the weighted "
                      "contribution of the seven components; the number on the right is "
                      "the total. Use the legend to remove a component and see the "
                      "ranking without it.")
    else:
        bars = ('<p class="caveat">No name passed the breakout gate this week. In '
                'CANSLIM terms that is a signal in itself — the market is not offering '
                'buyable strength. Nothing to chart.</p>')
        chart_note = ""

    # ---- valuation table ----
    if top8:
        vrows = ""
        for s in top8:
            tp, pr = s.get("target_price"), s.get("price")
            up = f"{(tp/pr-1)*100:+.1f}%" if tp and pr else "—"
            vrows += (
                f'<tr><td>{html.escape(s["ticker"])}</td>'
                f'<td>{html.escape(str(s.get("name") or ""))[:28]}</td>'
                f'<td class="num">{cap(s.get("market_cap"))}</td>'
                f'<td class="num">{fmt(s.get("price"),2)}</td>'
                f'<td class="num">{fmt(s.get("pe"))}</td>'
                f'<td class="num">{fmt(s.get("forward_pe"))}</td>'
                f'<td class="num">{fmt((s.get("profit_margin") or 0)*100 if s.get("profit_margin") else None)}</td>'
                f'<td class="num">{fmt((s.get("roe") or 0)*100 if s.get("roe") else None)}</td>'
                f'<td class="num">{fmt(s.get("beta"),2)}</td>'
                f'<td class="num">{up}</td></tr>')
        val = (
            '<div class="tablewrap"><table><thead><tr>'
            '<th>Ticker</th><th>Name</th><th>Mkt cap</th><th>Price</th><th>P/E</th>'
            '<th>Fwd P/E</th><th>Margin %</th><th>ROE %</th><th>Beta</th>'
            '<th>Target upside</th></tr></thead><tbody>' + vrows + '</tbody></table></div>')
    else:
        val = '<p class="caveat">No gate-passing names to value.</p>'

    # ---- full ranked table ----
    rows = ""
    for i, s in enumerate(stocks, 1):
        c = s["components"]
        badge = ('<span class="badge p">PASS</span>' if s["gate_pass"]
                 else f'<span class="badge f">FAIL</span>')
        why = "" if s["gate_pass"] else \
            f'<div class="flag">{html.escape("; ".join(s["gate_reasons"]))}</div>'
        flags = (f'<div class="flag">{html.escape("; ".join(s["flags"]))}</div>'
                 if s["flags"] else "")
        rows += (
            f'<tr><td class="num">{i}</td><td>{html.escape(s["ticker"])}{why}{flags}</td>'
            f'<td>{html.escape(str(s.get("sector") or "—"))}</td>'
            f'<td class="num">{cap(s.get("market_cap"))}</td>'
            f'<td class="num">{s["total"]:.1f}</td>'
            f'<td>{html.escape(s["band"])}</td><td>{badge}</td>'
            + "".join(f'<td class="num">{c[k]:.0f}</td>' for k in "CANSLIM" if k in c)
            + f'<td class="num">{fmt(s.get("high52_pct"),1,"%")}</td>'
              f'<td class="num">{fmt(s.get("perf_year"),1,"%")}</td>'
              f'<td class="num">{fmt(s.get("eps_qq"),1,"%")}</td>'
              f'<td class="num">{fmt(s.get("inst_own"),1,"%")}</td></tr>')

    caveats = "".join(f"<li>{html.escape(c)}</li>" for c in d.get("model_caveats", []))

    payload = json.dumps({
        "top": [{"t": s["ticker"], "c": s["components"], "total": s["total"]} for s in top15],
        "w": d["weights"],
        "colors": {k: v[1] for k, v in SERIES.items()},
        "colorsLight": {k: v[0] for k, v in SERIES.items()},
        "all": [{"t": s["ticker"], "total": s["total"], "gate": s["gate_pass"],
                 "band": s["band"], **{k: s["components"][k] for k in s["components"]}}
                for s in stocks],
    }, separators=(",", ":"))

    return f"""<!DOCTYPE html>
<html lang="en-AU" class="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stock Insights — CANSLIM Screen {html.escape(d['generated_date'])}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<header>
  <div>
    <h1>Stock Insights — CANSLIM Screen</h1>
    <p class="sub">{html.escape(d['generated_date'])} &middot; {d['universe_size']} US large caps
      &middot; {html.escape(d['source'])} &middot; all figures USD</p>
  </div>
  <div class="actions">
    <button type="button" id="csv">Export CSV</button>
    <button type="button" id="theme" aria-pressed="false">Light theme</button>
  </div>
</header>

<div class="tiles">{tile_html}</div>

<h2>Weighted component breakdown</h2>
<div class="card">
  <p class="sub" style="margin-top:0">{html.escape(chart_note)}</p>
  <div class="legend" role="group" aria-label="Toggle score components">{legend}</div>
  <div class="bars" id="bars">{bars}</div>
  <p class="sr">The same values are available in the full ranked table below, which
    lists every component score for every name.</p>
</div>

<h2>Valuation snapshot — top gate-passing names</h2>
{val}

<h2>Full ranking</h2>
<details open>
  <summary>All {d['universe_size']} names, ranked by total score</summary>
  <div class="tablewrap"><table id="full"><thead><tr>
    <th data-t="n">#</th><th data-t="s">Ticker</th><th data-t="s">Sector</th>
    <th data-t="n">Mkt cap</th><th data-t="n" aria-sort="descending">Total</th>
    <th data-t="s">Band</th><th data-t="s">Gate</th>
    <th data-t="n">C</th><th data-t="n">A</th><th data-t="n">N</th><th data-t="n">S</th>
    <th data-t="n">L</th><th data-t="n">I</th><th data-t="n">M</th>
    <th data-t="n">vs 52w high</th><th data-t="n">1yr perf</th>
    <th data-t="n">EPS Q/Q</th><th data-t="n">Inst own</th>
  </tr></thead><tbody>{rows}</tbody></table></div>
</details>

<h2>What these numbers mean</h2>
<div class="card notes">
  <p>The score is a weighted blend of seven CANSLIM components, then a separate
    pass-or-fail breakout gate. A high score with a failed gate is <em>not</em> a
    candidate — O'Neil's method buys strength near highs, so a beaten-down name with
    a strong earnings rebound is explicitly excluded rather than promoted.</p>
  <p><strong>Bands.</strong> 80 and above is where a name becomes genuinely
    interesting. 70–79 is a watchlist. Below 70 is noise. If nothing clears 70 in a
    given week, the honest read is that there is nothing to do — which is a normal
    and useful result, not a failed run.</p>
  <p class="caveat"><strong>Known limits of this run.</strong></p>
  <ul>{caveats}</ul>
  <p class="caveat"><strong>The score is unvalidated.</strong> No backtest has yet
    established that a high score precedes good forward returns. Treat the ranking as
    a way of narrowing 99 names to a handful worth reading about — not as a signal.
    There are also no sell rules in this system: it says what looks strong and goes
    silent afterwards.</p>
</div>

<footer>
  Generated {html.escape(d['generated_at'])} &middot; source {html.escape(d['source'])}
  &middot; educational and informational only, not financial advice.
  Figures are unaudited third-party data and may contain errors — verify before
  acting on anything here.
</footer>
</div>

<script>
const D = {payload};
const root = document.documentElement;

/* theme ------------------------------------------------------------------ */
const tbtn = document.getElementById('theme');
tbtn.addEventListener('click', () => {{
  const light = root.classList.toggle('light');
  root.classList.toggle('dark', !light);
  tbtn.textContent = light ? 'Dark theme' : 'Light theme';
  tbtn.setAttribute('aria-pressed', String(light));
  draw();
}});

/* stacked bars ----------------------------------------------------------- */
const off = new Set();
function draw() {{
  const light = root.classList.contains('light');
  const cols = light ? D.colorsLight : D.colors;
  const keys = 'CANSLIM'.split('').filter(k => D.w[k] !== undefined && !off.has(k));
  const max = Math.max(1, ...D.top.map(r =>
    keys.reduce((a, k) => a + r.c[k] * D.w[k], 0)));
  D.top.forEach(r => {{
    const el = document.querySelector('.track[data-row="' + r.t + '"]');
    if (!el) return;
    el.innerHTML = '';
    keys.forEach(k => {{
      const v = r.c[k] * D.w[k];
      const s = document.createElement('span');
      s.className = 'seg';
      s.style.width = (v / max * 100) + '%';
      s.style.background = cols[k];
      s.title = r.t + ' — ' + k + ': ' + r.c[k].toFixed(1) +
                ' x ' + D.w[k] + ' = ' + v.toFixed(1);
      el.appendChild(s);
    }});
  }});
}}
document.querySelectorAll('.legend button').forEach(b => {{
  b.addEventListener('click', () => {{
    const k = b.dataset.c;
    off.has(k) ? off.delete(k) : off.add(k);
    b.setAttribute('aria-pressed', String(!off.has(k)));
    draw();
  }});
}});
draw();

/* sortable table --------------------------------------------------------- */
const tbl = document.getElementById('full');
tbl.querySelectorAll('thead th').forEach((th, i) => {{
  th.tabIndex = 0;
  const go = () => {{
    const numeric = th.dataset.t === 'n';
    const asc = th.getAttribute('aria-sort') === 'ascending' ? false : true;
    tbl.querySelectorAll('thead th').forEach(o => o.removeAttribute('aria-sort'));
    th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
    const body = tbl.tBodies[0];
    const rows = Array.from(body.rows);
    const val = tr => {{
      const t = tr.cells[i].textContent.trim();
      if (!numeric) return t.toLowerCase();
      const n = parseFloat(t.replace(/[^0-9.+-]/g, ''));
      return isNaN(n) ? -Infinity : n;
    }};
    rows.sort((a, b) => {{
      const x = val(a), y = val(b);
      return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1);
    }});
    rows.forEach(r => body.appendChild(r));
  }};
  th.addEventListener('click', go);
  th.addEventListener('keydown', e => {{
    if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); go(); }}
  }});
}});

/* csv -------------------------------------------------------------------- */
document.getElementById('csv').addEventListener('click', () => {{
  const cols = ['t', 'total', 'band', 'gate', 'C', 'A', 'N', 'S', 'L', 'I', 'M'];
  const lines = [cols.join(',')].concat(D.all.map(r =>
    cols.map(c => r[c] === undefined ? '' : r[c]).join(',')));
  const url = URL.createObjectURL(
    new Blob([lines.join('\\n')], {{type: 'text/csv'}}));
  const a = document.createElement('a');
  a.href = url;
  a.download = 'stock-insights-{html.escape(d["generated_date"])}.csv';
  a.click();
  URL.revokeObjectURL(url);
}});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    with open(DATA_FILE) as fh:
        data = json.load(fh)
    with open(OUT_FILE, "w") as fh:
        fh.write(build(data))
    print(f"Wrote {OUT_FILE} ({len(open(OUT_FILE).read()):,} bytes)")
