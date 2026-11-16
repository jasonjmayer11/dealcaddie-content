#!/usr/bin/env python3
"""DealCaddie "Match Play" infographics: two properties, played hole by hole, with an AI voice.

On-brand look (cream canvas, forest green, gold, white app-style cards), illustrated buildings,
a golf scoreboard, count-up numbers, coins, and the app revealed at the end.
Each matchup is data (versus/<name>.json). Usage: python3 scripts/versus.py versus/x.json out.mp4
"""
import json, math, os, random, re, subprocess, sys, wave, zlib
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reelkit import (W, H, FPS, INK, MUTED, FOREST, GREEN, RED, WHITE, F_NUM, F_HEAD, F_SEMI, F_MED,
                     text_layer, wrap, place, ease_out, ease_in_out, gradient_bg, logo_layer, device_layer,
                     render_end_beat)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = json.load(open(sys.argv[1])); out_mp4 = os.path.abspath(sys.argv[2])
work = os.path.join(os.path.dirname(out_mp4), "versus_work"); os.makedirs(work, exist_ok=True)

GOLD = (201, 168, 76); GOLD_D = (150, 118, 38); TURF = (39, 165, 82); CREAM = (250, 247, 240)
LINE = (226, 222, 210); SKY = (226, 240, 232)
CX = W // 2

# ------------------------------------------------------------------ voice + timeline
SR = 24000; _k = None
def speak(text):
    global _k
    d = os.environ.get("KOKORO_ONNX_DIR")
    if d:
        if _k is None:
            from kokoro_onnx import Kokoro
            _k = Kokoro(os.path.join(d, "kokoro-v1.0.onnx"), os.path.join(d, "voices-v1.0.bin"))
        s, _ = _k.create(text, voice=os.environ.get("VOICE", "af_heart"), speed=float(os.environ.get("VOICE_SPEED", 1.05)), lang="en-us")
        return np.asarray(s, np.float32)
    if _k is None:
        from kokoro import KPipeline
        _k = KPipeline(lang_code="a")
    return np.concatenate([np.asarray(a.numpy() if hasattr(a, "numpy") else a) for _, _, a in
                           _k(text, voice=os.environ.get("VOICE", "af_heart"), speed=float(os.environ.get("VOICE_SPEED", 1.05)))]).astype(np.float32)

LEAD, GAP = 0.5, 0.14
WIN_HOLD = float(os.environ.get("WIN_HOLD", 1.3))
t = LEAD; phrases = []; clips = []; events = {}
from wordtime import speak_timed
LEADIN = 0.06                                   # show a word a hair before it's heard
for ph in M["script"]:
    a, units = speak_timed(ph["voice"]); d = len(a) / SR
    for u in units: u["t0"] += t; u["t1"] += t
    clips.append((t, a)); phrases.append((t, d, ph, units))
    cursor = 0                                  # "~" events are matched in order: each search starts at the previous hit
    for ev in ph.get("do", []):                 # "id", "id@0.6" (fraction of the phrase) or "id#3" (as unit 3 is spoken)
        if "~" in ev:                           # "id~word": as the next unit starting with that text is spoken
            k, _, w_ = ev.partition("~")
            hit = [i for i, u in enumerate(units) if i >= cursor and u["show"].lower().startswith(w_.lower())]
            if not hit: sys.exit(f"event {ev}: no unit from #{cursor} starts with {w_!r} in {[u['show'] for u in units]}")
            cursor = hit[0]; events[k] = units[cursor]["t0"]
        elif "#" in ev:
            k, _, n = ev.partition("#"); events[k] = units[min(int(n), len(units) - 1)]["t0"]
        else:
            k, _, f = ev.partition("@"); events[k] = t + d * float(f or 0)
    wins_here = any(re.match(r"h\d+w[~#@]?", e) for e in ph.get("do", []))
    ph["_hold"] = WIN_HOLD if wins_here else 0
    t += d + GAP + ph.get("pause", 0.25) + ph["_hold"]   # let each round's result land
if "endcard" in events:                         # the CTA line is spoken over the end card
    MAIN = events["endcard"] - 0.25; END = max(4.2, t + 1.6 - MAIN)
else:
    MAIN = t + 0.4; END = 3.6
TOTAL = MAIN + END
print(f"voice {MAIN:.1f}s + end {END}s = {TOTAL:.1f}s")
def since(k, now): return None if k not in events or now < events[k] else now - events[k]
def prog(k, now, dur=0.6):
    s = since(k, now); return 0.0 if s is None else ease_out(s / dur)

# ------------------------------------------------------------------ small drawing helpers
def shadowed_card(w, h, r=34, fill=WHITE, border=LINE, bw=2, glow=None):
    pad = 50; im = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([pad, pad + 14, pad + w, pad + h + 14], radius=r, fill=(20, 45, 30, 40))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(22)))
    if glow:
        g = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(g).rounded_rectangle([pad - 6, pad - 6, pad + w + 6, pad + h + 6], radius=r + 6, fill=glow)
        im.alpha_composite(g.filter(ImageFilter.GaussianBlur(14)))
    ImageDraw.Draw(im).rounded_rectangle([pad, pad, pad + w, pad + h], radius=r, fill=fill, outline=border, width=bw)
    return im, pad

