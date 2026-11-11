#!/usr/bin/env python3
"""Narrated product demo: real screen recording + script written from the real numbers +
Kokoro voice + captions, in a phone frame. Target: under 40 seconds.

Usage: python3 scripts/narrate.py <workdir from record_demo.js> <out.mp4>
Env:   VOICE (default af_heart), VOICE_SPEED (default 1.08)
Writes <out.mp4>, caption.txt, cover.jpg, script.txt next to it.
"""
import json, os, re, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reelkit as rk
from reelkit import (W, H, FPS, BG, INK, MUTED, GREEN, F_HEAD, F_SEMI, F_NUM, fit_size, logo_layer, text_layer, wrap,
                     render_end_beat, place, rounded)

work, out_mp4 = sys.argv[1], sys.argv[2]
out_dir = os.path.dirname(os.path.abspath(out_mp4))
rk.init(work)
data = json.load(open(os.path.join(work, "data.json")))
mk = json.load(open(os.path.join(work, "markers.json")))
SR = 24000
VOICE = os.environ.get("VOICE") or "af_heart"
SPEED = float(os.environ.get("VOICE_SPEED") or 1.05)
MAX_LEN = 45.0          # natural pacing beats a hard 40s cap

# ------------------------------------------------------------------ the script, from real numbers
num = lambda s: float(re.sub(r"[^0-9.\-]", "", s.replace("−", "-"))) if s and re.search(r"\d", s) else None
def dollars(x): return f"${int(round(x)):,}"
def short(x): return f"${round(x / 1000)}K" if x >= 1000 else dollars(x)

price = num(data.get("price") or "") or 0
city = (data.get("cityLine") or "").split(",")[0].strip() or "this market"
units = [float(u) for u in data.get("units") or []]
ptype = {2: "duplex", 3: "triplex", 4: "fourplex"}.get(len(units), f"{len(units)}-unit" if len(units) > 4 else "house")
score = (data.get("score") or "").strip()
AIRBNB = "[Airbnb](/ˈɛɹbˌiˌɛnbˌi/)"
NAMES = {"ltr": "long-term rental", "mtr": "mid-term rental", "str": "Airbnb", "s8": "Section 8", "hh": "house hack", "brrrr": "BRRRR"}
cf = {k: num(v) for k, v in (data.get("strategies") or {}).items() if num(v) is not None}
restricted = bool(data.get("strRestricted"))
legal = {k: v for k, v in cf.items() if not (restricted and k == "str")}
best = max(legal, key=legal.get) if legal else None
rehab = data.get("rehab") or {}

def signed(v): return ("plus " if v >= 0 else "minus ") + dollars(abs(v))
lines = []          # (segment, display text, spoken text)
def spoken_price(x):                        # "a 175 thousand dollar house" — singular, like people say it
    k = int(round(x / 1000))
    return f"{k // 1000} point {str(k % 1000)[0]} million dollar" if k >= 1000 else f"{k} thousand dollar"
lines.append(("intro", f"A {short(price)} {ptype} in {city}. Is it a deal?",
              f"A {spoken_price(price)} {ptype} in {city}. Is it a deal?"))
lines.append(("paste", "I just paste the Zillow link.", "I just paste the Zillow link."))
if score:
    lines.append(("score", f"Ten seconds later: deal score, {score} out of 10.",
                  f"Ten seconds later. Deal score: {score} out of ten."))
rent_total = sum(units) if len(units) >= 2 else (num(data.get("ltrRent") or "") or 0)
if rent_total:
    across = f" across {len(units)} units" if len(units) >= 2 else ""
    lines.append(("auto", f"Rent from RentCast: {dollars(rent_total)}/mo{across}. Taxes and insurance, filled in.",
                  f"Rent from Rent Cast: {dollars(rent_total)} a month{across}. Taxes and insurance, filled in."))
