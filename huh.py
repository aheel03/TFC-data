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

# Format: [[contest_id, weight], [contest_id, weight]]
CONTEST_LIST = [[802104, 1.25], [802757, 1], [804183, 1.25]]

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

def generate_weighted_csv(all_stats, contest_ids, form_csv_path, output_csv_path):
    """
    Maps vjudge handles to form info and calculates normalized weighted sums.
    Columns: name, vjudge handle, session, [contest_ids...], normalized_weighted_score
    """
    print(f"[*] Mapping data against '{form_csv_path}'...")
    
    # 1. Read form data: {handle_lower: {name, session}}
    user_info_map = {}
    if os.path.exists(form_csv_path):
        with open(form_csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                vj_handle = row.get("Vjudge Handle", "").strip().lower()
                if vj_handle:
                    user_info_map[vj_handle] = {
                        "name": row.get("Name", "").strip(),
                        "session": row.get("Session", "").strip()
                    }

    # 2. Prepare final data rows
    final_rows = []
    # Identify all unique handles across all contests and form
    all_handles = set(user_info_map.keys())
    for c_id in contest_ids:
        all_handles.update(all_stats[c_id]["results"].keys())

    # Precompute max solves per contest for normalization.
    # If a contest has no submissions, max defaults to 0.
    contest_max_solves = {}
    for c_id in contest_ids:
        solves_list = list(all_stats[c_id]["results"].values())
        contest_max_solves[c_id] = max(solves_list) if solves_list else 0

    for handle in all_handles:
        name = user_info_map.get(handle, {}).get("name", handle)
        session = user_info_map.get(handle, {}).get("session", "Unknown")
        
        row_data = {
            "name": name,
            "vjudge handle": handle,
            "session": session,
            "individual_solves": [],
            "normalized_weighted_score": 0.0
        }

        for c_id, weight in CONTEST_LIST:
            solves = all_stats[c_id]["results"].get(handle, 0)
            row_data["individual_solves"].append(solves)
            max_solves = contest_max_solves.get(c_id, 0)
            normalized_score = (solves / max_solves) * weight if max_solves > 0 else 0.0
            row_data["normalized_weighted_score"] += normalized_score
        
        final_rows.append(row_data)

    # 3. Sort: Weighted Score (Descending), then Name (Lexicographical Ascending)
    final_rows.sort(key=lambda x: (-x["normalized_weighted_score"], x["name"].lower()))

    # 4. Write to CSV
    with open(output_csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        header = ["name", "vjudge handle", "session"] + [f"Contest {c[0]}" for c in CONTEST_LIST] + ["normalized_weighted_score"]
        writer.writerow(header)
        
        for r in final_rows:
            writer.writerow([r["name"], r["vjudge handle"], r["session"]] + r["individual_solves"] + [r["normalized_weighted_score"]])

    print(f"[+] Multi-contest weighted CSV generated: '{output_csv_path}'")

def scrape_vjudge_multi():
    all_contest_stats = {}
    
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
        for contest_id, weight in CONTEST_LIST:
            rank_url = f"https://vjudge.net/contest/rank/single/{contest_id}"
            print(f"[*] Fetching Contest {contest_id}...")
            
            api_response = context.request.get(rank_url)
            if api_response.ok:
                data = api_response.json()
                # Store results for this contest
                all_contest_stats[contest_id] = {
                    "weight": weight,
                    "results": get_solve_counts(data)
                }
            else:
                print(f"[-] Failed to fetch contest {contest_id}. Status: {api_response.status}")

        # Process and save
        output_filename = "weighted_contest_results.csv"
        generate_weighted_csv(all_contest_stats, [c[0] for c in CONTEST_LIST], FORM_CSV_FILENAME, output_filename)
        
        browser.close()

if __name__ == "__main__":
    scrape_vjudge_multi()