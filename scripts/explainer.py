#!/usr/bin/env python3
"""DealCaddie "How it works" explainers: animated blueprint infographics + AI voice.

The style follows the book explainers (blueprint panel, word-by-word captions, a HUD pill,
camera punch-ins, WHY IT MATTERS stat card, product revealed last), re-skinned in DealCaddie
forest green + gold. Each lesson is data (explainers/<name>.json); this file is the engine.

Usage: python3 scripts/explainer.py explainers/cashflow.json out.mp4
Env:   KOKORO_ONNX_DIR (kokoro-v1.0.onnx + voices-v1.0.bin) or the kokoro pip package,
       VOICE (af_heart), VOICE_SPEED (1.05), MUSIC_TRACK (dc-NN)
"""
import json, math, os, random, re, subprocess, sys, wave, zlib
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reelkit import (W, H, FPS, WHITE, F_NUM, F_HEAD, F_SEMI, F_MED, text_layer, wrap, fit_size,
                     logo_layer, place, ease_out, ease_in_out, render_end_beat)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
lesson = json.load(open(sys.argv[1])); out_mp4 = sys.argv[2]
work = os.path.join(os.path.dirname(os.path.abspath(out_mp4)), "explainer_work"); os.makedirs(work, exist_ok=True)

# ------------------------------------------------------------------ palette (DealCaddie, dark)
CANVAS = (8, 16, 12)
GOLD = (232, 197, 92)
GOLD_D = (150, 120, 40)
BP_BG = (11, 38, 27)          # blueprint panel
BP_MIN = (22, 62, 44)         # minor grid
BP_MAJ = (34, 88, 62)         # major grid
LINE = (226, 236, 228)        # drawing line (chalk white)
MONEY = (52, 211, 120)        # money in
DRAIN = (240, 96, 84)         # money out
SOFT = (170, 190, 178)

# ------------------------------------------------------------------ voice
SR = 24000
VOICE = os.environ.get("VOICE") or "af_heart"
SPEED = float(os.environ.get("VOICE_SPEED") or 1.05)
_kok = None
def speak(text):
    global _kok
    d = os.environ.get("KOKORO_ONNX_DIR")
    if d:
        if _kok is None:
            from kokoro_onnx import Kokoro
            _kok = Kokoro(os.path.join(d, "kokoro-v1.0.onnx"), os.path.join(d, "voices-v1.0.bin"))
        s, sr = _kok.create(text, voice=VOICE, speed=SPEED, lang="en-us")
        return np.asarray(s, np.float32)
    if _kok is None:
        from kokoro import KPipeline
        _kok = KPipeline(lang_code="a")
    parts = [np.asarray(a.numpy() if hasattr(a, "numpy") else a) for _, _, a in _kok(text, voice=VOICE, speed=SPEED)]
    return np.concatenate(parts).astype(np.float32)

# Each scene: list of phrases. A phrase = {"text": on-screen, "voice": spoken, "do": [event ids]}
scenes = lesson["scenes"]
GAP, TAIL = 0.12, 0.45
timeline = []          # per scene: (t0, dur, [(phrase_t0, phrase_dur, phrase)])
audio_clips = []       # (t0, samples)
t = 0.5                # cover lead-in
for sc in scenes:
    pts, st = [], t
    for ph in sc["phrases"]:
        a = speak(ph["voice"]); d = len(a) / SR
        audio_clips.append((t, a)); pts.append((t, d, ph)); t += d + GAP
    t += TAIL + sc.get("extra", 0)
    timeline.append((st, t - st, pts))
END_DUR = 3.6
total = t + END_DUR
print(f"voice timeline {t:.1f}s + end {END_DUR}s = {total:.1f}s")

# event times: when each "do" id fires
events = {}
for st, dur, pts in timeline:
    for pt0, pd, ph in pts:
        for i, ev in enumerate(ph.get("do", [])):
            events[ev] = pt0 + pd * (i / max(1, len(ph["do"])))  # spread within the phrase
def since(ev, now):
    return now - events[ev] if ev in events and now >= events[ev] else None
def prog(ev, now, dur=0.8):
    s = since(ev, now)
    return 0.0 if s is None else ease_out(min(1.0, s / dur))

