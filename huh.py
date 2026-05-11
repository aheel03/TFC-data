import json
import time
import csv
import os
from playwright.sync_api import sync_playwright


def load_env_file(env_path=".env"):
    """Load key=value pairs from a local .env file into environment variables."""
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


load_env_file()

# --- CONFIGURATION ---
USERNAME = os.getenv("VJUDGE_USERNAME")
PASSWORD = os.getenv("VJUDGE_PASSWORD")

if not USERNAME or not PASSWORD:
    raise ValueError(
        "Missing VJUDGE_USERNAME or VJUDGE_PASSWORD. Set them in your environment or .env file."
    )

# --- CONTEST GROUPS ---
# Keep these lists updated with the correct contest IDs per day.
SATURDAY_CONTESTS = [802104, 804183, 807851,811576]
MONDAY_CONTESTS = [802757, 804587, 805225, 806580, 808448, 812090]

# Leaderboard parameters
K_PERCENT = 80
SATURDAY_WEIGHT = 1.25
MONDAY_WEIGHT = 1.0

HEADLESS = False  # Set to False so you can solve CAPTCHA if it appears

# The name of the CSV file you downloaded from Google Forms
FORM_CSV_FILENAME = "TFC Information Form (Responses) - Form Responses 1.csv"

def get_solve_counts(data):
    """
    Parses Vjudge raw submissions and returns a dictionary of {vj_handle: solve_count}.
    Ignores any submissions made after the official contest duration (upsolves).
    """
    participants = data.get("participants", {})
    submissions = data.get("submissions", [])
    contest_length_sec = data.get("length", 0) // 1000

    # Initialize solve tracker: {participant_id: {problem_index: is_solved}}
    solve_tracker = {}
    for pid in participants:
        solve_tracker[str(pid)] = {}

    # Sort submissions by time
    submissions.sort(key=lambda x: x[3])

    for sub in submissions:
        pid = str(sub[0])
        prob_idx = sub[1]
        verdict = sub[2]
        time_sec = sub[3]

        if pid not in solve_tracker or time_sec > contest_length_sec:
            continue
        
        # If solved (verdict == 1), mark problem index as True
        if verdict == 1:
            solve_tracker[pid][prob_idx] = True

    # Map participant ID back to Vjudge Handle and count True values
    results = {}
    for pid, solved_probs in solve_tracker.items():
        handle = participants[pid][0]
        results[handle.lower()] = len(solved_probs)
    
    return results

