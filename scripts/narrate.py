#!/usr/bin/env python3
"""Narrated product demo: real screen recording + script written from the real numbers +
Kokoro voice + captions, in a phone frame. Target: under 40 seconds.

Usage: python3 scripts/narrate.py <workdir from record_demo.js> <out.mp4>
Env:   VOICE (default af_heart), VOICE_SPEED (default 1.08)
Writes <out.mp4>, caption.txt, cover.jpg, script.txt next to it.
"""
import json, math, os, re, subprocess, sys
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
    t = re.sub(r"(\d(?:\.\d+)?)x\b", r"\1 times", t)                     # 1.28x → "1.28 times"
    t = t.replace("+$", "plus $").replace("−$", "minus $").replace("-$", "minus $")
    t = t.replace("DealCaddie", "Deal Caddie").replace("RentCast", "Rent Cast").replace("BRRRR", "burr")
    for word, ph in (("DSCR", "dˌiɛsˌsiˈɑɹ"), ("PMI", "pˌiɛmˈI"), ("LTV", "ˌɛltiˈvi"), ("PITIA", "pˌitˌiˌIˈA"),
                     ("IRR", "ˌIɑɹˈɑɹ"), ("HOA", "ˌAtʃˌOˈA"), ("ROI", "ˌɑɹˌOˈI"), ("ARV", "ˌAɑɹˈvi")):
        t = re.sub(rf"(?<!\[)\b{word}\b(?!\])", f"[{word}](/{ph}/)", t)      # one continuous acronym, no pauses
    t = re.sub(r"(?<!\[)\bAirbnb\b(?!\])", AIRBNB, t)
    return t

def say_names(t):
    """Place names and acronyms the voice gets wrong, on every spoken line."""
    t = re.sub(r"\b(?:St\.?|Saint) Louis\b", "Saint Lewis", t)   # "Lewis", never "Louie"
    t = re.sub(r"(?<!\[)\bHUD\b(?!\])", "hud", t)       # said as a word, not H-U-D
    t = re.sub(r"(?<!\[)\bZIP\b(?!\])", "zip", t)
    return t

if STORY:
    v = dict(price_short=short(price), city=city, ptype=ptype, score=score)
    if rent_total: v["rent"] = dollars(rent_total)
    if best is not None:
        v["best_name"] = NAMES[best]; v["best_cf"] = ("+" if legal[best] >= 0 else "−") + dollars(abs(legal[best]))
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
        if txt and sc.get("needs_focus") and (mk.get(sc["id"]) or {}).get("missed"):
            print(f"scene {sc['id']}: its subject never appeared on screen — dropped"); txt = None
        elif txt:
            lines.append((sc["id"], txt, speakify(txt)))
        elif not sc.get("needs_focus") or not (mk.get(sc["id"]) or {}).get("missed"):
            print(f"scene {sc['id']}: no line (missing numbers) — dropped")
    # lines for segments recorded outside the scene list (the on-camera paste of a "search" story)
    for sid, ln in (STORY.get("extra_lines") or {}).items():
        lines.append((sid, ln, speakify(ln)))
    if STORY.get("order"):                       # play scenes in story order, not recording order
        rank = {sid: i for i, sid in enumerate(STORY["order"])}
        lines = [l for l in lines if l[0] in rank]
        lines.sort(key=lambda l: rank[l[0]])
    wrap_line = STORY.get("wrap", "DealCaddie runs every number for you in seconds.")
    if wrap_line:
        lines.append(("wrap", wrap_line, speakify(wrap_line)))
    lines.append(("end", STORY.get("end", "Try it free at dealcaddie.ai."),
                  speakify(STORY.get("end", "Try it free at dealcaddie.ai.")).replace("dealcaddie.ai", "Deal Caddie dot [A.I.](/ˌAˈI/)")))
    for seg, d, sp in lines: print(f"[{seg}] {d}\n      say: {sp}")

# ------------------------------------------------------------------ voice (Kokoro, runs locally)
from kokoro import KPipeline
pipe = KPipeline(lang_code="a")
def _core(w): return re.sub(r"[^a-z0-9]", "", w.lower())
def speak(text, speed):
    """-> (audio, [(word, t0, t1)]) with the duration model's own per-word timestamps."""
    text = say_names(text)
    parts, words, off = [], [], 0.0
    for r in pipe(text, voice=VOICE, speed=speed):
        print(f"  phonemes: {r.phonemes}")
        a = r.audio.numpy() if hasattr(r.audio, "numpy") else np.asarray(r.audio)
        for tk in (getattr(r, "tokens", None) or []):
            if _core(tk.text) and getattr(tk, "start_ts", None) is not None:
                words.append((tk.text, off + tk.start_ts, off + (tk.end_ts or tk.start_ts)))
        parts.append(a); off += len(a) / SR
    return (np.concatenate(parts).astype(np.float32) if parts else np.zeros(1, np.float32)), words

