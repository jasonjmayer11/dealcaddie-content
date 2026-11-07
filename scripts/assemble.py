#!/usr/bin/env python3
"""Assemble a DealCaddie Deal Verdict reel — "product" style.

Usage: python3 scripts/assemble.py <workdir> <out.mp4>
Reads photo.jpg, card_*.png and data.json from <workdir>.
Writes the 1080x1920 MP4, caption.txt, cover.jpg and meta.json next to it.

Design language (borrowed from Zillow / Airbnb / fintech product social):
  - one calm canvas (warm off-white), real brand logo, Inter type, no text boxes
  - every beat = small caps eyebrow + one big number + one quiet sub line + the real UI card as proof
  - everything centred on x=540 and inside the Reels safe area (y 290–1420)
  - motion is eased: elements rise + fade in on a stagger, numbers count up, card settles, slow drift
  - frames are rendered one by one in PIL and piped to ffmpeg (no zoompan jitter)

Beats (~3.8s each — enough time to read every number):
  1. listing photo, full bleed: city · price · hook question
  2. DEAL SCORE        6.9/10      + property card
  3. CASH FLOW         +$33/mo     + cash-flow card
  4. MAX OFFER $171K  (or the strategy that works, or CoC)  + its card
  5. logo + "Analyze any rental in seconds." + dealcaddie.ai button
"""
import json, math, os, re, subprocess, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = lambda n: os.path.join(ROOT, "fonts", n)
F_NUM, F_HEAD = FONT("InterDisplay-Bold.otf"), FONT("InterDisplay-SemiBold.otf")
F_SEMI, F_MED = FONT("Inter-SemiBold.otf"), FONT("Inter-Medium.otf")
LOGO, LOGO_W = os.path.join(ROOT, "assets", "logo.png"), os.path.join(ROOT, "assets", "logo-white.png")

W, H, FPS = 1080, 1920, 30
CX = W // 2
BG_TOP, BG_BOT = (248, 246, 241), (239, 236, 228)
INK, MUTED = (14, 33, 23), (112, 120, 114)
FOREST = (3, 62, 36)
GREEN, RED, AMBER = (3, 144, 58), (196, 58, 52), (183, 137, 30)
WHITE = (255, 255, 255)

work, out_mp4 = sys.argv[1], sys.argv[2]
out_dir = os.path.dirname(os.path.abspath(out_mp4))
data = json.load(open(os.path.join(work, "data.json")))
P = lambda f: os.path.join(work, f)


# ------------------------------------------------------------------ numbers + copy
def num(s):
    try:
        return float(re.sub(r"[^0-9.\-]", "", (s or "").replace("−", "-")))
    except ValueError:
        return None

def short_price(v):
    n = num(v) if isinstance(v, str) else v
    if not n:
        return None
    if n >= 1_000_000:
        return f"${n/1e6:.2f}M".replace(".00M", "M")
    return f"${round(n/1000)}K"

def pretty_money(s):
    """'+$33' -> '+$33', '-$99' -> '−$99' (true minus sign)."""
    return (s or "").replace("-", "−")

def score_color(v):
    if v is None: return INK
    return GREEN if v >= 7 else AMBER if v >= 5 else RED

