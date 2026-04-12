from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

from flask import Flask, render_template


BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "weighted_contest_results.csv"
CSS_PATH = BASE_DIR / "static" / "styles.css"

app = Flask(__name__)


def parse_final_score(row: dict[str, Any]) -> float:
    """Read normalized score from CSV, with fallback for older files."""
    value = row.get("normalized_weighted_score", row.get("weighted_score", 0))
    return float(value or 0)


def load_results() -> tuple[list[str], list[dict[str, Any]]]:
    """Load contest rows from the weighted results CSV."""
    with CSV_PATH.open(mode="r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        columns = reader.fieldnames or []
        rows = [row for row in reader]

    columns = ["current position"] + columns
    for index, row in enumerate(rows, start=1):
        row["current position"] = index

    return columns, rows


@app.route("/")
def index() -> str:
    columns, rows = load_results()

    # Compute stats for the dashboard cards
    total = len(rows)
    scores = [parse_final_score(r) for r in rows]
    top_score = max(scores) if scores else 0
    top_name = next(
        (r["name"] for r in rows if parse_final_score(r) == top_score),
        "—",
    )
    sessions = len({r.get("session", "") for r in rows if r.get("session", "")})
    styles_version = int(os.path.getmtime(CSS_PATH)) if CSS_PATH.exists() else 1

    return render_template(
        "index.html",
        title="Team Forming Contest Results Data",
        columns=columns,
        rows=rows,
        total=total,
        top_score=round(top_score, 3),
        top_name=top_name,
        sessions=sessions,
        styles_version=styles_version,
    )


if __name__ == "__main__":
    app.run(debug=True)
