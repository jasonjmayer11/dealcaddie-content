#!/usr/bin/env python3
"""DealCaddie "Real Estate, Explained": short teach-one-concept videos with an AI voice.

Educational first. The brand is a small logo up top and one soft line at the end.
Opens on a bold hook (deep green, huge type) that is also the thumbnail, then shrinks into a
cream explainer: animated stacks of numbers, bars, checklists, a gauge and morphing values,
with captions popping word by word as they are spoken.

Data lives in explain/<name>.json. Usage: python3 scripts/explain.py explain/x.json out.mp4
Preview one frame: STILL=<seconds> python3 scripts/explain.py explain/x.json out.mp4
"""
import json, math, os, re, subprocess, sys, wave, zlib
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reelkit import (W, H, FPS, INK, MUTED, FOREST, GREEN, RED, AMBER, WHITE, F_NUM, F_HEAD, F_SEMI, F_MED,
                     text_layer, wrap, place, ease_out, ease_in_out, gradient_bg, logo_layer, enter)
os.environ.setdefault("VOICE_SPEED", "1.12")
from wordtime import speak_timed, SR

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = json.load(open(sys.argv[1])); out_mp4 = os.path.abspath(sys.argv[2])
work = os.path.join(os.path.dirname(out_mp4), "explain_work"); os.makedirs(work, exist_ok=True)

GOLD = (201, 168, 76); GOLD_D = (150, 118, 38); GOLD_L = (232, 205, 130); TURF = (39, 165, 82)
LINE = (226, 222, 210); DEEP = (10, 52, 31); DEEP2 = (22, 92, 53)
TONE = {"good": GREEN, "bad": RED, "warn": AMBER, "gold": GOLD_D, None: INK, "ink": INK}
CX = W // 2
VIS_Y = 470                      # top of the visual area
CAP_Y = 1370                     # captions (kept above the platform UI at the bottom)

# ------------------------------------------------------------------ voice + timeline
LEAD, GAP, LEADIN = 0.2, 0.06, 0.04
t = LEAD; clips = []; events = {}; scenes = []
for si, sc in enumerate(M["scenes"]):
    sc["_t0"] = t; sc["_units"] = []
    for ln in sc["lines"]:
        a, units = speak_timed(ln["voice"]); d = len(a) / SR
        for u in units: u["t0"] += t; u["t1"] += t
        clips.append((t, a)); sc["_units"].append(units)
        cursor = 0
        for ev in ln.get("do", []):              # "id~word" (next unit starting with word), "id#3", "id@0.5"
            if "~" in ev:
                k, _, w_ = ev.partition("~")
                hit = [i for i, u in enumerate(units) if i >= cursor and u["show"].lower().lstrip("$−-").startswith(w_.lower().lstrip("$−-"))]
                if not hit: sys.exit(f"event {ev}: nothing from #{cursor} starts with {w_!r} in {[u['show'] for u in units]}")
                cursor = hit[0]; events[k] = units[cursor]["t0"]
            elif "#" in ev:
                k, _, n = ev.partition("#"); events[k] = units[min(int(n), len(units) - 1)]["t0"]
            else:
                k, _, f = ev.partition("@"); events[k] = t + d * float(f or 0)
        t += d + GAP + ln.get("pause", 0.12)
    sc["_t1"] = t
    scenes.append(sc)
TOTAL = t + M.get("tail", 2.2)
HOOK_END = scenes[1]["_t0"] - 0.1 if len(scenes) > 1 else 2.0   # hook shrinks into the header here
print(f"total {TOTAL:.1f}s, hook ends {HOOK_END:.1f}s")

def since(k, now): return None if k not in events or now < events[k] else now - events[k]
def prog(k, now, dur=0.6):
    s = since(k, now); return 0.0 if s is None else ease_out(s / dur)
def shown(k, now): return k is None or since(k, now) is not None

# ------------------------------------------------------------------ helpers
_tc = {}
def T(text, path, size, fill, tracking=0.0):
    key = (text, path, size, fill, tracking)
    if key not in _tc: _tc[key] = text_layer(text, path, size, fill, tracking=tracking)
    return _tc[key]

