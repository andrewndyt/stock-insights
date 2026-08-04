# Stock Insights — CANSLIM Screen

Unattended weekly CANSLIM growth screen over the ~100 largest US listed
companies. Runs in GitHub Actions, so it does not need a laptop, a browser, or a
paid data subscription.

## How it runs

```
Friday 21:30 UTC  →  GitHub Actions runs screen.py + build_report.py
                     commits data/latest.json, data/history.jsonl, report.html
Friday 23:00 UTC  →  Cowork task "Stock Insights" pulls report.html
                     and refreshes the persisted artifact
```

That is Saturday 07:30 and 09:00 Sydney respectively. Actions cron is UTC and
does not follow Australian daylight saving; when Sydney shifts to AEDT the run
lands an hour earlier in local terms, which is harmless.

Trigger a run by hand any time from the Actions tab — the workflow has
`workflow_dispatch` enabled.

## Files

| File | Purpose |
|---|---|
| `universe.txt` | Candidate tickers. Wider than 100 on purpose; the top 100 by live market cap are kept. Edit freely — no code change needed. |
| `screen.py` | Harvests data, scores the seven components, applies the breakout gate, writes `data/latest.json` and appends `data/history.jsonl`. |
| `build_report.py` | Renders `report.html` — one self-contained file, no external requests. |
| `data/history.jsonl` | One line per run: M, universe size, gate-pass count, top ten. This is the raw material for eventually backtesting the score. |

## The model

Seven components, weighted, then a separate pass/fail breakout gate.

| Component | Weight | Input |
|---|---|---|
| C — current quarterly earnings | 15% | EPS and revenue, latest quarter vs the same quarter last year |
| A — annual earnings growth | 20% | EPS and revenue CAGR over available annual statements |
| N — new high | 15% | Distance below the 52-week high |
| S — supply | 15% | Latest volume vs 50-day average |
| L — leader vs laggard | 20% | 1-year price performance, plus position vs 50/200-day SMA |
| I — institutional sponsorship | 10% | Percentage held by institutions |
| M — market direction | 5% | SPY, QQQ, IWM vs their 20/50/200-day averages and 52-week highs |

**Breakout gate:** a name passes only if it is within 25% of its 52-week high
*and* above its 200-day SMA. Score and gate are independent — a high score with
a failed gate is not a candidate. CANSLIM buys strength near highs, and without
the gate a beaten-down name with a big earnings rebound ranks top of the list.

Bands: 80+ Exceptional, 70–79 Strong, 60–69 Above Average, under 60 Below
Threshold. Weeks where nothing clears 70 are normal and are reported as such.

## Known limits — read before trusting a number

1. **The score has never been backtested.** Nothing establishes that a high
   score precedes good forward returns. Treat the output as a way of narrowing
   ~100 names to a handful worth reading about.
2. **There are no sell rules.** The screen says what looks strong and goes
   silent. For most self-directed investors the exit decision is where returns
   are actually won or lost.
3. **Institutional transactions are unavailable** from this data source, so the
   I component reflects ownership level only, not net fund buying. Slightly less
   discriminating than the earlier Finviz-based version.
4. **Annual growth uses up to 4 years**, not 5, because that is what the source
   returns.
5. **Quarterly growth is suppressed where the year-ago base was negative**
   rather than reported as a huge positive. A loss narrowing from -10 to -2 is
   not 80% growth. Affected names are flagged in the report.
6. **Survivorship** — the universe is today's large caps, so any historical
   analysis built on `history.jsonl` going forward is clean, but backfilling from
   today's constituents would not be.
7. **Commodity names distort the earnings components.** A miner's or driller's
   EPS growth reflects the commodity price, not execution. Energy and materials
   names ranking highly on a rebound off a depressed base should be read
   sceptically.

Educational and informational only. Not financial advice. Data is unaudited
third-party output and may be wrong.

## Local run

```bash
pip install -r requirements.txt
python screen.py && python build_report.py
```
