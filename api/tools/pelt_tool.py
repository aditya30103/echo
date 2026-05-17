"""run_pelt tool — dedicated PELT changepoint detection wrapper."""

import json
import sqlite3

from echo.data.paths import get_db_path

_DB_PATH = str(get_db_path())


def run_pelt(
    table: str,
    ts_col: str,
    value_col: str = "*",
    freq: str = "W",
    penalty: float = 2.0,
) -> str:
    """Run PELT changepoint detection on a time series from echo.db.

    Args:
        table:     Any table with a timestamp column (e.g. 'watches', 'google_searches').
        ts_col:    Timestamp column (e.g. 'watched_at', 'searched_at').
        value_col: Column to aggregate per period, or '*' for row count (default).
        freq:      Pandas resample freq: 'D' (daily) or 'W' (weekly, default).
        penalty:   ruptures Pelt penalty — higher = fewer breakpoints (default 2.0).

    Returns [RAW-COMPUTED] tagged JSON with breakpoint dates and per-segment means.
    """
    try:
        import pandas as pd
        import ruptures as rpt

        conn = sqlite3.connect(_DB_PATH)
        if value_col == "*":
            df = pd.read_sql_query(
                f"SELECT {ts_col} FROM [{table}] WHERE {ts_col} IS NOT NULL ORDER BY {ts_col}",
                conn,
                parse_dates=[ts_col],
            )
            series = df.set_index(ts_col).assign(_count=1).resample(freq)["_count"].sum()
        else:
            df = pd.read_sql_query(
                f"SELECT {ts_col}, {value_col} FROM [{table}] "
                f"WHERE {ts_col} IS NOT NULL AND {value_col} IS NOT NULL ORDER BY {ts_col}",
                conn,
                parse_dates=[ts_col],
            )
            series = df.set_index(ts_col)[value_col].resample(freq).mean().fillna(0)
        conn.close()

        if len(series) < 4:
            return (
                f"[RAW-COMPUTED] ERROR: Not enough data points ({len(series)}) "
                f"for PELT with freq={freq!r}. Try freq='W' or a longer date range."
            )

        signal = series.values.reshape(-1, 1)
        model = rpt.Pelt(model="rbf", min_size=2).fit(signal)
        breakpoints = model.predict(pen=penalty)

        dates = series.index.tolist()
        segments = []
        prev = 0
        for bp in breakpoints:
            end = min(bp, len(dates)) - 1
            if end >= prev:
                seg_mean = float(series.iloc[prev : end + 1].mean())
                segments.append({
                    "start": str(dates[prev])[:10],
                    "end":   str(dates[end])[:10],
                    "mean":  round(seg_mean, 3),
                })
            prev = bp

        result = {
            "table":            table,
            "ts_col":           ts_col,
            "value_col":        value_col,
            "freq":             freq,
            "penalty":          penalty,
            "n_segments":       len(segments),
            "breakpoint_dates": [s["end"] for s in segments[:-1]],
            "segments":         segments,
        }
        return f"[RAW-COMPUTED]\n{json.dumps(result, indent=2)}"

    except ImportError as e:
        return f"[RAW-COMPUTED] ERROR: Missing dependency — {e}. Run: pip install ruptures pandas"
    except Exception as e:
        return f"[RAW-COMPUTED] ERROR: {e}"
