#!/usr/bin/env python3
"""
Expensify "Help Wanted" issue monitor -> Discord webhook.
GITHUB ACTIONS VERSION (NIGHT SHIFT).

Runs once per workflow trigger, scheduled by .github/workflows/monitor.yml
to fire only during the night shift window (Frankfurt 18:00-08:00).

State is persisted to seen_issues.json which is committed back to the repo
after every run.
"""

import json
import os
import sys
from pathlib import Path

import requests

# ----------------------------- Config -----------------------------------
REPO = "Expensify/App"
LABEL = "Help Wanted"
STATE_FILE = Path("seen_issues.json")

DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # provided automatically by Actions

ANNOUNCE_BACKLOG_ON_FIRST_RUN = False


# ----------------------------- GitHub -----------------------------------
def fetch_help_wanted_issues():
    """Return all OPEN issues currently labeled Help Wanted (PRs filtered out)."""
    url = f"https://api.github.com/repos/{REPO}/issues"
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    issues = []
    page = 1
    while True:
        params = {"labels": LABEL, "state": "open", "per_page": 100, "page": page}
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        batch = r.json()
        batch = [i for i in batch if "pull_request" not in i]  # strip PRs
        issues.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return issues


# ----------------------------- State ------------------------------------
def load_seen():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_seen(seen):
    STATE_FILE.write_text(json.dumps(sorted(seen), indent=2))


# ----------------------------- Discord ----------------------------------
def post_to_discord(issue):
    body_preview = (issue.get("body") or "").strip()
    if len(body_preview) > 400:
        body_preview = body_preview[:400].rstrip() + "..."

    label_names = ", ".join(l["name"] for l in issue.get("labels", [])) or "—"

    payload = {
        "embeds": [{
            "title": f"#{issue['number']} · {issue['title']}"[:256],
            "url": issue["html_url"],
            "description": body_preview or "_No description_",
            "color": 0x2ECC71,
            "fields": [
                {"name": "Labels", "value": label_names[:1024], "inline": False},
            ],
            "footer": {"text": f"{REPO} · opened by {issue['user']['login']}"},
            "timestamp": issue["created_at"],
        }]
    }
    r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
    r.raise_for_status()


# ----------------------------- Main -------------------------------------
def main():
    seen = load_seen()
    first_run = len(seen) == 0
    print(f"Loaded {len(seen)} previously-seen issue IDs.")

    issues = fetch_help_wanted_issues()
    current_ids = {i["id"] for i in issues}

    new_ids = current_ids - seen
    dropped_ids = seen - current_ids

    print(f"GitHub returned {len(current_ids)} Help Wanted issues.")
    print(f"  -> {len(new_ids)} newly labeled")
    print(f"  -> {len(dropped_ids)} dropped from Help Wanted (label removed or issue closed)")

    if first_run and not ANNOUNCE_BACKLOG_ON_FIRST_RUN:
        print(f"First run: cataloguing {len(current_ids)} existing issues silently.")
    else:
        for issue in issues:
            if issue["id"] in new_ids:
                print(f"  NEW: #{issue['number']} {issue['title']}")
                post_to_discord(issue)

    save_seen(current_ids)
    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[fatal] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