GAP = 0.35
if STORY and STORY.get("max_len"): MAX_LEN = float(STORY["max_len"])
_sc = {sc["id"]: sc for sc in (STORY or {}).get("scenes", [])}
gaps = [float(_sc.get(seg, {}).get("gap", GAP)) for seg, _, _ in lines]     # "gap": 0.1 chains lines tightly
for attempt in range(3):
    spoken = [speak(s, SPEED) for _, _, s in lines]
    audio = [a for a, _ in spoken]; wtimes = [w for _, w in spoken]
    seg_len = [len(a) / SR + g for a, g in zip(audio, gaps)]
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
    if (STORY and (_sc.get(seg, {}).get("laptop") or _sc.get(seg, {}).get("chat"))) or not m0: a, b = 0, 1        # drawn, not recorded
    need = seg_len[i]
    if seg == "paste":                       # the wait for the analysis is squeezed into the line
        hold = 1.1 if (STORY and any(sc_.get("laptop") for sc_ in STORY.get("scenes", []))) else 0.0
        # (intro: the phone is still flying in for the first ~1s, so start the typing once it has landed)
        sp = max(1.0, (b - a) / max(0.5, need - hold))
        f = f"[0:v]trim={a}:{b},setpts=(PTS-STARTPTS)/{sp:.3f}"
        if hold: f += f",tpad=start_mode=clone:start_duration={hold:.2f}"
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

# ------------------------------------------------------------------ captions: each chunk appears as its first word is spoken
def word_times(disp, words, speak_t):
    """Start time of every display word. Display and spoken text differ ("$1,450/mo" vs the words
    said), so match what we can in order and spread the rest evenly between matched neighbours."""
    dw = disp.split(); n = len(dw)
    if not words:                               # no timestamps: spread by length (the old way)
        L = [len(w) + 1 for w in dw]; tot = sum(L) or 1
        return [speak_t * sum(L[:i]) / tot for i in range(n)]
    cores = [_core(w) for w, _, _ in words]
    tok, j = [None] * n, 0                      # display word -> index of the spoken word it matched
    for i, w in enumerate(dw):
        c = _core(w)
        if not c: continue
        for k in range(j, min(j + 6, len(cores))):
            if cores[k] == c or (len(cores[k]) >= 3 and c.startswith(cores[k])):
                tok[i] = k; j = k + 1; break
    if tok[0] is None: tok[0] = 0
    got = [None] * n
    i = 0
    while i < n:
        if tok[i] is not None:
            got[i] = words[tok[i]][1]; i += 1; continue
        a = i - 1; b = i                        # unmatched run [i, b): it owns the spoken words between its neighbours
        while b < n and tok[b] is None: b += 1
        k0 = tok[a] + 1; k1 = tok[b] if b < n else len(words)
        for r, ii in enumerate(range(i, b)):
            kk = k0 + (k1 - k0) * r // max(1, b - i)
            got[ii] = words[kk][1] if kk < k1 and kk < len(words) else (words[k1][1] if k1 < len(words) else words[-1][2])
        i = b
    for i in range(1, n): got[i] = max(got[i], got[i - 1])
    return got

starts = np.cumsum([0] + seg_len[:-1])
caps = []                    # (t0, t1, text)
CAP_LEAD = 0.04              # a hair early reads as "in sync"; late reads as lag
_sync_log = []
for (seg, disp, _), t0, dur, a, wt in zip(lines, starts, seg_len, audio, wtimes):
    if seg == "end": continue
    words = disp.split()
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= 6 or (w.endswith((".", "?", ":", ",")) and len(cur) >= 2):
            chunks.append(cur); cur = []
    if cur:
        if len(cur) == 1 and chunks: chunks[-1] += cur      # never strand a single word
        else: chunks.append(cur)
    speak_t = len(a) / SR
    wt_ = word_times(disp, wt, speak_t)
    k = 0; cstarts = []
    for c in chunks:
        cstarts.append(t0 + max(0.0, wt_[k] - CAP_LEAD)); k += len(c)
    for ci, c in enumerate(chunks):
        c1 = cstarts[ci + 1] if ci + 1 < len(chunks) else t0 + max(speak_t, dur - 0.05)
        caps.append((cstarts[ci], c1, " ".join(c)))
    _sync_log.append(f"  [{seg}] {'real' if wt else 'estimated'} timing: " + " | ".join(f"{cs - t0:.2f}s {' '.join(c[:2])}…" for cs, c in zip(cstarts, chunks)))
