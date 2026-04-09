from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from flask import Flask, render_template


BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "weighted_contest_results.csv"

app = Flask(__name__)


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
    scores = [float(r.get("weighted_score", 0) or 0) for r in rows]
    top_score = max(scores) if scores else 0
    top_name = next(
        (r["name"] for r in rows if float(r.get("weighted_score", 0) or 0) == top_score),
        "—",
    )
    sessions = len({r.get("session", "") for r in rows if r.get("session", "")})

    return render_template(
        "index.html",
        title="Team Forming Contest Results Data",
        columns=columns,
        rows=rows,
        total=total,
        top_score=top_score,
        top_name=top_name,
        sessions=sessions,
    )


if __name__ == "__main__":
    app.run(debug=True)