def rich(text, path, size, color, accent, max_w, tracking=-0.02, line_h=1.06):
    """*accent* words, wrapped and centred."""
    words = text.split(); rows, cur, wsum = [], [], 0; sp = int(size * 0.26)
    for w in words:
        acc = "*" in w; l = T(w.replace("*", ""), path, size, accent if acc else color, tracking)
        if cur and wsum + sp + l.width > max_w: rows.append(cur); cur, wsum = [], 0
        cur.append(l); wsum += (sp if len(cur) > 1 else 0) + l.width
    if cur: rows.append(cur)
    lh = int(size * line_h); im = Image.new("RGBA", (max_w, lh * len(rows) + int(size * 0.25)), (0, 0, 0, 0))
    for r, row in enumerate(rows):
        x = (max_w - sum(l.width for l in row) - sp * (len(row) - 1)) // 2
        for l in row: im.alpha_composite(l, (x, r * lh)); x += l.width + sp
    return im

def card(w, h, r=30, fill=WHITE, border=LINE, bw=2, shadow=True):
    pad = 40; im = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([pad, pad + 14, pad + w, pad + h + 14], radius=r, fill=(14, 33, 23, 38))
        im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(16)))
    ImageDraw.Draw(im).rounded_rectangle([pad, pad, pad + w, pad + h], radius=r, fill=fill, outline=border, width=bw)
    return im, pad

def pill(text, fill=GOLD, color=INK, size=26, track=0.16, padx=26, pady=12):
    l = T(text, F_NUM, size, color, track); w, h = l.width + 2 * padx, l.height + 2 * pady
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=fill)
    im.alpha_composite(l, (padx, pady + 2)); return im

def money(v, sign=False):
    s = f"${abs(v):,.0f}"
    if v < -0.5: return "−" + s
    return ("+" + s) if sign and v > 0.5 else s

def fmtv(v, fmt):
    if fmt == "$": return money(v)
    if fmt == "$+": return money(v, True)
    if fmt == "x": return f"{v:.2f}"
    if fmt == "%": return f"{v:.2f}%".replace(".00%", "%")
    return f"{v:,.0f}"

def count(target, p):
    """Count a display string like "$300,000", "−$247", "1.25" or "1%" up from zero."""
    m = re.match(r"^([^0-9]*)([0-9][0-9,]*)(\.[0-9]+)?(.*)$", target)
    if not m or p >= 1: return target
    pre, ints, dec, suf = m.groups(); v = float(ints.replace(",", "") + (dec or "")) * ease_out(p)
    nd = len(dec) - 1 if dec else 0
    return pre + (f"{v:,.{nd}f}" if "," in ints else f"{v:.{nd}f}") + suf

def mix(c1, c2, k): return tuple(int(a + (b - a) * k) for a, b in zip(c1, c2))

def icon(kind, d=58):
    im = Image.new("RGBA", (d * 4, d * 4), (0, 0, 0, 0)); g = ImageDraw.Draw(im); s = 4
    g.ellipse([0, 0, d * s - 1, d * s - 1], fill=(GREEN if kind == "check" else RED) + (255,))
    if kind == "check":
        g.line([(d * s * .27, d * s * .53), (d * s * .44, d * s * .69), (d * s * .74, d * s * .35)], fill=WHITE, width=int(d * s * .11), joint="curve")
    else:
        a, b = d * s * .32, d * s * .68
        g.line([(a, a), (b, b)], fill=WHITE, width=int(d * s * .11)); g.line([(a, b), (b, a)], fill=WHITE, width=int(d * s * .11))
    return im.resize((d, d), Image.LANCZOS)
ICON = {k: icon(k) for k in ("check", "x")}

# ------------------------------------------------------------------ visuals (each returns an RGBA layer W x ~880)
VH = 800

