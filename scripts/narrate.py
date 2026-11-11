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
from reelkit import (W, H, FPS, BG, INK, MUTED, GREEN, F_HEAD, F_SEMI, logo_layer, text_layer, wrap,
                     render_end_beat, place, rounded)

work, out_mp4 = sys.argv[1], sys.argv[2]
out_dir = os.path.dirname(os.path.abspath(out_mp4))
rk.init(work)
data = json.load(open(os.path.join(work, "data.json")))
mk = json.load(open(os.path.join(work, "markers.json")))
SR = 24000
VOICE = os.environ.get("VOICE") or "af_heart"
SPEED = float(os.environ.get("VOICE_SPEED") or 1.05)
MAX_LEN = 39.5

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
lines.append(("end", "Every number, in seconds. Try it free at dealcaddie.ai.",
              "Every number. In seconds. Try it free at Deal Caddie dot [A.I.](/ˌAˈI/)"))

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
TOP_IN, BOT_IN = 64, 46
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
base.alpha_composite(shadow, (PX - 80, PY - 80))
base.alpha_composite(phone, (PX, PY))
place(base, LOGO, W // 2, 62)
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
for i in range(n_main):
    buf = dec.stdout.read(fsz)
    if len(buf) == fsz:
        last = Image.frombytes("RGB", (sw, sh), buf).resize((SCR_W, SCR_H), Image.LANCZOS)
    t = i / FPS
    f = base.copy()
    if last is not None:
        f.paste(screen_with_insets(last), (PX + bez, PY + bez), mask)
    cur = next((c for c in caps if c[0] <= t < c[1] + 0.12), None)
    if cur:
        cl = caption(cur[2])
        f.alpha_composite(cl, (0, 1752 - cl.height // 2))
    fr = f.convert("RGB")
    if not cover_saved and t >= 0.4:
        fr.save(os.path.join(out_dir, "cover.jpg"), quality=92); cover_saved = True
    enc.stdin.write(fr.tobytes())
dec.stdout.close()
for i in range(n_end):
    enc.stdin.write(end_fn(i / FPS).tobytes())
enc.stdin.close(); enc.wait()

# ------------------------------------------------------------------ audio: voice + quiet music bed
total = (n_main + n_end) / FPS
voice = np.zeros(int(total * SR) + SR, np.float32)
for t0, a in zip(starts, audio):
    s = int(t0 * SR); voice[s:s + len(a)] += a[: max(0, len(voice) - s)]
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
track = os.environ.get("MUSIC_TRACK") or tracks[(datetime.date.today().toordinal() * 5) % len(tracks)].rsplit(".", 1)[0]
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
open(os.path.join(out_dir, "caption.txt"), "w").write(
    f"""{hook}

{' '.join(d for s, d, _ in lines if s != 'end')}

Paste any Zillow link → rent, taxes, insurance, 7 strategies and a rehab estimate in about 10 seconds.

Try it free · dealcaddie.ai

#realestateinvesting #rentalproperty #cashflow #realestateinvestor #{re.sub(r'[^a-z]', '', city.lower())}realestate
""")
json.dump({"hook": hook, "duration": total, "voice": VOICE, "speed": SPEED, "track": track},
          open(os.path.join(out_dir, "meta.json"), "w"), indent=2)
