#!/usr/bin/env python3
"""Post an approved reel to social via Upload-Post (https://docs.upload-post.com).

Usage: python3 scripts/post_social.py <video.mp4> <title> <caption_file> [cover.jpg]
Env:   UPLOAD_POST_API_KEY   (secret)
       UPLOAD_POST_USER      profile name in Upload-Post (default: dealcaddie)
       POST_PLATFORMS        comma list (default: instagram,facebook,youtube; add tiktok on a paid plan)
       IDEMPOTENCY_KEY       reel slug, so a retried job never double-posts
"""
import json, os, sys, time
import requests

video, title, caption_file = sys.argv[1], sys.argv[2], sys.argv[3]
cover = sys.argv[4] if len(sys.argv) > 4 and os.path.exists(sys.argv[4]) else None
caption = open(caption_file, encoding="utf-8").read().strip()
key = os.environ.get("UPLOAD_POST_API_KEY")
if not key:
    sys.exit("UPLOAD_POST_API_KEY secret is missing — add it in repo Settings → Secrets → Actions")
user = os.environ.get("UPLOAD_POST_USER") or "dealcaddie"
platforms = [p.strip() for p in (os.environ.get("POST_PLATFORMS") or "instagram,facebook,youtube").split(",") if p.strip()]
idem = os.environ.get("IDEMPOTENCY_KEY") or os.path.basename(video)

short = title[:90]
fields = [("user", user)] + [("platform[]", p) for p in platforms] + [
    ("title", short),
    ("description", caption),
    # Instagram / Facebook / TikTok show the full caption
    ("instagram_title", caption[:2200]),
    ("media_type", "REELS"),
    ("share_to_feed", "true"),
    ("facebook_title", short),
    ("facebook_description", caption),
    ("tiktok_title", caption[:2200]),
    # YouTube: short title, full caption in the description, public Short, not for kids
    ("youtube_title", (short + " #shorts")[:100]),
    ("youtube_description", caption[:4900]),
    ("privacyStatus", "public"),
    ("selfDeclaredMadeForKids", "false"),
    ("request_id", idem),
]
print(f"posting {os.path.basename(video)} to {platforms} as '{user}'")
files = [("video", (os.path.basename(video), open(video, "rb"), "video/mp4"))]
if cover:
    # our own cover (the price/specs frame) instead of the platform picking frame 0
    for field in ("cover_image", "facebook_thumbnail", "thumbnail"):     # Instagram, Facebook, YouTube
        files.append((field, (os.path.basename(cover), open(cover, "rb"), "image/jpeg")))
    fields.append(("cover_timestamp", "1600"))                           # TikTok: frame at 1.6s
    print("cover:", cover)
r = requests.post("https://api.upload-post.com/api/upload",
                  headers={"Authorization": f"Apikey {key}", "Idempotency-Key": idem},
                  data=fields, files=files, timeout=300)
print("HTTP", r.status_code)
try:
    body = r.json()
    print(json.dumps(body, indent=2)[:4000])
except ValueError:
    print(r.text[:4000]); body = {}
summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a") as s:
        s.write(f"### Posted to {', '.join(platforms)}\nHTTP {r.status_code}\n\n```json\n{json.dumps(body, indent=2)[:3000]}\n```\n")
if r.status_code >= 400 or body.get("success") is False:
    sys.exit("Upload-Post rejected the post — see the response above")
