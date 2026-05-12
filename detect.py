#!/usr/bin/env python3
"""
Echo Layer 2 — PELT changepoint detection.

Signal dimensions (all per-week ratios, z-score normalised before PELT):
  [night_ratio, long_form_ratio, education_r, news_politics_r,
   science_tech_r, sports_r, people_blogs_r]

Sparse weeks (<MIN_WATCHES) are linearly interpolated from neighbours.
Detects changepoints and writes chapters + chapter_fingerprints to echo.db.

Usage:
    python detect.py                 # default penalty=3
    python detect.py --penalty 5     # tune: lower = more chapters
    python detect.py --plot          # save weekly_signal.png
    python detect.py --dry-run       # print chapters, don't write to DB
"""

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import ruptures as rpt
import sqlite_utils

BASE    = Path(__file__).parent
DB_PATH = BASE / "echo.db"

MIN_WATCHES     = 3     # weeks with fewer watches → treated as sparse, linearly interpolated
                        # lowering this risks signal noise from single-video weeks
MIN_CHAPTER_WKS = 8     # PELT min_size: no chapter shorter than 8 weeks (~2 months)
                        # prevents micro-chapters from one-off behavioral spikes
SIGNAL_START    = date(2020, 1, 1)
                        # 2017-2019 data is missing (YouTube History was paused/deleted)
                        # starting at 2020 avoids a misleading flat-zero signal prefix
DEFAULT_PENALTY = 3     # penalty=2 → 16 chapters (richer 2024-2026 sub-structure, chosen)
                        # penalty=3 → 13 chapters (cleaner but lost post-2024 granularity)
                        # penalty=6 → 8 chapters (useful for high-level overview)
                        # lower penalty = more chapters; tune with --dry-run first

# Categories tracked as explicit signal dimensions
CATEGORY_DIMS = [
    "Education",
    "News & Politics",
    "Science & Technology",
    "Sports",
    "People & Blogs",
]

# Signal column names (for display and plot labels)
SIGNAL_LABELS = (
    ["night_ratio", "shorts_ratio", "long_form_ratio"]
    + [c.split()[0].lower() for c in CATEGORY_DIMS]
)


# ── Data layer ────────────────────────────────────────────────────────────────

def get_weekly_data(db: sqlite_utils.Database) -> dict[str, dict]:
    """
    Returns {monday_iso_date: {n, night, long, cats, channels}} for all weeks.
    """
    rows = db.execute("""
        SELECT
            datetime(w.watched_at, '+330 minutes')       AS ist_dt,
            CASE
                WHEN CAST(substr(datetime(w.watched_at, '+330 minutes'), 12, 2) AS INTEGER) >= 22
                  OR CAST(substr(datetime(w.watched_at, '+330 minutes'), 12, 2) AS INTEGER) <  4
                THEN 1 ELSE 0
            END                                          AS is_night,
            CASE WHEN vm.duration_seconds > 0
                  AND vm.duration_seconds <= 60  THEN 1 ELSE 0 END AS is_short,
            CASE WHEN COALESCE(vm.duration_seconds, 0) > 1200 THEN 1 ELSE 0
            END                                          AS is_long,
            COALESCE(vm.category_name, 'unknown')        AS category,
            COALESCE(vm.channel_title, '')               AS channel
        FROM watches w
        LEFT JOIN video_metadata vm ON w.video_id = vm.video_id
        ORDER BY w.watched_at
    """).fetchall()

    weekly: dict = defaultdict(
        lambda: {"n": 0, "night": 0, "shorts": 0, "long": 0, "cats": [], "channels": set()}
    )
    for ist_dt, is_night, is_short, is_long, category, channel in rows:
        d = date.fromisoformat(ist_dt[:10])
        monday = (d - timedelta(days=d.weekday())).isoformat()
        w = weekly[monday]
        w["n"]      += 1
        w["night"]  += is_night
        w["shorts"] += is_short
        w["long"]   += is_long
        w["cats"].append(category)
        if channel:
            w["channels"].add(channel)

    return dict(weekly)


# ── Signal construction ───────────────────────────────────────────────────────

def _cat_ratio(cats: list[str], category: str) -> float:
    if not cats:
        return 0.0
    return sum(1 for c in cats if c == category) / len(cats)


