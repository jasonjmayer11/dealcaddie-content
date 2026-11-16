#!/usr/bin/env python3
"""List or cancel scheduled Upload-Post jobs (used when a better video takes a slot).

python3 scripts/schedule_admin.py list
python3 scripts/schedule_admin.py cancel <job_id>
"""
import os, sys, requests
key = os.environ["UPLOAD_POST_API_KEY"]; H = {"Authorization": f"Apikey {key}"}
API = "https://api.upload-post.com/api/uploadposts/schedule"
if sys.argv[1] == "list":
    items, off = [], 0
    while True:
        r = requests.get(API, headers=H, params={"limit": 100, "offset": off}, timeout=60); r.raise_for_status(); j = r.json()
        items += j.get("scheduled_posts", []); off += 100
        if off >= j.get("total", 0): break
    for p in sorted(items, key=lambda p: p.get("scheduled_date") or ""):
        print(f"{p.get('scheduled_date')}\t{p.get('job_id')}\t{p.get('source_filename') or ''}\t{(p.get('title') or '')[:70]}")
    print(f"{len(items)} scheduled")
elif sys.argv[1] == "cancel":
    r = requests.delete(f"{API}/{sys.argv[2]}", headers=H, timeout=60); print(r.status_code, r.text); r.raise_for_status()
