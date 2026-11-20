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
        # each sentence is its own take, with a short beat after it, so a new idea never runs into the last one
        parts, depth, cur_ = [], 0, ""
        for ch in ln["voice"]:
            depth += ch == "{"; depth -= ch == "}"; cur_ += ch
            if depth == 0 and ch in ".?!:" and cur_.strip() and not re.search(r"\d[.:]$", cur_): parts.append(cur_.strip()); cur_ = ""
        if cur_.strip(): parts.append(cur_.strip())
        if "beat" not in ln and "beat" not in M: parts = [ln["voice"]]            # default: one natural take per line
        units, tt, a_all = [], t, []
        for j, part in enumerate(parts):
            a_, us = speak_timed(part)
            for u in us: u["t0"] += tt; u["t1"] += tt
            clips.append((tt, a_)); units += us
            tt += len(a_) / SR + (ln.get("beat", M.get("beat", 0.3)) if j < len(parts) - 1 else 0)
        d = tt - t; sc["_units"].append(units)
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
    words = text.replace("\n", " \n ").split(" "); rows, cur, wsum = [], [], 0; sp = int(size * 0.26); in_acc = False
    for w in words:
        if not w: continue
        if w == "\n":
            if cur: rows.append(cur)
            cur, wsum = [], 0; continue
        starts, ends = w.startswith("*"), w.rstrip(".,!?:;").endswith("*")   # *multi word accent spans*
        if starts: in_acc = True
        acc = in_acc or ("*" in w)
        if ends: in_acc = False
        l = T(w.replace("*", ""), path, size, accent if acc else color, tracking)
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

# ------------------------------------------------------------------ illustrations: the concept, drawn (house, tenant, bills, bank, cash)
SS = 3                                                    # supersample for smooth vector edges
BILL_G = (39, 165, 82); SKY = (205, 228, 242); SLATE = (64, 78, 72); TENANT = (66, 110, 168)

def _canvas(w, h): return Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
def _down(im, w, h): return im.resize((w, h), Image.LANCZOS)