def pill(text, fill=FOREST, color=WHITE, size=26, track=0.1):
    tl = text_layer(text, F_NUM, size, color, tracking=track)
    b = Image.new("RGBA", (tl.width + 44, tl.height + 22), (0, 0, 0, 0))
    ImageDraw.Draw(b).rounded_rectangle([0, 0, b.width - 1, b.height - 1], radius=b.height // 2, fill=fill)
    b.alpha_composite(tl, (22, 11)); return b

def check_badge(d=64, fill=TURF):
    im = Image.new("RGBA", (d * 2, d * 2), (0, 0, 0, 0)); g = ImageDraw.Draw(im)
    g.ellipse([0, 0, d * 2 - 1, d * 2 - 1], fill=fill, outline=WHITE, width=8)
    g.line([(d * .55, d * 1.02), (d * .88, d * 1.36), (d * 1.48, d * .68)], fill=WHITE, width=int(d * .26), joint="curve")
    return im.resize((d, d), Image.LANCZOS)

def flag_icon(h=34):
    im = Image.new("RGBA", (h, h), (0, 0, 0, 0)); g = ImageDraw.Draw(im)
    g.line([(h * .25, h * .08), (h * .25, h * .95)], fill=WHITE, width=3)
    g.polygon([(h * .28, h * .08), (h * .9, h * .26), (h * .28, h * .44)], fill=GOLD)
    return im

def coin(r=22):
    im = Image.new("RGBA", (r * 4, r * 4), (0, 0, 0, 0)); g = ImageDraw.Draw(im); R = r * 2
    g.ellipse([0, 0, R * 2 - 1, R * 2 - 1], fill=GOLD_D); g.ellipse([0, 0, R * 2 - 1, R * 2 - 9], fill=GOLD)
    g.ellipse([R * .3, R * .3, R * 1.7, R * 1.62], outline=(232, 205, 128), width=4)
    s = text_layer("$", F_NUM, int(R * 1.05), (120, 92, 25)); im.alpha_composite(s, (R - s.width // 2, int(R * .42)))
    return im.resize((r * 2, r * 2), Image.LANCZOS)
COIN = coin()

# ------------------------------------------------------------------ building illustrations (drawn at 2x)
def building(kind, w, h, lights=1.0, accent=FOREST):
    S = 2; W2, H2 = w * S, h * S
    im = Image.new("RGBA", (W2, H2), (0, 0, 0, 0)); g = ImageDraw.Draw(im)
    g.rounded_rectangle([0, 0, W2 - 1, H2 - 1], radius=26 * S, fill=SKY)
    for i, (cx, cy, r) in enumerate([(.18, .22, 26), (.78, .16, 20)]):              # soft clouds
        x, y = cx * W2, cy * H2; r *= S
        for dx in (-1.1, 0, 1.1): g.ellipse([x + dx * r - r, y - r * .7, x + dx * r + r, y + r * .7], fill=(244, 250, 246))
    gy = H2 * .82
    g.rounded_rectangle([0, gy, W2 - 1, H2 - 1], radius=26 * S, fill=(150, 200, 160)); g.rectangle([0, gy, W2 - 1, gy + 30 * S], fill=(150, 200, 160))
    g.rectangle([0, gy, W2, gy + 8 * S], fill=(120, 182, 135))
    wall = (246, 240, 226); trim = (60, 72, 64); roof = (54, 66, 60)
    if kind in ("sheet", "phone"):                                                                   # Spreadsheet vs DealCaddie series
        ink = (60, 72, 64); desk = (222, 206, 180)
        g.rounded_rectangle([0, gy, W2 - 1, H2 - 1], radius=26 * S, fill=desk); g.rectangle([0, gy, W2 - 1, gy + 30 * S], fill=desk)
        g.rectangle([0, gy, W2, gy + 6 * S], fill=(200, 182, 152))
        if kind == "sheet":                                                                          # laptop with a messy spreadsheet
            lx0, ly0, lx1, ly1 = W2 * .12, H2 * .12, W2 * .88, H2 * .74
            g.rounded_rectangle([lx0, ly0, lx1, ly1], radius=10 * S, fill=(40, 46, 44))
            sx0, sy0, sx1, sy1 = lx0 + 10 * S, ly0 + 10 * S, lx1 - 10 * S, ly1 - 10 * S
            g.rectangle([sx0, sy0, sx1, sy1], fill=(255, 255, 255))
            g.rectangle([sx0, sy0, sx1, sy0 + 14 * S], fill=(33, 115, 70))
            rows, cols = 9, 6; cw_, rh = (sx1 - sx0) / cols, (sy1 - sy0 - 14 * S) / rows
            for r in range(rows + 1): g.line([(sx0, sy0 + 14 * S + r * rh), (sx1, sy0 + 14 * S + r * rh)], fill=(210, 214, 212), width=S)
            for c in range(cols + 1): g.line([(sx0 + c * cw_, sy0 + 14 * S), (sx0 + c * cw_, sy1)], fill=(210, 214, 212), width=S)
            rnd = __import__("random").Random(5)
            for r in range(rows):
                for c in range(cols):
                    if rnd.random() < .55:
                        x = sx0 + c * cw_ + 4 * S; y = sy0 + 14 * S + r * rh + rh * .35
                        g.rectangle([x, y, x + cw_ * rnd.uniform(.3, .75), y + rh * .3], fill=(170, 176, 172))
            ex, ey = sx0 + 3 * cw_, sy0 + 14 * S + 5 * rh                                            # the error cell
            g.rectangle([ex, ey, ex + cw_, ey + rh], fill=(252, 220, 216), outline=RED, width=2 * S)
            et = text_layer("#REF!", F_NUM, int(rh * .55), RED); im.alpha_composite(et, (int(ex + (cw_ - et.width) / 2), int(ey + (rh - et.height) / 2)))
            g.polygon([(W2 * .04, ly1), (W2 * .96, ly1), (W2 * .9, ly1 + 14 * S), (W2 * .1, ly1 + 14 * S)], fill=(90, 98, 94))
            for k, (cx_, cy_) in enumerate([(.86, .16)]):                                            # sticky note
                g.rectangle([W2 * cx_ - 22 * S, H2 * cy_, W2 * cx_ + 22 * S, H2 * cy_ + 40 * S], fill=(255, 226, 120))
        else:                                                                                        # phone running DealCaddie
            px0, py0, px1, py1 = W2 * .34, H2 * .06, W2 * .66, H2 * .94
            g.rounded_rectangle([px0, py0, px1, py1], radius=22 * S, fill=(20, 26, 22))
            sx0, sy0, sx1, sy1 = px0 + 6 * S, py0 + 6 * S, px1 - 6 * S, py1 - 6 * S
            g.rounded_rectangle([sx0, sy0, sx1, sy1], radius=17 * S, fill=(250, 247, 240))
            g.rounded_rectangle([sx0, sy0, sx1, sy0 + (sy1 - sy0) * .38], radius=17 * S, fill=(26, 92, 53))
            cx_, cy_, r_ = (sx0 + sx1) / 2, sy0 + (sy1 - sy0) * .2, 24 * S
            g.ellipse([cx_ - r_, cy_ - r_, cx_ + r_, cy_ + r_], fill=(0, 0, 0, 0), outline=GOLD, width=4 * S)
            sc = text_layer("7.5", F_NUM, 17 * S, WHITE); im.alpha_composite(sc, (int(cx_ - sc.width / 2), int(cy_ - sc.height / 2)))
            for k in range(5):
                y = sy0 + (sy1 - sy0) * (.46 + k * .1)
                g.rounded_rectangle([sx0 + 8 * S, y, sx1 - 8 * S, y + 14 * S], radius=5 * S, fill=WHITE, outline=(226, 222, 210), width=S)
                g.rectangle([sx0 + 12 * S, y + 4 * S, sx0 + 40 * S, y + 9 * S], fill=(190, 196, 192))
                g.rectangle([sx1 - 30 * S, y + 4 * S, sx1 - 12 * S, y + 9 * S], fill=TURF)
            for (bx, by) in ((.18, .3), (.82, .55), (.2, .78)):                                       # little sparkles
                x, y = W2 * bx, H2 * by
                g.polygon([(x, y - 9 * S), (x + 3 * S, y - 3 * S), (x + 9 * S, y), (x + 3 * S, y + 3 * S), (x, y + 9 * S), (x - 3 * S, y + 3 * S), (x - 9 * S, y), (x - 3 * S, y - 3 * S)], fill=GOLD)
        return im.resize((w, h), Image.LANCZOS), [w * .5], h * .9

    def gable(x0, x1, by0, peak):
        g.polygon([(x0 - 14 * S, by0 + 4 * S), ((x0 + x1) / 2, peak), (x1 + 14 * S, by0 + 4 * S)], fill=roof)
        g.rectangle([x0, by0, x1, gy], fill=wall, outline=trim, width=3 * S)
    wy = lambda by0: by0 + (gy - by0) * .22
    if kind in ("house", "fixer"):
        bx0, bx1, by0 = W2 * .2, W2 * .8, H2 * .44
        g.rectangle([W2 * .64, H2 * .18, W2 * .70, H2 * .34], fill=(150, 90, 70))                     # chimney
        g.polygon([(bx0 - 22 * S, by0 + 4 * S), (W2 * .5, H2 * .16), (bx1 + 22 * S, by0 + 4 * S)], fill=roof)
        if kind == "fixer": wall = (214, 204, 186)
        g.rectangle([bx0, by0, bx1, gy], fill=wall, outline=trim, width=3 * S)
        doors = [W2 * .5]; wins = [(W2 * .31, wy(by0)), (W2 * .69, wy(by0))]
    elif kind == "two":
        doors, wins = [], []
        for c in (.27, .73):
            x0, x1, by0 = W2 * (c - .19), W2 * (c + .19), H2 * .50
            gable(x0, x1, by0, H2 * .26); doors.append(W2 * c); wins.append((W2 * (c - .11), wy(by0))); wins.append((W2 * (c + .11), wy(by0)))
    elif kind == "townhouse":
        doors, wins = [], []
        for k, c in enumerate((.2, .5, .8)):
            x0, x1, by0 = W2 * (c - .15), W2 * (c + .15), H2 * .36
            gable(x0, x1, by0, H2 * .16); doors.append(W2 * c); wins.append((W2 * c, wy(by0)))
    elif kind == "triplex":
        bx0, bx1, by0 = W2 * .05, W2 * .95, H2 * .40
        g.polygon([(bx0 - 14 * S, by0 + 4 * S), (W2 * .2, H2 * .2), (W2 * .35, by0 - 8 * S), (W2 * .5, H2 * .2), (W2 * .65, by0 - 8 * S), (W2 * .8, H2 * .2), (bx1 + 14 * S, by0 + 4 * S)], fill=roof)
        g.rectangle([bx0, by0, bx1, gy], fill=wall, outline=trim, width=3 * S)
        for xx in (.35, .65): g.line([(W2 * xx, by0), (W2 * xx, gy)], fill=trim, width=3 * S)
        doors = [W2 * .2, W2 * .5, W2 * .8]; wins = [(W2 * x, wy(by0)) for x in (.2, .5, .8)]
    else:
        bx0, bx1, by0 = W2 * .08, W2 * .92, H2 * .40
        g.polygon([(bx0 - 18 * S, by0 + 4 * S), (W2 * .27, H2 * .18), (W2 * .5, by0 - 10 * S), (W2 * .73, H2 * .18), (bx1 + 18 * S, by0 + 4 * S)], fill=roof)
        g.rectangle([bx0, by0, bx1, gy], fill=wall, outline=trim, width=3 * S)
        g.line([(W2 * .5, by0), (W2 * .5, gy)], fill=trim, width=3 * S)                                 # party wall
        doors = [W2 * .30, W2 * .70]
        wins = [(W2 * .17, by0 + (gy - by0) * .22), (W2 * .41, by0 + (gy - by0) * .22), (W2 * .59, by0 + (gy - by0) * .22), (W2 * .83, by0 + (gy - by0) * .22)]
    lw = 40 * S if kind in ("house", "fixer") else 30 * S
    if kind == "fixer": lights = 0
    lit = tuple(int(a + (b - a) * lights) for a, b in zip((190, 210, 220), (255, 222, 140)))
    for x, y in wins:
        g.rectangle([x - lw / 2, y, x + lw / 2, y + lw * .9], fill=lit, outline=trim, width=2 * S)
        g.line([(x, y), (x, y + lw * .9)], fill=trim, width=2 * S); g.line([(x - lw / 2, y + lw * .45), (x + lw / 2, y + lw * .45)], fill=trim, width=2 * S)
        if kind == "fixer":                                                                         # boarded up
            for k in (-1, 1): g.line([(x - lw * .6, y + lw * (.45 + .25 * k)), (x + lw * .6, y + lw * (.45 - .25 * k))], fill=(160, 120, 80), width=6 * S)
    dw, dh = 34 * S, 62 * S
    for i, x in enumerate(doors):
        dc = accent if not (kind == "townhouse" and i != 1) else (120, 130, 124)
        g.rounded_rectangle([x - dw / 2, gy - dh, x + dw / 2, gy], radius=6 * S, fill=dc)
        g.ellipse([x + dw * .22, gy - dh * .5, x + dw * .36, gy - dh * .5 + 4 * S], fill=GOLD)
        if kind in ("duplex", "triplex"):
            lab = text_layer("ABC"[i], F_NUM, 15 * S, WHITE); im.alpha_composite(lab, (int(x - lab.width / 2), int(gy - dh + 8 * S)))
        g.rectangle([x - dw / 2 - 6 * S, gy, x + dw / 2 + 6 * S, gy + 6 * S], fill=(205, 198, 182))
    if kind == "townhouse":                                                                         # "for sale" sign on the middle unit
        g.rectangle([W2 * .62, gy - 46 * S, W2 * .625, gy], fill=trim); g.rectangle([W2 * .585, gy - 46 * S, W2 * .70, gy - 26 * S], fill=GOLD)
    for tx in ([W2 * .08] if kind in ("house", "fixer") else []):                                              # tree
        g.rectangle([tx - 4 * S, gy - 50 * S, tx + 4 * S, gy], fill=(110, 80, 55))
        g.ellipse([tx - 26 * S, gy - 96 * S, tx + 26 * S, gy - 40 * S], fill=(70, 150, 95))
    return im.resize((w, h), Image.LANCZOS), [x / S for x in doors], gy / S

# ------------------------------------------------------------------ fixed layout
A, B = M["a"], M["b"]
L2 = os.environ.get("LAYOUT", "1") == "2"      # v2 (Nov 16, proposed): roomier header, full-width scoreboard. Default flips to 2 once approved
CARD_W, CARD_H, CARD_Y = (470, 450, 478) if L2 else (470, 470, 470)
TAG_Y, TITLE_Y, SB_Y = (186, 220, 322) if L2 else (232, 268, 352)
CARD_X = [60, W - 60 - CARD_W]
ILL_W, ILL_H = CARD_W - 40, 290
holes = M["holes"]

def winner_of(i): return holes[i]["winner"]  # "a" | "b" | "tie"
def score(now):
    s = {"a": 0, "b": 0}
    for i, h in enumerate(holes):
        if since(f"h{i}w", now) is not None and h["winner"] in s: s[h["winner"]] += 1
    return s

def fmt(v, kind):
    if kind == "pct": return f"{v:.1f}%"
    if kind == "x": return f"{v:.2f}x"
    if kind == "text": return str(v)
    if kind == "money": return ("−" if v < 0 else "") + f"${abs(v):,.0f}"
    if kind == "money_s": return ("−" if v < 0 else "+") + f"${abs(v):,.0f}"
    if kind == "pct_s": return ("−" if v < 0 else "+") + f"{abs(v):.1f}%"
    if kind == "k": return f"${v / 1000:,.0f}K"
    return str(v)

def property_card(side, now):
    P = A if side == "a" else B
    hi = None
    for i, h in enumerate(holes):                          # glow briefly when this side wins a hole
        s = since(f"h{i}w", now)
        if s is not None and s < 1.4 and h["winner"] == side: hi = 1 - s / 1.4
    fin = since("final", now); champ = fin is not None and M.get("champion") == side
    glow = (39, 165, 82, int(150 * hi)) if hi else ((201, 168, 76, 170) if champ else None)
    card, pad = shadowed_card(CARD_W, CARD_H, border=GOLD if champ else LINE, bw=5 if champ else 2, glow=glow)
    ill, doors, gy = building(P["kind"], ILL_W, ILL_H, lights=0.5 + 0.5 * math.sin(now * 1.3) ** 2)
    card.alpha_composite(ill, (pad + 20, pad + 20))
    if P.get("badge"):
        bd = pill(P["badge"], fill=FOREST, color=WHITE, size=24, track=0.08); card.alpha_composite(bd, (pad + 36, pad + 36))
    nm = text_layer(P["name"], F_NUM, 46, INK, tracking=-0.02); card.alpha_composite(nm, (pad + 28, pad + 330))
    sp = text_layer(P["spec"], F_MED, 28, MUTED); card.alpha_composite(sp, (pad + 28, pad + 392))
    if champ:
        b = pill("WINNER", fill=GOLD, color=INK, size=24); card.alpha_composite(b, (pad + CARD_W - b.width - 24, pad + 336))
    return card, pad, doors, gy

# ------------------------------------------------------------------ hole panel (bottom card)
HP_Y, HP_H = 990, 380
def hole_panel(i, now, slide):
    h = holes[i]; card, pad = shadowed_card(W - 120, HP_H)
    g = ImageDraw.Draw(card)
    head = pill(f"{M.get('round_word', 'ROUND')} {i + 1}  ·  {h['label']}" if not h.get("tiebreak") else h["label"], size=26)
    fl = flag_icon(30); head2 = Image.new("RGBA", (head.width + 40, head.height), (0, 0, 0, 0))
    ImageDraw.Draw(head2).rounded_rectangle([0, 0, head2.width - 1, head2.height - 1], radius=head.height // 2, fill=FOREST)
    head2.alpha_composite(fl, (18, (head.height - 30) // 2)); head2.alpha_composite(head.crop((14, 0, head.width, head.height)), (44, 0))
    card.alpha_composite(head2, (pad + (W - 120 - head2.width) // 2, pad + 26))
    if h.get("sub"):
        s = text_layer(h["sub"], F_MED, 24, MUTED); card.alpha_composite(s, (pad + (W - 120 - s.width) // 2, pad + 92))
    cw = W - 120; mx = [cw * .25, cw * .75]
    txt = h["fmt"] == "text"
    vmax = 1 if txt else (max(abs(h["a"]), abs(h["b"])) or 1)
    for j, side in enumerate("ab"):
        p = prog(f"h{i}{side}", now, 0.9)
        if p <= 0: continue
        v = h[side] if txt else h[side] * p; won = since(f"h{i}w", now) is not None and h["winner"] == side
        lost = since(f"h{i}w", now) is not None and h["winner"] not in (side, "tie")
        if won:                                         # winner's half lights up and stays lit while the result sinks in
            kk = ease_out(since(f"h{i}w", now) / 0.4)
            hl = Image.new("RGBA", card.size, (0, 0, 0, 0))
            ImageDraw.Draw(hl).rounded_rectangle([pad + mx[j] - cw * .235, pad + 118, pad + mx[j] + cw * .235, pad + HP_H - 26],
                                                 radius=26, fill=(39, 165, 82, int(34 * kk)), outline=(39, 165, 82, int(200 * kk)), width=4)
            card.alpha_composite(hl)
        neg = (not txt) and h[side] < 0
        col = (RED if neg else INK) if h.get("signed") else INK
        if lost: col = tuple(int(c * .45 + 200 * .55) for c in col)
        fs_ = 84; tl = text_layer(fmt(v, h["fmt"]), F_NUM, fs_, col, tracking=-0.03)
        while txt and tl.width > 360 and fs_ > 40:
            fs_ -= 6; tl = text_layer(fmt(v, h["fmt"]), F_NUM, fs_, col, tracking=-0.03)
        card.alpha_composite(tl, (int(pad + mx[j] - tl.width / 2), pad + 140 + max(0, (100 - tl.height) // 2)))
        note = h.get(side + "_note") or h.get("unit")
        if note:                                        # what this side means / how DealCaddie does it
            fsn = 26; u = text_layer(note, F_MED if side == "a" else F_SEMI, fsn, MUTED if side == "a" else FOREST)
            while u.width > cw * .46 and fsn > 18:
                fsn -= 2; u = text_layer(note, F_MED if side == "a" else F_SEMI, fsn, MUTED if side == "a" else FOREST)
            card.alpha_composite(u, (int(pad + mx[j] - u.width / 2), pad + 240))
        # bar
        bw_full = cw * .38; frac = p if txt else abs(h[side]) / vmax * p
        x0 = pad + mx[j] - bw_full / 2; y0 = pad + 290
        g.rounded_rectangle([x0, y0, x0 + bw_full, y0 + 22], radius=11, fill=(236, 233, 224))
        bc = (TURF if won else ((RED if neg else (170, 178, 172)) if lost else (GREEN if not neg or not h.get("signed") else RED)))
        if frac > 0.02: g.rounded_rectangle([x0, y0, x0 + bw_full * frac, y0 + 22], radius=11, fill=bc)
        if won:
            k = ease_out(since(f"h{i}w", now) / 0.35); cb = check_badge(int(76 * (0.6 + 0.4 * k)))
            card.alpha_composite(cb, (int(pad + mx[j] + tl.width / 2 + 10), pad + 150))
    vs = text_layer("vs", F_SEMI, 34, MUTED); card.alpha_composite(vs, (pad + (cw - vs.width) // 2, pad + 180))
    g.line([(pad + cw / 2, pad + 240), (pad + cw / 2, pad + 330)], fill=LINE, width=2)
    return card, pad

def bonus_panel(now):
    bo = M["bonus"]; card, pad = shadowed_card(W - 120, HP_H, border=GOLD, bw=4); g = ImageDraw.Draw(card); cw = W - 120
    head = pill(bo["label"], fill=GOLD, color=INK, size=26); card.alpha_composite(head, (pad + (cw - head.width) // 2, pad + 26))
    p = prog("bonus_fill", now, 1.8); p = 1.0 if p > .99 else p
    x0, x1, y0 = pad + 60, pad + cw - 60, pad + 150
    g.rounded_rectangle([x0, y0, x1, y0 + 70], radius=35, fill=(236, 233, 224))
    f = bo["covered"] / bo["total"] * p
    if f > .02: g.rounded_rectangle([x0, y0, x0 + (x1 - x0) * f, y0 + 70], radius=35, fill=TURF)
    l1 = text_layer(f"{bo['covered_label']}  ${bo['covered'] * p:,.0f}", F_NUM, 34, WHITE if f > .45 else INK)
    card.alpha_composite(l1, (x0 + 28, y0 + 16))
    l2 = text_layer(f"{bo['total_label']}  ${bo['total']:,.0f}", F_SEMI, 28, MUTED)
    card.alpha_composite(l2, (x1 - l2.width, y0 + 92))
    if p > .95:
        big = text_layer(bo["result"], F_NUM, 56, FOREST, tracking=-0.02); card.alpha_composite(big, (pad + (cw - big.width) // 2, pad + 270))
    return card, pad

# ------------------------------------------------------------------ captions (spoken phrase, word by word, *accent*)
_lay_cache = {}
def _word(show, acc, size):
    key = (show, acc, size)
    if key not in _lay_cache:
        _lay_cache[key] = text_layer(show, F_HEAD, size, FOREST if acc else INK, tracking=-0.01)
    return _lay_cache[key]

def caption(units, now, size=60, max_rows=2):
    """Each word appears the moment it is spoken; long lines page, two rows at a time."""
    rows, cur, wsum = [], [], 0
    for u in units:
        l = _word(u["show"], u["accent"], size)
        if cur and wsum + 16 + l.width > 940: rows.append(cur); cur, wsum = [], 0
        cur.append((u, l)); wsum += (16 if len(cur) > 1 else 0) + l.width
    if cur: rows.append(cur)
    pages = [rows[i:i + max_rows] for i in range(0, len(rows), max_rows)]
    page = pages[0]
    for pg in pages:
        if pg[0][0][0]["t0"] - LEADIN <= now: page = pg
    lh = int(size * 1.2); im = Image.new("RGBA", (W, lh * len(page) + 20), (0, 0, 0, 0))
    for r, row in enumerate(page):
        x = (W - sum(l.width for _, l in row) - 16 * (len(row) - 1)) // 2
        for u, l in row:
            s_ = now - (u["t0"] - LEADIN)
            if s_ >= 0:
                k = ease_out(s_ / 0.16); y = r * lh + int((1 - k) * 14)
                lay = l if k >= .999 else l.copy()
                if k < .999: lay.putalpha(lay.getchannel("A").point(lambda v, k=k: int(v * k)))
                im.alpha_composite(lay, (x, y))
            x += l.width + 16
    return im

# ------------------------------------------------------------------ scoreboard + title
_SB_LA = text_layer(A["short"], F_SEMI, 28, (200, 225, 210), tracking=0.08)
_SB_LB = text_layer(B["short"], F_SEMI, 28, (200, 225, 210), tracking=0.08)
_SB_W = (W - 120) if L2 else max(560, 2 * max(_SB_LA.width, _SB_LB.width) + 2 * 34 + 2 * 120)
_SB_H = 108 if L2 else 96
def scoreboard(now):
    s = score(now); SW = _SB_W; SH = _SB_H; card, pad = shadowed_card(SW, SH, r=SH // 2, fill=FOREST, border=FOREST)
    ly = (SH - _SB_LA.height) // 2
    card.alpha_composite(_SB_LA, (pad + 48, pad + ly)); card.alpha_composite(_SB_LB, (pad + SW - 48 - _SB_LB.width, pad + ly))
    gap = 78 if L2 else 60; fs = 66 if L2 else 54
    for side, x in (("a", SW / 2 - gap), ("b", SW / 2 + gap)):
        last = max([events.get(f"h{i}w", -9) for i, h in enumerate(holes) if h["winner"] == side] + [-9])
        pop = 1 + 0.35 * max(0, 1 - (now - last) / 0.4) if now >= last else 1
        n = text_layer(str(s[side]), F_NUM, int(fs * pop), GOLD); card.alpha_composite(n, (int(pad + x - n.width / 2), int(pad + SH / 2 - n.height / 2)))
    d = text_layer("–", F_NUM, 44, (200, 225, 210)); card.alpha_composite(d, (int(pad + SW / 2 - d.width / 2), int(pad + SH / 2 - d.height / 2)))
    return card, pad

TITLE = text_layer(M["title"], F_NUM, 64, INK, tracking=-0.03)
TAG = text_layer(M.get("tag", "HEAD TO HEAD"), F_NUM, 22, GOLD_D, tracking=0.3)
_fl = wrap(M["footnote"], F_MED, 22, 960)
FOOT = Image.new("RGBA", (W, 30 * len(_fl)), (0, 0, 0, 0))
for _i, _l in enumerate(_fl):
    _t = text_layer(_l, F_MED, 22, MUTED); FOOT.alpha_composite(_t, ((W - _t.width) // 2, 30 * _i))
BG = gradient_bg().convert("RGBA")

# ------------------------------------------------------------------ frame
APP = M.get("app_screen", "compare.png")
_ap = Image.open(os.path.join(ROOT, "assets", "showcase", APP))
PHONE, PPAD = device_layer(os.path.join(ROOT, "assets", "showcase", APP), 980 if _ap.width > _ap.height * 0.8 else 560, 900)
rng = random.Random(3)
def frame(now):
    f = BG.copy()
    intro = prog("cards", now, 0.7); rev = prog("reveal", now, 0.9)
    place(f, TAG, CX, TAG_Y, alpha=min(1, now / .3)); place(f, TITLE, CX, TITLE_Y)
    sb, sp = scoreboard(now); place(f, sb, CX, SB_Y - sp, alpha=prog("score", now, .5))
    # property cards (slide up; slide away at reveal)
    pos = {}
    for j, side in enumerate("ab"):
        card, pad, doors, gy = property_card(side, now)
        dy = (1 - intro) * 140 - rev * 60
        x, y = CARD_X[j] - pad, CARD_Y - pad + dy
        if intro > 0 and rev < 1: place(f, card, x + card.width / 2, y, alpha=min(intro * 1.5, 1) * (1 - rev))
        pos[side] = (CARD_X[j] + 20, CARD_Y + dy + 20, doors, gy)
    # hole panel: whichever hole is current; slides in from the right
    cur = None
    for i in range(len(holes)):
        if since(f"h{i}", now) is not None: cur = i
    in_bonus = since("bonus", now) is not None
    if in_bonus and rev < 1:
        k = prog("bonus", now, .5); card, pad = bonus_panel(now)
        place(f, card, 60 - pad + (1 - k) * 900 + card.width / 2, HP_Y - pad + rev * 120, alpha=1 - rev)
        tag = holes[cur].get("tag", M.get("round_tag"))
        if tag and k > .6:                              # e.g. "DealCaddie calculates this for you"
            tg = text_layer(tag.upper(), F_SEMI, 24, GOLD_D, tracking=0.08); place(f, tg, CX, HP_Y + HP_H + 14, alpha=min(1, (k - .6) / .4) * (1 - rev))
    elif cur is not None and rev < 1:
        k = prog(f"h{cur}", now, .5); card, pad = hole_panel(cur, now, k)
        place(f, card, 60 - pad + (1 - k) * 900 + card.width / 2, HP_Y - pad + rev * 120, alpha=1 - rev)
        tag = holes[cur].get("tag", M.get("round_tag"))
        if tag and k > .6:                              # e.g. "DealCaddie calculates this for you"
            tg = text_layer(tag.upper(), F_SEMI, 24, GOLD_D, tracking=0.08); place(f, tg, CX, HP_Y + HP_H + 14, alpha=min(1, (k - .6) / .4) * (1 - rev))
        # outgoing previous hole
        if cur > 0 and k < 1:
            pc, pp = hole_panel(cur - 1, now, 1)
            f.alpha_composite(pc, (int(60 - pp - k * 1100), int(HP_Y - pp)))
    # coins: fall from each door into the hole panel during "coins" holes
    for i, h in enumerate(holes):
        if not h.get("coins"): continue
        for side in "ab":
            s = since(f"h{i}{side}", now)
            if s is None or s > 1.6: continue
            ix, iy, doors, gy = pos[side]; n = 4 if side == "a" else 7
            for c in range(n):
                u = (s - c * 0.12) / 0.9
                if not 0 < u < 1: continue
                d0 = doors[c % len(doors)]; x0, y0 = ix + d0, iy + gy - 30
                x1 = 60 + (W - 120) * (.25 if side == "a" else .75) + (c - n / 2) * 10; y1 = HP_Y + 160
                x = x0 + (x1 - x0) * u; y = y0 + (y1 - y0) * u - math.sin(u * math.pi) * 120
                f.alpha_composite(COIN, (int(x - COIN.width / 2), int(y)))
    # reveal: phone with the app rises into the space
    if rev > 0:
        place(f, PHONE, CX, 470 - PPAD + (1 - rev) * 300, alpha=rev)
    # caption
    cur_ph = None
    for pt0, pd, ph, units in phrases:
        if pt0 - 0.1 <= now < pt0 + pd + GAP + ph.get("pause", 0.25) + ph.get("_hold", 0): cur_ph = units
    if cur_ph:
        cl = caption(cur_ph, now)
        cy = 1452 if rev < .5 else 1460
        f.alpha_composite(cl, (0, cy))
    place(f, FOOT, CX, 1690, alpha=0.9 * (1 - rev))
    return f.convert("RGB")

# ------------------------------------------------------------------ cover (thumbnail + 0.5 s lead)
def make_cover():
    snap = events.get(f"h{len(holes) - 1}w", 6) + 0.8
    fr = frame(snap).convert("RGBA").crop((0, 462, W, 1390))
    fr = fr.resize((int(W * .86), int(fr.height * .86)), Image.LANCZOS)
    c = BG.copy(); place(c, logo_layer(300), CX, 140)
    size = 108; y = 230
    for line in wrap(M["cover"], F_NUM, size, 980):
        place(c, text_layer(line, F_NUM, size, INK, tracking=-0.03), CX, y); y += int(size * 1.04)
    if M.get("cover_sub"):
        b = pill(M["cover_sub"], fill=GOLD, color=INK, size=32, track=0.06); place(c, b, CX, y + 10); y += b.height + 10
    place(c, fr, CX, y + 50)
    return c.convert("RGB")

# ------------------------------------------------------------------ end card: logo, line, trial, CTA, store badges
from reelkit import enter
BADGES = os.path.join(ROOT, "assets", "badges")
def end_card(dur):
    logo = logo_layer(640)
    line = text_layer(M.get("end_line", "Every number. In seconds."), F_HEAD, 60, INK, tracking=-0.01)
    label = text_layer(M.get("cta", "14 days free  ·  dealcaddie.ai"), F_SEMI, 46, WHITE)
    bw, bh = label.width + 120, 116
    btn = Image.new("RGBA", (bw + 80, bh + 80), (0, 0, 0, 0)); sh = Image.new("RGBA", btn.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([40, 56, 40 + bw, 56 + bh], radius=bh // 2, fill=(3, 62, 36, 90))
    btn.alpha_composite(sh.filter(ImageFilter.GaussianBlur(18)))
    ImageDraw.Draw(btn).rounded_rectangle([40, 40, 40 + bw, 40 + bh], radius=bh // 2, fill=FOREST + (255,))
    btn.alpha_composite(label, (40 + (bw - label.width) // 2, 40 + (bh - label.height) // 2 + 2))
    bh_ = 112                                              # both store badges at the same height (Apple + Google rule)
    a = Image.open(os.path.join(BADGES, "app-store-badge@hi.png")).convert("RGBA"); g = Image.open(os.path.join(BADGES, "google-play-badge@hi.png")).convert("RGBA")
    a = a.resize((int(a.width * bh_ / a.height), bh_), Image.LANCZOS); g = g.resize((int(g.width * bh_ / g.height), bh_), Image.LANCZOS)
    row = Image.new("RGBA", (a.width + g.width + 36, bh_), (0, 0, 0, 0)); row.alpha_composite(a, (0, 0)); row.alpha_composite(g, (a.width + 36, 0))
    def fr(tt):
        f = BG.copy()
        p, dy = enter(tt, 0.0, dur=0.7, rise=24); place(f, logo, CX, 560 + dy, p, 0.97 + 0.03 * p)
        p, dy = enter(tt, 0.2); place(f, line, CX, 790 + dy, p)
        p, dy = enter(tt, 0.4); place(f, btn, CX, 880 + dy, p)
        p, dy = enter(tt, 0.6); place(f, row, CX, 1110 + dy, p)
        return f.convert("RGB")
    return fr

if os.environ.get("STILL"):                      # preview: STILL=<seconds or hN> writes one frame as PNG and exits
    st_ = os.environ["STILL"]; t_ = events[st_] + 1.0 if st_ in events else float(st_)
    frame(t_).save(out_mp4[:-4] + ".png"); print("still", t_); sys.exit(0)

# ------------------------------------------------------------------ encode
silent = os.path.join(work, "silent.mp4")
enc = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                        "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p", silent], stdin=subprocess.PIPE)
cover = make_cover(); cover.save(os.path.join(os.path.dirname(out_mp4), os.path.basename(out_mp4)[:-4] + "-cover.jpg"), quality=93)
XF = int(.35 * FPS); first = frame(LEAD)
for i in range(int(LEAD * FPS)):
    enc.stdin.write(cover.tobytes())
last = None
for i in range(int(LEAD * FPS), int(MAIN * FPS)):
    fr = frame(i / FPS)
    if i - int(LEAD * FPS) < XF: fr = Image.blend(cover, fr, (i - int(LEAD * FPS) + 1) / XF)
    enc.stdin.write(fr.tobytes()); last = fr
end_fn = end_card(END)
for i in range(int(END * FPS)):
    e = end_fn(i / FPS)
    if i < XF: e = Image.blend(last, e, (i + 1) / XF)
    enc.stdin.write(e.tobytes())
enc.stdin.close(); enc.wait()

voice = np.zeros(int(TOTAL * SR) + SR, np.float32)
for t0, a in clips: s0 = int(t0 * SR); voice[s0:s0 + len(a)] += a
voice = voice / (np.abs(voice).max() or 1) * 0.9
vw = os.path.join(work, "voice.wav")
with wave.open(vw, "wb") as w_:
    w_.setnchannels(1); w_.setsampwidth(2); w_.setframerate(SR); w_.writeframes((voice * 32767).astype(np.int16).tobytes())
tracks = sorted(x[:-4] for x in os.listdir(os.path.join(ROOT, "music")) if x.endswith(".m4a"))
track = os.environ.get("MUSIC_TRACK") or M.get("music") or tracks[zlib.crc32(M["cover"].encode()) % len(tracks)]
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", silent, "-i", vw, "-stream_loop", "-1", "-i", os.path.join(ROOT, "music", track + ".m4a"),
                "-filter_complex", f"[2:a]volume=0.11,afade=t=out:st={TOTAL - 1.5:.2f}:d=1.5,atrim=0:{TOTAL:.2f}[m];"
                "[1:a]aresample=48000,highpass=f=70,acompressor=threshold=-18dB:ratio=3:attack=5:release=80[v];"
                "[v][m]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-15:TP=-1.5[a]",
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out_mp4], check=True)
d_ = os.path.dirname(out_mp4)
if M.get("caption"): open(os.path.join(d_, "caption.txt"), "w").write(M["caption"])
open(os.path.join(d_, "title.txt"), "w").write(M.get("post_title") or M["title"])
print(f"wrote {out_mp4} ({TOTAL:.1f}s, music {track})")
