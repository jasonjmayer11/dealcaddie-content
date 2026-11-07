#!/usr/bin/env python3
"""Compose DealCaddie's original background tracks (and three sound effects) in code.

Nothing here is sampled or licensed: every sound is synthesized from sine waves and noise,
so the music belongs to DealCaddie outright and can't trigger copyright claims.

Usage: python3 scripts/make_music.py            -> music/dc-01..15.m4a, assets/sfx/*.wav
Each track is 34 s (longer than any reel). Style: calm, modern "tech product" bed —
soft pads, a warm bass, a light pluck arpeggio, gentle drums — at 92–116 BPM.
"""
import os, subprocess, wave
import numpy as np

SR = 44100
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEN = 34.0
rng_global = np.random.default_rng(7)

def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)

MAJOR = [0, 2, 4, 5, 7, 9, 11]
MINOR = [0, 2, 3, 5, 7, 8, 10]

def chord(root_midi, scale, degree, size=4):
    """Diatonic chord (triad + 7th) on a scale degree, 0-based."""
    notes = []
    for k in range(size):
        d = degree + 2 * k
        notes.append(root_midi + scale[d % 7] + 12 * (d // 7))
    return notes

def env_adsr(n, a, d, s, r, sr=SR):
    a, d, r = int(a * sr), int(d * sr), int(r * sr)
    e = np.full(n, s, dtype=np.float32)
    if a: e[:a] = np.linspace(0, 1, a, dtype=np.float32)
    if d: e[a:a + d] = np.linspace(1, s, min(d, max(0, n - a)), dtype=np.float32)[: max(0, min(d, n - a))]
    if r and n > r: e[-r:] *= np.linspace(1, 0, r, dtype=np.float32)
    return e

def additive(freq, n, harmonics, rolloff, phase=0.0, detune_cents=0.0):
    t = np.arange(n, dtype=np.float32) / SR
    f = freq * 2 ** (detune_cents / 1200)
    out = np.zeros(n, dtype=np.float32)
    for h in range(1, harmonics + 1):
        if f * h > 9000: break
        out += np.sin(2 * np.pi * f * h * t + phase * h) / (h ** rolloff)
    return out

def place(buf, sig, start, gain=1.0, pan=0.0):
    i = int(start * SR)
    if i >= buf.shape[0]: return
    sig = sig[: buf.shape[0] - i]
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[i:i + len(sig), 0] += sig * gain * l
    buf[i:i + len(sig), 1] += sig * gain * r

def smooth(x, k):
    if k <= 1: return x
    c = np.cumsum(np.concatenate([[0.0], x]))
    y = (c[k:] - c[:-k]) / k
    return np.concatenate([y, np.full(k - 1, y[-1])]).astype(np.float32)

def reverb_ir(seconds, seed, damp=3.2):
    r = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    ir = np.stack([r.standard_normal(n), r.standard_normal(n)], 1) * np.exp(-damp * t)[:, None]
    ir[:, 0] = smooth(ir[:, 0], 3); ir[:, 1] = smooth(ir[:, 1], 3)   # darker tail
    return (ir / np.sqrt((ir ** 2).sum(0))).astype(np.float32)

def convolve(x, ir):
    n = len(x) + len(ir) - 1
    N = 1 << (n - 1).bit_length()
    out = np.zeros((len(x), 2), dtype=np.float32)
    for c in range(2):
        y = np.fft.irfft(np.fft.rfft(x[:, c], N) * np.fft.rfft(ir[:, c], N), N)[: len(x)]
        out[:, c] = y
    return out

# ------------------------------------------------------------------ instruments
def pad_note(freq, dur, bright):
    n = int((dur + 0.8) * SR)
    s = sum(additive(freq, n, 14, 1.0 + (1 - bright), detune_cents=d, phase=p)
            for d, p in ((-7, 0.0), (0.0, 1.3), (7, 2.1))) / 3
    return s * env_adsr(n, 0.35, 0.4, 0.75, 0.8)

def pluck(freq, bright):
    n = int(0.9 * SR)
    t = np.arange(n) / SR
    s = additive(freq, n, 6, 1.6 - 0.4 * bright) * np.exp(-t * 7)
    return s * env_adsr(n, 0.004, 0.0, 1.0, 0.05)

def bass_note(freq, dur):
    n = int((dur + 0.08) * SR)
    s = additive(freq, n, 3, 2.0)
    return s * env_adsr(n, 0.01, 0.1, 0.85, 0.08)

def kick():
    n = int(0.45 * SR); t = np.arange(n) / SR
    f = 45 + 75 * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return (np.sin(ph) * np.exp(-t * 7.5) + 0.15 * np.sin(ph * 2) * np.exp(-t * 30)).astype(np.float32)

def clap(seed):
    r = np.random.default_rng(seed); n = int(0.3 * SR); t = np.arange(n) / SR
    no = r.standard_normal(n).astype(np.float32)
    band = smooth(no, 6) - smooth(no, 40)                 # crude band-pass ~1–4 kHz
    e = np.exp(-t * 16) * (1 + 0.6 * np.exp(-((t - 0.012) ** 2) / 1e-5))
    return band * e * 1.6

def hat(seed, open_=False):
    r = np.random.default_rng(seed); n = int((0.18 if open_ else 0.06) * SR); t = np.arange(n) / SR
    no = r.standard_normal(n).astype(np.float32)
    hp = no - smooth(no, 3)
    return hp * np.exp(-t * (18 if open_ else 70)) * 0.5

def delay(x, seconds, feedback, taps=4):
    out = x.copy(); d = int(seconds * SR)
    for k in range(1, taps + 1):
        g = feedback ** k
        sh = np.zeros_like(x)
        sh[d * k:] = x[: len(x) - d * k] * g
        if k % 2: sh = sh[:, ::-1]                        # ping-pong
        out += sh
    return out

# ------------------------------------------------------------------ one track
def compose(preset, seed):
    bpm, root, mode, prog, bright, arp, hats16, swing = preset
    scale = MAJOR if mode == "maj" else MINOR
    beat = 60.0 / bpm; bar = 4 * beat
    n = int(LEN * SR)
    pad = np.zeros((n, 2), np.float32); keys = np.zeros((n, 2), np.float32)
    bass = np.zeros((n, 2), np.float32); drums = np.zeros((n, 2), np.float32)
    duck = np.ones(n, np.float32)
    K, H, HO = kick(), [hat(seed + i) for i in range(4)], hat(seed + 9, True)
    CL = [clap(seed + 20 + i) for i in range(3)]
    bars = int(LEN / bar) + 1
    for b in range(bars):
        t0 = b * bar
        deg = prog[b % len(prog)]
        ch = chord(root, scale, deg)
        # pads: whole bar, voiced around middle C
        for i, m in enumerate(ch):
            place(pad, pad_note(midi_hz(m), bar, bright), t0, 0.11, pan=(-0.35, 0.35, -0.15, 0.15)[i])
        # bass: root on 1 and the "and" of 2, fifth on 3 in later bars
        r = ch[0] - 24
        place(bass, bass_note(midi_hz(r), beat * 1.4), t0, 0.42)
        place(bass, bass_note(midi_hz(r), beat * 0.5), t0 + beat * 1.5, 0.30)
        place(bass, bass_note(midi_hz(r + (7 if b % 2 else 0)), beat * 1.4), t0 + 2 * beat, 0.38)
        # arpeggio from bar 2
        if arp and b >= 1:
            pattern = [0, 1, 2, 3, 2, 1, 2, 3] if arp == 1 else [0, 2, 1, 3, 0, 2, 3, 1]
            for k, idx in enumerate(pattern):
                place(keys, pluck(midi_hz(ch[idx] + 12), bright), t0 + k * beat / 2, 0.16, pan=0.25 if k % 2 else -0.25)
        # drums from bar 2 (bar 1 is the intro under the hook)
        if b >= 1:
            for q in range(4):
                if q in (0, 2) or (q == 3 and b % 4 == 3):
                    place(drums, K, t0 + q * beat, 0.65)
                    i = int((t0 + q * beat) * SR)
                    L = min(int(0.32 * SR), n - i)
                    if L > 0:
                        duck[i:i + L] = np.minimum(duck[i:i + L], 1 - 0.45 * np.exp(-np.arange(L) / SR * 9))
                if q in (1, 3):
                    place(drums, CL[(b + q) % 3], t0 + q * beat, 0.22, pan=0.05)
            steps = 16 if hats16 else 8
            for k in range(steps):
                st = t0 + k * bar / steps + (swing * bar / steps if k % 2 else 0)
                vel = 0.10 if k % 2 else 0.16
                if hats16 and k % 4 == 2: vel = 0.13
                place(drums, H[k % 4], st, vel, pan=0.3)
            if b % 2 == 1:
                place(drums, HO, t0 + 3.5 * beat, 0.07, pan=-0.3)
    ir = reverb_ir(2.2, seed)
    pad = pad * duck[:, None]; bass = bass * (0.55 + 0.45 * duck[:, None])
    wet = convolve(pad * 0.6 + keys * 0.8 + drums * 0.15, ir)
    keys = delay(keys, beat * 0.75, 0.32)
    mix = pad + keys * 0.9 + bass + drums + wet * 0.35
    mix = np.tanh(mix * 1.6) / np.tanh(1.6)                  # gentle glue
    mix *= 0.89 / (np.abs(mix).max() + 1e-9)
    return mix

PRESETS = [  # bpm, root midi, mode, progression (scale degrees), brightness, arp, 16th hats, swing
    (104, 60, "maj", [0, 4, 5, 3], 0.55, 1, False, 0.00),   # C  I–V–vi–IV
    (98,  57, "min", [0, 5, 2, 6], 0.45, 2, False, 0.04),   # Am i–VI–III–VII
    (110, 62, "maj", [3, 0, 4, 5], 0.60, 1, True,  0.00),   # D  IV–I–V–vi
    (96,  55, "maj", [5, 3, 0, 4], 0.40, 2, False, 0.06),   # G  vi–IV–I–V (lo-fi swing)
    (112, 64, "min", [0, 3, 5, 4], 0.55, 1, True,  0.00),   # Em
    (100, 65, "maj", [0, 2, 3, 4], 0.50, 1, False, 0.03),   # F  I–iii–IV–V
    (116, 59, "min", [0, 6, 5, 6], 0.60, 2, True,  0.00),   # Bm
    (94,  58, "maj", [1, 4, 0, 5], 0.40, 2, False, 0.07),   # Bb ii–V–I–vi (jazzy lo-fi)
    (106, 61, "min", [0, 5, 3, 4], 0.50, 1, False, 0.02),   # C#m
    (102, 63, "maj", [0, 5, 1, 4], 0.55, 1, True,  0.00),   # Eb I–vi–ii–V
    (108, 56, "min", [5, 6, 0, 0], 0.50, 2, True,  0.00),   # G#m VI–VII–i
    (92,  60, "maj", [3, 4, 2, 5], 0.35, 1, False, 0.08),   # C  IV–V–iii–vi (soft)
    (114, 62, "min", [0, 2, 5, 4], 0.60, 1, True,  0.00),   # Dm
    (99,  57, "maj", [0, 3, 5, 4], 0.45, 2, False, 0.05),   # A  I–IV–vi–V
    (105, 64, "maj", [5, 4, 3, 4], 0.50, 1, False, 0.02),   # E  vi–V–IV–V
]

def write_wav(path, x):
    x16 = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2 if x.ndim == 2 else 1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(x16.tobytes())

def sfx():
    out = os.path.join(ROOT, "assets", "sfx"); os.makedirs(out, exist_ok=True)
    r = np.random.default_rng(3)
    # whoosh: noise swept from dark to bright and back, 0.5 s
    n = int(0.5 * SR); t = np.arange(n) / SR
    no = r.standard_normal(n).astype(np.float32)
    segs = []
    for k in range(25):
        a, b = k * n // 25, (k + 1) * n // 25
        width = int(40 - 34 * np.sin(np.pi * k / 24))
        seg = no[a:b] - smooth(no[a:b], max(2, width))
        segs.append(smooth(seg, 2))
    w = np.concatenate(segs) * np.sin(np.pi * t / t[-1]) ** 2 * 0.5
    write_wav(os.path.join(out, "whoosh.wav"), np.stack([w, w[::-1] * 0.0 + np.roll(w, 300)], 1))
    # landing: soft bell chord for the end card
    n = int(1.8 * SR); t = np.arange(n) / SR
    bell = sum(np.sin(2 * np.pi * midi_hz(m) * t) * g for m, g in ((72, 0.5), (79, 0.3), (84, 0.25), (88, 0.12)))
    bell = (bell * np.exp(-t * 2.6) * env_adsr(n, 0.005, 0, 1, 0.1)).astype(np.float32) * 0.5
    write_wav(os.path.join(out, "landing.wav"), np.stack([bell, bell], 1))
    print("sfx written")

if __name__ == "__main__":
    out = os.path.join(ROOT, "music"); os.makedirs(out, exist_ok=True)
    for i, p in enumerate(PRESETS, 1):
        x = compose(p, seed=100 + i)
        tmp = f"/tmp/dc-{i:02d}.wav"
        write_wav(tmp, x)
        dst = os.path.join(out, f"dc-{i:02d}.m4a")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-af", "loudnorm=I=-16:TP=-1.5:LRA=9",
                        "-c:a", "aac", "-b:a", "160k", dst], check=True)
        os.remove(tmp)
        print("wrote", dst, p[:3])
    sfx()