def pick_copy(d):
    city_line = d.get("cityLine") or ""
    city = city_line.split(",")[0].strip()
    place = re.sub(r"\s*\d{5}(-\d{4})?$", "", city_line).strip()          # "Indianapolis, IN"
    price_full = d.get("price") or ""
    cf_s = d.get("ltrCashflow") or ""
    cf = num(cf_s)
    score = d.get("score")
    score_s = (score[:-2] if score and score.endswith(".0") else score) or None
    asking = num(price_full)

    if cf is not None and cf >= 200:
        q, cf_sub = "Guess the cash flow.", "After mortgage, taxes, insurance and reserves."
    elif cf is not None and cf < 0:
        q, cf_sub = "Looks like a deal. Is it?", "After mortgage, taxes, insurance and reserves."
    else:
        q, cf_sub = "Does it cash flow?", "Positive, but thin after every expense."

    plural = lambda n, w: f"{n} {w}" + ("" if str(n) in ("1", "1.0") else "s")
    specs = "  ·  ".join(x for x in [
        plural(d["beds"], "bed") if d.get("beds") else None,
        plural(d["baths"], "bath") if d.get("baths") else None,
        f"{d['sqft']} sq ft" if d.get("sqft") else None] if x)
    hook = {"kind": "photo", "eyebrow": place.upper() or "ACTIVE LISTING",
            "value": price_full or "This house", "specs": specs, "sub": q}

    beats = []
    if score_s:
        beats.append({"kind": "stat", "eyebrow": "DEAL SCORE", "value": score_s, "unit": "/10",
                      "color": score_color(num(score_s)), "sub": "Cash flow, price and market in one number.",
                      "card": "hero", "crop": 0.70, "say": f"{score_s}/10 deal score."})
    if cf is not None:
        beats.append({"kind": "stat", "eyebrow": "CASH FLOW · LONG-TERM RENTAL", "value": pretty_money(cf_s),
                      "unit": "/mo", "color": GREEN if cf > 0 else RED, "sub": cf_sub, "card": "ltr",
                      "say": (f"{cf_s}/mo as a rental." if cf >= 200 else
                              f"Loses ${abs(int(cf)):,}/mo as a rental." if cf < 0 else f"{cf_s}/mo. Barely.")})

    strat = d.get("strategies") or {}
    names = {"MTR": "mid-term rental", "STR": "Airbnb", "S8": "Section 8", "HH": "house hack", "BRRRR": "BRRRR"}
    alts = [(k, v) for k, v in strat.items() if k not in ("LTR", "FLIP") and (num(v) or 0) > 0]
    best_alt = max(alts, key=lambda kv: num(kv[1]), default=None)
    mo = num(d.get("maxOffer"))
    if cf is not None and cf < 0 and best_alt:
        nm = names.get(best_alt[0], best_alt[0])
        beats.append({"kind": "stat", "eyebrow": f"AS A {nm.upper()}", "value": pretty_money(best_alt[1]), "unit": "/mo",
                      "color": GREEN, "sub": "Same house. Different strategy.", "card": "strats",
                      "say": f"As a {nm}: {best_alt[1]}/mo."})
    elif mo and asking:
        diff = abs(asking - mo)
        if mo < asking:
            sub = f"{short_price(diff)} under asking to hit your target return."
            say = f"Max offer: {short_price(mo)}."
        else:
            sub = f"Still hits the target return {short_price(diff)} over asking."
            say = f"Worth up to {short_price(mo)}."
        beats.append({"kind": "stat", "eyebrow": "MAX OFFER", "value": short_price(mo), "unit": "",
                      "color": INK, "sub": sub, "card": "maxoffer", "say": say})
    elif d.get("coc"):
        beats.append({"kind": "stat", "eyebrow": "CASH-ON-CASH RETURN", "value": d["coc"], "unit": "",
                      "color": INK, "sub": "What the cash you put in earns each year.", "card": "ltr",
                      "say": f"{d['coc']} cash-on-cash."})

    title = [f"{short_price(price_full) or 'This'} {city} house." if city else "This house.", q]
    return hook, beats, title


hook, beats, title = pick_copy(data)


# ------------------------------------------------------------------ drawing primitives
_fonts = {}
def font(path, size):
    k = (path, size)
    if k not in _fonts:
        _fonts[k] = ImageFont.truetype(path, size)
    return _fonts[k]

