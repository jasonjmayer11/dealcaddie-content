#!/usr/bin/env python3
"""Assemble a DealCaddie Deal Verdict reel.

Usage: python3 scripts/assemble.py <workdir> <out.mp4>
Reads raw.webm, marks.json, data.json, optional photo.jpg from <workdir>.
Writes the 1080x1920 MP4, caption.txt and cover.jpg next to it.

Layout rules (Instagram Reels / TikTok safe zones at 1080x1920):
  - nothing important above y=260 (app top bar) or below y=1450 (caption, username, audio)
  - nothing important right of x=900 (like / comment / share rail)
"""
import json, os, re, subprocess, sys
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FB = os.path.join(ROOT, "fonts", "Poppins-Bold.ttf")
W, H, FPS = 1080, 1920, 30
FOREST, CREAM, GOLD = (26, 92, 53), (250, 247, 240), (201, 168, 76)
SAFE_X0, SAFE_X1 = 60, 900          # usable horizontal band
SAFE_CX = (SAFE_X0 + SAFE_X1) // 2  # text centred in the band, not the frame

work, out_mp4 = sys.argv[1], sys.argv[2]
out_dir = os.path.dirname(os.path.abspath(out_mp4))
marks = json.load(open(os.path.join(work, "marks.json")))
data = json.load(open(os.path.join(work, "data.json")))
raw = os.path.join(work, "raw.webm")


def sh(cmd):
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------- copy
def short_price(p):
    n = int(re.sub(r"[^0-9]", "", p or "0") or 0)
    if n >= 1_000_000:
        return f"${n/1e6:.2f}M".replace(".00M", "M")
    return f"${round(n/1000)}K" if n else "this"

def city_of(line):
    return (line or "").split(",")[0].strip()

def pick_copy(d):
    price, city = short_price(d.get("price")), city_of(d.get("cityLine"))
    cf_s = d.get("ltrCashflow") or ""
    try:
        cf = float(re.sub(r"[^0-9.\-]", "", cf_s.replace("\u2212", "-"))) if cf_s else None
    except ValueError:
        cf = d.get("ltrCashflowNum")
    score = d.get("score") or "?"
    score = score[:-2] if score.endswith(".0") else score
    strat = d.get("strategies") or {}
    def num(s):
        try: return float(re.sub(r"[^0-9.\-]", "", s.replace("−", "-")))
        except Exception: return None
    best_alt = max(((k, v) for k, v in strat.items() if k not in ("LTR", "FLIP") and num(v) is not None),
                   key=lambda kv: num(kv[1]), default=(None, None))
    names = {"MTR": "mid-term rental", "STR": "Airbnb", "S8": "Section 8", "HH": "house hack", "BRRRR": "BRRRR"}
    where = f"{price} {city} house." if city else f"This {price} house."

    if cf is not None and cf >= 200:
        hook = [f"This {where}" if city else where, "Guess the cashflow."]
        reveal = [f"{score}/10 deal score.", f"{cf_s}/mo as a rental."]
    elif cf is not None and cf < 0:
        hook = [where, "Looks like a deal. Watch."]
        reveal = [f"Loses {cf_s.replace('-', '').replace('−', '')}/mo", "as a long-term rental."]
    else:
        hook = [where, "Does it cash flow?"]
        reveal = ["Barely.", f"{cf_s}/mo after every expense."]

    max_offer, asking = d.get("maxOffer"), d.get("price")
    if cf is not None and cf < 0 and best_alt[0] and (num(best_alt[1]) or 0) > 0:
        proof = [f"As a {names.get(best_alt[0], best_alt[0])}:", f"{best_alt[1]}/mo"]
    elif cf is not None and cf < 200 and max_offer and asking:
        proof = [f"Max offer: {max_offer}", f"vs {short_price(asking)} asking"]
    elif d.get("coc") and d.get("cashToClose"):
        proof = [f"{d['coc']} cash-on-cash", f"on {d['cashToClose']} to close"]
    else:
        proof = ["Taxes, insurance, rent comps.", "Pulled automatically."]

    cta = ["Run any address free", "dealcaddie.ai"]
    return hook, reveal, proof, cta


hook, reveal, proof, cta = pick_copy(data)


# ---------------------------------------------------------------- text plates
def plate(lines, y, name, size=70, gold_last=True):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(FB, size)
    max_w = SAFE_X1 - SAFE_X0 - 60
    while max(d.textlength(l, font=f) for l in lines) > max_w and size > 44:
        size -= 2
        f = ImageFont.truetype(FB, size)
    pad, gap = 26, 14
    yy = y
    for i, ln in enumerate(lines):
        bb = d.textbbox((0, 0), ln, font=f)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        x = SAFE_CX - tw // 2
        d.rounded_rectangle([x - pad, yy - pad, x + tw + pad, yy + th + pad], radius=16, fill=FOREST + (242,))
        col = GOLD if (gold_last and i == len(lines) - 1 and len(lines) > 1) else CREAM
        d.text((x, yy - bb[1]), ln, font=f, fill=col)
        yy += th + pad * 2 + gap
    p = os.path.join(work, f"plate_{name}.png")
    img.save(p)
    return p