def build_signal(
    weekly: dict,
    start: date = SIGNAL_START,
    min_watches: int = MIN_WATCHES,
) -> tuple[list[date], np.ndarray, np.ndarray]:
    """
    Returns (mondays, signal, has_data):
    - mondays: list[date], one per week from start → last watch
    - signal:  np.array (n_weeks, 7), fully interpolated, no NaNs
    - has_data: bool array, True where >= min_watches watches exist
    """
    mondays_with_data = sorted(
        date.fromisoformat(k) for k in weekly if date.fromisoformat(k) >= start
    )
    if not mondays_with_data:
        return [], np.array([]), np.array([])

    last = mondays_with_data[-1]
    all_mondays: list[date] = []
    cur = start - timedelta(days=start.weekday())
    while cur <= last:
        all_mondays.append(cur)
        cur += timedelta(weeks=1)

    n    = len(all_mondays)
    dims = 3 + len(CATEGORY_DIMS)   # night, shorts, long + category dims
    raw  = np.full((n, dims), np.nan)
    has_data = np.zeros(n, dtype=bool)

    for i, monday in enumerate(all_mondays):
        d = weekly.get(monday.isoformat())
        if d and d["n"] >= min_watches:
            has_data[i]  = True
            raw[i, 0]    = d["night"]  / d["n"]
            raw[i, 1]    = d["shorts"] / d["n"]
            raw[i, 2]    = d["long"]   / d["n"]
            for j, cat in enumerate(CATEGORY_DIMS):
                raw[i, 3 + j] = _cat_ratio(d["cats"], cat)

    idx = np.arange(n)
    for col in range(dims):
        arr    = raw[:, col]
        finite = np.isfinite(arr)
        if finite.sum() >= 2:
            arr[:] = np.interp(idx, idx[finite], arr[finite])
        elif finite.sum() == 1:
            arr[:] = arr[finite][0]
        else:
            arr[:] = 0.0

    return all_mondays, raw, has_data


# ── PELT ──────────────────────────────────────────────────────────────────────

def run_pelt(signal: np.ndarray, penalty: float, min_size: int = MIN_CHAPTER_WKS) -> list[int]:
    """Z-score normalise then run PELT with RBF cost."""
    std = signal.std(axis=0)
    std[std == 0] = 1.0
    normed = (signal - signal.mean(axis=0)) / std

    model = rpt.Pelt(model="rbf", min_size=min_size, jump=1)
    model.fit(normed)
    return model.predict(pen=penalty)


# ── Fingerprints ──────────────────────────────────────────────────────────────

def chapter_fingerprint(db: sqlite_utils.Database, start_iso: str, end_iso: str) -> dict:
    rows = db.execute("""
        SELECT
            COALESCE(vm.category_name, 'unknown')   AS cat,
            COALESCE(vm.duration_seconds, 0)         AS dur,
            CAST(substr(datetime(w.watched_at, '+330 minutes'), 12, 2) AS INTEGER) AS hour_ist,
            COALESCE(vm.channel_title, '')           AS channel
        FROM watches w
        LEFT JOIN video_metadata vm ON w.video_id = vm.video_id
        WHERE date(datetime(w.watched_at, '+330 minutes')) BETWEEN ? AND ?
    """, [start_iso, end_iso]).fetchall()

    if not rows:
        return {}

    cats     = [r[0] for r in rows]
    durs     = [r[1] for r in rows]
    hours    = [r[2] for r in rows]
    channels = [r[3] for r in rows if r[3]]
    total    = len(rows)

    cat_counts = Counter(cats)
    top_cats   = {c: round(n * 100.0 / total, 1) for c, n in cat_counts.most_common(5)}

    return {
        "top_categories":          json.dumps(top_cats),
        "median_duration_seconds": float(np.median(durs)),
        "modal_hour":              Counter(hours).most_common(1)[0][0],
        "channel_density_score":   round(len(set(channels)) / total, 3) if total else 0,
        "night_ratio":             round(sum(1 for h in hours if h >= 22 or h < 4) / total, 3),
        "shorts_ratio":            round(sum(1 for d in durs if 0 < d <= 60) / total, 3),
        "long_form_ratio":         round(sum(1 for d in durs if d > 1200) / total, 3),
    }


# ── DB write ──────────────────────────────────────────────────────────────────

def write_chapters(
    db: sqlite_utils.Database,
    mondays: list[date],
    bkps: list[int],
    dry_run: bool = False,
) -> list[dict]:
    chapters_out = []
    prev = 0
    for num, bkp in enumerate(bkps, start=1):
        start_monday = mondays[prev]
        end_monday   = mondays[min(bkp, len(mondays)) - 1]
        start_iso    = start_monday.isoformat()
        end_iso      = (end_monday + timedelta(days=6)).isoformat()
        fp           = chapter_fingerprint(db, start_iso, end_iso)
        chapters_out.append({
            "num":    num,
            "start":  start_iso,
            "end":    end_iso,
            "n_weeks": bkp - prev,
            "label":  f"Chapter {num}",
            "fp":     fp,
        })
        prev = bkp

    if dry_run:
        return chapters_out

    # Add shorts_ratio column if schema predates it
    existing = {r[1] for r in db.execute("PRAGMA table_info(chapter_fingerprints)").fetchall()}
    if "shorts_ratio" not in existing:
        db.execute("ALTER TABLE chapter_fingerprints ADD COLUMN shorts_ratio REAL")
        db.conn.commit()

    db.execute("DELETE FROM chapter_fingerprints")
    db.execute("DELETE FROM chapters")
    db.conn.commit()

    for ch in chapters_out:
        row_id = db["chapters"].insert({
            "start_at": ch["start"],
            "end_at":   ch["end"],
            "label":    ch["label"],
        }).last_pk
        if ch["fp"]:
            db["chapter_fingerprints"].insert({"chapter_id": row_id, **ch["fp"]})

    db.conn.commit()
    return chapters_out


