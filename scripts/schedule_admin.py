#!/usr/bin/env python3
"""List or cancel scheduled Upload-Post jobs (used when a better video takes a slot).

python3 scripts/schedule_admin.py list
python3 scripts/schedule_admin.py cancel <job_id>
python3 scripts/schedule_admin.py accounts      # connected accounts + LinkedIn/Facebook page ids
python3 scripts/schedule_admin.py history       # what has actually been published
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
elif sys.argv[1] == "accounts":
    B = "https://api.upload-post.com/api/uploadposts"
    for path, params in (("/users", {}), ("/users/linkedin-page", {"profile_username": "dealcaddie"}),
                         ("/linkedin/pages", {"profile": "dealcaddie"}), ("/facebook/pages", {"profile": "dealcaddie"})):
        r = requests.get(B + path, headers=H, params=params, timeout=60)
        txt = r.text
        import re as _re
        txt = _re.sub(r'"(access_token|token|refresh_token)"\s*:\s*"[^"]*"', r'"\1":"<hidden>"', txt)
        print(f"== GET {path} -> {r.status_code}\n{txt[:6000]}\n")
elif sys.argv[1] == "history":
    rows, page = [], 1
    while page <= 20:
        r = requests.get("https://api.upload-post.com/api/uploadposts/history", headers=H, params={"page": page, "limit": 50}, timeout=60)
        if r.status_code != 200: print(r.status_code, r.text[:500]); break
        j = r.json(); h = j.get("history") or j.get("items") or j.get("data") or []
        if page == 1: print("keys:", list(j.keys()), "| first item keys:", list(h[0].keys()) if h else None)
        rows += h
        if len(h) < 50: break
        page += 1
    for x in rows:
        print("\t".join(str(x.get(k, "")) for k in ("upload_timestamp", "platform", "success", "request_id", "media_name", "post_url"))[:300],
              "|", (x.get("post_title") or x.get("title") or "")[:60])
    print(len(rows), "history rows")
