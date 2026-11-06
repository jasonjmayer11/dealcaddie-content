#!/usr/bin/env python3
"""Assemble a DealCaddie Deal Verdict reel from card stills.

Usage: python3 scripts/assemble.py <workdir> <out.mp4>
Reads photo.jpg, card_*.png, logo.png and data.json from <workdir>.
Writes the 1080x1920 MP4, caption.txt, cover.jpg and meta.json next to it.

Five beats, one idea each, ~3 seconds apiece:
  1. listing photo           + two-line hook
  2. property / score card   + "Deal score: 6.9/10"
  3. cashflow card           + "+$33/mo. Barely."
  4. max offer / strategies  + "Max offer: $171K"
  5. branded end card        + "Run any address free · dealcaddie.ai"

Readability rules:
  - one short line of text per beat (two on the hook), never more than ~6 words
  - text sits on its own solid plate, under the card, never on top of UI
  - the background is a dark blur of the card, so the card and the text are the only sharp things
  - motion is only a slow push-in on each still plus a soft crossfade
  - everything inside the Instagram/TikTok safe area (y 300–1430, x 60–900)
"""
import json, os, re, subprocess, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps, ImageEnhance

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FB = os.path.join(ROOT, "fonts", "Poppins-Bold.ttf")
W, H, FPS = 1080, 1920, 30
FOREST, DEEP, CREAM, GOLD = (26, 92, 53), (12, 40, 24), (250, 247, 240), (226, 190, 92)
X0, X1 = 60, 900                     # usable band; right of 900 is the like/comment rail
CX = (X0 + X1) // 2
CARD_TOP, CARD_BOT = 300, 1130       # cards live here
TEXT_MAX_Y = 1430                    # text plates must end above the caption area

work, out_mp4 = sys.argv[1], sys.argv[2]
out_dir = os.path.dirname(os.path.abspath(out_mp4))
data = json.load(open(os.path.join(work, "data.json")))
P = lambda f: os.path.join(work, f)


def sh(cmd):
    subprocess.run(cmd, check=True)


# ------------------------------------------------------------------ copy
def short_price(p):
    n = int(re.sub(r"[^0-9]", "", p or "0") or 0)
    if n >= 1_000_000:
        return f"${n/1e6:.2f}M".replace(".00M", "M")
    return f"${round(n/1000)}K" if n else "this"

def city_of(line):
    return (line or "").split(",")[0].strip()

def num(s):
    try:
        return float(re.sub(r"[^0-9.\-]", "", (s or "").replace("−", "-")))
    except ValueError:
        return None

def pick_copy(d):
    """Returns (hook_lines, [(card, line), (card, line), (card, line)])."""
    price, city = short_price(d.get("price")), city_of(d.get("cityLine"))
    cf_s = d.get("ltrCashflow") or ""
    cf = num(cf_s)
    score = d.get("score") or "?"
    score = score[:-2] if score.endswith(".0") else score
    strat = d.get("strategies") or {}
    names = {"MTR": "a mid-term rental", "STR": "an Airbnb", "S8": "Section 8", "HH": "a house hack", "BRRRR": "a BRRRR"}
    alts = [(k, v) for k, v in strat.items() if k not in ("LTR", "FLIP") and (num(v) or 0) > 0]
    best_alt = max(alts, key=lambda kv: num(kv[1]), default=None)
    where = f"{price} {city} house." if city else f"This {price} house."

    if cf is not None and cf >= 200:
        hook = [f"This {where}" if city else where, "Guess the cashflow."]
        b_cf = f"{cf_s}/mo as a rental."
    elif cf is not None and cf < 0:
        hook = [where, "Looks like a deal. Watch."]
        b_cf = f"Loses ${abs(int(cf)):,}/mo as a rental."
    else:
        hook = [where, "Does it cash flow?"]
        b_cf = f"{cf_s}/mo. Barely."

    b_score = f"{score}/10 deal score." if score not in ("?",) else "Full deal score."

    mo, asking = d.get("maxOffer"), num(d.get("price"))
    if cf is not None and cf < 0 and best_alt:
        b_proof = ("strats", f"As {names.get(best_alt[0], best_alt[0])}: {best_alt[1]}/mo")
    elif mo and asking:
        b_proof = ("maxoffer", f"Max offer: {short_price(mo)}" if num(mo) < asking else f"Worth up to {short_price(mo)}")
    elif d.get("coc"):
        b_proof = ("ltr", f"{d['coc']} cash-on-cash.")
    else:
        b_proof = ("strats", "Seven strategies, one tap.")

    return hook, [("hero", b_score), ("ltr", b_cf), b_proof]