# ── Output ────────────────────────────────────────────────────────────────────

def print_summary(chapters: list[dict], mondays: list[date], has_data: np.ndarray, penalty: float):
    print("=" * 66)
    print("ECHO LAYER 2 — CHANGEPOINT DETECTION")
    print("=" * 66)
    print(f"  Signal:  {len(SIGNAL_LABELS)} dims [{', '.join(SIGNAL_LABELS)}]")
    print(f"  Weeks:   {mondays[0]} → {mondays[-1]}  ({len(mondays)} total, {int(has_data.sum())} dense)")
    print(f"  Penalty: {penalty}  |  Chapters: {len(chapters)}")
    print()

    for ch in chapters:
        fp  = ch["fp"]
        top = json.loads(fp.get("top_categories", "{}")) if fp else {}
        top_items = list(top.items())[:2]
        top_str   = "  |  ".join(f"{cat} {pct}%" for cat, pct in top_items)
        print(f"  Ch{ch['num']:>2}  {ch['start']} → {ch['end']}  ({ch['n_weeks']} wks)")
        if fp:
            print(f"        night={fp['night_ratio']:.2f}  "
                  f"shorts={fp.get('shorts_ratio',0):.2f}  "
                  f"long={fp['long_form_ratio']:.2f}  "
                  f"modal={fp.get('modal_hour','?'):>2}h IST  "
                  f"ch-density={fp.get('channel_density_score',0):.3f}")
            print(f"        {top_str}")
        print()

    print("Next: python detect.py --plot  or  datasette echo.db")


def save_plot(mondays: list[date], signal: np.ndarray, bkps: list[int], has_data: np.ndarray):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        dim_labels = ["Night ratio", "Shorts ratio", "Long-form ratio"] + CATEGORY_DIMS
        colours = ["#6B3FA0", "#F44336", "#2196F3", "#FF7043", "#E91E63",
                   "#009688", "#FF9800", "#607D8B"]

        fig, axes = plt.subplots(len(dim_labels), 1, figsize=(14, 14), sharex=True)
        for ax, col, label, colour in zip(axes, range(len(dim_labels)), dim_labels, colours):
            y = signal[:, col]
            ax.plot(mondays, y, color=colour, linewidth=0.9, alpha=0.85)
            ax.fill_between(mondays, y, alpha=0.12, color=colour)
            ax.set_ylabel(label, fontsize=8)
            ax.grid(axis="x", linestyle=":", linewidth=0.4, alpha=0.5)
            sparse = ~has_data
            if sparse.any():
                ylim = ax.get_ylim()
                ax.fill_between(mondays, ylim[0], ylim[1], where=sparse,
                                alpha=0.06, color="gray")

        for bkp in bkps[:-1]:
            x = mondays[bkp - 1]
            for ax in axes:
                ax.axvline(x, color="#E53935", linewidth=1.1, linestyle="--", alpha=0.75)

        axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        axes[-1].xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        plt.xticks(rotation=30, ha="right", fontsize=7)
        fig.suptitle("Echo — Weekly Watch Signal + PELT Changepoints", fontsize=11)
        plt.tight_layout()

        out = BASE / "weekly_signal.png"
        plt.savefig(out, dpi=150)
        print(f"Plot saved: {out}")
    except ImportError:
        print("matplotlib not installed — skipping plot")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Echo Layer 2 — PELT changepoint detection")
    parser.add_argument("--penalty", type=float, default=DEFAULT_PENALTY)
    parser.add_argument("--plot",    action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = sqlite_utils.Database(DB_PATH)

    print("Loading watch data...", end=" ", flush=True)
    weekly = get_weekly_data(db)
    mondays, signal, has_data = build_signal(weekly)
    if not mondays:
        print("ERROR: no data from 2020+")
        sys.exit(1)
    print(f"{len(mondays)} weeks  ({mondays[0]} → {mondays[-1]})")

    print("Running PELT...", end=" ", flush=True)
    bkps = run_pelt(signal, penalty=args.penalty)
    print(f"{len(bkps)} changepoints → {len(bkps)} chapters")

    chapters = write_chapters(db, mondays, bkps, dry_run=args.dry_run)

    print()
    print_summary(chapters, mondays, has_data, penalty=args.penalty)

    if args.plot:
        save_plot(mondays, signal, bkps, has_data)

    if args.dry_run:
        print("\n(dry-run: DB not modified)")


if __name__ == "__main__":
    main()