def text_layer(text, path, size, fill, tracking=0.0, alpha=255):
    """Tight RGBA layer for one line of text. tracking is in em (0.12 = 12% letter spacing)."""
    f = font(path, size)
    asc, desc = f.getmetrics()
    track = tracking * size
    width = 0
    for i, ch in enumerate(text):
        width += f.getlength(ch) + (track if i < len(text) - 1 else 0)
    if not tracking:
        width = f.getlength(text)
    img = Image.new("RGBA", (int(math.ceil(width)) + 4, asc + desc), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if tracking:
        x = 0
        for ch in text:
            d.text((x, 0), ch, font=f, fill=fill + (alpha,))
            x += f.getlength(ch) + track
    else:
        d.text((0, 0), text, font=f, fill=fill + (alpha,))
    return img

def wrap(text, path, size, max_w):
    f = font(path, size)
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if f.getlength(t) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    if len(lines) == 2:
        best = None
        for i in range(1, len(words)):
            a, b = " ".join(words[:i]), " ".join(words[i:])
            wa, wb = f.getlength(a), f.getlength(b)
            if max(wa, wb) <= max_w and (best is None or abs(wa - wb) < best[0]):
                best = (abs(wa - wb), [a, b])
        if best: lines = best[1]
    return lines

def fit_size(text, path, size, max_w, min_size):
    while size > min_size and font(path, size).getlength(text) > max_w:
        size -= 4
    return size

def stack(layers, gap):
    """Vertically stack centred layers into one."""
    w = max(l.width for l in layers)
    h = sum(l.height for l in layers) + gap * (len(layers) - 1)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    y = 0
    for l in layers:
        out.alpha_composite(l, ((w - l.width) // 2, y)); y += l.height + gap
    return out

def value_layer(value, unit, color, size, on_dark=False):
    """Big number + smaller unit ('/10', '/mo') sitting on the same baseline."""
    fn = font(F_NUM, size)
    asc, desc = fn.getmetrics()
    num_l = text_layer(value, F_NUM, size, color, tracking=-0.035)
    if not unit:
        return num_l
    us = int(size * 0.34)
    fu = font(F_HEAD, us)
    u_l = text_layer(unit, F_HEAD, us, WHITE if on_dark else MUTED)
    gap = int(size * 0.04)
    out = Image.new("RGBA", (num_l.width + gap + u_l.width, num_l.height), (0, 0, 0, 0))
    out.alpha_composite(num_l, (0, 0))
    base = asc                                     # baseline of the big number
    out.alpha_composite(u_l, (num_l.width + gap, base - fu.getmetrics()[0]))
    return out

def rounded(img, r):
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=r, fill=255)
    out = img.convert("RGBA"); out.putalpha(m)
    return out

def card_layer(name, max_w, max_h, crop=None):
    path = P(f"card_{name}.png")
    if not os.path.exists(path):
        return None
    c = Image.open(path).convert("RGB")
    if crop:
        c = c.crop((0, 0, c.width, int(c.height * crop)))
    s = min(max_w / c.width, max_h / c.height)
    c = c.resize((int(c.width * s), int(c.height * s)), Image.LANCZOS)
    c = rounded(c, 34)
    # hairline border + soft, wide shadow (the "floating UI" look)
    ImageDraw.Draw(c).rounded_rectangle([0, 0, c.width - 1, c.height - 1], radius=34, outline=(0, 0, 0, 22), width=2)
    pad = 90
    out = Image.new("RGBA", (c.width + pad * 2, c.height + pad * 2), (0, 0, 0, 0))
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([pad, pad + 26, pad + c.width, pad + c.height + 26], radius=34, fill=(20, 40, 28, 70))
    out.alpha_composite(sh.filter(ImageFilter.GaussianBlur(34)))
    out.alpha_composite(c, (pad, pad))
    return out, pad

def gradient_bg():
    col = Image.new("RGB", (1, H))
    for y in range(H):
        t = y / (H - 1)
        col.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOT)))
    return col.resize((W, H))

def logo_layer(width, white=False):
    p = LOGO_W if white else LOGO
    if not os.path.exists(p):
        return text_layer("DealCaddie", F_NUM, int(width / 5.2), WHITE if white else FOREST)
    l = Image.open(p).convert("RGBA")
    return l.resize((width, int(l.height * width / l.width)), Image.LANCZOS)


# ------------------------------------------------------------------ easing + compositing
def ease_out(t):  # cubic
    t = max(0.0, min(1.0, t)); return 1 - (1 - t) ** 3

def ease_in_out(t):
    t = max(0.0, min(1.0, t)); return 3 * t * t - 2 * t * t * t

def with_alpha(layer, a):
    if a >= 0.999: return layer
    l = layer.copy()
    l.putalpha(l.getchannel("A").point(lambda v: int(v * a)))
    return l

def place(frame, layer, cx, y, alpha=1.0, scale=1.0):
    if alpha <= 0.003: return
    if abs(scale - 1) > 0.001:
        layer = layer.resize((max(1, int(layer.width * scale)), max(1, int(layer.height * scale))), Image.BICUBIC)
    frame.alpha_composite(with_alpha(layer, alpha), (int(cx - layer.width / 2), int(y)))

def enter(t, delay, dur=0.55, rise=34):
    p = ease_out((t - delay) / dur)
    return p, (1 - p) * rise

def count_value(target, p):
    """Format the target string at progress p (0..1), keeping its prefix/suffix/commas/decimals."""
    m = re.match(r"^([^0-9]*)([0-9][0-9,]*)(\.[0-9]+)?(.*)$", target)
    if not m or p >= 1: return target
    pre, ints, dec, suf = m.groups()
    v = float(ints.replace(",", "") + (dec or ""))
    cur = v * ease_out(p)
    nd = len(dec) - 1 if dec else 0
    s = f"{cur:,.{nd}f}" if "," in ints else f"{cur:.{nd}f}"
    return f"{pre}{s}{suf}"


# ------------------------------------------------------------------ beat renderers
BG = gradient_bg()
TOP_LOGO = logo_layer(260)
TOP_Y = 300                    # top logo (just under the platform's top bar)
EXIT = 0.28                    # seconds of fade-out at the end of a beat