hook, beats = pick_copy(data)


# ------------------------------------------------------------------ drawing helpers
def fit_font(text, max_w, size, min_size=54):
    d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    f = ImageFont.truetype(FB, size)
    while d.textlength(text, font=f) > max_w and size > min_size:
        size -= 2
        f = ImageFont.truetype(FB, size)
    return f

def draw_line(img, text, y, size=82, plate=True):
    """One line on a solid forest plate. Dollar figures, scores and percents in gold."""
    d = ImageDraw.Draw(img)
    pad_x, pad_y = 34, 24
    f = fit_font(text, (X1 - X0) - pad_x * 2, size)
    asc, desc = f.getmetrics()
    tw = d.textlength(text, font=f)
    x = CX - tw / 2
    if plate:
        d.rounded_rectangle([x - pad_x, y - pad_y, x + tw + pad_x, y + asc + desc + pad_y - 6],
                            radius=22, fill=FOREST)
    # word-by-word so numbers can be gold
    cx = x
    for i, word in enumerate(text.split(" ")):
        token = word + (" " if i < len(text.split(" ")) - 1 else "")
        col = GOLD if re.search(r"[\$%]|\d+/10", word) else CREAM
        d.text((cx, y), token, font=f, fill=col)
        cx += d.textlength(token, font=f)
    return y + asc + desc + pad_y * 2

def blurred_bg(src):
    bg = ImageOps.fit(src.convert("RGB"), (W, H), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(48))
    bg = ImageEnhance.Brightness(bg).enhance(0.38)
    tint = Image.new("RGB", (W, H), DEEP)
    return Image.blend(bg, tint, 0.55)

def rounded(img, r):
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=r, fill=255)
    out = img.convert("RGBA"); out.putalpha(m)
    return out


# ------------------------------------------------------------------ frames
frames = []   # (png_path, seconds, zoom_to)

# 1. photo + hook
src_photo = P("photo.jpg") if os.path.exists(P("photo.jpg")) else (P("card_hero.png") if os.path.exists(P("card_hero.png")) else None)
f1 = Image.new("RGB", (W, H), DEEP)
if src_photo:
    ph = Image.open(src_photo).convert("RGB")
    f1 = ImageOps.fit(ph, (W, H), Image.LANCZOS, centering=(0.5, 0.45))
    # gentle darkening at top/bottom so the plates sit on calm tone
    shade = Image.new("L", (W, H), 0); sd = ImageDraw.Draw(shade)
    for y in range(H):
        a = int(110 * max(0, 1 - abs(y - 640) / 700))
        sd.line([(0, y), (W, y)], fill=a)
    f1 = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), f1, shade)
y = 520
for i, line in enumerate(hook):
    y = draw_line(f1, line, y, size=84 if i == 0 else 78) + 18
f1.save(P("beat1.png")); frames.append((P("beat1.png"), 2.8, 1.08))

