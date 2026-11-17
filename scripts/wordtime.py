"""Kokoro speech with per-word timings, so captions can pop each word as it's spoken.

Script markup (in a "voice" string):
  *word*                     accent colour on screen
  {spoken words|Shown}       say one thing, show another: {three hundred thousand|$300K}
Everything else is said and shown as written.

speak_timed(voice) -> (samples float32 @24k, units)
  units = [{"show": "$300K", "accent": False, "t0": 1.23, "t1": 1.71}, ...]  (seconds from clip start)

Timing source:
  1. kokoro (pip) KPipeline: real per-token timestamps from the duration model, when available.
  2. kokoro-onnx: estimate. Words are weighted by phoneme count, punctuation boundaries are
     snapped to the real pauses found in the audio, and the words between pauses are spread by weight.
     In practice this lands within about a tenth of a second.
"""
import os, re
import numpy as np

SR = 24000
VOICE = os.environ.get("VOICE") or "af_heart"
SPEED = float(os.environ.get("VOICE_SPEED") or 1.05)
_onnx = _pipe = _tok = None

# phrases the TTS mangles -> how to say them (shown unchanged). Applied to plain words only, so
# an explicit {spoken|Shown} group always wins.
SAY = [(r"(?i)\bairbnb", "Air-bee-en-bee"),
       (r"\b(?:St\.?|Saint) Louis\b", "{Saint Lewis|\\g<0>}")]

def parse(voice):
    """-> spoken text, units [(spoken_words[], show, accent)]"""
    units = []
    for pat, rep in SAY:
        if rep.startswith("{"):
            voice = re.sub(r"(\{[^}]*\})|(" + pat + ")", lambda m: m.group(1) or m.expand(rep.replace("\\g<0>", "\\g<2>")), voice)
    for m in re.finditer(r"\{([^|}]*)\|([^}]*)\}|(\S+)", voice):
        if m.group(3) is None:
            spoken, show = m.group(1).split(), m.group(2)
        else:
            show = m.group(3); spoken = [show]
        acc = "*" in show
        show = show.replace("*", ""); spoken = [w.replace("*", "") for w in spoken]
        for pat, rep in SAY:
            if not rep.startswith("{"): spoken = [re.sub(pat, rep, w) for w in spoken]
        if units and not re.search(r"\w", show):          # bare punctuation after a {..|..} group
            ps, pshow, pacc = units[-1]; units[-1] = (ps[:-1] + [ps[-1] + show] if ps else ps, pshow + show, pacc); continue
        units.append((spoken, show, acc))
    text = " ".join(" ".join(s) for s, _, _ in units if s)
    return text, units

def _core(w):
    return re.sub(r"[^\w']", "", w.lower())

def _real_timestamps(text):
    """kokoro pip: [(word, t0, t1)] or None."""
    global _pipe
    try:
        if _pipe is None:
            from kokoro import KPipeline
            _pipe = KPipeline(lang_code="a")
    except Exception:
        return None
    audio, words, off = [], [], 0.0
    for r in _pipe(text, voice=VOICE, speed=SPEED):
        a = np.asarray(r.audio.numpy() if hasattr(r.audio, "numpy") else r.audio, np.float32)
        for tk in (r.tokens or []):
            if _core(tk.text) and tk.start_ts is not None:
                words.append((tk.text, off + tk.start_ts, off + (tk.end_ts or tk.start_ts)))
        audio.append(a); off += len(a) / SR
    return np.concatenate(audio), words