def render_photo_beat(spec, dur):
    src = P("photo.jpg") if os.path.exists(P("photo.jpg")) else None
    base = None
    if src:
        ph = Image.open(src).convert("RGB")
        base = ImageOps.fit(ph, (int(W * 1.08), int(H * 1.08)), Image.LANCZOS, centering=(0.5, 0.42))
    # scrims: light at top for the logo, deep at the bottom for the type
    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0)); sd = ImageDraw.Draw(scrim)
    for y in range(H):
        a = 0
        if y < 520: a = int(120 * (1 - y / 520) ** 1.6)
        if y > 760: a = max(a, int(215 * ease_in_out((y - 760) / 760)))
        sd.line([(0, y), (W, y)], fill=(6, 18, 11, a))
    eb = text_layer(spec["eyebrow"], F_SEMI, 34, WHITE, tracking=0.16, alpha=215)
    vs = fit_size(spec["value"], F_NUM, 196, 860, 120)
    val = text_layer(spec["value"], F_NUM, vs, WHITE, tracking=-0.035)
    sub = text_layer(spec["sub"], F_HEAD, 66, WHITE)
    specs = text_layer(spec["specs"], F_MED, 42, WHITE, alpha=230) if spec.get("specs") else None
    logo = logo_layer(260, white=True)

    def frame(t):
        if base is not None:
            z = 1.0 + 0.06 * (t / dur)                       # slow push-in
            cw, ch = int(W * 1.08 / z * (1 / 1.0)), int(H * 1.08 / z)
            cw, ch = min(cw, base.width), min(ch, base.height)
            x0, y0 = (base.width - cw) // 2, (base.height - ch) // 2
            f = base.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.BILINEAR).convert("RGBA")
        else:
            f = Image.new("RGBA", (W, H), FOREST + (255,))
        f.alpha_composite(scrim)
        place(f, logo, CX, TOP_Y, ease_out(t / 0.5))
        rows = [(eb, 18), (val, 10)] + ([(specs, 40)] if specs else []) + [(sub, 0)]
        y = 1420 - sum(l.height + g for l, g in rows)         # bottom-anchored inside the safe zone
        for i, (l, gap) in enumerate(rows):
            p, dy = enter(t, 0.15 + i * 0.12)
            place(f, l, CX, y + dy, p)
            y += l.height + gap
        # exit: dissolve to the canvas the next beat starts on
        k = ease_in_out((t - (dur - EXIT - 0.1)) / (EXIT + 0.1))
        if k > 0:
            f = Image.blend(f.convert("RGB"), BG, k).convert("RGBA")
        return f.convert("RGB")
    return frame

