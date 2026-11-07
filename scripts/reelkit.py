"""Shared rendering kit for DealCaddie reels (product style).

Everything visual lives here so the daily Deal Verdict reel and the feature videos look identical:
Inter type, warm off-white canvas, the real logo, eased motion, centred inside the Reels safe area.
Call init(workdir) first; card_*.png and photo.jpg are read from that folder.
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

WORK = "."
def init(work):
    global WORK
    WORK = work
def P(f):
    return os.path.join(WORK, f)

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
    if crop:                                   # bottom fraction, or (top, bottom) fractions
        t, b = (crop if isinstance(crop, (list, tuple)) else (0, crop))
        c = c.crop((0, int(c.height * t), c.width, int(c.height * b)))
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
    sub = text_layer(spec["sub"], F_HEAD, fit_size(spec["sub"], F_HEAD, 66, 900, 44), WHITE)
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

def headline_layer(text, size=92, color=INK, max_w=860):
    lines = wrap(text, F_HEAD, size, max_w)
    return stack([text_layer(l, F_HEAD, size, color, tracking=-0.02) for l in lines], int(size * 0.06))

def render_stat_beat(spec, dur):
    """eyebrow + (big counted number | headline) + sub line + optional real UI card.
    spec keys: eyebrow, value+unit+color  OR  headline;  sub;  card, crop, card_max_h."""
    eb = text_layer(spec["eyebrow"], F_SEMI, 32, MUTED, tracking=0.16)
    value = spec.get("value")
    head = headline_layer(spec["headline"]) if spec.get("headline") else None
    vs = fit_size(value, F_NUM, 210, 760, 120) if value else 0
    sub_lines = wrap(spec["sub"], F_MED, 42, 820) if spec.get("sub") else []
    sub = stack([text_layer(s, F_MED, 42, (62, 74, 66)) for s in sub_lines], 8) if sub_lines else Image.new("RGBA", (1, 1))
    max_h = spec.get("card_max_h") or (560 if len(sub_lines) <= 1 else 520)
    card = card_layer(spec["card"], 860, max_h, spec.get("crop")) if spec.get("card") else None
    # vertical rhythm
    y_eb = 440
    y_val = y_eb + eb.height + (16 if head else 6)
    val_h = head.height if head else value_layer(value, spec["unit"], spec["color"], vs).height
    y_sub = y_val + val_h + 6
    y_card_area = y_sub + sub.height + 40
    card_top = None
    if card:
        cl, pad = card
        area_h = 1415 - y_card_area
        card_top = y_card_area + max(0, (area_h - (cl.height - 2 * pad)) // 2) - pad

    finished_val = head if head else value_layer(value, spec["unit"], spec["color"], vs)

    def frame(t):
        f = BG.copy().convert("RGBA")
        place(f, TOP_LOGO, CX, TOP_Y)
        out_a = 1 - ease_in_out((t - (dur - EXIT)) / EXIT)
        out_dy = -18 * (1 - out_a)
        p, dy = enter(t, 0.0)
        place(f, eb, CX, y_eb + dy + out_dy, p * out_a)
        p, dy = enter(t, 0.08)
        cp = min(1.0, max(0.0, (t - 0.08) / 0.9))
        vl = finished_val if (cp >= 1 or head) else value_layer(count_value(value, cp), spec["unit"], spec["color"], vs)
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

def render_end_beat(dur, line="Analyze any rental in seconds.", sub="Rent comps, taxes and insurance — pulled for you."):
    logo = logo_layer(720)
    line = text_layer(line, F_HEAD, fit_size(line, F_HEAD, 54, 900, 38), INK)
    sub = text_layer(sub, F_MED, fit_size(sub, F_MED, 36, 900, 28), MUTED)
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



def render_list_beat(spec, dur):
    """eyebrow + headline + sub, then a white panel of rows that slide in one by one with counted values.
    spec: eyebrow, headline, sub, rows=[{label, note, value, color, best}]"""
    eb = text_layer(spec["eyebrow"], F_SEMI, 32, MUTED, tracking=0.16)
    head = headline_layer(spec["headline"])
    sub = text_layer(spec["sub"], F_MED, 40, (62, 74, 66)) if spec.get("sub") else None
    rows = spec["rows"]
    pw, rh, pad = 860, 92 if len(rows) > 5 else 108, 22
    ph = pad * 2 + rh * len(rows)
    y_eb = 440
    y_head = y_eb + eb.height + 16
    y_sub = y_head + head.height + 10
    y_panel = (y_sub + (sub.height if sub else 0)) + 40
    # panel background with shadow
    sh_pad = 90
    panel = Image.new("RGBA", (pw + sh_pad * 2, ph + sh_pad * 2), (0, 0, 0, 0))
    shl = Image.new("RGBA", panel.size, (0, 0, 0, 0))
    ImageDraw.Draw(shl).rounded_rectangle([sh_pad, sh_pad + 26, sh_pad + pw, sh_pad + ph + 26], radius=34, fill=(20, 40, 28, 60))
    panel.alpha_composite(shl.filter(ImageFilter.GaussianBlur(34)))
    pd = ImageDraw.Draw(panel)
    pd.rounded_rectangle([sh_pad, sh_pad, sh_pad + pw, sh_pad + ph], radius=34, fill=(255, 255, 255, 255), outline=(0, 0, 0, 18), width=2)
    for i, r in enumerate(rows):
        y0 = sh_pad + pad + i * rh
        if r.get("best"):
            pd.rounded_rectangle([sh_pad + 12, y0 + 4, sh_pad + pw - 12, y0 + rh - 4], radius=20, fill=(232, 246, 236, 255))
        elif i:
            pd.line([(sh_pad + 40, y0), (sh_pad + pw - 40, y0)], fill=(0, 0, 0, 16), width=2)
    row_layers = []
    for r in rows:
        lab = text_layer(r["label"], F_SEMI, 40, INK)
        note = text_layer(r["note"], F_MED, 28, MUTED) if r.get("note") else None
        row_layers.append((lab, note))
    vsize = 54 if len(rows) > 5 else 60

    def frame(t):
        f = BG.copy().convert("RGBA")
        place(f, TOP_LOGO, CX, TOP_Y)
        out_a = 1 - ease_in_out((t - (dur - EXIT)) / EXIT)
        out_dy = -18 * (1 - out_a)
        p, dy = enter(t, 0.0); place(f, eb, CX, y_eb + dy + out_dy, p * out_a)
        p, dy = enter(t, 0.08); place(f, head, CX, y_head + dy + out_dy, p * out_a)
        if sub:
            p, dy = enter(t, 0.16); place(f, sub, CX, y_sub + dy + out_dy, p * out_a)
        p, dy = enter(t, 0.24, dur=0.6, rise=50)
        place(f, panel, CX, y_panel - sh_pad + dy + out_dy, p * out_a)
        x0 = CX - pw // 2
        for i, (r, (lab, note)) in enumerate(zip(rows, row_layers)):
            d = 0.40 + i * 0.11
            p, dx = enter(t, d, dur=0.5, rise=28)
            a = p * out_a
            if a <= 0.003: continue
            y0 = y_panel + pad + i * rh + dy * 0 + out_dy
            ty = y0 + (rh - lab.height - (note.height if note else 0)) / 2
            f.alpha_composite(with_alpha(lab, a), (int(x0 + 40 + dx), int(ty)))
            if note:
                f.alpha_composite(with_alpha(note, a), (int(x0 + 40 + dx), int(ty + lab.height - 4)))
            cp = min(1.0, max(0.0, (t - d) / 0.7))
            vl = text_layer(count_value(r["value"], cp), F_NUM, vsize, r.get("color", INK), tracking=-0.03)
            f.alpha_composite(with_alpha(vl, a), (int(x0 + pw - 40 - vl.width - dx), int(y0 + (rh - vl.height) / 2)))
        return f.convert("RGB")
    return frame


# ------------------------------------------------------------------ encode
def encode(timeline, out_mp4, still_at=1.6):
    """timeline: list of (frame_fn, seconds). Writes the MP4 and beat<N>.png stills into WORK."""
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", out_mp4], stdin=subprocess.PIPE)
    starts, t0 = [], 0.0
    for bi, (fn, dur) in enumerate(timeline, start=1):
        starts.append(t0); t0 += int(round(dur * FPS)) / FPS
        n = int(round(dur * FPS))
        for i in range(n):
            img = fn(i / FPS)
            enc.stdin.write(img.tobytes())
            if i == int(still_at * FPS):
                img.save(P(f"beat{bi}.png"))
    enc.stdin.close()
    if enc.wait() != 0:
        sys.exit("ffmpeg failed")
    # music + whooshes + end chime (original tracks in music/, see make_music.py)
    try:
        from soundtrack import add_soundtrack
        return add_soundtrack(out_mp4, starts, t0)
    except Exception as e:                       # never lose a reel over audio
        print("soundtrack skipped:", e)
        return None

def duration(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", p]).decode().strip())