def v_stack(sp, now):
    """Rows of label/value cards joined by operator badges; the result row is highlighted."""
    im = Image.new("RGBA", (W, VH), (0, 0, 0, 0)); rows = sp["rows"]
    rh = sp.get("row_h", 150); gap = sp.get("gap", 34); n = len(rows)
    total_h = n * rh + (n - 1) * gap; y = max(0, (VH - total_h) // 2 - 20)
    cw = 900
    for r in rows:
        on = r.get("on"); p = prog(on, now, 0.5) if on else 1.0
        if p <= 0: y += rh + gap; continue
        res = r.get("result"); tone = TONE[r.get("tone")]
        fill = WHITE if not res else (mix(WHITE, tone, 0.10) if r.get("tone") else (247, 241, 222))
        border = LINE if not res else (tone if r.get("tone") else GOLD)
        c, pad = card(cw, rh, fill=fill, border=border, bw=4 if res else 2)
        lab = T(r["label"], F_SEMI, 38 if not res else 40, MUTED if not res else INK)
        sub = r.get("sub")
        ly = pad + (rh - lab.height) // 2 - (16 if sub else 0)
        c.alpha_composite(lab, (pad + 44, ly))
        if sub: c.alpha_composite(T(sub, F_MED, 28, MUTED), (pad + 44, ly + lab.height + 8))
        vtxt = r["value"]; pv = prog(on, now, 0.9) if on and r.get("count", True) else 1.0
        vl = T(count(vtxt, pv), F_NUM, r.get("size", 84 if not res else 92), tone, -0.02)
        c.alpha_composite(vl, (pad + cw - 44 - vl.width, pad + (rh - vl.height) // 2 + 4))
        place(im, c, CX, y - pad + (1 - p) * 30, p, 0.96 + 0.04 * p)
        if r.get("op"):                                       # operator badge on the card's top edge
            b = 74; bi = Image.new("RGBA", (b, b), (0, 0, 0, 0)); g = ImageDraw.Draw(bi)
            g.ellipse([0, 0, b - 1, b - 1], fill=FOREST); o = T(r["op"], F_NUM, 50, WHITE)
            bi.alpha_composite(o, ((b - o.width) // 2, (b - o.height) // 2 - 3))
            place(im, bi, CX - cw // 2 + 4, y - gap // 2 - b // 2 + 4, p)
        y += rh + gap
    return im

def v_bars(sp, now):
    im = Image.new("RGBA", (W, VH), (0, 0, 0, 0)); items = sp["items"]
    vmax = max(i["value"] for i in items) * 1.08; bw_max = 880; y = 70
    if sp.get("title"):
        place(im, T(sp["title"], F_SEMI, 36, MUTED, 0.02), CX, 0)
    for it in items:
        p = prog(it.get("on"), now, 0.9) if it.get("on") else 1.0
        if p <= 0: y += 230; continue
        place(im, T(it["label"], F_SEMI, 38, INK), CX - bw_max // 2 + T(it["label"], F_SEMI, 38, INK).width // 2, y, min(1, p * 2))
        tone = TONE[it.get("tone", "ink")]; bh = 104
        g = ImageDraw.Draw(im)
        g.rounded_rectangle([CX - bw_max // 2, y + 60, CX + bw_max // 2, y + 60 + bh], radius=22, fill=(233, 229, 218))
        w_ = int(bw_max * it["value"] / vmax * ease_out(p))
        if w_ > 44: g.rounded_rectangle([CX - bw_max // 2, y + 60, CX - bw_max // 2 + w_, y + 60 + bh], radius=22, fill=tone)
        vl = T(count(fmtv(it["value"], it.get("fmt", "$")), p) + it.get("suffix", ""), F_NUM, 60, WHITE)
        if w_ > vl.width + 60: im.alpha_composite(vl, (CX - bw_max // 2 + w_ - vl.width - 30, y + 60 + (bh - vl.height) // 2 + 3))
        y += 230
    st = sp.get("stamp")
    if st and shown(st["on"], now):
        s_ = since(st["on"], now); k = ease_out(s_ / 0.35)
        sc = 1.5 - 0.5 * k
        tone = TONE[st.get("tone", "bad")]
        lab = T(st["text"], F_NUM, 64, tone, 0.04); pw, ph = lab.width + 80, lab.height + 50
        stamp = Image.new("RGBA", (pw, ph), (0, 0, 0, 0)); g = ImageDraw.Draw(stamp)
        g.rounded_rectangle([3, 3, pw - 4, ph - 4], radius=18, outline=tone, width=7, fill=(255, 255, 255, 235))
        stamp.alpha_composite(lab, (40, 25 + 2)); stamp = stamp.rotate(-6, expand=True, resample=Image.BICUBIC)
        place(im, stamp, CX, y + 10 - stamp.height * (sc - 1) / 2, min(1, k * 1.5), sc)
    return im

def v_check(sp, now):
    im = Image.new("RGBA", (W, VH), (0, 0, 0, 0)); y = 30
    if sp.get("title"):
        tl = rich(sp["title"], F_NUM, 56, INK, GOLD_D, 940); place(im, tl, CX, y); y += tl.height + 40
    items = sp["items"]; ih = 128
    c, pad = card(900, ih * len(items) + 30)
    place(im, c, CX, y - pad)
    for i, it in enumerate(items):
        p = prog(it.get("on"), now, 0.45) if it.get("on") else 1.0
        yy = y + 15 + i * ih
        if i: ImageDraw.Draw(im).line([CX - 410, yy, CX + 410, yy], fill=(236, 232, 222), width=2)
        if p <= 0: continue
        ic = ICON[it.get("mark", "check")]
        place(im, ic, CX - 450 + 50 + ic.width // 2, yy + (ih - ic.height) // 2, p, 0.6 + 0.4 * p)
        tl = T(it["text"], F_SEMI, 44, INK)
        im.alpha_composite(tl.copy() if p >= 1 else Image.blend(Image.new("RGBA", tl.size, (0, 0, 0, 0)), tl, p),
                           (CX - 450 + 140 + int((1 - p) * 20), yy + (ih - tl.height) // 2))
    if sp.get("note") and shown(sp.get("note_on"), now):
        nl = rich(sp["note"], F_HEAD, 44, MUTED, FOREST, 900)
        place(im, nl, CX, y + ih * len(items) + 90, prog(sp.get("note_on"), now) if sp.get("note_on") else 1)
    return im

def v_big(sp, now):
    im = Image.new("RGBA", (W, VH), (0, 0, 0, 0))
    lay = rich(sp["text"], F_NUM, sp.get("size", 104), INK, sp.get("accent_color") and tuple(sp["accent_color"]) or GREEN, 960)
    sub = rich(sp["sub"], F_HEAD, 50, MUTED, FOREST, 900) if sp.get("sub") else None
    h_ = lay.height + (sub.height + 40 if sub else 0); y = (VH - h_) // 2 - 30
    p = prog(sp.get("on"), now, 0.6) if sp.get("on") else 1
    place(im, lay, CX, y + (1 - p) * 30, p)
    if sub:
        q = prog(sp.get("sub_on"), now, 0.6) if sp.get("sub_on") else p
        place(im, sub, CX, y + lay.height + 40 + (1 - q) * 20, q)
    return im

def v_gauge(sp, now):
    im = Image.new("RGBA", (W, VH), (0, 0, 0, 0)); S = 2
    lo, hi = sp["min"], sp["max"]; R = 330; cy = 400; ring = 60
    big = Image.new("RGBA", (W * S, VH * S), (0, 0, 0, 0)); g = ImageDraw.Draw(big)
    def ang(v): return 180 + 180 * (max(lo, min(hi, v)) - lo) / (hi - lo)
    box = [(CX - R) * S, (cy - R) * S, (CX + R) * S, (cy + R) * S]
    for a, b, tone in sp["zones"]:
        g.arc(box, ang(a), ang(b), fill=TONE[tone] + (255,), width=ring * S)
    for a, b, tone in sp["zones"][1:]:                       # thin cream seams between zones
        g.arc(box, ang(a) - .4, ang(a) + .4, fill=(248, 246, 241, 255), width=ring * S)
    im.alpha_composite(big.resize((W, VH), Image.LANCZOS))
    for v in sp.get("ticks", []):
        th = math.radians(ang(v)); r2 = R + ring // 2 + 34
        tl = T(f"{v:.1f}" if isinstance(v, float) else str(v), F_SEMI, 32, MUTED)
        place(im, tl, CX + r2 * math.cos(th), cy + r2 * math.sin(th) - tl.height / 2)
    # needle: eases between keyframes as each is spoken
    cur = sp["needle"][0]["value"] if not sp["needle"][0].get("on") else lo; note = None; tone = "ink"
    for kf in sp["needle"]:
        s_ = since(kf.get("on"), now) if kf.get("on") else 99
        if s_ is None: break
        k = ease_in_out(s_ / 1.1); cur = cur + (kf["value"] - cur) * k
        note, tone = kf.get("note"), kf.get("tone", "ink") if k > .55 else tone
    th = math.radians(ang(cur)); L = R - ring // 2 - 26
    nd = Image.new("RGBA", (W * S, VH * S), (0, 0, 0, 0)); g = ImageDraw.Draw(nd)
    g.line([(CX * S, cy * S), ((CX + L * math.cos(th)) * S, (cy + L * math.sin(th)) * S)], fill=INK + (255,), width=14 * S)
    g.ellipse([(CX - 26) * S, (cy - 26) * S, (CX + 26) * S, (cy + 26) * S], fill=INK + (255,))
    g.ellipse([(CX - 10) * S, (cy - 10) * S, (CX + 10) * S, (cy + 10) * S], fill=GOLD + (255,))
    im.alpha_composite(nd.resize((W, VH), Image.LANCZOS))
    vl = T(f"{cur:.2f}", F_NUM, 150, TONE[tone], -0.03); place(im, vl, CX, cy + 50)
    if sp.get("label"): place(im, T(sp["label"], F_NUM, 30, MUTED, 0.2), CX, cy + 50 + vl.height + 18)
    if note:
        nl = pill(note, fill=TONE[tone], color=WHITE, size=34, track=0.04); place(im, nl, CX, cy + 50 + vl.height + 76)
    return im

def v_morph(sp, now):
    im = Image.new("RGBA", (W, VH), (0, 0, 0, 0)); y = 60
    k = ease_in_out((since(sp["on"], now) or 0) / sp.get("dur", 1.6)) if shown(sp["on"], now) else 0
    for r in sp["rows"]:
        v = r["from"] + (r["to"] - r["from"]) * k
        c, pad = card(900, 230)
        c.alpha_composite(T(r["label"], F_SEMI, 38, MUTED), (pad + 50, pad + 34))
        col = INK
        if r.get("tone_from"): col = mix(TONE[r["tone_from"]], TONE[r["tone_to"]], min(1, k * 1.3))
        vl = T(fmtv(round(v), r.get("fmt", "$")), F_NUM, 110, col, -0.03)
        c.alpha_composite(vl, (pad + 50, pad + 90))
        if r.get("arrow") and k > 0:
            a = T(r["arrow"], F_NUM, 44, MUTED); c.alpha_composite(with_a(a, min(1, k * 2)), (pad + 900 - 50 - a.width, pad + 130))
        place(im, c, CX, y - pad); y += 290
    if sp.get("note") and k >= .98:
        q = prog(sp["on"], now - sp.get("dur", 1.6), 0.5)
        nl = pill(sp["note"], fill=FOREST, color=WHITE, size=40, track=0.04, padx=40, pady=20)
        place(im, nl, CX, y + 10 + (1 - q) * 20, q)
    return im

def with_a(l, a):
    l = l.copy(); l.putalpha(l.getchannel("A").point(lambda v: int(v * a))); return l

VIS = {"stack": v_stack, "bars": v_bars, "check": v_check, "big": v_big, "gauge": v_gauge, "morph": v_morph}

# ------------------------------------------------------------------ captions (spoken words pop as they're heard)
def caption(units, now, size=64, max_rows=2):
    rows, cur, wsum = [], [], 0
    for u in units:
        l = T(u["show"], F_HEAD, size, FOREST if u["accent"] else INK, -0.01)
        if cur and wsum + 16 + l.width > 940: rows.append(cur); cur, wsum = [], 0
        cur.append((u, l)); wsum += (16 if len(cur) > 1 else 0) + l.width
    if cur: rows.append(cur)
    pages = [rows[i:i + max_rows] for i in range(0, len(rows), max_rows)]; page = pages[0]
    for pg in pages:
        if pg[0][0][0]["t0"] - LEADIN <= now: page = pg
    lh = int(size * 1.2); im = Image.new("RGBA", (W, lh * max_rows + 20), (0, 0, 0, 0))
    for r, row in enumerate(page):
        x = (W - sum(l.width for _, l in row) - 16 * (len(row) - 1)) // 2
        for u, l in row:
            s_ = now - (u["t0"] - LEADIN)
            if s_ >= 0:
                k = ease_out(s_ / 0.07)
                im.alpha_composite(l if k >= .999 else with_a(l, k), (x, r * lh + int((1 - k) * 6)))
            x += l.width + 16
    return im

# ------------------------------------------------------------------ static layers
BG = gradient_bg().convert("RGBA")
LOGO_S = logo_layer(210)
TAG = pill(M.get("series", "REAL ESTATE, EXPLAINED"), fill=GOLD, color=INK, size=24, track=0.2)
HOOK = M["hook"]
HOOK_BIG = rich(HOOK["text"], F_NUM, HOOK.get("size", 132), WHITE, GOLD_L, 960, line_h=1.02)
HOOK_SUB = rich(HOOK["sub"], F_HEAD, 56, (200, 228, 210), WHITE, 940) if HOOK.get("sub") else None
HEAD_T = rich(M.get("header", HOOK["text"]), F_NUM, 52, INK, GOLD_D, 960)
DEEP_BG = Image.new("RGB", (1, H))
for y_ in range(H):
    DEEP_BG.putpixel((0, y_), mix(DEEP2, DEEP, y_ / (H - 1)))
DEEP_BG = DEEP_BG.resize((W, H)).convert("RGBA")
_gl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
ImageDraw.Draw(_gl).ellipse([CX - 520, 520, CX + 520, 1400], fill=GOLD + (60,))
DEEP_BG.alpha_composite(_gl.filter(ImageFilter.GaussianBlur(140)))
LOGO_W = logo_layer(260, white=True)

def hook_frame(now):
    f = DEEP_BG.copy()
    place(f, LOGO_W, CX, 230, 0.95)
    hy = (H - HOOK_BIG.height - (HOOK_SUB.height + 50 if HOOK_SUB else 0)) // 2 - 80
    sc = 1.0 + 0.03 * (1 - ease_out(now / 1.2))                 # visible from frame 0, settles gently
    place(f, HOOK_BIG, CX, hy, 1.0, sc)
    if HOOK_SUB:
        q = prog("sub", now, 0.5) if "sub" in events else ease_out((now - 0.4) / 0.5)
        place(f, HOOK_SUB, CX, hy + HOOK_BIG.height + 50 + (1 - q) * 20, q)
    place(f, TAG, CX, H - 560, 0.95)
    return f

def header(f, a=1.0):
    place(f, LOGO_S, CX, 175, a)
    place(f, TAG, CX, 262, a)
    place(f, HEAD_T, CX, 340, a)

def scene_at(now):
    cur = 0
    for i, sc in enumerate(scenes):
        if now >= sc["_t0"] - 0.15: cur = i
    return cur

def scene_layer(i, now):
    sc = scenes[i]; v = sc.get("visual")
    return VIS[v["type"]](v, now) if v else None

def body(now):
    f = BG.copy(); header(f)
    i = scene_at(now); sc = scenes[i]
    xf = 0.32; s_ = now - (sc["_t0"] - 0.15)
    if i > 1 and s_ < xf:                                      # crossfade from the previous visual
        pl = scene_layer(i - 1, now)
        if pl: place(f, pl, CX, VIS_Y - s_ / xf * 40, 1 - s_ / xf)
    lay = scene_layer(i, now)
    if lay:
        k = ease_out(s_ / xf) if i > 0 else 1
        place(f, lay, CX, VIS_Y + (1 - k) * 40, k)
    if sc.get("example") or M.get("example"):
        ex = T(sc.get("example") or M["example"], F_MED, 28, MUTED); place(f, ex, CX, VIS_Y + VH + 26, 0.9)
    for units in sc["_units"]:                                 # caption = the line being spoken now
        if units and units[0]["t0"] - LEADIN <= now: cu = units
    if sc["_units"] and now >= sc["_units"][0][0]["t0"] - LEADIN:
        place(f, caption(cu, now), CX, CAP_Y)
    return f

BADGE_H = 104
def _badges():
    d = os.path.join(ROOT, "assets", "badges")
    a = Image.open(os.path.join(d, "app-store-badge@hi.png")).convert("RGBA"); g = Image.open(os.path.join(d, "google-play-badge@hi.png")).convert("RGBA")
    a = a.resize((int(a.width * BADGE_H / a.height), BADGE_H), Image.LANCZOS); g = g.resize((int(g.width * BADGE_H / g.height), BADGE_H), Image.LANCZOS)
    row = Image.new("RGBA", (a.width + g.width + 32, BADGE_H), (0, 0, 0, 0)); row.alpha_composite(a, (0, 0)); row.alpha_composite(g, (a.width + 32, 0))
    return row
END_LOGO = logo_layer(520)
END_LINE = rich(scenes[-1].get("end_line", "Run the real numbers on any listing."), F_HEAD, 58, INK, FOREST, 880)
END_AVAIL = T("AVAILABLE ON", F_SEMI, 26, MUTED, 0.24)
END_BADGES = _badges()
END_SITE = T("dealcaddie.ai", F_SEMI, 36, MUTED)

def end_frame(now):
    """Clean close: logo, one line, store badges, site. No captions: the voice says what's on screen."""
    tt = now - scenes[-1]["_t0"] + 0.15
    f = BG.copy(); y = 610
    p, dy = enter(tt, 0.0, 0.8, 20); place(f, END_LOGO, CX, y + dy, p, 0.98 + 0.02 * p); y += END_LOGO.height + 70
    p, dy = enter(tt, 0.2, 0.7, 16); place(f, END_LINE, CX, y + dy, p); y += END_LINE.height + 90
    p, dy = enter(tt, 0.45, 0.7, 16); place(f, END_AVAIL, CX, y + dy, p); y += END_AVAIL.height + 26
    place(f, END_BADGES, CX, y + dy, p); y += BADGE_H + 70
    p, dy = enter(tt, 0.65, 0.7, 12); place(f, END_SITE, CX, y + dy, p)
    return f

def frame(now):
    if now < HOOK_END:
        return hook_frame(now).convert("RGB")
    if scenes[-1].get("end") and now >= scenes[-1]["_t0"] - 0.15:
        s_ = now - (scenes[-1]["_t0"] - 0.15)
        e = end_frame(now)
        if s_ < 0.5: e = Image.blend(body(scenes[-1]["_t0"] - 0.16), e, ease_in_out(s_ / 0.5))
        return e.convert("RGB")
    s_ = now - HOOK_END; tr = 0.55
    f = body(now)
    if s_ < tr:                                                # deep green panel lifts away, revealing the explainer
        k = ease_in_out(s_ / tr); hf = hook_frame(HOOK_END)
        cut = int(H * (1 - k))
        if cut > 0:
            f.alpha_composite(hf.crop((0, H - cut, W, H)), (0, 0))
    return f.convert("RGB")

if os.environ.get("STILL"):
    for s in os.environ["STILL"].split(","):
        frame(float(s)).save(out_mp4[:-4] + f"-{s}.png")
    print("stills", os.environ["STILL"]); sys.exit(0)

# ------------------------------------------------------------------ encode
silent = os.path.join(work, "silent.mp4")
enc = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                        "-c:v", "libx264", "-crf", "17", "-preset", os.environ.get("X264_PRESET", "medium"), "-pix_fmt", "yuv420p", silent], stdin=subprocess.PIPE)
cover = hook_frame(1.6).convert("RGB")
cover.save(os.path.join(os.path.dirname(out_mp4), os.path.basename(out_mp4)[:-4] + "-cover.jpg"), quality=93)
for i in range(int(TOTAL * FPS)):
    enc.stdin.write(frame(i / FPS).tobytes())
enc.stdin.close(); enc.wait()

voice = np.zeros(int(TOTAL * SR) + SR, np.float32)
for t0, a in clips: s0 = int(t0 * SR); voice[s0:s0 + len(a)] += a[:len(voice) - s0]
voice = voice / (np.abs(voice).max() or 1) * 0.9
vw = os.path.join(work, "voice.wav")
with wave.open(vw, "wb") as w_:
    w_.setnchannels(1); w_.setsampwidth(2); w_.setframerate(SR); w_.writeframes((voice * 32767).astype(np.int16).tobytes())
tracks = sorted(x[:-4] for x in os.listdir(os.path.join(ROOT, "music")) if x.endswith(".m4a"))
track = os.environ.get("MUSIC_TRACK") or M.get("music") or tracks[zlib.crc32(HOOK["text"].encode()) % len(tracks)]
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", silent, "-i", vw, "-stream_loop", "-1", "-i", os.path.join(ROOT, "music", track + ".m4a"),
                "-filter_complex", f"[2:a]volume=0.10,afade=t=out:st={TOTAL - 2.2:.2f}:d=2.2,atrim=0:{TOTAL:.2f}[m];"
                "[1:a]aresample=48000,highpass=f=70,acompressor=threshold=-18dB:ratio=3:attack=5:release=80[v];"
                "[v][m]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-15:TP=-1.5[a]",
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out_mp4], check=True)
d_ = os.path.dirname(out_mp4)
if M.get("caption"): open(os.path.join(d_, "caption.txt"), "w").write(M["caption"])
open(os.path.join(d_, "title.txt"), "w").write(M.get("post_title") or HOOK["text"].replace("*", ""))
print(f"wrote {out_mp4} ({TOTAL:.1f}s, music {track})")