if best is not None:
    if restricted and cf.get("str") is not None and cf["str"] > legal[best]:
        d = (f"Airbnb pays most, but it's restricted in {city}, and DealCaddie flags it. "
             f"The real play: {NAMES[best]}, at {'+' if legal[best] >= 0 else '−'}{dollars(abs(legal[best]))}/mo.")
        s = (f"AIRBNB pays most, but it's restricted in {city}, and Deal Caddie flags it. "
             f"The real play: {NAMES[best]}, at {signed(legal[best])} a month.")
    elif best == "ltr" or cf.get("ltr") is None:
        d = f"Every strategy, side by side. Best play: {NAMES[best]}, at {'+' if legal[best] >= 0 else '−'}{dollars(abs(legal[best]))}/mo."
        s = f"Every strategy, side by side. Best play: {NAMES[best]}, at {signed(legal[best])} a month."
    else:
        d = (f"Every strategy, side by side. Long-term rental: {'+' if cf['ltr'] >= 0 else '−'}{dollars(abs(cf['ltr']))}/mo. "
             f"But as a {NAMES[best]}: {'+' if legal[best] >= 0 else '−'}{dollars(abs(legal[best]))}/mo.")
        s = (f"Every strategy, side by side. Long-term rental, {signed(cf['ltr'])} a month. "
             f"But as a {NAMES[best]}, {signed(legal[best])} a month.")
    lines.append(("strategies", d, re.sub(r"(?<!\[)\b(?:AIRBNB|Airbnb)\b(?!\])", AIRBNB, s.replace("BRRRR", "burr"))))
rng = (rehab.get("range") or "").replace("–", "-")
m = re.findall(r"\$(\d+)K", rng)
if len(m) == 2:
    lvl = (rehab.get("level") or "").strip().lower() or "light"
    lines.append(("rehab", f"It even reads the photos: {lvl} rehab, ${m[0]}K to ${m[1]}K.",
                  f"It even reads the photos. {lvl.capitalize()} rehab, {m[0]} to {m[1]} thousand."))
lines.append(("wrap", "DealCaddie runs every number for you, in seconds.",
              "Deal Caddie runs every number for you in seconds."))
lines.append(("end", "Try it free at dealcaddie.ai.",
              "Try it free, at Deal Caddie dot [A.I.](/ˌAˈI/)"))

# ------------------------------------------------------------------ storyboard mode (feature videos)
STORY = json.load(open(os.environ["STORY"])) if os.environ.get("STORY") else None

def speakify(t):
    """Display text → what the voice should say (prices as people say them, brand names, units)."""
    t = re.sub(r"\$(\d+(?:\.\d)?)[Kk] (house|rental|duplex|triplex|fourplex|condo|townhome|home|property|listing|deal)\b",
               lambda m: f"{m.group(1)} thousand dollar {m.group(2)}", t)
    t = re.sub(r"\$(\d+(?:\.\d)?)M\b", lambda m: f"{m.group(1)} million dollars", t)
    t = re.sub(r"\$(\d+)[Kk]\s*[–-]\s*\$(\d+)[Kk]", r"\1 to \2 thousand dollars", t)
    t = re.sub(r"(\$[\d.,]+[KkM]?)\s*[–-]\s*(\$[\d.,]+[KkM]?)", r"\1 to \2", t)
    t = re.sub(r"\$(\d+(?:\.\d)?)[Kk]\b", lambda m: f"{m.group(1)} thousand dollars", t)
    t = re.sub(r"(\$[\d,]+)/mo\b", r"\1 a month", t)
    t = re.sub(r"(\$[\d,]+)/sqft\b", r"\1 a square foot", t)
    t = t.replace("+$", "plus $").replace("−$", "minus $").replace("-$", "minus $")
    t = t.replace("DealCaddie", "Deal Caddie").replace("RentCast", "Rent Cast").replace("BRRRR", "burr")
    for word, ph in (("DSCR", "dˌiɛsˌsiˈɑɹ"), ("PMI", "pˌiɛmˈI"), ("LTV", "ˌɛltiˈvi"), ("PITIA", "pˌitˌiˌIˈA"),
                     ("IRR", "ˌIɑɹˈɑɹ"), ("HOA", "ˌAtʃˌOˈA"), ("ROI", "ˌɑɹˌOˈI"), ("ARV", "ˌAɑɹˈvi")):
        t = re.sub(rf"(?<!\[)\b{word}\b(?!\])", f"[{word}](/{ph}/)", t)      # one continuous acronym, no pauses
    t = re.sub(r"(?<!\[)\bAirbnb\b(?!\])", AIRBNB, t)
    return t