print("caption timing:\n" + "\n".join(_sync_log))

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
# no top logo: Instagram/TikTok overlay the account name + audio label there (it collided). Brand lives on the cover + end card.
def ease_out(k): k = min(1.0, max(0.0, k)); return 1 - (1 - k) ** 3
# ---- laptop scenes ("the old way"): the laptop is the centerpiece. Every number you have to go and find
# pops up above it as she names it, then flies down into its cell in the spreadsheet.
_lap_seg = [bool(_sc.get(seg, {}).get("laptop")) for seg, _, _ in lines]
_seg_t0 = np.cumsum([0] + seg_len[:-1])
_chat_seg = [bool(_sc.get(seg, {}).get("chat")) for seg, _, _ in lines]
REVEAL_T = next((float(_seg_t0[i]) for i, (seg, _, _) in enumerate(lines) if not _lap_seg[i] and seg != "end"), 0.0)
PHONE_T0 = next((float(_seg_t0[i]) for i, (seg, _, _) in enumerate(lines) if not _lap_seg[i] and not _chat_seg[i] and seg != "end"), 0.0)
LAP_END = REVEAL_T if any(_lap_seg) else 0.0
HERO = any(_lap_seg)                      # the brand reveal + hero entrance of the phone
_cards, _sheets = [], []                  # cards: dict(t, fly, land, key, label, sub, slot); sheets: (t, key, drift)
_lap_img = {}
def ease_io(k): k = min(1.0, max(0.0, k)); return 4 * k ** 3 if k < 0.5 else 1 - (-2 * k + 2) ** 3 / 2
def ease_back(k, s_=1.6):
    k = min(1.0, max(0.0, k)) - 1; return 1 + (s_ + 1) * k ** 3 + s_ * k ** 2
def rounded_box(w, h, col, r):
    b = Image.new("RGBA", (w, h), (0, 0, 0, 0)); ImageDraw.Draw(b).rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=col + (255,)); return b
