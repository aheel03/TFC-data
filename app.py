from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

from flask import Flask, render_template


BASE_DIR = Path(__file__).resolve().parent
ALL_RESULTS_CSV = BASE_DIR / "all_contest_results.csv"
LEADERBOARD_CSV = BASE_DIR / "main_leaderboard_results.csv"
CSS_PATH = BASE_DIR / "static" / "styles.css"

app = Flask(__name__)

# Keep these values aligned with huh.py
SATURDAY_CONTESTS = [802104, 804183, 807851, 811576]
MONDAY_CONTESTS = [802757, 804587, 805225, 806580, 808448, 812090]
K_PERCENT = 80
SATURDAY_WEIGHT = 1.25
MONDAY_WEIGHT = 1.0


def parse_final_score(row: dict[str, Any]) -> float:
    """Read leaderboard score from CSV, with fallback for older files."""
    value = row.get("final_score", row.get("normalized_weighted_score", row.get("weighted_score", 0)))
    return float(value or 0)


def load_results(csv_path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    """Load contest rows from a CSV file."""
    with csv_path.open(mode="r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        columns = reader.fieldnames or []
        rows = [row for row in reader]

    columns = ["current position"] + columns
    for index, row in enumerate(rows, start=1):
        row["current position"] = index

    return columns, rows


@app.route("/")
def index() -> str:
    all_columns, all_rows = load_results(ALL_RESULTS_CSV)
    leaderboard_columns, leaderboard_rows = load_results(LEADERBOARD_CSV)

    # Compute stats for the dashboard cards
    total = len(leaderboard_rows)
    scores = [parse_final_score(r) for r in leaderboard_rows]
    top_score = max(scores) if scores else 0
    top_name = next(
        (r["name"] for r in leaderboard_rows if parse_final_score(r) == top_score),
        "—",
    )
    sessions = len(
        {r.get("session", "") for r in leaderboard_rows if r.get("session", "")}
    )
    styles_version = int(os.path.getmtime(CSS_PATH)) if CSS_PATH.exists() else 1
    saturday_total = len(SATURDAY_CONTESTS)
    monday_total = len(MONDAY_CONTESTS)
    saturday_take = int((K_PERCENT / 100) * saturday_total)
    monday_take = int((K_PERCENT / 100) * monday_total)

    return render_template(
        "index.html",
        title="Team Forming Contest Results Data",
        all_columns=all_columns,
        all_rows=all_rows,
        leaderboard_columns=leaderboard_columns,
        leaderboard_rows=leaderboard_rows,
        total=total,
        top_score=round(top_score, 3),
        top_name=top_name,
        sessions=sessions,
        styles_version=styles_version,
        k_percent=K_PERCENT,
        saturday_total=saturday_total,
        monday_total=monday_total,
        saturday_take=saturday_take,
        monday_take=monday_take,
        saturday_weight=SATURDAY_WEIGHT,
        monday_weight=MONDAY_WEIGHT,
        saturday_contests=SATURDAY_CONTESTS,
        monday_contests=MONDAY_CONTESTS,
    )


if __name__ == "__main__":
    app.run(debug=True)