if STORY:
    v = dict(price_short=short(price), city=city, ptype=ptype, score=score)
    v.update({k: x for k, x in (data.get("vars") or {}).items() if x})
    if v.get("verdict"): v["verdict"] = v["verdict"].lower().replace("buy", "buy").strip()
    class _Miss(dict):
        def __missing__(self, k): raise KeyError(k)
    lines = []
    for sc in STORY["scenes"]:
        for cand in [sc.get("line")] + list(sc.get("alts") or []):
            if not cand: continue
            try:
                txt = cand.format_map(_Miss(v)); break
            except KeyError:
                txt = None
        if txt:
            lines.append((sc["id"], txt, speakify(txt)))
        else:
            print(f"scene {sc['id']}: no line (missing numbers) — dropped")
    wrap_line = STORY.get("wrap", "DealCaddie runs every number for you in seconds.")
    if wrap_line:
        lines.append(("wrap", wrap_line, speakify(wrap_line)))
    lines.append(("end", STORY.get("end", "Try it free at dealcaddie.ai."),
                  speakify(STORY.get("end", "Try it free at dealcaddie.ai.")).replace("dealcaddie.ai", "Deal Caddie dot [A.I.](/ˌAˈI/)")))
    for seg, d, sp in lines: print(f"[{seg}] {d}\n      say: {sp}")

# ------------------------------------------------------------------ voice (Kokoro, runs locally)
from kokoro import KPipeline
pipe = KPipeline(lang_code="a")
def speak(text, speed):
    parts = []
    for gs, ps, a in pipe(text, voice=VOICE, speed=speed):
        print(f"  phonemes: {ps}")
        parts.append(a.numpy() if hasattr(a, "numpy") else np.asarray(a))
    return np.concatenate(parts).astype(np.float32) if parts else np.zeros(1, np.float32)

GAP = 0.35
for attempt in range(3):
    audio = [speak(s, SPEED) for _, _, s in lines]
    seg_len = [len(a) / SR + GAP for a in audio]
    total = sum(seg_len) + 0.6
    print(f"voice @ {SPEED:.2f}x: {total:.1f}s")
    if total <= MAX_LEN: break
    SPEED = round(SPEED * min(1.18, total / MAX_LEN + 0.02), 2)

# ------------------------------------------------------------------ retime the screen recording
src = os.path.join(work, "screen.mp4")
filters, labels = [], []
for i, (seg, _, _) in enumerate(lines):
    if seg == "end": continue
    m0 = mk.get(seg) or {}
    a, b = m0.get("start", 0), m0.get("end", m0.get("start", 0) + 6)
    need = seg_len[i]
    if seg == "paste":                       # the wait for the analysis is squeezed into the line
        sp = max(1.0, (b - a) / need)
        f = f"[0:v]trim={a}:{b},setpts=(PTS-STARTPTS)/{sp:.3f}"
    else:
        f = f"[0:v]trim={a}:{min(b, a + need)},setpts=PTS-STARTPTS"
    f += f",fps={FPS},tpad=stop_mode=clone:stop_duration={need:.2f},trim=0:{need:.3f},setpts=PTS-STARTPTS[v{i}]"
    filters.append(f); labels.append(f"[v{i}]")
cut = os.path.join(work, "screen_cut.mp4")
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-filter_complex",
                ";".join(filters) + f";{''.join(labels)}concat=n={len(labels)}:v=1:a=0[v]",
                "-map", "[v]", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", cut], check=True)
probe = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                 "stream=width,height", "-of", "csv=p=0", cut]).decode().strip().split(",")
sw, sh = int(probe[0]), int(probe[1])