if HERO:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    LDIR = os.path.join(root, "assets", "intro", "laptop")
    LSW, LSH = 960, 600
    LX, LY = (W - LSW) // 2, 720
    SHEET = STORY.get("laptop_sheet", "xls")             # page states: <sheet>0..N as cards land, <sheet>E at the end
    CELLS = json.load(open(os.path.join(LDIR, STORY.get("laptop_cells", "cells.json"))))
    CROPS = STORY.get("laptop_crop", {})                  # which part of each 1440x900 page the laptop shows
    def crop_of(k): return tuple(CROPS.get(k) or CROPS.get(re.sub(r"(\d+|E)$", "", k)) or (0, 0, 768, 480))
    def limg(k):
        if k not in _lap_img: _lap_img[k] = Image.open(os.path.join(LDIR, k + ".png")).convert("RGB")
        return _lap_img[k]
    SLOTS = [(4, 110), (355, 110), (706, 110), (180, 404), (530, 404)]
    CW_, CH_ = 330, 262
    for i, (seg, disp, _) in enumerate(lines):
        if not _lap_seg[i]: continue
        cfg = _sc[seg]["laptop"]; t0 = float(_seg_t0[i])
        wt_ = word_times(disp, wtimes[i], len(audio[i]) / SR); dw = [re.sub(r"[^a-z]", "", w.lower()) for w in disp.split()]
        if cfg.get("sheet"): _sheets.append((t0, cfg["sheet"], bool(cfg.get("drift"))))
        for cd in cfg.get("cards", []):
            word, key, label, sub = cd[:4]; cellkey = cd[4] if len(cd) > 4 else None
            k = next((j for j, w in enumerate(dw) if w.startswith(word)), None)
            tw = t0 + (max(0.0, wt_[k] - 0.05) if k is not None else 0.0)
            _cards.append(dict(fly=tw, key=key, label=label, sub=sub, slot=len(_cards), cell=word, cellkey=cellkey))
    # every lookup appears up front (the whole to-do list, hovering over the laptop), then each one
    # flies down into its cell as she names it
    t_first = float(_seg_t0[next(i for i in range(len(lines)) if _lap_seg[i])])
    for ci, c in enumerate(_cards):
        c["t"] = t_first + 0.7 + 0.22 * ci; c["fly"] = max(c["fly"], c["t"] + 0.6); c["land"] = c["fly"] + 0.65
        cellk = c["cellkey"] or {"taxes": "tax", "hoa": "hoa", "rent": "rent", "comps": "comps", "insurance": "ins"}.get(c["cell"], c["key"] or "hoa")
        cx_, cy_ = CELLS[cellk]; x0_, y0_, x1_, y1_ = crop_of(SHEET + "0")
        c["tx"], c["ty"] = LX + (cx_ - x0_) * LSW / (x1_ - x0_), LY + (cy_ - y0_) * LSH / (y1_ - y0_)
        # the card itself
        card = Image.new("RGBA", (CW_ + 40, CH_ + 40), (0, 0, 0, 0))
        sh_ = Image.new("RGBA", card.size, (0, 0, 0, 0)); ImageDraw.Draw(sh_).rounded_rectangle([20, 28, CW_ + 20, CH_ + 26], radius=22, fill=(10, 30, 18, 90))
        card.alpha_composite(sh_.filter(ImageFilter.GaussianBlur(12)))
        card.alpha_composite(rounded_box(CW_, CH_, (255, 255, 255), 22), (20, 20))
        if c["key"]:
            th = limg(c["key"]).crop({"ins": (430, 100, 1110, 430), "tax": (20, 100, 700, 430), "rent": (20, 95, 700, 425),
                                      "comps": (20, 95, 700, 425)}.get(c["key"], (0, 0, 780, 486))).resize((CW_ - 24, 160), Image.LANCZOS)
            m = Image.new("L", th.size, 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, th.width - 1, th.height - 1], radius=12, fill=255)
            card.paste(th, (32, 32), m)
        else:
            ImageDraw.Draw(card).rounded_rectangle([32, 32, 32 + CW_ - 24, 192], radius=12, fill=(244, 240, 230))
            q = text_layer("?  ?  ?", F_NUM, 64, (201, 168, 76)); card.alpha_composite(q, (20 + (CW_ - q.width) // 2, 112 - q.height // 2))
        lab = text_layer(c["label"], F_HEAD, 34, INK, tracking=-0.01); card.alpha_composite(lab, (36, 202))
        sb = text_layer(c["sub"], F_SEMI, 22, (170, 70, 60)); card.alpha_composite(sb, (37, 244))
        c["img"] = card
    lid = Image.new("RGBA", (LSW + 44, LSH + 52), (0, 0, 0, 0))
    ImageDraw.Draw(lid).rounded_rectangle([0, 0, lid.width - 1, lid.height - 1], radius=30, fill=(24, 28, 26, 255))
    ImageDraw.Draw(lid).ellipse([lid.width // 2 - 5, 9, lid.width // 2 + 5, 19], fill=(60, 66, 63, 255))
    deck = Image.new("RGBA", (W - 20, 46), (0, 0, 0, 0)); dd = ImageDraw.Draw(deck)
    dd.rounded_rectangle([0, 0, deck.width - 1, 30], radius=12, fill=(196, 201, 205, 255))
    dd.rounded_rectangle([0, 18, deck.width - 1, 45], radius=16, fill=(160, 166, 171, 255))
    dd.rounded_rectangle([deck.width // 2 - 90, 0, deck.width // 2 + 90, 12], radius=6, fill=(170, 176, 181, 255))
    lshadow = Image.new("RGBA", (W + 200, LSH + 300), (0, 0, 0, 0))
    ImageDraw.Draw(lshadow).rounded_rectangle([140, 120, W + 60, LSH + 190], radius=40, fill=(10, 30, 18, 60))
    lshadow = lshadow.filter(ImageFilter.GaussianBlur(40))
    # brand reveal assets
    GREEN_BG = Image.new("RGBA", (W, H)); gd = ImageDraw.Draw(GREEN_BG)
    for y in range(H):
        k = y / H; gd.line([(0, y), (W, y)], fill=(int(14 + 12 * (1 - k)), int(70 - 24 * k), int(42 - 12 * k), 255))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ImageDraw.Draw(glow).ellipse([W // 2 - 520, 380, W // 2 + 520, 1380], fill=(201, 168, 76, 120))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    BIG_LOGO = logo_layer(640, white=True)
    TAG = text_layer("Every number. In seconds.", F_HEAD, 54, (232, 197, 92), tracking=-0.01)
def laptop_frame(f, t):
    """laptop + spreadsheet; lookup cards pop in above it as they're named and fly into their cells."""
    out = max(0.0, min(1.0, (t - (LAP_END - 0.35)) / 0.45))          # exit as the brand takes over
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    lay.alpha_composite(lshadow, (-100, LY - 140))
    lay.alpha_composite(lid, (LX - 22, LY - 26))
    sh_now = [x for x in _sheets if x[0] <= t]
    landed = sum(1 for c in _cards if c["land"] <= t)
    key, drift, t_s = (SHEET + "%d" % landed, False, 0.0)
    if sh_now and sh_now[-1][1].endswith("E"): key, drift, t_s = sh_now[-1][1], sh_now[-1][2], sh_now[-1][0]
    dy = min(300.0, 170.0 * max(0.0, t - t_s - 0.3)) if drift else 0.0
    x0_, y0_, x1_, y1_ = crop_of(key)
    scr = limg(key).crop((x0_, y0_ + int(dy), x1_, y1_ + int(dy))).resize((LSW, LSH), Image.LANCZOS)
    lay.paste(scr, (LX, LY))
    lay.alpha_composite(deck, (10, LY + LSH + 26))
    d = ImageDraw.Draw(lay)
    for c in _cards:                                   # gold flash on the cell a card just landed in
        if c["land"] <= t < c["land"] + 0.5:
            a = int(255 * (1 - (t - c["land"]) / 0.5))
            d.rounded_rectangle([c["tx"] - 230, c["ty"] - 26, c["tx"] + 190, c["ty"] + 26], radius=10, outline=(201, 168, 76, a), width=6)
    for c in _cards:
        if t < c["t"] or t >= c["land"]: continue
        sx, sy = SLOTS[c["slot"] % len(SLOTS)]
        if t < c["fly"]:
            k = ease_back((t - c["t"]) / 0.4); sc_ = 0.6 + 0.4 * k; x, y = sx, sy + 8 * math.sin((t - c["t"]) * 3.0); al = min(1.0, (t - c["t"]) / 0.2)
        else:
            k = ease_io((t - c["fly"]) / 0.6); sc_ = 1 - 0.88 * k; al = 1 - 0.5 * k
            x = sx + (c["tx"] - (sx + CW_ / 2 + 20)) * k; y = sy + (c["ty"] - (sy + CH_ / 2 + 20)) * k
        im = c["img"]
        if abs(sc_ - 1) > 0.01: im = im.resize((max(1, int(im.width * sc_)), max(1, int(im.height * sc_))), Image.BILINEAR)
        if al < 1: im = im.copy(); im.putalpha(im.getchannel("A").point(lambda v: int(v * al)))
        lay.alpha_composite(im, (int(x + (c["img"].width - im.width) / 2), int(y + (c["img"].height - im.height) / 2)))
    mins = int(64 * ease_out(min(1.0, t / max(LAP_END, 0.1))))
    txt = f"{mins // 60}:{mins % 60:02d} hrs" if mins >= 60 else f"{mins} min"
    chip = text_layer("Time spent  " + txt, F_HEAD, 46, (180, 40, 40)); cw_ = chip.width + 60
    cy0 = LY + LSH + 100
    lay.alpha_composite(rounded_box(cw_, 84, (255, 236, 233), 42), ((W - cw_) // 2, cy0))
    lay.alpha_composite(chip, ((W - chip.width) // 2, cy0 + 42 - chip.height // 2))
    if out > 0: lay.putalpha(lay.getchannel("A").point(lambda v: int(v * (1 - out))))
    f.alpha_composite(lay, (0, int(-40 * out)))
def brand_alpha(t):
    if not HERO: return 0.0
    a = (t - (REVEAL_T - 0.2)) / 0.45
    b = 1 - (t - (PHONE_T0 + (2.0 if PHONE_T0 == REVEAL_T else 0.6))) / 0.6
    return max(0.0, min(1.0, a, b))
def brand_frame(f, t):
    """deep green, gold glow, the logo sweeps in, then the phone arrives like it owns the place."""
    g = brand_alpha(t)
    if g <= 0: return
    lay = GREEN_BG.copy()
    gl = max(0.0, min(1.0, (t - REVEAL_T - 0.6) / 0.6))
    if gl > 0:
        gg = glow.copy(); gg.putalpha(gg.getchannel("A").point(lambda v: int(v * gl))); lay.alpha_composite(gg)
    k = (t - REVEAL_T - 0.05) / 0.5; ko = 1 - max(0.0, min(1.0, (t - REVEAL_T - 1.05) / 0.4))
    if k > 0 and ko > 0:
        sc_ = 0.86 + 0.14 * ease_back(k, 1.2); lg = BIG_LOGO.resize((int(BIG_LOGO.width * sc_), int(BIG_LOGO.height * sc_)), Image.LANCZOS)
        al = min(1.0, k * 1.6) * ko
        # light sweep across the logo
        sw_ = (t - REVEAL_T - 0.35) / 0.6
        if 0 < sw_ < 1:
            band = Image.new("L", lg.size, 0); bd = ImageDraw.Draw(band); bx = int(-200 + (lg.width + 400) * sw_)
            bd.polygon([(bx, 0), (bx + 90, 0), (bx - 40, lg.height), (bx - 130, lg.height)], fill=170)
            band = band.filter(ImageFilter.GaussianBlur(14))
            hi = Image.new("RGBA", lg.size, (255, 244, 210, 0)); hi.putalpha(Image.fromarray(np.minimum(np.asarray(band), np.asarray(lg.getchannel("A")))))
            lg = lg.copy(); lg.alpha_composite(hi)
        lg.putalpha(lg.getchannel("A").point(lambda v: int(v * al)))
        lay.alpha_composite(lg, ((W - lg.width) // 2, 760 - lg.height // 2 - int(40 * (1 - ko))))
        ta = max(0.0, min(1.0, (t - REVEAL_T - 0.45) / 0.35)) * ko
        if ta > 0:
            tg = TAG.copy(); tg.putalpha(tg.getchannel("A").point(lambda v: int(v * ta)))
            lay.alpha_composite(tg, ((W - TAG.width) // 2, 760 + lg.height // 2 + 40))
    if g < 1: lay.putalpha(lay.getchannel("A").point(lambda v: int(v * g)))
    f.alpha_composite(lay)
# ---- chat scenes: two phones, a link sent from one and received on the other
_chats = []
for i, (seg, disp, _) in enumerate(lines):
    if not _chat_seg[i]: continue
    cs, ce = float(_seg_t0[i]), float(_seg_t0[i]) + seg_len[i]
    _chats.append(dict(cfg=_sc[seg]["chat"], s=cs + (1.15 if abs(cs - REVEAL_T) < 1e-6 and HERO else 0.15), e=ce))
if _chats:
    MPW, MPH = 450, 900
    def mini_phone(title):
        ph = Image.new("RGBA", (MPW, MPH), (0, 0, 0, 0)); d_ = ImageDraw.Draw(ph)
        d_.rounded_rectangle([0, 0, MPW - 1, MPH - 1], radius=64, fill=(16, 22, 19, 255))
        d_.rounded_rectangle([14, 14, MPW - 15, MPH - 15], radius=52, fill=(255, 255, 255, 255))
        d_.rounded_rectangle([MPW // 2 - 56, 30, MPW // 2 + 56, 58], radius=14, fill=(10, 12, 11, 255))
        d_.rectangle([14, 84, MPW - 15, 150], fill=(247, 247, 248, 255)); d_.line([14, 150, MPW - 15, 150], fill=(225, 225, 228, 255), width=2)
        tl = text_layer(title, F_SEMI, 26, (40, 40, 40)); ph.alpha_composite(tl, ((MPW - tl.width) // 2, 117 - tl.height // 2))
        return ph
    def bubble(text, out):
        ls = wrap(text, F_SEMI, 28, 300); lays = [text_layer(l, F_SEMI, 28, (255, 255, 255) if out else (20, 20, 20)) for l in ls]
        w_ = max(l.width for l in lays) + 44; h_ = sum(l.height for l in lays) + 8 * (len(lays) - 1) + 32
        b_ = rounded_box(w_, h_, (39, 165, 82) if out else (233, 233, 235), 26); y_ = 16
        for l in lays: b_.alpha_composite(l, (22, y_)); y_ += l.height + 8
        return b_
    def link_card(title, sub):
        c_ = Image.new("RGBA", (340, 210), (0, 0, 0, 0)); d_ = ImageDraw.Draw(c_)
        d_.rounded_rectangle([0, 0, 339, 209], radius=22, fill=(240, 241, 243, 255))
        top = Image.new("RGBA", (340, 118)); td = ImageDraw.Draw(top)
        for y in range(118): td.line([(0, y), (340, y)], fill=(26 + y // 8, 92 + y // 5, 53 + y // 8, 255))
        lg = logo_layer(200, white=True); top.alpha_composite(lg, ((340 - lg.width) // 2, 59 - lg.height // 2))
        m_ = Image.new("L", (340, 118), 0); ImageDraw.Draw(m_).rounded_rectangle([0, 0, 339, 140], radius=22, fill=255)
        c_.paste(top, (0, 0), m_)
        t1 = text_layer(title, F_HEAD, 25, INK); c_.alpha_composite(t1, (18, 132))
        t2 = text_layer(sub, F_SEMI, 21, (110, 120, 116)); c_.alpha_composite(t2, (18, 170))
        return c_
    for ch in _chats:
        c = ch["cfg"]
        ch["L"] = mini_phone(c.get("to_title", "To: Alex (partner)")); ch["R"] = mini_phone(c.get("from_title", "Jason"))
        ch["b_out"] = bubble(c["msg"], True); ch["b_in"] = bubble(c["msg"], False)
        ch["card"] = link_card(c["title"], c["sub"])
        nb = rounded_box(410, 104, (248, 248, 250), 26); nt = text_layer(c.get("from_name", "Jason"), F_HEAD, 24, INK); nb.alpha_composite(nt, (22, 16))
        nm = text_layer(c["msg"][:34], F_SEMI, 22, (90, 90, 95)); nb.alpha_composite(nm, (22, 56)); ch["notif"] = nb
LPX, RPX, CPY = 70, 560, 520
def chat_frame(f, t):
    for ch in _chats:
        if not (ch["s"] - 0.1 <= t < ch["e"]): continue
        k = t - ch["s"]
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        rise = int(1300 * (1 - ease_back(k / 0.65, 1.0)))
        for ph, px in ((ch["L"], LPX), (ch["R"], RPX)):
            lay.alpha_composite(ph, (px, CPY + rise))
        def pop(im, x, y, t_on):                            # scale-in pop
            q = (t - t_on) / 0.3
            if q <= 0: return
            sc_ = 0.7 + 0.3 * ease_back(q, 1.4)
            im2 = im.resize((max(1, int(im.width * sc_)), max(1, int(im.height * sc_))), Image.BILINEAR)
            lay.alpha_composite(im2, (int(x + (im.width - im2.width) / 2), int(y + (im.height - im2.height) / 2 + rise)))
        bo = ch["b_out"]; pop(bo, LPX + MPW - 30 - bo.width, CPY + 190, ch["s"] + 0.55)
        cx_l, cy_l = LPX + MPW - 30 - 340, CPY + 210 + bo.height
        pop(ch["card"], cx_l, cy_l, ch["s"] + 0.85)
        bi = ch["b_in"]; cx_r, cy_r = RPX + 30, CPY + 210 + bi.height
        # the link flies across
        q = (t - ch["s"] - 1.35) / 0.6
        if 0 < q < 1:
            e_ = ease_io(q); x = cx_l + (cx_r - cx_l) * e_; y = cy_l + (cy_r - cy_l) * e_ - 260 * math.sin(math.pi * e_)
            sc_ = 1 - 0.25 * math.sin(math.pi * e_); im2 = ch["card"].resize((int(340 * sc_), int(210 * sc_)), Image.BILINEAR)
            lay.alpha_composite(im2, (int(x + (340 - im2.width) / 2), int(y + (210 - im2.height) / 2)))
        pop(bi, RPX + 30, CPY + 190, ch["s"] + 1.9); pop(ch["card"], cx_r, cy_r, ch["s"] + 1.95)
        nq = t - ch["s"] - 1.8                              # notification banner drops in, then lifts away
        if 0 < nq < 1.2:
            yy = CPY + 70 + int(-130 * (1 - ease_out(nq / 0.3))) - int(130 * max(0.0, (nq - 0.9) / 0.3))
            lay.alpha_composite(ch["notif"], (RPX + 20, yy + rise))
        tq = t - ch["s"] - 2.7                              # tap
        if 0 < tq < 0.8:
            d_ = ImageDraw.Draw(lay); cx, cy = cx_r + 170, cy_r + 90 + rise
            for rr, aa in ((30 + 90 * tq, int(220 * (1 - tq / 0.8))), (14, 200)):
                d_.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=(201, 168, 76, aa), width=6)
        out = max(0.0, (t - (ch["e"] - 0.35)) / 0.35)
        if out > 0: lay.putalpha(lay.getchannel("A").point(lambda v: int(v * (1 - out))))
        f.alpha_composite(lay)
def phone_dy(t):                         # the phone arrives: from below, a confident overshoot, then settles
    t0 = PHONE_T0 + (1.0 if HERO and PHONE_T0 == REVEAL_T else 0.0)
    if t < t0: return 99999
    if HERO: return int(1500 * (1 - ease_back((t - t0) / 0.85, 1.1)))
    return int(760 * (1 - ease_out((t - t0) / 0.95)))
cap_cache = {}
def caption(text, white=False):
    if (text, white) not in cap_cache:
        ls = wrap(text, F_HEAD, 64, 940)
        layers = [text_layer(l, F_HEAD, 64, (255, 255, 255) if white else INK, tracking=-0.015) for l in ls]
        hh = sum(l.height for l in layers) + 10 * (len(layers) - 1)
        im = Image.new("RGBA", (W, hh), (0, 0, 0, 0)); y = 0
        for l in layers:
            im.alpha_composite(l, ((W - l.width) // 2, y)); y += l.height + 10
        cap_cache[(text, white)] = im
    return cap_cache[(text, white)]

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
    _ht = word_times(hook_txt, wtimes[0], len(audio[0]) / SR) if audio else [0.15] * len(words)
    k = 0
    for ri, row in enumerate(rows_):
        lays = [text_layer(w_, F_HEAD, HS, INK, tracking=-0.015) for w_ in row]
        x = (W - (sum(l.width for l in lays) + space * (len(lays) - 1))) // 2
        for l in lays:
            _hw.append((l, x, top + ri * lh, max(0.0, _ht[k] - CAP_LEAD))); x += l.width + space; k += 1
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
    x, y, w, h = r                        # the gold ring's rect: it must stay fully in shot
    M = 18                                # breathing room around the ring, in CSS px
    fit = min(VW / (w + 2 * M), VH / (h + 2 * M))
    if w < 0.6 * VW:                      # a small label/button: gentle push only
        z = min(1.1, 0.80 * VH / max(h, 1), fit)
    else:
        z = min(1.5, 0.96 * VW / max(w, 1), 0.80 * VH / max(h, 1), fit)
    z = max(1.0, z)
    if z < 1.06: zplan.append(None); continue
    zplan.append((t0, dur, z, (x + w / 2) / VW, (y + h / 2) / VH, (x - M, y - M, x + w + M, y + h + M)))
def zoom_at(t):
    for zp in zplan:
        if zp and zp[0] <= t < zp[0] + zp[1]:
            t0, dur, z, cx, cy, box = zp
            k = min(1.0, (t - t0) / 0.7, (t0 + dur - t) / 0.45)
            k = max(0.0, k); k = k * k * (3 - 2 * k)
            return 1 + (z - 1) * k, cx, cy, box
    return 1.0, 0.5, 0.5, None
for i in range(n_main):
    buf = dec.stdout.read(fsz)
    if len(buf) == fsz:
        src_im = Image.frombytes("RGB", (sw, sh), buf)
        z, cx, cy, box = zoom_at(i / FPS)
        if z > 1.001:
            cw, ch = sw / z, sh / z
            x0, y0 = cx * sw - cw / 2, cy * sh - ch / 2
            if box:                                       # slide the crop so the ring is never cut
                bx0, by0, bx1, by1 = (box[0] * sw / VW, box[1] * sh / VH, box[2] * sw / VW, box[3] * sh / VH)
                x0 = min(max(x0, bx1 - cw), bx0); y0 = min(max(y0, by1 - ch), by0)
            x0 = min(max(x0, 0), sw - cw); y0 = min(max(y0, 0), sh - ch)
            src_im = src_im.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch)))
        last = src_im.resize((SCR_W, SCR_H), Image.LANCZOS)
    t = i / FPS
    f = base.copy()
    dy = phone_dy(t)
    if t < LAP_END: laptop_frame(f, t)
    if HERO: brand_frame(f, t)
    if _chats: chat_frame(f, t)
    if dy < H:
        f.alpha_composite(shadow, (PX - 80, PY - 80 + dy))
        f.alpha_composite(phone, (PX, PY + dy))
        if last is not None and dy + PY + bez < H:
            f.paste(screen_with_insets(last), (PX + bez, PY + bez + dy), mask)
    cur = next((c for c in reversed(caps) if c[0] <= t < c[1] + 0.12), None)   # newest chunk wins the hand-over
    if t < hook_end:
        f.alpha_composite(hook_frame(t), (0, 0)); cur = None
    if cur:
        cl = caption(cur[2], white=brand_alpha(t) > 0.5)
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