def build_user_info_map(form_csv_path):
    """Read form data: {handle_lower: {name, session, department}}."""
    user_info_map = {}
    if os.path.exists(form_csv_path):
        with open(form_csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                vj_handle = row.get("Vjudge Handle", "").strip().lower()
                if vj_handle:
                    user_info_map[vj_handle] = {
                        "name": row.get("Name", "").strip(),
                        "session": row.get("Session", "").strip(),
                        "department": row.get("Department", "").strip(),
                    }
    return user_info_map


def build_contest_max_solves(all_stats, contest_ids):
    contest_max_solves = {}
    for contest_id in contest_ids:
        solves_list = list(all_stats[contest_id]["results"].values())
        contest_max_solves[contest_id] = max(solves_list) if solves_list else 0
    return contest_max_solves


def generate_all_contests_csv(all_stats, contest_ids, form_csv_path, output_csv_path):
    """
    Maps vjudge handles to form info and lists all contest solves.
    Columns: name, vjudge handle, session, department, [contest_ids...], total_solve_count
    """
    print(f"[*] Mapping data against '{form_csv_path}' for all-contest table...")

    user_info_map = build_user_info_map(form_csv_path)

    final_rows = []
    all_handles = set(user_info_map.keys())
    for contest_id in contest_ids:
        all_handles.update(all_stats[contest_id]["results"].keys())

    for handle in all_handles:
        name = user_info_map.get(handle, {}).get("name", handle)
        session = user_info_map.get(handle, {}).get("session", "Unknown")
        department = user_info_map.get(handle, {}).get("department", "Unknown")

        contest_solves = []
        total_solve_count = 0
        for contest_id in contest_ids:
            solves = all_stats[contest_id]["results"].get(handle, 0)
            contest_solves.append(solves)
            total_solve_count += solves

        final_rows.append(
            {
                "name": name,
                "vjudge handle": handle,
                "session": session,
                "department": department,
                "contest_solves": contest_solves,
                "total_solve_count": total_solve_count,
            }
        )

    final_rows.sort(key=lambda x: (-x["total_solve_count"], x["name"].lower()))

    with open(output_csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        header = ["name", "vjudge handle", "session", "department"] + [
            f"Contest {contest_id}" for contest_id in contest_ids
        ] + ["total_solve_count"]
        writer.writerow(header)

        for row in final_rows:
            writer.writerow(
                [row["name"], row["vjudge handle"], row["session"], row["department"]]
                + row["contest_solves"]
                + [row["total_solve_count"]]
            )

    print(f"[+] All-contest CSV generated: '{output_csv_path}'")


def generate_leaderboard_csv(
    all_stats,
    saturday_ids,
    monday_ids,
    form_csv_path,
    output_csv_path,
    k_percent,
    saturday_weight,
    monday_weight,
):
    """
    Computes leaderboard using top k% contests per category.
    Columns: name, vjudge handle, session, department, [normalized contests...],
    best_saturday_sum, best_monday_sum, final_score
    """
    print(f"[*] Mapping data against '{form_csv_path}' for leaderboard...")

    user_info_map = build_user_info_map(form_csv_path)
    contest_ids = saturday_ids + monday_ids

    final_rows = []
    all_handles = set(user_info_map.keys())
    for contest_id in contest_ids:
        all_handles.update(all_stats[contest_id]["results"].keys())

    contest_max_solves = build_contest_max_solves(all_stats, contest_ids)

    saturday_take = int((k_percent / 100) * len(saturday_ids))
    monday_take = int((k_percent / 100) * len(monday_ids))

    for handle in all_handles:
        name = user_info_map.get(handle, {}).get("name", handle)
        session = user_info_map.get(handle, {}).get("session", "Unknown")
        department = user_info_map.get(handle, {}).get("department", "Unknown")

        normalized_values = {}
        for contest_id in contest_ids:
            solves = all_stats[contest_id]["results"].get(handle, 0)
            max_solves = contest_max_solves.get(contest_id, 0)
            normalized_values[contest_id] = (solves / max_solves) if max_solves > 0 else 0.0

        saturday_values = [normalized_values[cid] for cid in saturday_ids]
        monday_values = [normalized_values[cid] for cid in monday_ids]

        best_saturday_sum = sum(sorted(saturday_values, reverse=True)[:saturday_take])
        best_monday_sum = sum(sorted(monday_values, reverse=True)[:monday_take])

        denominator = (saturday_weight * saturday_take) + (monday_weight * monday_take)
        final_score = (
            ((saturday_weight * best_saturday_sum) + (monday_weight * best_monday_sum))
            / denominator
            * 100
            if denominator > 0
            else 0.0
        )

        final_rows.append(
            {
                "name": name,
                "vjudge handle": handle,
                "session": session,
                "department": department,
                "normalized_values": [normalized_values[cid] for cid in contest_ids],
                "best_saturday_sum": best_saturday_sum,
                "best_monday_sum": best_monday_sum,
                "final_score": final_score,
            }
        )

    final_rows.sort(key=lambda x: (-x["final_score"], x["name"].lower()))

    with open(output_csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        header = ["name", "vjudge handle", "session", "department"] + [
            f"Contest {contest_id} normalized" for contest_id in contest_ids
        ] + ["best_saturday_sum", "best_monday_sum", "final_score"]
        writer.writerow(header)

        for row in final_rows:
            writer.writerow(
                [row["name"], row["vjudge handle"], row["session"], row["department"]]
                + row["normalized_values"]
                + [row["best_saturday_sum"], row["best_monday_sum"], row["final_score"]]
            )

    print(f"[+] Leaderboard CSV generated: '{output_csv_path}'")

def scrape_vjudge_multi():
    all_contest_stats = {}
    contest_ids = SATURDAY_CONTESTS + MONDAY_CONTESTS
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context()
        page = context.new_page()

        # Login once
        print("[*] Logging in to Vjudge...")
        page.goto("https://vjudge.net/")
        page.wait_for_load_state("networkidle")
        page.locator("a:has-text('Login')").first.click()
        page.get_by_placeholder("Username or Email", exact=True).fill(USERNAME)
        page.get_by_placeholder("Password", exact=True).fill(PASSWORD)
        page.get_by_placeholder("Password", exact=True).press("Enter")
        page.wait_for_selector("input[placeholder='Password']", state="hidden", timeout=60000)

        # Scrape each contest
        for contest_id in contest_ids:
            rank_url = f"https://vjudge.net/contest/rank/single/{contest_id}"
            print(f"[*] Fetching Contest {contest_id}...")
            
            api_response = context.request.get(rank_url)
            if api_response.ok:
                data = api_response.json()
                # Store results for this contest
                all_contest_stats[contest_id] = {"results": get_solve_counts(data)}
            else:
                print(f"[-] Failed to fetch contest {contest_id}. Status: {api_response.status}")

        # Process and save
        all_results_filename = "all_contest_results.csv"
        leaderboard_filename = "main_leaderboard_results.csv"

        generate_all_contests_csv(
            all_contest_stats,
            contest_ids,
            FORM_CSV_FILENAME,
            all_results_filename,
        )
        generate_leaderboard_csv(
            all_contest_stats,
            SATURDAY_CONTESTS,
            MONDAY_CONTESTS,
            FORM_CSV_FILENAME,
            leaderboard_filename,
            K_PERCENT,
            SATURDAY_WEIGHT,
            MONDAY_WEIGHT,
        )
        
        browser.close()

if __name__ == "__main__":
    scrape_vjudge_multi()