# ---------------------------------------------------------------- opener image
def cover_crop(im, w, h):
    return ImageOps.fit(im.convert("RGB"), (w, h), Image.LANCZOS, centering=(0.5, 0.45))

photo = os.path.join(work, "photo.jpg")
opener = os.path.join(work, "opener.jpg")
if os.path.exists(photo):
    base = Image.open(photo)
else:
    # fallback: the hero card from the first results frame
    tmp = os.path.join(work, "_hero.png")
    sh(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(marks["results"]), "-i", raw, "-frames:v", "1", tmp])
    base = Image.open(tmp).crop((0, 60, 540, 520))
cover_crop(base, W * 2, H * 2).save(opener, quality=92)

# ---------------------------------------------------------------- segments
OPEN_S = 2.4
SPEED = 1.6
seg_open = os.path.join(work, "s1.mp4")
seg_paste = os.path.join(work, "s2.mp4")
seg_res = os.path.join(work, "s3.mp4")
scale = f"scale={W}:{H}:flags=lanczos,fps={FPS},format=yuv420p,setsar=1"

sh(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", opener, "-t", str(OPEN_S),
    "-vf", f"zoompan=z='min(zoom+0.0011,1.10)':d={int(OPEN_S*FPS)}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},format=yuv420p,setsar=1",
    "-c:v", "libx264", "-preset", "fast", "-crf", "18", seg_open])

p_start, p_end = max(0, marks["ready"] - 0.2), marks["submitted"] + 0.3
sh(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{p_start:.2f}", "-to", f"{p_end:.2f}", "-i", raw,
    "-vf", f"setpts=PTS/{SPEED},{scale}", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "18", seg_paste])

# start once the page has settled (photo loaded, splash gone), not when the DOM first appears
r_start = max(marks.get("results", marks["results_dom"]) - 0.4, marks["submitted"])
sh(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{r_start:.2f}", "-to", f"{marks['end']:.2f}", "-i", raw,
    "-vf", scale, "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "18", seg_res])

def dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", p]).decode().strip())

d1, d2, d3 = dur(seg_open), dur(seg_paste), dur(seg_res)
t_res = d1 + d2

# ---------------------------------------------------------------- overlay schedule
# time each text beat to the tab clicks when we have them
def rel(k, default):
    return t_res + (marks[k] - r_start) if k in marks else t_res + default
t_cash, t_ai = rel("tab_cashflow", 3.4), rel("tab_ai", 6.0)
plates = [
    (plate(hook, 520, "hook", 74), 0, d1),
    (plate(["One paste.", "Full underwrite."], 1120, "paste", 66), d1, t_res),
    (plate(reveal, 1140, "reveal", 72), t_res + 0.2, t_cash),
    (plate(proof, 1140, "proof", 62), t_cash + 0.3, t_ai + 0.6),
    (plate(cta, 1140, "cta", 64), t_ai + 0.6, t_res + d3 + 1),
]

inputs = ["-i", seg_open, "-i", seg_paste, "-i", seg_res]
for p, _, _ in plates:
    inputs += ["-i", p]
fc = "[0:v][1:v][2:v]concat=n=3:v=1:a=0[base];"
last = "base"
for i, (_, a, b) in enumerate(plates):
    nxt = f"v{i}"
    fc += f"[{last}][{i+3}:v]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[{nxt}];"
    last = nxt
fc = fc.rstrip(";")

sh(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", fc, "-map", f"[{last}]",
    "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
    "-movflags", "+faststart", out_mp4])

# ---------------------------------------------------------------- cover + caption
cov = Image.open(opener).resize((W, H), Image.LANCZOS).convert("RGBA")
cov.alpha_composite(Image.open(plates[0][0]))
cov.convert("RGB").save(os.path.join(out_dir, "cover.jpg"), quality=90)

def sentence(lines):
    t = ' '.join(l.strip() for l in lines).strip()
    return t if t.endswith(('.', '!', '?')) else t + '.'

city = city_of(data.get("cityLine"))
city_tag = "#" + re.sub(r"[^a-z]", "", city.lower()) + "realestate" if city else "#realestatedeals"
specs = " · ".join(x for x in [
    f"{data['beds']} bed" if data.get("beds") else None,
    f"{data['baths']} bath" if data.get("baths") else None,
    f"{data['sqft']} sqft" if data.get("sqft") else None] if x)
caption = f"""{' '.join(hook)}

{specs}. Pasted the Zillow link into DealCaddie: {sentence(reveal)} {sentence(proof)}

Taxes, insurance and rent comps pulled automatically — about 10 seconds start to finish.

Comment a city and I'll run the next one 👇

Try it free · dealcaddie.ai

#realestateinvesting #rentalproperty #cashflow #realestateinvestor {city_tag}
"""
open(os.path.join(out_dir, "caption.txt"), "w").write(caption)
json.dump({"hook": hook, "reveal": reveal, "proof": proof, "duration": round(dur(out_mp4), 1),
           "had_photo": os.path.exists(photo), **data},
          open(os.path.join(out_dir, "meta.json"), "w"), indent=2)
print(f"built {out_mp4} ({dur(out_mp4):.1f}s, photo={'yes' if os.path.exists(photo) else 'fallback'})")
