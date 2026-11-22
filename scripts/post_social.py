#!/usr/bin/env python3
"""Post an approved reel to social via Upload-Post (https://docs.upload-post.com).

Usage: python3 scripts/post_social.py <video.mp4> <title> <caption_file> [cover.jpg]
Env:   UPLOAD_POST_API_KEY   (secret)
       UPLOAD_POST_USER      profile name in Upload-Post (default: dealcaddie)
       POST_PLATFORMS        comma list (default: instagram,facebook,youtube; add tiktok on a paid plan)
       IDEMPOTENCY_KEY       reel slug, so a retried job never double-posts
"""
import json, os, re, subprocess, sys, time
import requests

video, title, caption_file = sys.argv[1], sys.argv[2], sys.argv[3]
cover = sys.argv[4] if len(sys.argv) > 4 and os.path.exists(sys.argv[4]) else None
caption = open(caption_file, encoding="utf-8").read().strip()
key = os.environ.get("UPLOAD_POST_API_KEY")
if not key:
    sys.exit("UPLOAD_POST_API_KEY secret is missing — add it in repo Settings → Secrets → Actions")
user = os.environ.get("UPLOAD_POST_USER") or "dealcaddie"
platforms = [p.strip() for p in (os.environ.get("POST_PLATFORMS") or "instagram,facebook,youtube").split(",") if p.strip()]
tag = os.environ.get("IDEMPOTENCY_KEY") or os.path.basename(video)
MAIN = {"instagram", "facebook", "youtube", "tiktok"}
# X / Threads / LinkedIn go out as their own jobs (often at other times than the main post), so they
# need their own idempotency key or Upload-Post would treat them as a retry of the main post.
idem = tag if set(platforms) <= MAIN else f"{tag}-{'-'.join(sorted(platforms))}"
# Platform-native copy for X / Threads / LinkedIn, written per video: social-copy/<tag>.json
_cp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "social-copy", tag + ".json")
copy = json.load(open(_cp, encoding="utf-8")) if os.path.exists(_cp) else {}
for p in ("x", "threads", "linkedin"):
    if p in platforms and not copy.get(p):
        sys.exit(f"no {p} copy for {tag}: add social-copy/{tag}.json before posting to {p}")

short = title[:90]

def tracked(text, source, medium):
    """Swap the bare 'dealcaddie.ai' for a clickable UTM link (YouTube/Facebook make links clickable;
    Instagram/TikTok captions don't, so those rely on the UTM'd bio link). Shows up in Plausible
    → Sources/Campaigns and on the signup row (first-touch attribution in the app)."""
    url = f"https://www.dealcaddie.ai/?utm_source={source}&utm_medium={medium}&utm_campaign=reels&utm_content={tag}"
    out, n = re.subn(r"(?<![\w/.#@])dealcaddie\.ai(?![\w/])", url, text, count=1)
    return out if n else text + "\n\n" + url
# Every DealCaddie post carries a one-line disclaimer (added here so no post can forget it).
DISC_LONG = "Education only. Not financial, tax or legal advice."
DISC_SHORT = "Not financial advice."
def disc(text, limit, short=False, fit=lambda t: t):
    if user != "dealcaddie" or "not financial" in text.lower(): return text
    for d in ([DISC_SHORT] if short else [DISC_LONG, DISC_SHORT]):
        t = text.rstrip() + "\n\n" + d
        if len(fit(t)) <= limit: return t
    return text
caption = disc(caption, 2200)
for _p, _lim, _src in (("x", 280, None), ("threads", 500, "threads"), ("linkedin", 3000, "linkedin")):
    if copy.get(_p):
        copy[_p] = disc(copy[_p], _lim, short=(_p == "x"), fit=(lambda t, s=_src: tracked(t, s, "video")) if _src else (lambda t: t))