def _estimate(text, a):
    global _tok
    if _tok is None:
        from kokoro_onnx.tokenizer import Tokenizer
        _tok = Tokenizer()
    words = text.split()
    wt = []
    for w in words:
        c = _core(w)
        try: n = len(_tok.phonemize(c)) if c else 0
        except Exception: n = len(c)
        wt.append(max(1.0, n) + 1.0)
    # speech envelope, 10 ms frames
    hop = SR // 100; fr = len(a) // hop
    rms = np.sqrt(np.mean(a[:fr * hop].reshape(fr, hop) ** 2, axis=1)) if fr else np.zeros(1)
    th = max(rms.max() * 0.06, 1e-4); voiced = rms > th
    on = np.flatnonzero(voiced)
    s0, s1 = (on[0], on[-1] + 1) if len(on) else (0, fr)
    # pauses: silent runs >= 60 ms inside speech
    pauses, i = [], s0
    while i < s1:
        if not voiced[i]:
            j = i
            while j < s1 and not voiced[j]: j += 1
            if j - i >= 6: pauses.append((i / 100, j / 100))
            i = j
        else: i += 1
    t_start, t_end = s0 / 100, s1 / 100
    # expected boundary (after word k) for punctuation, estimated by weight, then snapped to a pause
    total = sum(wt); cum = np.cumsum(wt)
    speech = (t_end - t_start) - sum(b - a_ for a_, b in pauses)
    anchors = [(0, t_start)]                       # (word index that starts here, time)
    used = set()
    for k, w in enumerate(words[:-1]):
        if not re.search(r"[,.;:!?]$", w): continue
        guess = t_start + speech * cum[k] / total + sum(b - a_ for a_, b in pauses if b <= t_start + speech * cum[k] / total)
        best = None
        for pi, (pa, pb) in enumerate(pauses):
            if pi in used: continue
            d = abs((pa + pb) / 2 - guess)
            if d < 0.45 and (best is None or d < best[0]): best = (d, pi)
        if best:
            used.add(best[1]); anchors.append((k + 1, pauses[best[1]][1]))
            anchors.append((-(k + 1), pauses[best[1]][0]))       # negative = segment end before pause
    # build segments [start_word, end_word) with [ts, te]
    starts = sorted([x for x in anchors if x[0] >= 0])
    ends = {-k: t for k, t in anchors if k < 0}
    out = [None] * len(words)
    for si, (w0, ts) in enumerate(starts):
        w1 = starts[si + 1][0] if si + 1 < len(starts) else len(words)
        te = ends.get(w1, t_end) if si + 1 < len(starts) else t_end
        seg = wt[w0:w1]; tot = sum(seg) or 1; t = ts
        for k in range(w0, w1):
            d = (te - ts) * wt[k] / tot; out[k] = (words[k], t, t + d); t += d
    return out

def speak_timed(voice):
    text, units = parse(voice)
    real = None if os.environ.get("KOKORO_ONNX_DIR") else _real_timestamps(text)
    if real:
        a, words = real
    else:
        global _onnx
        if _onnx is None:
            from kokoro_onnx import Kokoro
            d = os.environ["KOKORO_ONNX_DIR"]
            _onnx = Kokoro(os.path.join(d, "kokoro-v1.0.onnx"), os.path.join(d, "voices-v1.0.bin"))
        a, _ = _onnx.create(text, voice=VOICE, speed=SPEED, lang="en-us")
        a = np.asarray(a, np.float32); words = _estimate(text, a)
    # walk spoken words in order and give each display unit the span of its words
    wi, res = 0, []
    cores = [_core(w) for w, _, _ in words]
    for spoken, show, acc in units:
        span = []
        for sw in spoken:
            c = _core(sw)
            if not c: continue
            j = wi
            while j < len(cores) and cores[j] != c and j < wi + 3: j += 1   # tolerate tokenizer splits
            if j < len(cores) and cores[j] == c: wi = j
            if wi < len(words): span.append(words[wi]); wi += 1
        if span: res.append({"show": show, "accent": acc, "t0": span[0][1], "t1": span[-1][2]})
        else: res.append({"show": show, "accent": acc, "t0": res[-1]["t1"] if res else 0.0, "t1": res[-1]["t1"] if res else 0.0})
    return a, res
