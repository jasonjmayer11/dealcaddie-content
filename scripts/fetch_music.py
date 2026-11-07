#!/usr/bin/env python3
"""One-off: collect CC0 tracks from FreePD category pages for the reel music rotation.
Writes <out>/index.json (title guess, page, url, seconds, nearby description) and the MP3s."""
import html, json, os, re, subprocess, sys, urllib.parse, urllib.request
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
pages = ["upbeat", "electronic", "misc", "scoring", "world", "comedy"]
UA = {"User-Agent": "Mozilla/5.0 (DealCaddie content bot)"}
items, seen = [], set()
for p in pages:
    url = f"https://freepd.com/{p}.php"
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf-8", "replace")
    except Exception as e:
        print("page fail", url, e); continue
    for m in re.finditer(r'''(?:href|src|data-src|value)=["']([^"']+\.mp3)["']''', raw, re.I):
        u = urllib.parse.urljoin(url, html.unescape(m.group(1)))
        if u in seen: continue
        seen.add(u)
        ctx = re.sub(r"<[^>]+>", " ", raw[max(0, m.start() - 900):m.start() + 400])
        ctx = re.sub(r"\s+", " ", html.unescape(ctx)).strip()
        items.append({"page": p, "url": u, "file": urllib.parse.unquote(u.rsplit("/", 1)[-1]), "context": ctx[-700:]})
print(len(items), "tracks found")
for it in items:
    dst = os.path.join(out, it["file"])
    try:
        with open(dst, "wb") as f:
            f.write(urllib.request.urlopen(urllib.request.Request(it["url"], headers=UA), timeout=60).read())
        it["seconds"] = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", dst]).decode().strip() or 0)
        it["bytes"] = os.path.getsize(dst)
    except Exception as e:
        it["error"] = str(e)
json.dump(items, open(os.path.join(out, "index.json"), "w"), indent=1)
print(json.dumps([(i["page"], i["file"], i.get("seconds")) for i in items], indent=0))
