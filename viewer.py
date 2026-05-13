#!/usr/bin/env python3
"""
Generate a static HTML viewer of chapter reflections for proofreading.

Usage:
    python viewer.py              # writes reflections_viewer.html and opens it
    python viewer.py --no-open    # write only, don't open browser
"""

import argparse
import sqlite_utils
import webbrowser
from datetime import datetime
from pathlib import Path

BASE     = Path(__file__).parent
DB_PATH  = BASE / "echo.db"
OUT_PATH = BASE / "reflections_viewer.html"


def fmt_month_year(date_str: str) -> str:
    """'2020-07-13' -> 'July 2020'"""
    return datetime.strptime(date_str[:10], "%Y-%m-%d").strftime("%B %Y")


def fmt_date_range(start: str, end: str) -> str:
    """'2020-07-13', '2020-10-04' -> 'July 2020 – October 2020'"""
    s = fmt_month_year(start)
    e = fmt_month_year(end)
    return s if s == e else f"{s} – {e}"


def build_html(rows: list) -> str:
    nav_items = "\n".join(
        f'        <a href="#ch{ch_id}">Ch {ch_id:02d} &mdash; {fmt_date_range(start, end)}</a>'
        for ch_id, start, end, _, _ in rows
    )

    sections = []
    for ch_id, start, end, reflection, created_at in rows:
        date_range = fmt_date_range(start, end)
        # raw ISO dates shown small for reference
        raw_range  = f"{start[:10]} &rarr; {end[:10]}"
        paras = "".join(
            f"<p>{para.strip()}</p>\n"
            for para in reflection.split("\n\n")
            if para.strip()
        )
        sections.append(f"""
    <section id="ch{ch_id}">
      <h2><span class="ch-num">Chapter {ch_id}</span>{date_range}</h2>
      <div class="raw-dates">{raw_range}</div>
      <div class="reflection">{paras}</div>
    </section>""")

    sections_html = "\n".join(sections)
    generated_at  = datetime.now().strftime("%d %b %Y, %H:%M")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Echo — Chapter Reflections</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: Georgia, 'Times New Roman', serif;
      font-size: 17px;
      line-height: 1.75;
      color: #1a1a1a;
      background: #f9f7f4;
    }}

    /* ── Sidebar nav ── */
    nav {{
      position: fixed;
      top: 0; left: 0;
      width: 220px;
      height: 100vh;
      overflow-y: auto;
      background: #1e1e2e;
      padding: 24px 0;
    }}
    nav h1 {{
      font-family: system-ui, sans-serif;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: .08em;
      text-transform: uppercase;
      color: #888;
      padding: 0 20px 16px;
      border-bottom: 1px solid #333;
      margin-bottom: 12px;
    }}
    nav a {{
      display: block;
      font-family: system-ui, sans-serif;
      font-size: 12px;
      color: #aaa;
      text-decoration: none;
      padding: 6px 20px;
      line-height: 1.4;
      transition: background .1s, color .1s;
    }}
    nav a:hover {{
      background: #2a2a3e;
      color: #fff;
    }}

    /* ── Main content ── */
    main {{
      margin-left: 220px;
      padding: 60px 80px 100px;
      max-width: 860px;
    }}

    section {{
      margin-bottom: 72px;
      padding-bottom: 48px;
      border-bottom: 1px solid #ddd;
    }}
    section:last-child {{ border-bottom: none; }}

    h2 {{
      font-family: system-ui, sans-serif;
      font-size: 22px;
      font-weight: 700;
      color: #111;
      margin-bottom: 4px;
    }}
    .ch-num {{
      display: block;
      font-size: 11px;
      font-weight: 600;
      letter-spacing: .1em;
      text-transform: uppercase;
      color: #888;
      margin-bottom: 4px;
    }}

    .raw-dates {{
      font-family: 'Courier New', monospace;
      font-size: 12px;
      color: #aaa;
      margin-bottom: 20px;
    }}

    .reflection p {{
      margin-bottom: 1em;
      color: #222;
    }}
    .reflection p:last-child {{ margin-bottom: 0; }}

    footer {{
      margin-left: 220px;
      padding: 20px 80px;
      font-family: system-ui, sans-serif;
      font-size: 12px;
      color: #aaa;
      border-top: 1px solid #e0ddd8;
    }}

    @media (max-width: 700px) {{
      nav {{ display: none; }}
      main, footer {{ margin-left: 0; padding: 32px 24px; }}
    }}
  </style>
</head>
<body>

<nav>
  <h1>Echo &mdash; Chapters</h1>
{nav_items}
</nav>

<main>
{sections_html}
</main>

<footer>Generated {generated_at} &middot; model: openai/gpt-4o &middot; echo.db</footer>

</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate reflections HTML viewer")
    parser.add_argument("--no-open", action="store_true", help="Write file but don't open browser")
    args = parser.parse_args()

    db   = sqlite_utils.Database(DB_PATH)
    rows = db.execute("""
        SELECT r.chapter_id, c.start_at, c.end_at, r.reflection, r.created_at
        FROM reflections r
        JOIN chapters c ON r.chapter_id = c.id
        WHERE r.kind = 'chapter'
        ORDER BY c.start_at
    """).fetchall()

    if not rows:
        print("No chapter reflections found — run reflect.py first.")
        return

    html = build_html(rows)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"Written: {OUT_PATH}")

    if not args.no_open:
        webbrowser.open(OUT_PATH.as_uri())
        print("Opened in browser.")


if __name__ == "__main__":
    main()
