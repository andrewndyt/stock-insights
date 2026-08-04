#!/usr/bin/env python3
"""
Stock Insights — CANSLIM growth screen.

Runs unattended in GitHub Actions. Harvests price and fundamental data from
Yahoo Finance via yfinance, scores the seven CANSLIM components, applies
O'Neil's breakout gate, and writes data/latest.json.

Deliberate design notes:
  * The scoring model reproduces the original Finviz-based model exactly, so
    scores stay comparable across the source change. See scoring notes below.
  * One component degrades: institutional TRANSACTIONS (the net insider/fund
    buying figure Finviz exposes) has no yfinance equivalent. It is recorded as
    None, which the scale helper treats as neutral 50. The I component is
    therefore based on ownership level alone. This is flagged in the output so
    the report can say so rather than quietly pretending otherwise.
  * Annual growth history is capped at ~4 years by yfinance, not 5. The field
    is named eps_past_4y and the scale range is unchanged, so a 4-year CAGR is
    read against the same band as the old 5-year figure. Slight optimism bias
    for names that grew fastest 5 years ago; noted in output.
  * Every ticker is wrapped in its own try/except. One bad symbol degrades that
    row to nulls rather than killing the run.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

UNIVERSE_FILE = "universe.txt"
OUT_FILE = "data/latest.json"
HISTORY_FILE = "data/history.jsonl"

TOP_N = 100                 # keep the largest N by market cap
DROP_TICKERS = {"GOOG"}     # duplicate share class of GOOGL
MIN_MARKET_CAP = 2_000_000_000   # US$2B floor
INDEXES = ["SPY", "QQQ", "IWM"]

WEIGHTS = {"C": 0.15, "A": 0.20, "N": 0.15, "S": 0.15, "L": 0.20, "I": 0.10, "M": 0.05}


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def clip(v, lo, hi):
    return max(lo, min(hi, v))


def scale(v, lo, hi):
    """Map v from [lo, hi] onto 0-100, clipped. Missing -> neutral 50.0."""
    if v is None:
        return 50.0
    try:
        if pd.isna(v):
            return 50.0
    except (TypeError, ValueError):
        pass
    return clip((float(v) - lo) / (hi - lo) * 100.0, 0.0, 100.0)


def band(total):
    if total >= 90:
        return "Exceptional+"
    if total >= 80:
        return "Exceptional"
    if total >= 70:
        return "Strong"
    if total >= 60:
        return "Above Average"
    return "Below Threshold"


def pct_change(new, old):
    """YoY percentage change, guarding the sign-flip trap.

    Growth off a negative base is not meaningful — a loss narrowing from -10 to
    -2 is not '80% growth'. Return None so the component reads as neutral
    rather than spuriously strong.
    """
    if new is None or old is None:
        return None
    try:
        new, old = float(new), float(old)
    except (TypeError, ValueError):
        return None
    if pd.isna(new) or pd.isna(old) or old <= 0:
        return None
    return (new - old) / abs(old) * 100.0


def cagr(latest, earliest, years):
    if latest is None or earliest is None or years <= 0:
        return None
    try:
        latest, earliest = float(latest), float(earliest)
    except (TypeError, ValueError):
        return None
    if pd.isna(latest) or pd.isna(earliest) or earliest <= 0 or latest <= 0:
        return None
    return ((latest / earliest) ** (1.0 / years) - 1.0) * 100.0


def row_get(df, names):
    """Fetch the first matching row label from a yfinance statement frame."""
    if df is None or df.empty:
        return None
    for n in names:
        if n in df.index:
            s = df.loc[n]
            if isinstance(s, pd.DataFrame):
                s = s.iloc[0]
            return s
    return None


# ----------------------------------------------------------------------------
# price-derived metrics
# ----------------------------------------------------------------------------

def price_metrics(hist: pd.DataFrame) -> dict:
    """52w high distance, SMA positions, 1y performance, relative volume."""
    out = {"price": None, "high52_pct": None, "sma50_pct": None,
           "sma200_pct": None, "sma20_pct": None, "perf_year": None,
           "rel_vol": None}
    if hist is None or hist.empty or "Close" not in hist:
        return out

    close = hist["Close"].dropna()
    if len(close) < 30:
        return out

    price = float(close.iloc[-1])
    out["price"] = round(price, 2)

    window = close.tail(252)
    high52 = float(window.max())
    if high52 > 0:
        out["high52_pct"] = round((price / high52 - 1.0) * 100.0, 2)

    for label, n in (("sma20_pct", 20), ("sma50_pct", 50), ("sma200_pct", 200)):
        if len(close) >= n:
            sma = float(close.tail(n).mean())
            if sma > 0:
                out[label] = round((price / sma - 1.0) * 100.0, 2)

    if len(close) >= 252:
        past = float(close.iloc[-252])
        if past > 0:
            out["perf_year"] = round((price / past - 1.0) * 100.0, 2)
    elif len(close) >= 120:
        # Less than a year of history: annualise rather than drop, and the
        # shorter base is disclosed via data_flags upstream.
        past = float(close.iloc[0])
        if past > 0:
            yrs = len(close) / 252.0
            out["perf_year"] = round(((price / past) ** (1 / yrs) - 1.0) * 100.0, 2)

    if "Volume" in hist:
        vol = hist["Volume"].dropna()
        if len(vol) >= 50:
            avg50 = float(vol.tail(50).mean())
            if avg50 > 0:
                out["rel_vol"] = round(float(vol.iloc[-1]) / avg50, 2)
    return out


def fundamentals(tk: yf.Ticker) -> dict:
    """Quarterly YoY growth, multi-year CAGRs, institutional ownership."""
    out = {"eps_qq": None, "sales_qq": None, "eps_this_y": None,
           "eps_past_4y": None, "sales_past_4y": None, "inst_own": None,
           "inst_trans": None, "years_of_annual": 0}

    # --- quarterly: same quarter last year, so index -1 vs -5 ---
    try:
        q = tk.quarterly_income_stmt
        if q is not None and not q.empty:
            q = q.reindex(sorted(q.columns, reverse=True), axis=1)  # newest first
            eps = row_get(q, ["Diluted EPS", "Basic EPS"])
            rev = row_get(q, ["Total Revenue", "Operating Revenue"])
            if eps is not None and len(eps) >= 5:
                out["eps_qq"] = pct_change(eps.iloc[0], eps.iloc[4])
            if rev is not None and len(rev) >= 5:
                out["sales_qq"] = pct_change(rev.iloc[0], rev.iloc[4])
    except Exception:
        pass

    # --- annual: CAGR across whatever yfinance gives (usually 4 years) ---
    try:
        a = tk.income_stmt
        if a is not None and not a.empty:
            a = a.reindex(sorted(a.columns, reverse=True), axis=1)
            eps = row_get(a, ["Diluted EPS", "Basic EPS"])
            rev = row_get(a, ["Total Revenue", "Operating Revenue"])
            if eps is not None and len(eps) >= 2:
                out["years_of_annual"] = int(len(eps))
                out["eps_this_y"] = pct_change(eps.iloc[0], eps.iloc[1])
                out["eps_past_4y"] = cagr(eps.iloc[0], eps.iloc[-1], len(eps) - 1)
            if rev is not None and len(rev) >= 2:
                out["sales_past_4y"] = cagr(rev.iloc[0], rev.iloc[-1], len(rev) - 1)
    except Exception:
        pass

    # --- institutional ownership ---
    try:
        info = tk.get_info()
        held = info.get("heldPercentInstitutions")
        if held is not None and not pd.isna(held):
            out["inst_own"] = round(float(held) * 100.0, 2)
    except Exception:
        pass

    return out


# ----------------------------------------------------------------------------
# scoring
# ----------------------------------------------------------------------------

def market_direction(index_hist: dict) -> tuple:
    """M: 25 pts each for above 20/50/200-day, plus 25 x scaled dist from high."""
    scores, detail = [], {}
    for sym in INDEXES:
        m = price_metrics(index_hist.get(sym))
        s = 0.0
        for key in ("sma20_pct", "sma50_pct", "sma200_pct"):
            if m.get(key) is not None and m[key] > 0:
                s += 25.0
        s += 25.0 * scale(m.get("high52_pct"), -20, 0) / 100.0
        scores.append(s)
        detail[sym] = {"score": round(s, 1), **m}
    m_score = round(sum(scores) / len(scores), 1) if scores else 50.0
    return m_score, detail


def score_one(d: dict, m_score: float) -> dict:
    C = 0.7 * scale(d.get("eps_qq"), -50, 200) + 0.3 * scale(d.get("sales_qq"), -20, 60)

    annual = d.get("eps_past_4y")
    used_fallback = False
    if annual is None:
        annual = d.get("eps_this_y")
        used_fallback = annual is not None
    A = 0.7 * scale(annual, -20, 100) + 0.3 * scale(d.get("sales_past_4y"), -20, 40)

    N = scale(d.get("high52_pct"), -50, 0)
    S = scale(d.get("rel_vol"), 0.4, 1.6)
    L = 0.6 * scale(d.get("perf_year"), -30, 150) + 0.4 * (
        0.5 * scale(d.get("sma50_pct"), -20, 20) + 0.5 * scale(d.get("sma200_pct"), -20, 20))

    inst_adj = 0.0
    if d.get("inst_trans") is not None:
        inst_adj = clip(float(d["inst_trans"]) * 6, -15, 15)
    I = clip(scale(d.get("inst_own"), 20, 90) + inst_adj, 0, 100)

    comps = {"C": C, "A": A, "N": N, "S": S, "L": L, "I": I, "M": float(m_score)}
    total = sum(comps[k] * WEIGHTS[k] for k in WEIGHTS)

    # --- breakout gate ---
    high52, sma200 = d.get("high52_pct"), d.get("sma200_pct")
    reasons = []
    if high52 is None or sma200 is None:
        gate, reasons = False, ["insufficient price history"]
    else:
        if high52 < -25:
            reasons.append(f"{abs(high52):.0f}% below 52w high")
        if sma200 <= 0:
            reasons.append("below 200-day SMA")
        gate = not reasons

    flags = []
    if used_fallback:
        flags.append("A uses 1yr growth — no multi-year EPS history")
    if d.get("eps_qq") is None:
        flags.append("no usable quarterly EPS growth (negative or missing base)")
    if d.get("inst_own") is None:
        flags.append("institutional ownership missing")
    if 0 < d.get("years_of_annual", 0) < 4:
        flags.append(f"only {d['years_of_annual']}yr annual history")

    return {
        "components": {k: round(v, 1) for k, v in comps.items()},
        "total": round(total, 1),
        "band": band(total),
        "gate_pass": gate,
        "gate_reasons": reasons,
        "flags": flags,
    }


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def load_universe() -> list:
    syms = []
    with open(UNIVERSE_FILE) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                syms.append(line.upper())
    return sorted(set(syms))


def bulk_history(symbols: list) -> dict:
    """One batched download for all price history. Far kinder than per-ticker."""
    out = {}
    chunk = 40
    for i in range(0, len(symbols), chunk):
        part = symbols[i:i + chunk]
        for attempt in range(3):
            try:
                df = yf.download(part, period="2y", interval="1d",
                                 auto_adjust=True, progress=False,
                                 group_by="ticker", threads=True)
                for s in part:
                    try:
                        sub = df[s] if len(part) > 1 else df
                        if sub is not None and not sub.dropna(how="all").empty:
                            out[s] = sub.dropna(how="all")
                    except Exception:
                        pass
                break
            except Exception:
                if attempt == 2:
                    print(f"  ! history chunk failed: {part}", file=sys.stderr)
                time.sleep(5 * (attempt + 1))
        time.sleep(1)
    return out


def main() -> int:
    started = datetime.now(timezone.utc)
    print(f"Stock Insights screen — {started.isoformat()}")

    universe = load_universe()
    print(f"Universe file: {len(universe)} candidate symbols")

    print("Downloading index history...")
    idx_hist = bulk_history(INDEXES)
    m_score, m_detail = market_direction(idx_hist)
    print(f"  M = {m_score}")

    print("Downloading price history...")
    hist = bulk_history(universe)
    print(f"  got history for {len(hist)}/{len(universe)}")

    print("Fetching fundamentals...")
    rows = []
    for n, sym in enumerate(universe, 1):
        if sym not in hist:
            continue
        rec = {"ticker": sym}
        try:
            tk = yf.Ticker(sym)
            rec.update(price_metrics(hist[sym]))
            rec.update(fundamentals(tk))
            try:
                info = tk.get_info()
                rec["name"] = info.get("shortName") or info.get("longName") or sym
                rec["sector"] = info.get("sector")
                rec["market_cap"] = info.get("marketCap")
                rec["pe"] = info.get("trailingPE")
                rec["forward_pe"] = info.get("forwardPE")
                rec["target_price"] = info.get("targetMeanPrice")
                rec["beta"] = info.get("beta")
                rec["profit_margin"] = info.get("profitMargins")
                rec["roe"] = info.get("returnOnEquity")
            except Exception:
                rec.setdefault("name", sym)
        except Exception:
            print(f"  ! {sym} failed:\n{traceback.format_exc()}", file=sys.stderr)
            rec["error"] = True
        rows.append(rec)
        if n % 20 == 0:
            print(f"  {n}/{len(universe)}")
        time.sleep(0.4)

    # --- rank by market cap, keep top N, drop duplicate share classes ---
    capped = [r for r in rows if r.get("market_cap")]
    capped.sort(key=lambda r: r["market_cap"], reverse=True)
    kept = [r for r in capped[:TOP_N] if r["ticker"] not in DROP_TICKERS]
    kept = [r for r in kept if r["market_cap"] >= MIN_MARKET_CAP]
    print(f"Scoring {len(kept)} names (dropped {len(rows) - len(kept)})")

    for r in kept:
        r.update(score_one(r, m_score))
    kept.sort(key=lambda r: r["total"], reverse=True)

    gate_passers = [r for r in kept if r["gate_pass"]]

    payload = {
        "generated_at": started.isoformat(),
        "generated_date": started.strftime("%d-%b-%y"),
        "source": "Yahoo Finance via yfinance",
        "universe_size": len(kept),
        "gate_pass_count": len(gate_passers),
        "market_direction": {"score": m_score, "indexes": m_detail},
        "weights": WEIGHTS,
        "model_caveats": [
            "Institutional transactions unavailable from this source — the I "
            "component reflects ownership level only, not net fund buying. "
            "Scores are marginally less discriminating than the Finviz-era model.",
            "Annual growth uses up to 4 years of statements, not 5.",
            "Quarterly growth is suppressed where the year-ago base was negative, "
            "rather than reported as a large positive.",
        ],
        "stocks": kept,
    }

    os.makedirs("data", exist_ok=True)
    with open(OUT_FILE, "w") as fh:
        json.dump(payload, fh, indent=1, default=str)

    with open(HISTORY_FILE, "a") as fh:
        fh.write(json.dumps({
            "date": started.strftime("%Y-%m-%d"),
            "m": m_score,
            "universe": len(kept),
            "gate_pass": len(gate_passers),
            "top": [{"t": r["ticker"], "s": r["total"]} for r in gate_passers[:10]],
        }, default=str) + "\n")

    print(f"\nWrote {OUT_FILE}")
    print(f"M={m_score}  gate {len(gate_passers)}/{len(kept)}")
    print("Top gate-passing:")
    for r in gate_passers[:10]:
        print(f"  {r['ticker']:6s} {r['total']:5.1f}  {r['band']}")
    if not gate_passers:
        print("  (none — every name failed the breakout gate)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