# ------------------------------------------------------------------ captions: short chunks timed by length
starts = np.cumsum([0] + seg_len[:-1])
caps = []                    # (t0, t1, text)
for (seg, disp, _), t0, dur, a in zip(lines, starts, seg_len, audio):
    if seg == "end": continue
    words = disp.split()
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= 6 or (w.endswith((".", "?", ":", ",")) and len(cur) >= 2):
            chunks.append(" ".join(cur)); cur = []
    if cur:
        if len(cur) == 1 and chunks: chunks[-1] += " " + cur[0]      # never strand a single word
        else: chunks.append(" ".join(cur))
    speak_t = len(a) / SR
    tot = sum(len(c) for c in chunks) or 1
    t = t0
    for c in chunks:
        d = speak_t * len(c) / tot
        caps.append((t, t + d, c)); t += d

# ------------------------------------------------------------------ compose: brand canvas, phone, captions
LOGO = logo_layer(250)
# A real phone keeps content clear of its rounded corners: a status-bar strip on top and a
# home-indicator strip at the bottom. The recording sits between them, so the app header and the
# bottom tab bar are never clipped by the corner radius.
TOP_IN, BOT_IN = 64, 60      # bottom = an iPhone's home-indicator safe area (the emulator reports 0)
INNER_H = 1440
SCR_H = INNER_H - TOP_IN - BOT_IN
SCR_W = int(sw * SCR_H / sh)
bez = 20
phone = Image.new("RGBA", (SCR_W + 2 * bez, INNER_H + 2 * bez), (0, 0, 0, 0))
ImageDraw.Draw(phone).rounded_rectangle([0, 0, phone.width - 1, phone.height - 1], radius=86, fill=(16, 22, 19, 255))
shadow = Image.new("RGBA", (phone.width + 160, phone.height + 160), (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle([80, 110, 80 + phone.width, 110 + phone.height], radius=86, fill=(10, 30, 18, 70))
from PIL import ImageFilter
shadow = shadow.filter(ImageFilter.GaussianBlur(40))
PX, PY = (W - phone.width) // 2, 150
mask = Image.new("L", (SCR_W, INNER_H), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, SCR_W - 1, INNER_H - 1], radius=68, fill=255)
ISLAND = (SCR_W // 2 - 70, 18, SCR_W // 2 + 70, 52)

def screen_with_insets(fr):
    """status-bar + home-indicator strips in the app's own edge colours, island + home bar drawn on."""
    top_c = fr.getpixel((fr.width // 2, 2)); bot_c = fr.getpixel((fr.width // 2, fr.height - 3))
    inner = Image.new("RGB", (SCR_W, INNER_H), top_c)
    ImageDraw.Draw(inner).rectangle([0, INNER_H - BOT_IN, SCR_W, INNER_H], fill=bot_c)
    inner.paste(fr, (0, TOP_IN))
    d = ImageDraw.Draw(inner)
    d.rounded_rectangle(ISLAND, radius=17, fill=(10, 12, 11))
    lum = sum(bot_c[:3]) / 3
    d.rounded_rectangle([SCR_W // 2 - 90, INNER_H - 22, SCR_W // 2 + 90, INNER_H - 14], radius=4,
                        fill=(20, 20, 20) if lum > 128 else (235, 235, 235))
    return inner
base = BG.copy().convert("RGBA")
place(base, LOGO, W // 2, 62)
def ease_out(k): k = min(1.0, max(0.0, k)); return 1 - (1 - k) ** 3
def phone_dy(t):                         # opening move: the phone rises into place over the first second
    return int(760 * (1 - ease_out(t / 0.95)))
cap_cache = {}
def caption(text):
    if text not in cap_cache:
        ls = wrap(text, F_HEAD, 64, 940)
        layers = [text_layer(l, F_HEAD, 64, INK, tracking=-0.015) for l in ls]
        hh = sum(l.height for l in layers) + 10 * (len(layers) - 1)
        im = Image.new("RGBA", (W, hh), (0, 0, 0, 0)); y = 0
        for l in layers:
            im.alpha_composite(l, ((W - l.width) // 2, y)); y += l.height + 10
        cap_cache[text] = im
    return cap_cache[text]

# opening hook: the first line as a big title, words popping in as they're spoken
hook_end = seg_len[0] if lines else 0
_hw = []
if lines:
    hook_txt = lines[0][1]; HS = 66
    words = hook_txt.split(); rows_, cur_ = [], []
    for w_ in words:
        test = " ".join(cur_ + [w_])
        if cur_ and text_layer(test, F_HEAD, HS, INK).width > 960: rows_.append(cur_); cur_ = [w_]
        else: cur_.append(w_)
    if cur_: rows_.append(cur_)
    space = text_layer("a a", F_HEAD, HS, INK).width - 2 * text_layer("a", F_HEAD, HS, INK).width
    lh = int(HS * 1.12); top = 1752 - (lh * len(rows_)) // 2
    spoken = len(audio[0]) / SR if audio else hook_end
    k = 0; nwords = len(words)
    for ri, row in enumerate(rows_):
        lays = [text_layer(w_, F_HEAD, HS, INK, tracking=-0.015) for w_ in row]
        x = (W - (sum(l.width for l in lays) + space * (len(lays) - 1))) // 2
        for l in lays:
            _hw.append((l, x, top + ri * lh, 0.15 + spoken * k / max(1, nwords))); x += l.width + space; k += 1
def hook_frame(t):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for l, x, y, t0 in _hw:
        a = min(1.0, max(0.0, (t - t0) / 0.18))
        if a <= 0: continue
        if a < 1: l = l.copy(); l.putalpha(l.getchannel("A").point(lambda v: int(v * a)))
        im.alpha_composite(l, (x, int(y + 18 * (1 - a))))
    return im

end_dur = seg_len[-1] + 0.6
end_fn = render_end_beat(end_dur)
n_main = int(round(sum(seg_len[:-1]) * FPS))
n_end = int(round(end_dur * FPS))
silent = os.path.join(work, "demo_silent.mp4")
enc = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                        "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "17", "-preset", "medium",
                        "-pix_fmt", "yuv420p", silent], stdin=subprocess.PIPE)
dec = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", cut, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       stdout=subprocess.PIPE)
fsz = sw * sh * 3
last = None
cover_saved = False
_cs = (STORY or {}).get("cover_scene") if STORY else "strategies"
_cover_seg = next((i for i, (seg, _, _) in enumerate(lines) if seg == _cs), 1 if len(lines) > 2 else 0)
_cover_t = float(np.cumsum([0] + seg_len)[_cover_seg] + seg_len[_cover_seg] * 0.6)
cover_shot = None
last_main = None
# camera punch-in: on storyboard scenes the recorder noted where the subject sits on screen;
# ease in to it so small table text is readable on a phone, ease back out before the next scene
VW, VH = 430.0, 932.0
seg_t0 = np.cumsum([0] + seg_len[:-1])
zplan = []
for (seg, _, _), t0, dur in zip(lines, seg_t0, seg_len):
    r = (mk.get(seg) or {}).get("rect")
    if not r or seg == "end":
        zplan.append(None); continue
    x, y, w, h = r
    if w < 0.6 * VW:                      # a small label/button: keep the whole row in shot, gentle push only
        z, cx = min(1.1, 0.80 * VH / max(h, 1)), 0.5
    else:
        z, cx = min(1.5, 0.96 * VW / max(w, 1), 0.80 * VH / max(h, 1)), (x + w / 2) / VW
    z = max(1.0, z)
    if z < 1.06: zplan.append(None); continue
    zplan.append((t0, dur, z, cx, (y + h / 2) / VH))
def zoom_at(t):
    for zp in zplan:
        if zp and zp[0] <= t < zp[0] + zp[1]:
            t0, dur, z, cx, cy = zp
            k = min(1.0, (t - t0) / 0.7, (t0 + dur - t) / 0.45)
            k = max(0.0, k); k = k * k * (3 - 2 * k)
            return 1 + (z - 1) * k, cx, cy
    return 1.0, 0.5, 0.5
for i in range(n_main):
    buf = dec.stdout.read(fsz)
    if len(buf) == fsz:
        src_im = Image.frombytes("RGB", (sw, sh), buf)
        z, cx, cy = zoom_at(i / FPS)
        if z > 1.001:
            cw, ch = sw / z, sh / z
            x0 = min(max(cx * sw - cw / 2, 0), sw - cw); y0 = min(max(cy * sh - ch / 2, 0), sh - ch)
            src_im = src_im.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch)))
        last = src_im.resize((SCR_W, SCR_H), Image.LANCZOS)
    t = i / FPS
    f = base.copy()
    dy = phone_dy(t)
    f.alpha_composite(shadow, (PX - 80, PY - 80 + dy))
    f.alpha_composite(phone, (PX, PY + dy))
    if last is not None:
        f.paste(screen_with_insets(last), (PX + bez, PY + bez + dy), mask)
    cur = next((c for c in caps if c[0] <= t < c[1] + 0.12), None)
    if t < hook_end:
        f.alpha_composite(hook_frame(t), (0, 0)); cur = None
    if cur:
        cl = caption(cur[2])
        f.alpha_composite(cl, (0, 1752 - cl.height // 2))
    fr = f.convert("RGB")
    if cover_shot is None and t >= _cover_t and last is not None:
        cover_shot = screen_with_insets(last).copy()
    enc.stdin.write(fr.tobytes())
    last_main = fr
dec.stdout.close()
XF = int(0.6 * FPS)                      # soft cross-fade from the phone into the end card
for i in range(n_end):
    e = end_fn(i / FPS)
    if i < XF and last_main is not None:
        e = Image.blend(last_main, e, (i + 1) / XF)
    enc.stdin.write(e.tobytes())
enc.stdin.close(); enc.wait()

# ------------------------------------------------------------------ designed cover (grid thumbnail)
def make_cover(headline, sub, shot):
    cv = Image.new("RGB", (W, H), (3, 62, 36)); d = ImageDraw.Draw(cv)
    for y in range(H):                                             # forest gradient
        k = y / H; d.line([(0, y), (W, y)], fill=(int(3 + 14 * (1 - k)), int(62 - 30 * k), int(36 - 14 * k)))
    cv = cv.convert("RGBA")
    place(cv, logo_layer(330, white=True), W // 2, 250)
    size = 128
    while size > 76:
        ls = wrap(headline, F_NUM, size, 960)
        if len(ls) <= 3: break
        size -= 8
    y = 360
    for l in ls:
        tl = text_layer(l, F_NUM, size, (255, 255, 255), tracking=-0.03)
        cv.alpha_composite(tl, ((W - tl.width) // 2, y)); y += int(size * 1.04)
    if sub:
        st = text_layer(sub, F_SEMI, fit_size(sub, F_SEMI, 46, 980, 30), (232, 197, 92)); cv.alpha_composite(st, ((W - st.width) // 2, y + 18)); y += 44 + 40
    if shot is not None:                                           # the payoff screen, in the phone, lower half
        ph_h = max(640, 1800 - (y + 40)); ph_w = int(ph_h * shot.width / shot.height)
        sh_ = shot.resize((ph_w, ph_h), Image.LANCZOS)
        m_ = Image.new("L", sh_.size, 0); ImageDraw.Draw(m_).rounded_rectangle([0, 0, ph_w - 1, ph_h - 1], radius=52, fill=255)
        bz = 16; body = Image.new("RGBA", (ph_w + 2 * bz, ph_h + 2 * bz), (0, 0, 0, 0))
        ImageDraw.Draw(body).rounded_rectangle([0, 0, body.width - 1, body.height - 1], radius=66, fill=(12, 16, 14, 255))
        body.paste(sh_, (bz, bz), m_)
        cv.alpha_composite(body, ((W - body.width) // 2, y + 40))
    return cv.convert("RGB")

cover_head = (STORY or {}).get("cover") if STORY else "Is it a deal? 10 seconds."
cover_sub = (STORY or {}).get("cover_sub") if STORY else None
try:
    cover_head = (cover_head or lines[0][1]).format_map(v) if STORY else cover_head
    cover_sub = cover_sub.format_map(v) if cover_sub else None
except Exception:
    cover_head, cover_sub = lines[0][1], None
cover_img = make_cover(cover_head, cover_sub, cover_shot)
cover_path = os.path.join(out_dir, "cover.jpg"); cover_img.save(cover_path, quality=93)
COVER_LEAD = 0.5                                                   # cover holds, then fades into the opening
lead = os.path.join(work, "demo_lead.mp4")
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-loop", "1", "-t", f"{COVER_LEAD}", "-i", cover_path, "-i", silent,
                "-filter_complex", f"[0:v]scale={W}:{H},fps={FPS},format=yuv420p,setsar=1,settb=AVTB[a];[1:v]fps={FPS},format=yuv420p,setsar=1,settb=AVTB[b];[a][b]xfade=transition=fade:duration=0.3:offset={COVER_LEAD - 0.3}[v]",
                "-map", "[v]", "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p", lead], check=True)
silent = lead

# ------------------------------------------------------------------ audio: voice + quiet music bed
total = (n_main + n_end) / FPS + COVER_LEAD - 0.3
LEAD_S = COVER_LEAD - 0.3
voice = np.zeros(int(total * SR) + SR, np.float32)
for t0, a in zip(starts, audio):
    s = int((t0 + LEAD_S) * SR); voice[s:s + len(a)] += a[: max(0, len(voice) - s)]
peak = np.abs(voice).max() or 1
voice = (voice / peak * 0.9).astype(np.float32)
vwav = os.path.join(work, "voice.wav")
import wave
with wave.open(vwav, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((voice * 32767).astype(np.int16).tobytes())
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tracks = sorted(x for x in os.listdir(os.path.join(root, "music")) if x.endswith(".m4a"))
import datetime
import zlib
_salt = zlib.crc32(((STORY or {}).get("title", "full") if STORY else "full").encode())
track = os.environ.get("MUSIC_TRACK") or tracks[(datetime.date.today().toordinal() * 5 + _salt) % len(tracks)].rsplit(".", 1)[0]
music = os.path.join(root, "music", track + ".m4a")
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", silent, "-i", vwav, "-stream_loop", "-1", "-i", music,
                "-filter_complex",
                f"[2:a]volume=0.11,afade=t=out:st={total - 1.5:.2f}:d=1.5,atrim=0:{total:.2f}[m];"
                f"[1:a]aresample=48000,highpass=f=70,acompressor=threshold=-18dB:ratio=3:attack=5:release=80[v];"
                f"[v][m]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-15:TP=-1.5[a]",
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out_mp4],
               check=True)
print(f"wrote {out_mp4}  ({total:.1f}s, voice {VOICE} @ {SPEED}x, music {track})")

# ------------------------------------------------------------------ caption + script files
open(os.path.join(out_dir, "script.txt"), "w").write("\n".join(f"[{s}] {d}" for s, d, _ in lines))
hook = f"{short(price)} {city} {ptype}. Watch DealCaddie run the numbers."
blurb = "Paste any Zillow link → rent, taxes, insurance, 7 strategies and a rehab estimate in about 10 seconds."
tags = f"#realestateinvesting #rentalproperty #cashflow #realestateinvestor #{re.sub(r'[^a-z]', '', city.lower())}realestate"
if STORY:
    try: hook = STORY.get("title", hook).format_map(v)
    except KeyError: pass
    blurb = STORY.get("blurb", blurb)
    tags = STORY.get("tags", tags)
why = (STORY or {}).get("why", "Stop guessing on deals. Know the numbers before you buy.") if STORY else \
      "Stop guessing on deals. Know the numbers in seconds, and buy with confidence."
ask = (STORY or {}).get("ask", "Would you buy it? 👇") if STORY else "Would you buy it? Comment BUY or PASS 👇"
open(os.path.join(out_dir, "caption.txt"), "w").write(
    f"""{hook}

{why}

{' '.join(d for s, d, _ in lines if s not in ('end', 'wrap'))}

{blurb}

💬 {ask}
📌 Save this for your next deal.

Try it free → dealcaddie.ai

{tags}
""")
json.dump({"hook": hook, "duration": total, "voice": VOICE, "speed": SPEED, "track": track},
          open(os.path.join(out_dir, "meta.json"), "w"), indent=2)