def render_stat_beat(spec, dur):
    eb = text_layer(spec["eyebrow"], F_SEMI, 32, MUTED, tracking=0.16)
    value = spec["value"]
    vs = fit_size(value, F_NUM, 210, 760, 120)
    sub_lines = wrap(spec["sub"], F_MED, 42, 820)
    sub = stack([text_layer(s, F_MED, 42, (62, 74, 66)) for s in sub_lines], 8)
    card = card_layer(spec["card"], 860, 560 if len(sub_lines) == 1 else 520, spec.get("crop"))
    # vertical rhythm
    y_eb = 440
    y_val = y_eb + eb.height + 6
    val_h = value_layer(value, spec["unit"], spec["color"], vs).height
    y_sub = y_val + val_h + 6
    y_card_area = y_sub + sub.height + 40
    card_top = None
    if card:
        cl, pad = card
        area_h = 1415 - y_card_area
        card_top = y_card_area + max(0, (area_h - (cl.height - 2 * pad)) // 2) - pad

    finished_val = value_layer(value, spec["unit"], spec["color"], vs)

    def frame(t):
        f = BG.copy().convert("RGBA")
        place(f, TOP_LOGO, CX, TOP_Y)
        out_a = 1 - ease_in_out((t - (dur - EXIT)) / EXIT)
        out_dy = -18 * (1 - out_a)
        p, dy = enter(t, 0.0)
        place(f, eb, CX, y_eb + dy + out_dy, p * out_a)
        p, dy = enter(t, 0.08)
        cp = min(1.0, max(0.0, (t - 0.08) / 0.9))
        vl = finished_val if cp >= 1 else value_layer(count_value(value, cp), spec["unit"], spec["color"], vs)
        place(f, vl, CX, y_val + dy + out_dy, p * out_a)
        p, dy = enter(t, 0.20)
        place(f, sub, CX, y_sub + dy + out_dy, p * out_a)
        if card:
            cl, pad = card
            p, dy = enter(t, 0.30, dur=0.75, rise=70)
            drift = 1.0 + 0.012 * ease_in_out(t / dur)
            sc = (0.965 + 0.035 * p) * drift
            h_scaled = cl.height * sc
            place(f, cl, CX, card_top + dy + out_dy + (cl.height - h_scaled) / 2, p * out_a, sc)
        return f.convert("RGB")
    return frame

def render_end_beat(dur):
    logo = logo_layer(720)
    line = text_layer("Analyze any rental in seconds.", F_HEAD, 54, INK)
    sub = text_layer("Rent comps, taxes and insurance — pulled for you.", F_MED, 36, MUTED)
    label = text_layer("Try it free  ·  dealcaddie.ai", F_SEMI, 44, WHITE)
    bw, bh = label.width + 120, 112
    btn = Image.new("RGBA", (bw + 80, bh + 80), (0, 0, 0, 0))
    sh = Image.new("RGBA", btn.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([40, 56, 40 + bw, 56 + bh], radius=bh // 2, fill=(3, 62, 36, 90))
    btn.alpha_composite(sh.filter(ImageFilter.GaussianBlur(18)))
    ImageDraw.Draw(btn).rounded_rectangle([40, 40, 40 + bw, 40 + bh], radius=bh // 2, fill=FOREST + (255,))
    fl = font(F_SEMI, 44)
    btn.alpha_composite(label, (40 + (bw - label.width) // 2, 40 + (bh - label.height) // 2 + 2))

    def frame(t):
        f = BG.copy().convert("RGBA")
        p, dy = enter(t, 0.0, dur=0.7, rise=24)
        place(f, logo, CX, 700 + dy, p, 0.97 + 0.03 * p)
        p, dy = enter(t, 0.25); place(f, line, CX, 900 + dy, p)
        p, dy = enter(t, 0.35); place(f, sub, CX, 984 + dy, p)
        p, dy = enter(t, 0.50); place(f, btn, CX, 1080 + dy, p)
        return f.convert("RGB")
    return frame


# ------------------------------------------------------------------ timeline + encode
timeline = [(render_photo_beat(hook, 3.8), 3.8)]
for b in beats:
    timeline.append((render_stat_beat(b, 3.8), 3.8))
timeline.append((render_end_beat(3.6), 3.6))

enc = subprocess.Popen(
    ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
     "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
     "-movflags", "+faststart", out_mp4], stdin=subprocess.PIPE)
for bi, (fn, dur) in enumerate(timeline, start=1):
    n = int(round(dur * FPS))
    for i in range(n):
        t = i / FPS
        img = fn(t)
        enc.stdin.write(img.tobytes())
        if i == int(1.6 * FPS):                     # a settled frame of each beat, for review + the cover
            img.save(P(f"beat{bi}.png"))
enc.stdin.close()
if enc.wait() != 0:
    sys.exit("ffmpeg failed")

def dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", p]).decode().strip())


# ------------------------------------------------------------------ cover + caption
Image.open(P("beat1.png")).save(os.path.join(out_dir, "cover.jpg"), quality=92)

city = (data.get("cityLine") or "").split(",")[0].strip()
city_tag = "#" + re.sub(r"[^a-z]", "", city.lower()) + "realestate" if city else "#realestatedeals"
specs = " · ".join(x for x in [
    f"{data['beds']} bed" if data.get("beds") else None,
    f"{data['baths']} bath" if data.get("baths") else None,
    f"{data['sqft']} sqft" if data.get("sqft") else None] if x)
body = " ".join(b["say"] for b in beats)
caption = f"""{' '.join(title)}

{specs + '. ' if specs else ''}Pasted the Zillow link into DealCaddie: {body}

Taxes, insurance and rent comps pulled automatically — about 10 seconds start to finish.

Comment a city and I'll run the next one 👇

Try it free · dealcaddie.ai

#realestateinvesting #rentalproperty #cashflow #realestateinvestor {city_tag}
"""
open(os.path.join(out_dir, "caption.txt"), "w").write(caption)
json.dump({"hook": title, "beats": [{k: v for k, v in b.items() if k != "color"} for b in beats],
           "duration": round(dur(out_mp4), 1), "had_photo": os.path.exists(P("photo.jpg")), **data},
          open(os.path.join(out_dir, "meta.json"), "w"), indent=2)
print(f"built {out_mp4} ({dur(out_mp4):.1f}s, photo={'yes' if os.path.exists(P('photo.jpg')) else 'no'}, "
      f"cards={sorted(f for f in os.listdir(work) if f.startswith('card_'))})")