_sc = {}
def sprite(kind, s):
    key = (kind, s)
    if key in _sc: return _sc[key]
    if kind == "house":
        w = h = s; im = _canvas(w, h); g = ImageDraw.Draw(im); k = s * SS
        g.ellipse([.10 * k, .88 * k, .90 * k, .99 * k], fill=(14, 33, 23, 40))
        g.rectangle([.66 * k, .14 * k, .76 * k, .34 * k], fill=(120, 60, 40, 255))
        g.rounded_rectangle([.17 * k, .42 * k, .83 * k, .93 * k], radius=.02 * k, fill=WHITE + (255,), outline=LINE + (255,), width=int(.012 * k))
        g.polygon([(.06 * k, .47 * k), (.5 * k, .08 * k), (.94 * k, .47 * k)], fill=FOREST + (255,))
        g.polygon([(.06 * k, .47 * k), (.5 * k, .08 * k), (.5 * k, .15 * k), (.13 * k, .47 * k)], fill=(19, 84, 50, 255))
        for x0 in (.24, .62):
            g.rounded_rectangle([x0 * k, .54 * k, (x0 + .14) * k, .68 * k], radius=.012 * k, fill=SKY + (255,), outline=(150, 170, 160, 255), width=int(.008 * k))
            g.line([((x0 + .07) * k, .54 * k), ((x0 + .07) * k, .68 * k)], fill=(150, 170, 160, 255), width=int(.006 * k))
        g.rounded_rectangle([.43 * k, .63 * k, .57 * k, .93 * k], radius=.05 * k, fill=GOLD + (255,))
        g.ellipse([.535 * k, .77 * k, .555 * k, .79 * k], fill=GOLD_D + (255,))
    elif kind in ("tenant", "you"):
        w, h = s, int(s * 1.15); im = _canvas(w, h); g = ImageDraw.Draw(im); k = s * SS
        col = TENANT if kind == "tenant" else FOREST
        g.ellipse([.31 * k, .02 * k, .69 * k, .40 * k], fill=(232, 190, 150, 255))
        g.pieslice([.31 * k, .0 * k, .69 * k, .30 * k], 180, 360, fill=(70, 50, 40, 255))
        g.rounded_rectangle([.12 * k, .46 * k, .88 * k, 1.13 * k], radius=.3 * k, fill=col + (255,))
    elif kind == "bank":
        w = h = s; im = _canvas(w, h); g = ImageDraw.Draw(im); k = s * SS; c = SLATE + (255,)
        g.polygon([(.08 * k, .32 * k), (.5 * k, .06 * k), (.92 * k, .32 * k)], fill=c)
        g.rectangle([.12 * k, .34 * k, .88 * k, .40 * k], fill=c)
        for i in range(4):
            x = .19 + i * .19; g.rectangle([x * k, .43 * k, (x + .10) * k, .80 * k], fill=c)
        g.rectangle([.08 * k, .83 * k, .92 * k, .92 * k], fill=c)
        d = T("$", F_NUM, int(s * .2), WHITE); im2 = _down(im, w, h); im2.alpha_composite(d, ((w - d.width) // 2, int(h * .13))); _sc[key] = im2; return im2
    elif kind == "bill":
        w, h = s, int(s * .52); im = _canvas(w, h); g = ImageDraw.Draw(im); k = SS
        g.rounded_rectangle([0, 0, w * k - 1, h * k - 1], radius=8 * k, fill=BILL_G + (255,))
        g.rounded_rectangle([6 * k, 6 * k, (w - 6) * k, (h - 6) * k], radius=6 * k, outline=(150, 220, 170, 255), width=2 * k)
        g.ellipse([(w / 2 - h * .3) * k, h * .2 * k, (w / 2 + h * .3) * k, h * .8 * k], fill=(26, 135, 64, 255))
        im2 = _down(im, w, h); d = T("$", F_NUM, int(h * .5), WHITE); im2.alpha_composite(d, ((w - d.width) // 2, (h - d.height) // 2 + 2)); _sc[key] = im2; return im2
    elif kind == "bag":
        w = h = s; im = _canvas(w, h); g = ImageDraw.Draw(im); k = s * SS
        g.ellipse([.12 * k, .30 * k, .88 * k, .98 * k], fill=GOLD + (255,))
        g.polygon([(.36 * k, .34 * k), (.30 * k, .10 * k), (.70 * k, .10 * k), (.64 * k, .34 * k)], fill=GOLD + (255,))
        g.rectangle([.33 * k, .27 * k, .67 * k, .33 * k], fill=GOLD_D + (255,))
        im2 = _down(im, w, h); d = T("$", F_NUM, int(s * .38), WHITE); im2.alpha_composite(d, ((w - d.width) // 2, int(h * .45))); _sc[key] = im2; return im2
    out = _down(im, w, h); _sc[key] = out; return out

_rot = {}
def bill_rot(s, deg):
    deg = int(deg) // 6 * 6; key = (s, deg)
    if key not in _rot: _rot[key] = sprite("bill", s).rotate(deg, expand=True, resample=Image.BICUBIC)
    return _rot[key]

def fly(im, ev, now, a, b, n=6, size=86, dur=0.75, stagger=0.13, arc=-120):
    """A stream of dollar bills arcing from a to b, starting when ev is spoken."""
    s_ = since(ev, now)
    if s_ is None: return
    for i in range(n):
        u = (s_ - i * stagger) / dur
        if not 0 < u < 1: continue
        e = ease_in_out(u); x = a[0] + (b[0] - a[0]) * e; y = a[1] + (b[1] - a[1]) * e + arc * 4 * e * (1 - e)
        sp = bill_rot(size, (i * 37 + u * 160) % 360 - 180)
        al = min(1, u * 5, (1 - u) * 5); place(im, with_a(sp, al) if al < 1 else sp, x, y - sp.height / 2)

def label_under(im, text, x, y, a=1.0, size=32, color=INK):
    l = T(text, F_SEMI, size, color); place(im, l, x, y, a)

def tile(text, tone=RED, size=30):
    return pill(text, fill=WHITE, color=tone, size=size, track=0.02, padx=24, pady=14)

def pile(im, level, cx, base, size=170):
    n = int(round(level * 12))
    for i in range(n):
        b = sprite("bill", size); place(im, b, cx + (10 if i % 2 else -10), base - b.height - i * 16)
    return base - (n * 13 + sprite("bill", size).height if n else 0)

def pop(ev, now, dur=0.4):
    s_ = since(ev, now)
    if s_ is None: return 0, 1
    k = ease_out(s_ / dur); return min(1, k * 1.6), 1.25 - 0.25 * k

def v_flow(sp, now):
    """Rent flows in, costs (and the bank) take their cut, what's left piles up."""
    im = Image.new("RGBA", (W, VH), (0, 0, 0, 0))
    HX, HY, HS = CX - 40, 300, 440
    house = sprite("house", HS); place(im, house, HX, HY - HS // 2)
    src = sp.get("source"); lvl = sp.get("pile", {}).get("start", 0.0)
    if src:
        tx, ty = 135, HY - 40; t_ = sprite("tenant", 180)
        place(im, t_, tx, ty - t_.height // 2); label_under(im, src.get("who", "Tenant"), tx, ty + t_.height // 2 + 12, 1, 34, MUTED)
        rp = pop(src["on"], now)
        if rp[0]: place(im, pill(src["label"], fill=BILL_G, color=WHITE, size=38, track=0.04), tx, ty - t_.height // 2 - 86, rp[0], rp[1])
        fly(im, src["on"], now, (tx + 50, ty), (HX - 40, HY), n=8, size=104, arc=-160)
        s_ = since(src["on"], now)
        if s_ is not None: lvl = max(lvl, min(1.0, ease_out((s_ - 0.5) / 1.2)))
    sinks = sp.get("sinks", []); sx = W - 140
    for i, sk in enumerate(sinks):
        sy = 130 + i * 128; a, sc = pop(sk["on"], now)
        if a: place(im, tile(sk["label"], TONE[sk.get("tone", "bad")], 36), sx, sy - 36, a, sc)
        fly(im, sk["on"], now, (HX + 80, HY + 60), (sx - 70, sy), n=3, size=84, arc=-60)
        s_ = since(sk["on"], now)
        if s_ is not None: lvl -= sk.get("take", 0.09) * min(1, ease_out(s_ / 0.9))
    bk = sp.get("bank")
    if bk:
        bx, by = W - 175, 470; b_ = sprite("bank", 220); a, sc = pop(bk["on"], now, 0.5)
        if a:
            place(im, b_, bx, by - b_.height // 2, a, sc)
            place(im, tile(bk["label"], SLATE), bx, by + b_.height // 2 + 6, a)
        fly(im, bk["on"], now, (CX - 40, 640), (bx, by), n=9, size=100, arc=-100, stagger=0.1)
        s_ = since(bk["on"], now)
        if s_ is not None: lvl -= bk.get("take", 0.75) * min(1, ease_out(s_ / 1.3))
    pl = sp.get("pile")
    if pl:
        top = pile(im, max(0.0, lvl), CX - 40, VH - 10)
        lab, val = pl.get("label"), pl.get("value")
        rl = pl.get("relabel")
        if rl and shown(rl["on"], now): lab, val = rl["label"], rl.get("value")
        if pl.get("on") and shown(pl["on"], now) and lab:
            ev = rl["on"] if rl and shown(rl["on"], now) else pl["on"]; a, sc = pop(ev, now)
            c = pill(lab + (f"   {val}" if val else ""), fill=FOREST, color=WHITE, size=42, track=0.02, padx=36, pady=20)
            place(im, c, CX + 250, VH - 150, a, sc)
    return im

def seal(text, label, tone, d=250):
    im = _canvas(d, d); g = ImageDraw.Draw(im); k = d * SS
    g.ellipse([0, 0, k - 1, k - 1], fill=TONE[tone] + (255,)); g.ellipse([.07 * k, .07 * k, .93 * k, .93 * k], outline=(255, 255, 255, 200), width=int(.015 * k))
    im = _down(im, d, d); v = T(text, F_NUM, int(d * .27), WHITE, -0.02); l = T(label, F_NUM, int(d * .085), WHITE, 0.18)
    im.alpha_composite(v, ((d - v.width) // 2, int(d * .30))); im.alpha_composite(l, ((d - l.width) // 2, int(d * .62)))
    return im.rotate(-8, resample=Image.BICUBIC)

def v_house(sp, now):
    """One house, the buyer, and a grade seal stamped on it."""
    im = Image.new("RGBA", (W, VH), (0, 0, 0, 0))
    HS = 470; house = sprite("house", HS); place(im, house, CX + 70, 30)
    bg = sp.get("bag")
    if bg:
        a, sc = pop(bg["on"], now, 0.5)
        if a:
            y_ = sprite("you", 180); place(im, y_, 170, 240, a)
            bag = sprite("bag", 160); place(im, bag, 310, 300, a, sc)
            label_under(im, bg["label"], 240, 480, a, 38, INK)
    se = sp.get("seal")
    if se:
        a, sc = pop(se["on"], now, 0.45)
        if a: place(im, seal(se["value"], se["label"], se.get("tone", "good"), 290), CX + 330, 0, a, sc)
    cp = sp.get("caption")
    if cp and shown(cp["on"], now):
        a, sc = pop(cp["on"], now)
        place(im, pill(cp["text"], fill=WHITE, color=INK, size=42, track=0.02, padx=38, pady=22), CX, 580, a)
        if cp.get("sub"): label_under(im, cp["sub"], CX, 690, a, 36, MUTED)
    return im

def v_compare(sp, now):
    """Same house, two buyers: who put in what, who takes a cut, and the return each one gets."""
    im = Image.new("RGBA", (W, VH), (0, 0, 0, 0))
    for side, x in (("left", CX - 255), ("right", CX + 255)):
        p = sp[side]; a, _ = pop(p["on"], now, 0.5)
        if not a: continue
        c, pad = card(480, 760); place(im, c, x, -pad + 10, a)
        place(im, pill(p["title"], fill=FOREST if side == "left" else SLATE, color=WHITE, size=28, track=0.06), x, 40, a)
        place(im, sprite("house", 230), x, 100, a)
        bx_ = x - 40 if p.get("bank") else x
        place(im, sprite("you", 100), bx_ - 110, 355, a)
        bag = sprite("bag", max(40, int(130 * p.get("bag", 1.0)))); place(im, bag, bx_, 470 - bag.height, a)
        label_under(im, p["put_in"], bx_ - 40, 482, a, 30, INK)
        if p.get("bank"):
            place(im, sprite("bank", 100), x + 150, 368, a); label_under(im, "+ mortgage", x + 150, 482, a, 26, MUTED)
        va, vsc = pop(p["val_on"], now, 0.5)
        if va:
            v = T(count(p["value"], min(1, (since(p["val_on"], now) or 0) / 0.8)), F_NUM, 120, TONE[p.get("tone", "good")], -0.03)
            place(im, v, x, 545, va, vsc); label_under(im, p["label"], x, 690, va, 32, INK)
    return im

# ------------------------------------------------------------------ BRRRR-style journey: one house, transformed step by step
def _fixer(s):
    im = _canvas(s, s); g = ImageDraw.Draw(im); k = s * SS
    g.ellipse([.10 * k, .88 * k, .90 * k, .99 * k], fill=(14, 33, 23, 40))
    g.rectangle([.66 * k, .20 * k, .74 * k, .34 * k], fill=(110, 90, 80, 255))
    g.polygon([(.18 * k, .42 * k), (.83 * k, .44 * k), (.82 * k, .93 * k), (.17 * k, .93 * k)], fill=(214, 200, 176, 255), outline=(150, 135, 110, 255))
    g.polygon([(.06 * k, .48 * k), (.5 * k, .10 * k), (.94 * k, .46 * k)], fill=(96, 84, 74, 255))
    g.polygon([(.42 * k, .22 * k), (.55 * k, .18 * k), (.58 * k, .30 * k), (.47 * k, .34 * k)], fill=(248, 246, 241, 255))     # roof hole
    g.line([(.30 * k, .30 * k), (.36 * k, .40 * k)], fill=(70, 60, 52, 255), width=int(.01 * k))
    g.rectangle([.24 * k, .54 * k, .38 * k, .68 * k], fill=(60, 60, 60, 255))                                               # broken window
    for y0 in (.56, .62):
        g.polygon([(.22 * k, (y0 - .01) * k), (.40 * k, (y0 + .02) * k), (.40 * k, (y0 + .05) * k), (.22 * k, (y0 + .02) * k)], fill=(176, 132, 82, 255))
    g.rectangle([.62 * k, .54 * k, .76 * k, .68 * k], fill=(120, 140, 150, 255)); g.line([(.63 * k, .55 * k), (.75 * k, .67 * k)], fill=WHITE + (255,), width=int(.006 * k))
    door = Image.new("RGBA", (int(.14 * k), int(.30 * k)), (126, 96, 66, 255)); door = door.rotate(9, expand=True, resample=Image.BICUBIC)
    im.alpha_composite(door, (int(.42 * k), int(.62 * k)))
    g.line([(.70 * k, .74 * k), (.74 * k, .80 * k), (.71 * k, .86 * k)], fill=(120, 105, 85, 255), width=int(.006 * k))  # crack
    for x0 in (.20, .28, .80):
        g.polygon([(x0 * k, .93 * k), ((x0 + .02) * k, .84 * k), ((x0 + .04) * k, .93 * k)], fill=(120, 150, 80, 255))     # weeds
    return _down(im, s, s)

def _person(s, body, hat=None, extra=None):
    w, h = s, int(s * 1.15); im = _canvas(w, h); g = ImageDraw.Draw(im); k = s * SS
    g.ellipse([.31 * k, .06 * k, .69 * k, .42 * k], fill=(232, 190, 150, 255))
    if hat == "hard":
        g.pieslice([.26 * k, -.02 * k, .74 * k, .36 * k], 180, 360, fill=(245, 196, 40, 255)); g.rectangle([.22 * k, .16 * k, .78 * k, .2 * k], fill=(220, 170, 20, 255))
    else:
        g.pieslice([.31 * k, .04 * k, .69 * k, .32 * k], 180, 360, fill=(70, 50, 40, 255))
    g.rounded_rectangle([.12 * k, .48 * k, .88 * k, 1.13 * k], radius=.3 * k, fill=body + (255,))
    if extra == "vest":
        g.rectangle([.30 * k, .52 * k, .36 * k, 1.1 * k], fill=(250, 250, 200, 255)); g.rectangle([.64 * k, .52 * k, .70 * k, 1.1 * k], fill=(250, 250, 200, 255))
    if extra == "clip":
        g.rounded_rectangle([.56 * k, .62 * k, .92 * k, 1.05 * k], radius=.03 * k, fill=(196, 160, 110, 255)); g.rectangle([.61 * k, .68 * k, .87 * k, 1.0 * k], fill=WHITE + (255,))
        for yy in (.75, .82, .89): g.line([(.65 * k, yy * k), (.83 * k, yy * k)], fill=(150, 160, 155, 255), width=int(.012 * k))
    return _down(im, w, h)

def _hammer(s):
    im = _canvas(s, s); g = ImageDraw.Draw(im); k = s * SS
    g.rounded_rectangle([.44 * k, .25 * k, .56 * k, .98 * k], radius=.04 * k, fill=(150, 100, 50, 255))
    g.rounded_rectangle([.18 * k, .08 * k, .82 * k, .30 * k], radius=.04 * k, fill=(90, 96, 100, 255))
    return _down(im, s, s)

JS = {}
def jsprite(kind, s):
    key = (kind, s)
    if key not in JS:
        JS[key] = {"fixer": lambda: _fixer(s), "builder": lambda: _person(s, (232, 110, 30), "hard", "vest"),
                   "appraiser": lambda: _person(s, (90, 100, 110), None, "clip"), "hammer": lambda: _hammer(s)}[kind]()
    return JS[key]

def sparkle(im, x, y, r, a):
    g = ImageDraw.Draw(im); c = GOLD_L + (int(255 * a),)
    g.polygon([(x, y - r), (x + r * .25, y - r * .25), (x + r, y), (x + r * .25, y + r * .25), (x, y + r), (x - r * .25, y + r * .25), (x - r, y), (x - r * .25, y - r * .25)], fill=c)

def v_journey(sp, now):
    im = Image.new("RGBA", (W, VH), (0, 0, 0, 0)); steps = sp["steps"]; E = sp.get("ev", {})
    cur = -1
    for i, st in enumerate(steps):
        if shown(st["on"], now): cur = i
    # step strip
    cw, gap = 176, 14; x0 = CX - (len(steps) * cw + (len(steps) - 1) * gap) // 2
    for i, st in enumerate(steps):
        done, on = i < cur, i == cur
        fill = GOLD if on else (FOREST if done else (230, 226, 214)); col = INK if on else (WHITE if done else MUTED)
        c = Image.new("RGBA", (cw, 64), (0, 0, 0, 0)); ImageDraw.Draw(c).rounded_rectangle([0, 0, cw - 1, 63], radius=32, fill=fill)
        l = T(("✓ " if done else "") + st["label"], F_NUM, 26, col, 0.02); c.alpha_composite(l, ((cw - l.width) // 2, (64 - l.height) // 2 + 2))
        sc = 1.0 + (0.08 * (1 - ease_out((since(st["on"], now) or 0) / 0.4)) if on else 0)
        place(im, c, x0 + i * (cw + gap) + cw // 2, 0, 1, sc)
    HS = 400; hx, hy = CX, 110
    def stime(k): return since(k, now)
    # house: fixer -> fixed during rehab; slides out on repeat
    rh = stime(steps[1]["on"]) if len(steps) > 1 else None; k_fix = 0 if rh is None else ease_in_out((rh - 0.6) / 2.0)
    rp = stime(steps[4]["on"]) if len(steps) > 4 else None; slide = 0 if rp is None else ease_in_out((rp - 0.3) / 1.0)
    hxx = hx - slide * 640
    if k_fix < 1: place(im, jsprite("fixer", HS), hxx, hy, 1 - k_fix if k_fix > 0 else 1)
    if k_fix > 0: place(im, sprite("house", HS), hxx, hy, k_fix)
    if 0 < k_fix < 1:
        for j in range(5):
            ph = (rh * 3 + j * .7) % 1; sparkle(im, hxx - 150 + j * 75, hy + 80 + (j * 53) % 220, 22 * math.sin(ph * math.pi), 1)
    if slide > 0:                                                  # the next fixer slides in
        place(im, jsprite("fixer", HS), hx + 640 - slide * 640, hy, slide)
    # you + your bag (left), shrinks when you pay, refills on the refinance loan
    you = sprite("you", 150); place(im, you, 140, 300)
    paid = stime(steps[0]["on"]); loan = stime(E["loan"]) if E.get("loan") else None
    bag_k = 1.0
    if paid is not None: bag_k = 1 - 0.55 * ease_out(paid / 1.0)
    if rh is not None: bag_k -= 0.25 * ease_out(rh / 1.0)
    if loan is not None: bag_k += 0.8 * ease_out((loan - 0.4) / 1.0)
    bag = sprite("bag", max(40, int(150 * max(0.2, min(1.0, bag_k))))); place(im, bag, 250, 470 - bag.height)
    fly(im, steps[0]["on"], now, (230, 380), (hx - 60, hy + 230), n=5, size=90, arc=-120)
    # right side actor by step
    ax, ay = W - 150, 300; slot = None
    if cur == 1: slot = "builder"
    elif cur == 2: slot = "tenant"
    elif cur == 3: slot = "bank" if loan is not None else ("appraiser" if E.get("appraise") and shown(E["appraise"], now) else None)
    if slot == "builder":
        b = jsprite("builder", 160); a, sc = pop(steps[1]["on"], now, 0.5); place(im, b, ax, ay, a, sc)
        hm = jsprite("hammer", 90).rotate(25 * math.sin(now * 11), resample=Image.BICUBIC); place(im, hm, ax - 95, ay + 40, a)
        fly(im, steps[1]["on"], now, (230, 380), (ax - 20, ay + 60), n=4, size=84, arc=-160)
    elif slot == "tenant":
        t_ = sprite("tenant", 150); s_ = stime(steps[2]["on"]) or 0; a, sc = pop(steps[2]["on"], now, 0.5)
        place(im, t_, ax - 20 * ease_out(s_ / 1.0), ay, a)
        fly(im, steps[2]["on"], now, (ax - 60, ay + 60), (250, 400), n=4, size=84, arc=-200, stagger=0.25)
    elif slot == "appraiser":
        p_ = jsprite("appraiser", 160); a, sc = pop(E["appraise"], now, 0.5); place(im, p_, ax, ay, a, sc)
    elif slot == "bank":
        b_ = sprite("bank", 190); a, sc = pop(E["loan"], now, 0.5); place(im, b_, ax, ay + 10, a, sc)
        fly(im, E["loan"], now, (ax - 40, ay + 90), (250, 400), n=8, size=96, arc=-200, stagger=0.1)
    # tag under the house: what just happened
    tag = None
    for i, st in enumerate(steps):
        if shown(st["on"], now) and st.get("tag"): tag, tev = st["tag"], st["on"]
    for kk in ("appraise", "loan"):
        if E.get(kk) and shown(E[kk], now) and sp.get("tags", {}).get(kk): tag, tev = sp["tags"][kk], E[kk]
    if tag:
        a, sc = pop(tev, now, 0.4); place(im, pill(tag, fill=WHITE, color=INK, size=40, track=0.02, padx=36, pady=20), CX, 540, a, sc)
    # meter: your cash in the deal
    mt = sp.get("meter")
    if mt and cur >= 0:
        v = 0.0; prev = 0.0
        for ev, val in mt["keys"]:
            s_ = stime(ev)
            if s_ is None: break
            v = prev + (val - prev) * ease_in_out(s_ / 1.2); prev = val
        c, pad = card(900, 120, fill=WHITE)
        c.alpha_composite(T(mt["label"], F_SEMI, 36, MUTED), (pad + 40, pad + 38))
        col = RED if v > 1000 else GREEN
        vl = T(("≈ $0" if v < 500 and loan is not None else money(v)), F_NUM, 64, col, -0.02)
        c.alpha_composite(vl, (pad + 900 - 40 - vl.width, pad + (120 - vl.height) // 2 + 4))
        place(im, c, CX, 640 - pad)
    return im

def v_split(sp, now):
    """One rent check splits in half: costs on one side, what's left for the mortgage on the other."""
    im = Image.new("RGBA", (W, VH), (0, 0, 0, 0))
    a0, sc0 = pop(sp["on"], now, 0.5)
    if not a0: return im
    k = ease_in_out(((since(sp["split_on"], now) or 0) - 0) / 0.9) if shown(sp["split_on"], now) else 0
    bw, bh = 880, 170; gapx = int(60 * k); hw = bw // 2
    for side, sgn in (("left", -1), ("right", 1)):
        p = sp[side]; col = (226, 78, 66) if side == "left" else BILL_G
        if k == 0: col = BILL_G
        c = Image.new("RGBA", (hw, bh), (0, 0, 0, 0)); g = ImageDraw.Draw(c)
        r = 34
        if side == "left": g.rounded_rectangle([0, 0, hw + r, bh - 1], radius=r, fill=col)
        else: g.rounded_rectangle([-r, 0, hw - 1, bh - 1], radius=r, fill=col)
        place(im, c, CX + sgn * (hw // 2 + gapx // 2), 40, a0, sc0)
        if k > 0.5:
            q = min(1, (k - .5) * 2)
            l = T(p["label"], F_SEMI, 34, WHITE); v = T(p["value"], F_NUM, 64, WHITE, -0.02)
            place(im, l, CX + sgn * (hw // 2 + gapx // 2), 62, q); place(im, v, CX + sgn * (hw // 2 + gapx // 2), 110, q)
    if k < 0.5:
        t = T(sp["total"], F_NUM, 72, WHITE, -0.02); place(im, t, CX, 40 + (bh - t.height) // 2, a0 * (1 - k * 2), sc0)
    # what's in the cost half, and what the other half has to cover
    for i, (txt, ev) in enumerate(zip(sp["left"]["items"], sp["left"]["items_on"])):
        a, sc = pop(ev, now, 0.35)
        if a: place(im, tile(txt, (190, 60, 50), 34), CX - hw // 2 - gapx // 2, 250 + i * 92, a, sc)
    rp = sp["right"]
    if rp.get("items_on"):
        for i, (txt, ev) in enumerate(zip(rp["items"], rp["items_on"])):
            a, sc = pop(ev, now, 0.35)
            if a: place(im, tile(txt, FOREST, 34), CX + hw // 2 + gapx // 2, 250 + i * 92, a, sc)
    return im

def v_screen(sp, now):
    """A grid of listings checked in seconds: most fail, the few that pass light up."""
    im = Image.new("RGBA", (W, VH), (0, 0, 0, 0)); n = 9; passes = set(sp["pass"])
    s_ = since(sp["on"], now)
    for i in range(n):
        r, c = divmod(i, 3); x = CX + (c - 1) * 300; y = 40 + r * 235
        a = 1 if s_ is not None else 0
        if not a: continue
        k = (s_ - 0.3 - i * sp.get("step", 0.32))
        ok = i in passes
        h = sprite("house", 180); hh = h if (k < 0.2 or ok) else with_a(h, 0.35)
        if k > 0.2 and ok:
            g = Image.new("RGBA", (230, 230), (0, 0, 0, 0)); ImageDraw.Draw(g).ellipse([0, 0, 229, 229], fill=GOLD + (70,))
            place(im, g.filter(ImageFilter.GaussianBlur(14)), x, y - 25)
        place(im, hh, x, y)
        if k > 0:
            ic = ICON["check" if ok else "x"]; q = ease_out(k / 0.25); place(im, ic, x + 70, y + 120, min(1, q * 1.5), 1.3 - .3 * q)
    return im

def shield_sprite(s, text):
    im = _canvas(s, int(s * 1.15)); g = ImageDraw.Draw(im); k = s * SS
    g.polygon([(.5 * k, .02 * k), (.95 * k, .18 * k), (.92 * k, .62 * k), (.5 * k, 1.12 * k), (.08 * k, .62 * k), (.05 * k, .18 * k)], fill=GOLD + (255,))
    g.polygon([(.5 * k, .10 * k), (.86 * k, .23 * k), (.84 * k, .60 * k), (.5 * k, 1.01 * k), (.16 * k, .60 * k), (.14 * k, .23 * k)], fill=GOLD_D + (255,))
    im = _down(im, s, int(s * 1.15)); l = T(text, F_NUM, int(s * .26), WHITE, 0.02); im.alpha_composite(l, ((s - l.width) // 2, int(s * .36))); return im

def v_shield(sp, now):
    """You (small down payment), the house, the bank, and the PMI shield that protects the bank."""
    im = Image.new("RGBA", (W, VH), (0, 0, 0, 0))
    HX = CX - 90; place(im, sprite("house", 330), HX, 50)
    a, _ = pop(sp["you_on"], now, 0.5)
    if a:
        place(im, sprite("you", 140), 120, 200, a); bag = sprite("bag", 64); place(im, bag, 210, 330 - bag.height, a)
        place(im, tile(sp["you_label"], FOREST, 30), 150, 380, a)
    BX = W - 120; a, sc = pop(sp["bank_on"], now, 0.5)
    if a:
        place(im, sprite("bank", 180), BX, 170, a, sc); place(im, tile(sp["bank_label"], SLATE, 30), BX, 380, a)
    sh = since(sp["shield_on"], now); SX = CX + 230
    r = since(sp.get("risk_on"), now) if sp.get("risk_on") else None
    if r is not None:                                                  # missed payments fly at the bank (the shield stops them)
        place(im, pill(sp["risk_label"], fill=(226, 78, 66), color=WHITE, size=34, track=0.02, padx=30, pady=16), CX, 470, min(1, r / 0.4))
        end = SX - 60 if sh is not None else BX - 40
        for i in range(3):
            u = ((r - i * 0.5) % 1.5) / 1.0
            if 0 < u < 1:
                x = HX + 120 + (end - HX - 120) * ease_in_out(u); place(im, with_a(ICON["x"], min(1, u * 4, (1 - u) * 4)), x, 240 - 70 * math.sin(u * math.pi))
    if sh is not None:
        k = ease_out(sh / 0.5); place(im, shield_sprite(190, "PMI"), SX, 130, min(1, k * 1.5), 1.4 - .4 * k)
        place(im, pill(sp["shield_label"], fill=GOLD, color=INK, size=34, track=0.02, padx=30, pady=16), CX, 570, min(1, k * 1.5))
    return im

def v_timeline(sp, now):
    im = Image.new("RGBA", (W, VH), (0, 0, 0, 0)); ev = sp["events"]; n = len(ev)
    x0, x1, y = (220, W - 220, 330) if n < 3 else (170, W - 170, 330)
    started = [e for e in ev if shown(e["on"], now)]
    if not started: return im
    g = ImageDraw.Draw(im); g.rounded_rectangle([x0, y - 5, x1, y + 5], radius=5, fill=(222, 216, 200))
    for i, e in enumerate(ev):
        x = x0 + (x1 - x0) * i / max(1, n - 1)
        a, sc = pop(e["on"], now, 0.5)
        if not a: continue
        g.ellipse([x - 22, y - 22, x + 22, y + 22], fill=GOLD if e.get("now") else FOREST)
        yr = T(e["year"], F_NUM, 84, FOREST, -0.02); place(im, yr, x, y - 140, a, sc)
        lab = rich(e["text"], F_SEMI, 34, INK, FOREST, 400 if n < 3 else 300, tracking=0, line_h=1.2); place(im, lab, x, y + 50, a)
    return im

def v_people(sp, now):
    im = Image.new("RGBA", (W, VH), (0, 0, 0, 0)); ps = sp["people"]
    for i, p in enumerate(ps):
        x = CX + (i - (len(ps) - 1) / 2) * 500; a, sc = pop(p["on"], now, 0.5)
        if not a: continue
        c, pad = card(460, 700); place(im, c, x, -pad + 20, a)
        place(im, sprite(p.get("art", "house"), 220), x, 70, a)
        place(im, sprite("you", 110), x - 120, 200, a)
        if p.get("bag"): place(im, sprite("bag", 90), x + 140, 240, a)
        place(im, rich(p["title"], F_NUM, 46, INK, FOREST, 400), x, 360, a)
        place(im, rich(p["sub"], F_MED, 32, MUTED, FOREST, 400, tracking=0, line_h=1.25), x, 450, a)
    return im

VIS = {"shield": v_shield, "timeline": v_timeline, "people": v_people, "split": v_split, "screen": v_screen, "journey": v_journey, "flow": v_flow, "house": v_house, "compare": v_compare, "stack": v_stack, "bars": v_bars, "check": v_check, "big": v_big, "gauge": v_gauge, "morph": v_morph}

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
END_LINE = rich(scenes[-1].get("end_line", "We read the greens.\nYou take the *shot.*"), F_NUM, 66, INK, GOLD_D, 900, line_h=1.12)
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