# ------------------------------------------------------------------ chrome: canvas + moving stripe bands
def stripe_band(w, h, phase):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    step = 46
    for x in range(-h - step, w + step, step):
        x0 = x + int(phase) % step
        d.polygon([(x0, h), (x0 + h, 0), (x0 + h + step // 2, 0), (x0 + step // 2, h)], fill=GOLD + (255,))
    bg = Image.new("RGBA", (w, h), (18, 30, 22, 255)); bg.alpha_composite(im); return bg

BASE = Image.new("RGBA", (W, H), CANVAS + (255,))
vig = Image.new("L", (W, H), 0); ImageDraw.Draw(vig).ellipse([-300, 200, W + 300, H + 200], fill=110)
vig = vig.filter(ImageFilter.GaussianBlur(160))
BASE.paste(Image.new("RGBA", (W, H), (16, 40, 28, 255)), (0, 0), vig)

# ------------------------------------------------------------------ blueprint panel (drawn at 2x)
PX, PY, PW, PH = 70, 250, 940, 940
S = 2.0; DW, DH = int(PW * S), int(PH * S)
def bp_background():
    im = Image.new("RGB", (DW, DH), BP_BG); d = ImageDraw.Draw(im)
    for i in range(0, DW, int(24 * S)): d.line([(i, 0), (i, DH)], fill=BP_MIN, width=1)
    for i in range(0, DH, int(24 * S)): d.line([(0, i), (DW, i)], fill=BP_MIN, width=1)
    for i in range(0, DW, int(120 * S)): d.line([(i, 0), (i, DH)], fill=BP_MAJ, width=2)
    for i in range(0, DH, int(120 * S)): d.line([(0, i), (DW, i)], fill=BP_MAJ, width=2)
    for (cx, cy) in [(30, 30), (PW - 30, 30), (30, PH - 30), (PW - 30, PH - 30)]:      # corner ticks
        cx, cy = cx * S, cy * S; L = 18 * S
        d.line([(cx - L, cy), (cx + L, cy)], fill=LINE, width=3); d.line([(cx, cy - L), (cx, cy + L)], fill=LINE, width=3)
    v = Image.new("L", (DW, DH), 0); ImageDraw.Draw(v).rectangle([0, 0, DW, DH], fill=255)
    v = Image.new("L", (DW, DH), 0); ImageDraw.Draw(v).ellipse([-DW * .2, -DH * .2, DW * 1.2, DH * 1.2], fill=255)
    v = v.filter(ImageFilter.GaussianBlur(120)); dark = Image.new("RGB", (DW, DH), (4, 14, 9))
    return Image.composite(im, dark, v)
BP = bp_background()

def T(s, size, color, font=F_SEMI, tracking=0.0):
    return text_layer(s, font, int(size * S), color, tracking=tracking)
def sp(x): return int(x * S)

# ------------------------------------------------------------------ diagram elements (lesson-specific data, generic draw)
D = lesson["diagram"]
rng = random.Random(7)
BUBBLES = [(rng.random(), rng.random(), rng.uniform(.4, 1)) for _ in range(26)]

def pipe(d, pts, color, width, glow=True):
    pts = [(sp(x), sp(y)) for x, y in pts]
    if glow: d.line(pts, fill=tuple(int(c * .35) for c in color), width=sp(width + 10), joint="curve")
    d.line(pts, fill=(18, 30, 24), width=sp(width + 4), joint="curve")
    d.line(pts, fill=color, width=sp(width), joint="curve")

def along(pts, f):
    seg = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]; L = sum(seg); d = f * L
    for i, s in enumerate(seg):
        if d <= s:
            k = d / s; return (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * k, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * k)
        d -= s
    return pts[-1]

def particles(d, pts, now, color, rate=7, speed=0.55):
    for k in range(rate):
        f = (now * speed + k / rate) % 1.0
        x, y = along(pts, f); r = sp(5.5)
        d.ellipse([sp(x) - r, sp(y) - r, sp(x) + r, sp(y) + r], fill=color)

def money_fmt(v, sign=False):
    s = f"${abs(int(round(v))):,}"
    return (("+" if v >= 0 else "−") + s) if sign else (("−" if v < 0 else "") + s)

def draw_cashflow(now):
    """Tank (rent in) draining through labelled pipes (each cost). Data-driven from D."""
    im = BP.copy(); d = ImageDraw.Draw(im)
    rent = D["rent"]; costs = D["costs"]
    active = [(c, prog(c["id"], now)) for c in costs if since(c["id"], now) is not None]
    spent = sum(c["amount"] * p for c, p in active)
    tank_in = prog("rent", now, 1.6)
    level = max(0.0, min(1.0, tank_in * (rent - spent) / rent)) if tank_in else 0.0
    tx0, ty0, tx1, ty1 = 70, 300, 330, 820
    # inflow
    inflow = [(30, 170), (200, 170), (200, 300)]
    pipe(d, inflow, MONEY if tank_in else SOFT, 12)
    if tank_in: particles(d, inflow, now, (190, 255, 210), rate=6, speed=0.9)
    lab = T("RENT IN", 22, GOLD, F_SEMI, 0.12); im.paste(lab, (sp(30), sp(122)), lab)
    # tank body + liquid
    d.rounded_rectangle([sp(tx0), sp(ty0), sp(tx1), sp(ty1)], radius=sp(26), fill=(14, 30, 22), outline=LINE, width=sp(4))
    lh = (ty1 - ty0 - 16) * level
    if lh > 2:
        liq = Image.new("RGB", (sp(tx1 - tx0 - 16), sp(lh)), (0, 0, 0)); ld = ImageDraw.Draw(liq)
        for yy in range(liq.height):
            k = yy / max(1, liq.height); ld.line([(0, yy), (liq.width, yy)], fill=(int(30 + 30 * k), int(170 - 60 * k), int(95 - 25 * k)))
        m = Image.new("L", liq.size, 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, liq.width - 1, liq.height - 1], radius=sp(18), fill=255)
        im.paste(liq, (sp(tx0 + 8), sp(ty1 - 8 - lh)), m)
        for bx, by, bs in BUBBLES:                                  # rising bubbles
            yy = ty1 - 8 - ((by + now * 0.12 * bs) % 1.0) * lh
            xx = tx0 + 18 + bx * (tx1 - tx0 - 36); r = sp(3 + 4 * bs)
            if yy > ty1 - 8 - lh + 6: d.ellipse([sp(xx) - r, sp(yy) - r, sp(xx) + r, sp(yy) + r], outline=(190, 255, 215), width=sp(1.5))
        d.line([(sp(tx0 + 12), sp(ty1 - 8 - lh)), (sp(tx1 - 12), sp(ty1 - 8 - lh))], fill=(200, 255, 220), width=sp(2))
    for k in range(1, 5):                                           # tick marks on the tank
        yy = ty0 + (ty1 - ty0) * k / 5; d.line([(sp(tx1 - 26), sp(yy)), (sp(tx1 - 6), sp(yy))], fill=LINE, width=sp(2))
    if tank_in:
        v = T(money_fmt(rent * min(1, tank_in)), 40, WHITE, F_NUM); im.paste(v, (sp((tx0 + tx1) / 2) - v.width // 2, sp(ty0 + 30)), v)
        s = T("/mo", 20, SOFT); im.paste(s, (sp((tx0 + tx1) / 2) - s.width // 2, sp(ty0 + 78)), s)
    # drains
    n = len(costs); y0, y1 = 150, 860
    for i, c in enumerate(costs):
        p = prog(c["id"], now)
        if p <= 0: continue
        yy = y0 + (y1 - y0) * i / max(1, n - 1)
        path = [(tx1, 760 - i * 6), (470 + i * 10, 760 - i * 6), (470 + i * 10, yy), (600, yy)]
        L = int(len(path) * 10)
        pipe(d, path, DRAIN, 7, glow=True)
        particles(d, path, now + i * .13, (255, 190, 180), rate=5, speed=0.7)
        # label box with leader dot
        bx0, by0, bx1, by1 = 600, yy - 38, 905, yy + 38
        box = Image.new("RGBA", (sp(bx1 - bx0), sp(by1 - by0)), (0, 0, 0, 0)); bd = ImageDraw.Draw(box)
        bd.rounded_rectangle([0, 0, box.width - 1, box.height - 1], radius=sp(14), fill=(12, 26, 19, 235), outline=DRAIN + (255,), width=sp(2.5))
        nm = T(c["label"], 22, WHITE, F_SEMI); box.alpha_composite(nm, (sp(16), (box.height - nm.height) // 2))
        val = T("−" + money_fmt(c["amount"] * p), 26, (255, 150, 140), F_NUM)
        box.alpha_composite(val, (box.width - val.width - sp(16), (box.height - val.height) // 2))
        if c.get("note"):
            nt = T(c["note"], 15, SOFT); box.alpha_composite(nt, (sp(16), box.height - nt.height - sp(5)))
        a = min(1.0, p * 1.4); box.putalpha(box.getchannel("A").point(lambda v, a=a: int(v * a)))
        im.paste(box, (sp(bx0), sp(by0)), box)
    # HUD
    net = rent - spent if tank_in else None
    if net is not None:
        good = net >= 0
        hud = f"CASH FLOW {money_fmt(net, sign=True)}/MO" + ""
        if spent == 0: hud = "CASH FLOW ?"
        col = (34, 150, 82) if good else (196, 58, 52)
        if len(active) == 1: hud, col = f"PROFIT {money_fmt(net)}/MO?", (150, 120, 40)
        draw_hud(im, hud, col)
    ex = T("EXAMPLE NUMBERS", 15, SOFT, F_SEMI, 0.14); im.paste(ex, (sp(PW - 30) - ex.width, sp(PH - 40)), ex)
    return im

def draw_hud(im, text, col):
    tl = T(text, 21, WHITE, F_NUM, 0.06)
    pad = sp(14); box = Image.new("RGBA", (tl.width + 2 * pad, tl.height + sp(16)), (0, 0, 0, 0))
    ImageDraw.Draw(box).rounded_rectangle([0, 0, box.width - 1, box.height - 1], radius=box.height // 2, fill=col + (255,))
    box.alpha_composite(tl, (pad, sp(8))); im.paste(box, (sp(PW - 30) - box.width, sp(30)), box)

def draw_bars(now):
    """Rent vs stacked costs, with the gap called out."""
    im = BP.copy(); d = ImageDraw.Draw(im)
    rent = D["rent"]; costs = D["costs"]; tot = sum(c["amount"] for c in costs)
    top = max(rent, tot) * 1.12; base_y, h = 820, 620
    p = prog("bars", now, 1.2)
    def y(v): return base_y - h * v / top
    # rent bar
    d.rounded_rectangle([sp(150), sp(y(rent * p)), sp(390), sp(base_y)], radius=sp(16), fill=(34, 150, 82), outline=LINE, width=sp(3))
    l = T("RENT", 22, WHITE, F_SEMI, 0.12); im.paste(l, (sp(270) - l.width // 2, sp(base_y + 20)), l)
    v = T(money_fmt(rent * p), 34, WHITE, F_NUM); im.paste(v, (sp(270) - v.width // 2, sp(y(rent * p)) - v.height - sp(14)), v)
    # stacked costs
    acc = 0; pal = [(196, 58, 52), (214, 96, 70), (226, 128, 84), (183, 137, 30), (160, 110, 40), (130, 90, 60), (110, 80, 70)]
    for i, c in enumerate(costs):
        q = max(0.0, min(1.0, p * len(costs) - i))
        if q <= 0: break
        a0, a1 = acc, acc + c["amount"] * q; acc += c["amount"] * q
        d.rectangle([sp(560), sp(y(a1)), sp(800), sp(y(a0))], fill=pal[i % len(pal)], outline=(14, 30, 22), width=sp(2))
        if c["amount"] > tot * 0.06 and q > .9:
            t_ = T(c["short"], 17, WHITE, F_SEMI); im.paste(t_, (sp(680) - t_.width // 2, sp((y(a0) + y(a1)) / 2) - t_.height // 2), t_)
    l = T("COSTS", 22, WHITE, F_SEMI, 0.12); im.paste(l, (sp(680) - l.width // 2, sp(base_y + 20)), l)
    v = T(money_fmt(acc), 34, (255, 150, 140), F_NUM); im.paste(v, (sp(680) - v.width // 2, sp(y(acc)) - v.height - sp(14)), v)
    d.line([(sp(120), sp(base_y)), (sp(860), sp(base_y))], fill=LINE, width=sp(3))
    g = prog("gap", now, 0.7)
    if g:                                   # dimension line showing the shortfall
        yr, yc = y(rent), y(tot)
        d.line([(sp(400), sp(yr)), (sp(860), sp(yr))], fill=GOLD, width=sp(2))
        x = 840; d.line([(sp(x), sp(yr)), (sp(x), sp(yc))], fill=GOLD, width=sp(4))
        for yy in (yr, yc): d.line([(sp(x - 14), sp(yy)), (sp(x + 14), sp(yy))], fill=GOLD, width=sp(4))
        gl = T(money_fmt(rent - tot, sign=True) + "/mo", 30, GOLD, F_NUM)
        gl.putalpha(gl.getchannel("A").point(lambda vv: int(vv * g)))
        im.paste(gl, (sp(475) - gl.width // 2, sp(yr) - gl.height - sp(16)), gl)
        draw_hud(im, f"CASH FLOW {money_fmt(rent - tot, sign=True)}/MO", (196, 58, 52))
    ex = T("EXAMPLE NUMBERS", 15, SOFT, F_SEMI, 0.14); im.paste(ex, (sp(PW - 30) - ex.width, sp(PH - 40)), ex)
    return im

APP = Image.open(os.path.join(ROOT, "assets", "showcase", lesson.get("app_screen", "analysis.png"))).convert("RGBA")
def draw_reveal(now):
    im = Image.new("RGB", (DW, DH), (10, 24, 17)); d = ImageDraw.Draw(im)
    for r in range(8):
        rr = sp(300 + r * 70); c = (int(14 + 4 * (8 - r)), int(40 + 8 * (8 - r)), int(28 + 5 * (8 - r)))
        d.ellipse([DW // 2 - rr, DH // 2 - rr, DW // 2 + rr, DH // 2 + rr], outline=c, width=sp(2))
    p = prog("reveal", now, 1.0)
    ph_h = sp(820); ph = APP.copy(); ph.thumbnail((sp(700), ph_h), Image.LANCZOS)
    y = int(DH - (DH - ph.height) / 2 - ph.height + (1 - p) * sp(400))
    a = ph.getchannel("A").point(lambda v: int(v * p)); ph.putalpha(a)
    im.paste(ph, ((DW - ph.width) // 2, y), ph)
    return im

PANELS = {"cashflow": draw_cashflow, "bars": draw_bars, "reveal": draw_reveal}

# ------------------------------------------------------------------ captions (word by word, *accent* words in gold)
def caption_layer(text, k):
    words = text.split(); size = 66
    lines_, cur = [], []
    for w_ in words:
        test = " ".join(x.strip("*") for x in cur + [w_])
        if cur and text_layer(test, F_HEAD, size, WHITE).width > 940: lines_.append(cur); cur = [w_]
        else: cur.append(w_)
    if cur: lines_.append(cur)
    im = Image.new("RGBA", (W, int(size * 1.18) * len(lines_)), (0, 0, 0, 0))
    space = 18; n = len(words); shown = int(math.ceil(k * n)); idx = 0
    for li, row in enumerate(lines_):
        lays = []
        for w_ in row:
            acc = w_.startswith("*") or w_.rstrip(".,?!:").endswith("*")
            lays.append((text_layer(w_.replace("*", ""), F_HEAD, size, GOLD if acc else WHITE, tracking=-0.01), idx < shown)); idx += 1
        x = (W - (sum(l.width for l, _ in lays) + space * (len(lays) - 1))) // 2
        for l, on in lays:
            if on: im.alpha_composite(l, (x, li * int(size * 1.18)))
            x += l.width + space
    return im

def pill(text, fill=GOLD, color=(20, 20, 14), size=24):
    tl = text_layer(text, F_NUM, size, color, tracking=0.12)
    b = Image.new("RGBA", (tl.width + 40, tl.height + 18), (0, 0, 0, 0))
    ImageDraw.Draw(b).rounded_rectangle([0, 0, b.width - 1, b.height - 1], radius=b.height // 2, fill=fill + (255,))
    b.alpha_composite(tl, (20, 9)); return b

# ------------------------------------------------------------------ stat card scene (WHY IT MATTERS)
def stat_frame(f, sc, now, st, dur):
    k = ease_out(min(1, (now - st) / 0.6))
    pl = pill(sc.get("label", "WHY IT MATTERS")); place(f, pl, W // 2, 400)
    big = sc["stat"]; m = re.match(r"([^\d]*)([\d.]+)(.*)", big)
    val = float(m.group(2)) * ease_out(min(1, (now - st) / 1.2)); dec = len(m.group(2).split(".")[1]) if "." in m.group(2) else 0
    bl = text_layer(f"{m.group(1)}{val:.{dec}f}{m.group(3)}", F_NUM, 230, GOLD, tracking=-0.03); place(f, bl, W // 2, 500)
    src = text_layer(sc.get("source", ""), F_MED, 30, SOFT); place(f, src, W // 2, 1760)
    if sc.get("grid"):                                  # 100 little houses, N of them empty
        n_hi = sc["grid"]; cell = 48; gx0 = (W - cell * 20) // 2 + 4; gy0 = 830
        g = ImageDraw.Draw(f)
        for i in range(100):
            r, c = divmod(i, 20); x = gx0 + c * cell; y = gy0 + r * 34 * 1.0
            y = gy0 + r * 54
            lit = i >= 100 - n_hi and (now - st) > 1.0 + (i - (100 - n_hi)) * 0.12
            col = (90, 110, 98) if lit else (52, 170, 98)
            pts = [(x + 5, y + 40), (x + 5, y + 18), (x + 22, y + 2), (x + 39, y + 18), (x + 39, y + 40)]
            if lit: g.polygon(pts, outline=GOLD + (255,), width=3)
            else: g.polygon(pts, fill=col + (255,))
        lab = text_layer(sc.get("grid_label", ""), F_SEMI, 34, GOLD); place(f, lab, W // 2, gy0 + 300)

# ------------------------------------------------------------------ camera: per-scene keyframes [frac, cx, cy, zoom]
def camera(sc, now, st, dur):
    keys = sc.get("cam") or [[0, .5, .5, 1.0]]
    f = (now - st) / max(dur, .01)
    for a, b in zip(keys, keys[1:] + [keys[-1]]):
        if a[0] <= f <= b[0] or b is keys[-1]:
            span = max(1e-6, b[0] - a[0]); u = ease_in_out(min(1, max(0, (f - a[0]) / span)))
            return [a[i] + (b[i] - a[i]) * u for i in (1, 2, 3)]
    return keys[-1][1:]

# ------------------------------------------------------------------ cover (0.5 s lead + platform thumbnail)
def make_cover():
    c = BASE.copy()
    top = stripe_band(W, 34, 0); c.alpha_composite(top, (0, 0)); c.alpha_composite(top, (0, H - 34))
    place(c, logo_layer(300, white=True), W // 2, 120)
    size = 112; ls = wrap(lesson["cover"].replace("*", ""), F_NUM, size, 960)
    acc = {w.strip("*.,?!") for w in lesson["cover"].split() if "*" in w}
    y = 250
    for l in ls:
        lays = [text_layer(w_, F_NUM, size, GOLD if w_.strip(".,?!'\u2019") in acc else WHITE, tracking=-0.03) for w_ in l.split()]
        gap = int(size * .26); tw = sum(x.width for x in lays) + gap * (len(lays) - 1)
        lay = Image.new("RGBA", (tw, max(x.height for x in lays)), (0, 0, 0, 0)); x = 0
        for wl in lays: lay.alpha_composite(wl, (x, 0)); x += wl.width + gap
        place(c, lay, W // 2, y); y += int(size * 1.04)
    sub = text_layer(lesson.get("cover_sub", ""), F_SEMI, 40, GOLD); place(c, sub, W // 2, y + 20)
    # a still of the main diagram, mid-story
    mid = timeline[1][0] + timeline[1][1] * .9 if len(timeline) > 1 else 2
    pan = PANELS[scenes[1]["panel"]](mid).resize((760, 760), Image.LANCZOS)
    m = Image.new("L", pan.size, 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, 759, 759], radius=36, fill=255)
    c.paste(pan, ((W - 760) // 2, max(y + 110, 980)), m)
    return c.convert("RGB")

# ------------------------------------------------------------------ render
silent = os.path.join(work, "explainer_silent.mp4")
enc = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                        "-i", "-", "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p", silent], stdin=subprocess.PIPE)
cover = make_cover(); cover_path = os.path.join(os.path.dirname(os.path.abspath(out_mp4)), "cover.jpg"); cover.save(cover_path, quality=93)
n_main = int(t * FPS); end_fn = render_end_beat(END_DUR)
pmask = Image.new("L", (PW, PH), 0); ImageDraw.Draw(pmask).rounded_rectangle([0, 0, PW - 1, PH - 1], radius=40, fill=255)
last = None
for i in range(n_main):
    now = i / FPS
    if now < 0.5:
        fr = cover if now < 0.2 else Image.blend(cover, last or cover, 0)  # held cover
        enc.stdin.write(cover.tobytes()); continue
    si = max(j for j, (st, _, _) in enumerate(timeline) if st <= now) if now >= timeline[0][0] else 0
    st, dur, pts = timeline[si]; sc = scenes[si]
    f = BASE.copy()
    band = stripe_band(W, 34, now * 60); f.alpha_composite(band, (0, 0)); f.alpha_composite(band, (0, H - 34))
    if sc.get("panel"):
        pan = PANELS[sc["panel"]](now)
        cx, cy, z = camera(sc, now, st, dur)
        cw, ch = DW / z, DH / z
        x0 = min(max(cx * DW - cw / 2, 0), DW - cw); y0 = min(max(cy * DH - ch / 2, 0), DH - ch)
        pan = pan.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch))).resize((PW, PH), Image.LANCZOS)
        sh = Image.new("RGBA", (PW + 80, PH + 80), (0, 0, 0, 0)); ImageDraw.Draw(sh).rounded_rectangle([40, 50, PW + 40, PH + 50], radius=44, fill=(0, 0, 0, 150))
        f.alpha_composite(sh.filter(ImageFilter.GaussianBlur(24)), (PX - 40, PY - 40))
        f.paste(pan, (PX, PY), pmask)
        ImageDraw.Draw(f).rounded_rectangle([PX, PY, PX + PW - 1, PY + PH - 1], radius=40, outline=GOLD_D + (255,), width=3)
        place(f, pill(sc.get("label", "HOW IT WORKS")), W // 2, PY - 64)
    elif sc.get("stat"):
        stat_frame(f, sc, now, st, dur)
    # caption: the phrase currently being spoken, words appearing as said
    cur = next(((pt0, pd, ph) for pt0, pd, ph in pts if pt0 <= now < pt0 + pd + GAP + (TAIL if ph is pts[-1][2] else 0)), None)
    if cur:
        pt0, pd, ph = cur; k = min(1.0, (now - pt0) / max(.1, pd) * 1.08)
        cl = caption_layer(ph["text"], k)
        cy_cap = (PY + PH + 70) if sc.get("panel") else 1300
        f.alpha_composite(cl, (0, cy_cap))
    fr = f.convert("RGB"); last = fr
    enc.stdin.write(fr.tobytes())
XF = int(.5 * FPS)
for i in range(int(END_DUR * FPS)):
    e = end_fn(i / FPS)
    if i < XF: e = Image.blend(last, e, (i + 1) / XF)
    enc.stdin.write(e.tobytes())
enc.stdin.close(); enc.wait()

# ------------------------------------------------------------------ audio: voice + music bed
voice = np.zeros(int(total * SR) + SR, np.float32)
for t0, a in audio_clips:
    s0 = int(t0 * SR); voice[s0:s0 + len(a)] += a[:len(voice) - s0]
voice = voice / (np.abs(voice).max() or 1) * 0.9
vwav = os.path.join(work, "voice.wav")
with wave.open(vwav, "wb") as w_:
    w_.setnchannels(1); w_.setsampwidth(2); w_.setframerate(SR); w_.writeframes((voice * 32767).astype(np.int16).tobytes())
tracks = sorted(x for x in os.listdir(os.path.join(ROOT, "music")) if x.endswith(".m4a"))
track = os.environ.get("MUSIC_TRACK") or tracks[zlib.crc32(lesson["cover"].encode()) % len(tracks)][:-4]
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", silent, "-i", vwav, "-stream_loop", "-1", "-i", os.path.join(ROOT, "music", track + ".m4a"),
                "-filter_complex", f"[2:a]volume=0.10,afade=t=out:st={total - 1.5:.2f}:d=1.5,atrim=0:{total:.2f}[m];"
                f"[1:a]aresample=48000,highpass=f=70,acompressor=threshold=-18dB:ratio=3:attack=5:release=80[v];"
                f"[v][m]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-15:TP=-1.5[a]",
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out_mp4], check=True)
print(f"wrote {out_mp4} ({total:.1f}s, music {track})")
