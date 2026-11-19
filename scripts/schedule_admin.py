#!/usr/bin/env python3
"""List or cancel scheduled Upload-Post jobs (used when a better video takes a slot).

python3 scripts/schedule_admin.py list
python3 scripts/schedule_admin.py cancel <job_id>
python3 scripts/schedule_admin.py accounts      # connected accounts + LinkedIn/Facebook page ids
python3 scripts/schedule_admin.py history       # what has actually been published
"""
import json, os, sys, requests
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
elif sys.argv[1] == "analytics":
    B = "https://api.upload-post.com/api"
    r = requests.get(f"{B}/analytics/dealcaddie", headers=H, params={"platforms": "instagram,tiktok,youtube,Facebook,X,threads,Linkedin"}, timeout=90)
    print("== profile", r.status_code); print(r.text[:5000])
    rows, page = [], 1
    while page <= 10:
        r = requests.get(f"{B}/uploadposts/history", headers=H, params={"page": page, "limit": 50}, timeout=60)
        if r.status_code != 200: break
        h = r.json().get("history") or []; rows += h
        if len(h) < 50: break
        page += 1
    seen = set()
    print("== posts")
    for x in rows:
        rid = (x.get("request_id") or "").strip()
        if not rid or rid in seen or not x.get("success"): continue
        seen.add(rid)
        a = requests.get(f"{B}/uploadposts/post-analytics/{rid}", headers=H, timeout=60)
        if a.status_code != 200: print(rid, "->", a.status_code); continue
        j = a.json(); title = ((j.get("post") or {}).get("post_title") or "")[:50]; ts = (j.get("post") or {}).get("upload_timestamp", "")
        for pf, v in (j.get("platforms") or {}).items():
            m = (v or {}).get("post_metrics") or {}
            print("\t".join([str(ts)[:16], pf, rid[:44], json.dumps(m)[:220], title]))
elif sys.argv[1] == "cancelmany":
    for jid in [x.strip() for x in sys.argv[2].split(",") if x.strip()]:
        r = requests.delete(f"{API}/{jid}", headers=H, timeout=60); print(jid, r.status_code, r.text[:120])
elif sys.argv[1] == "find":
    page = 1
    while page <= 10:
        r = requests.get("https://api.upload-post.com/api/uploadposts/history", headers=H, params={"page": page, "limit": 50}, timeout=60)
        h = r.json().get("history") or []
        for x in h:
            if sys.argv[2].lower() in json.dumps(x).lower():
                print(json.dumps({k: x.get(k) for k in ("upload_timestamp", "platform", "success", "request_id", "platform_post_id", "post_id", "post_url", "media_name", "profile_username")}))
        if len(h) < 50: break
        page += 1
elif sys.argv[1] == "unpublish":
    pf, pid = sys.argv[2].split(":", 1)
    r = requests.post("https://api.upload-post.com/api/uploadposts/posts/unpublish", headers=H,
                      json={"platform": pf, "user": "dealcaddie", "post_id": pid}, timeout=60)
    print(r.status_code, r.text)