# 2–4. card beats
def card_beat(idx, card, text):
    path = P(f"card_{card}.png")
    if not os.path.exists(path):
        path = next((P(f) for f in ("card_hero.png", "card_ltr.png", "card_maxoffer.png", "card_strats.png")
                     if os.path.exists(P(f))), None)
    if not path:
        img = Image.new("RGB", (W, H), DEEP)
        draw_line(img, text, 900, size=88)
    else:
        card = Image.open(path).convert("RGB")
        img = blurred_bg(card)
        max_w, max_h = X1 - X0, CARD_BOT - CARD_TOP
        s = min(max_w / card.width, max_h / card.height)
        cw, ch = int(card.width * s), int(card.height * s)
        card = rounded(card.resize((cw, ch), Image.LANCZOS), 30)
        top = CARD_TOP + (max_h - ch) // 2
        # soft shadow
        sh_ = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(sh_).rounded_rectangle([X0 + 6, top + 18, X0 + 6 + cw, top + 18 + ch], radius=30, fill=(0, 0, 0, 150))
        img = Image.alpha_composite(img.convert("RGBA"), sh_.filter(ImageFilter.GaussianBlur(26)))
        img.alpha_composite(card, (CX - cw // 2, top))
        img = img.convert("RGB")
        ty = min(top + ch + 70, TEXT_MAX_Y - 130)
        draw_line(img, text, ty, size=84)
    p = P(f"beat{idx}.png"); img.save(p)
    return p

for i, (card, text) in enumerate(beats, start=2):
    frames.append((card_beat(i, card, text), 3.0, 1.035))

# 5. end card
f5 = Image.new("RGB", (W, H)); px = f5.load()
for yy in range(H):
    t = yy / (H - 1)
    c = tuple(int(a + (b - a) * t) for a, b in zip(FOREST, DEEP))
    for xx in range(0, W):
        px[xx, yy] = c
if os.path.exists(P("logo.png")):
    logo = Image.open(P("logo.png")).convert("RGBA")
    s = min(620 / logo.width, 180 / logo.height)
    logo = logo.resize((int(logo.width * s), int(logo.height * s)), Image.LANCZOS)
    plate_w, plate_h = logo.width + 120, logo.height + 90
    pl = Image.new("RGBA", (plate_w, plate_h), (0, 0, 0, 0))
    ImageDraw.Draw(pl).rounded_rectangle([0, 0, plate_w - 1, plate_h - 1], radius=36, fill=CREAM + (255,))
    pl.alpha_composite(logo, (60, 45))
    f5 = f5.convert("RGBA"); f5.alpha_composite(pl, (CX - plate_w // 2, 620)); f5 = f5.convert("RGB")
    ty = 620 + plate_h + 90
else:
    ty = 760
ty = draw_line(f5, "Run any address free", ty, size=78, plate=False) + 10
draw_line(f5, "dealcaddie.ai", ty, size=84, plate=False)
f5.save(P("beat5.png")); frames.append((P("beat5.png"), 2.6, 1.0))


# ------------------------------------------------------------------ video
XF = 0.4
segs = []
for i, (png, secs, zmax) in enumerate(frames):
    seg = P(f"seg{i}.mp4")
    n = int(secs * FPS)
    big = P(f"big{i}.png")
    Image.open(png).resize((W * 2, H * 2), Image.LANCZOS).save(big)
    z = f"1+{zmax - 1:.4f}*on/{n}"
    sh(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", big, "-t", f"{secs:.2f}",
        "-vf", f"zoompan=z='{z}':d={n}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},format=yuv420p,setsar=1",
        "-c:v", "libx264", "-preset", "fast", "-crf", "17", seg])
    segs.append((seg, secs))

inputs, fc, prev, t = [], "", "0:v", segs[0][1]
for s, _ in segs:
    inputs += ["-i", s]
for i in range(1, len(segs)):
    off = t - XF
    lbl = f"x{i}"
    fc += f"[{prev}][{i}:v]xfade=transition=fade:duration={XF}:offset={off:.2f}[{lbl}];"
    prev, t = lbl, t + segs[i][1] - XF
sh(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", fc.rstrip(";"), "-map", f"[{prev}]",
    "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
    "-movflags", "+faststart", out_mp4])

def dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", p]).decode().strip())


# ------------------------------------------------------------------ cover + caption
Image.open(P("beat1.png")).save(os.path.join(out_dir, "cover.jpg"), quality=90)

def sentence(t):
    t = t.strip()
    return t if t.endswith((".", "!", "?")) else t + "."

city = city_of(data.get("cityLine"))
city_tag = "#" + re.sub(r"[^a-z]", "", city.lower()) + "realestate" if city else "#realestatedeals"
specs = " · ".join(x for x in [
    f"{data['beds']} bed" if data.get("beds") else None,
    f"{data['baths']} bath" if data.get("baths") else None,
    f"{data['sqft']} sqft" if data.get("sqft") else None] if x)
body = " ".join(sentence(t) for _, t in beats)
caption = f"""{' '.join(hook)}

{specs + '. ' if specs else ''}Pasted the Zillow link into DealCaddie: {body}

Taxes, insurance and rent comps pulled automatically — about 10 seconds start to finish.

Comment a city and I'll run the next one 👇

Try it free · dealcaddie.ai

#realestateinvesting #rentalproperty #cashflow #realestateinvestor {city_tag}
"""
open(os.path.join(out_dir, "caption.txt"), "w").write(caption)
json.dump({"hook": hook, "beats": beats, "duration": round(dur(out_mp4), 1),
           "had_photo": os.path.exists(P("photo.jpg")), **data},
          open(os.path.join(out_dir, "meta.json"), "w"), indent=2)
print(f"built {out_mp4} ({dur(out_mp4):.1f}s, photo={'yes' if os.path.exists(P('photo.jpg')) else 'no'}, "
      f"cards={sorted(f for f in os.listdir(work) if f.startswith('card_'))})")