fields = [("user", user)] + [("platform[]", p) for p in platforms] + [
    ("title", short),
    ("description", caption),
    # Instagram / Facebook / TikTok show the full caption
    ("instagram_title", caption[:2200]),
    ("media_type", "REELS"),
    ("audio_name", "DealCaddie · Deal Verdict"),          # label instead of "Original audio"
    ("share_to_feed", "true"),
    ("facebook_title", short),
    ("facebook_description", tracked(caption, "facebook", "reel")),
    ("tiktok_title", caption[:2200]),
    ("brand_organic_toggle", "true"),     # TikTok: disclose "promoting my own business" (unlabeled self-promo gets removed)
    # YouTube: short title, full caption in the description, public Short, not for kids
    ("youtube_title", (short + " #shorts")[:100]),
    ("youtube_description", tracked(caption, "youtube", "shorts")[:4900]),
    ("privacyStatus", "public"),
    ("selfDeclaredMadeForKids", "false"),
    ("request_id", idem),
]
if "x" in platforms:
    # X: 280 characters, one post (no auto-thread), no link (Upload-Post strips clickable URLs on X)
    fields += [("x_title", copy["x"][:280]), ("x_long_text_as_post", "false"),
               ("x_alt_text", f"Video: {short}. Screen recording of the DealCaddie app with captions.")]
if "threads" in platforms:
    fields += [("threads_title", tracked(copy["threads"], "threads", "video")[:500]),
               ("threads_topic_tag", "Real Estate Investing"), ("threads_reply_control", "everyone")]
if "linkedin" in platforms:
    fields += [("linkedin_title", short), ("linkedin_description", tracked(copy["linkedin"], "linkedin", "video")[:3000]),
               ("visibility", "PUBLIC")]       # the DealCaddie company page is pinned in Upload-Post

sched = (os.environ.get("SCHEDULE_AT") or "").strip()
if sched:
    fields.append(("scheduled_date", sched))            # ISO-8601, e.g. 2026-11-08T15:00:00Z
    print("scheduled for", sched)
print(f"posting {os.path.basename(video)} to {platforms} as '{user}'")
if "x" in platforms and len(platforms) > 1:
    # X caps uploads at 1200x1900 and wants its own request: post X separately, then the rest
    env = dict(os.environ, POST_PLATFORMS="x")
    subprocess.run([sys.executable, *sys.argv], env=env, check=True)
    platforms = [p for p in platforms if p != "x"]
    fields = [f for f in fields if f[0] != "platform[]" and not f[0].startswith("x_")]
    fields = [f for f in fields if f[0] != "request_id"] + [("request_id", f"{tag}-{'-'.join(sorted(platforms))}")]
    fields[1:1] = [("platform[]", p) for p in platforms]
    idem = f"{tag}-{'-'.join(sorted(platforms))}"
    print("then", platforms)
if platforms == ["x"]:
    small = os.path.join(os.path.dirname(os.path.abspath(video)), "x-" + os.path.basename(video))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", video, "-vf", "scale=900:1600:flags=lanczos",
                    "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", "30",
                    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", small], check=True)
    video = small; print("X copy: 900x1600")
files = [("video", (os.path.basename(video), open(video, "rb"), "video/mp4"))]
if cover:
    # our own cover (the price/specs frame) instead of the platform picking frame 0
    for field in ("cover_image", "facebook_thumbnail", "thumbnail"):     # Instagram, Facebook, YouTube
        files.append((field, (os.path.basename(cover), open(cover, "rb"), "image/jpeg")))
    # TikTok can't take an uploaded image — it picks a frame. Narrated demos open on their designed cover.
    fields.append(("cover_timestamp", "80" if os.path.basename(video).startswith(("demo-", "versus-")) else "1600"))
    print("cover:", cover)
if os.environ.get("DRY_RUN"):
    for k, v in fields:
        if k in ("description", "instagram_title", "tiktok_title", "facebook_description", "youtube_description"): v = v[:40] + "…"
        print(f"  {k}: {v!r}")
    print("  files:", [(f[0], f[1][0]) for f in files], "| Idempotency-Key:", idem); sys.exit(0)
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
