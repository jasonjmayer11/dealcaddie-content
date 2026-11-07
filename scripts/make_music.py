#!/usr/bin/env python3
"""Compose DealCaddie's original background tracks in code — 7 genres, 15 tracks.

Every sound is synthesized here (sines, noise, Karplus–Strong strings), so DealCaddie owns the
music outright: no licenses, no credits, nothing for Content ID to match.

Usage: python3 scripts/make_music.py      -> music/dc-01..15.m4a (34 s each) + assets/sfx/*.wav
Genres (each has its own tempo, instruments, groove and mix):
  lofi · house · cinematic · trap · funk · synthwave · acoustic
"""
import os, subprocess, wave
import numpy as np

SR = 44100
LEN = 34.0
N = int(LEN * SR)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAJOR = [0, 2, 4, 5, 7, 9, 11]
MINOR = [0, 2, 3, 5, 7, 8, 10]
DORIAN = [0, 2, 3, 5, 7, 9, 10]

def hz(m): return 440.0 * 2 ** ((m - 69) / 12)

def chord(root, scale, deg, size=4, ext=False):
    out = []
    for k in range(size + (1 if ext else 0)):
        d = deg + 2 * k
        out.append(root + scale[d % 7] + 12 * (d // 7))
    return out

# ------------------------------------------------------------------ utilities
def t_of(n): return np.arange(n, dtype=np.float32) / SR

def env(n, a=0.005, d=0.1, s=0.7, r=0.1):
    e = np.full(n, s, np.float32)
    A, D, R = int(a * SR), int(d * SR), int(r * SR)
    A = min(A, n); e[:A] = np.linspace(0, 1, A, dtype=np.float32) if A else e[:A]
    D2 = min(D, max(0, n - A))
    if D2: e[A:A + D2] = np.linspace(1, s, D2, dtype=np.float32)
    if R and n > R: e[-R:] *= np.linspace(1, 0, R, dtype=np.float32)
    return e

def expdec(n, rate): return np.exp(-t_of(n) * rate).astype(np.float32)

def smooth(x, k):
    if k <= 1: return x.astype(np.float32)
    c = np.cumsum(np.concatenate([[0.0], x]))
    y = (c[k:] - c[:-k]) / k
    return np.concatenate([y, np.full(k - 1, y[-1])]).astype(np.float32)

def lowpass(x, cutoff):
    """One-pole low-pass (vectorized via exponential smoothing with lfilter-free recursion by blocks)."""
    a = np.exp(-2 * np.pi * cutoff / SR)
    # IIR y[n] = (1-a)x[n] + a y[n-1], computed with a short FIR approximation
    L = max(4, int(5 / (1 - a)))
    L = min(L, 4096)
    k = (1 - a) * a ** np.arange(L)
    return np.convolve(x, k.astype(np.float32))[: len(x)].astype(np.float32)

def highpass(x, cutoff): return (x - lowpass(x, cutoff)).astype(np.float32)

def osc(freq, n, kind="sine", phase=0.0, detune=0.0):
    t = t_of(n); f = freq * 2 ** (detune / 1200)
    if kind == "sine": return np.sin(2 * np.pi * f * t + phase).astype(np.float32)
    nh = max(1, int(min(40, 9000 / max(f, 1))))
    s = np.zeros(n, np.float32)
    for h in range(1, nh + 1):
        if kind == "saw": s += np.sin(2 * np.pi * f * h * t + phase * h) / h
        elif kind == "square" and h % 2: s += np.sin(2 * np.pi * f * h * t + phase * h) / h
        elif kind == "tri" and h % 2: s += ((-1) ** ((h - 1) // 2)) * np.sin(2 * np.pi * f * h * t) / (h * h)
    return s * (0.6 if kind == "saw" else 0.8)

def put(buf, sig, at, gain=1.0, pan=0.0):
    i = int(at * SR)
    if i >= len(buf) or i < 0: return
    sig = sig[: len(buf) - i]
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[i:i + len(sig), 0] += sig * gain * l
    buf[i:i + len(sig), 1] += sig * gain * r

def reverb(x, seconds, seed, wet=0.3, damp=3.0, bright=3):
    r = np.random.default_rng(seed); n = int(seconds * SR)
    ir = np.stack([r.standard_normal(n), r.standard_normal(n)], 1) * np.exp(-damp * t_of(n))[:, None]
    ir[:, 0] = smooth(ir[:, 0], bright); ir[:, 1] = smooth(ir[:, 1], bright)
    ir /= np.sqrt((ir ** 2).sum(0))
    L = len(x) + n - 1; F = 1 << (L - 1).bit_length()
    out = np.zeros_like(x)
    for c in range(2):
        out[:, c] = np.fft.irfft(np.fft.rfft(x[:, c], F) * np.fft.rfft(ir[:, c], F), F)[: len(x)]
    return x * (1 - wet) + out * wet

def stereo_delay(x, secs, fb=0.35, taps=4):
    out = x.copy(); d = int(secs * SR)
    for k in range(1, taps + 1):
        sh = np.zeros_like(x); sh[d * k:] = x[: len(x) - d * k] * fb ** k
        if k % 2: sh = sh[:, ::-1]
        out += sh
    return out

def duck_curve(times, depth=0.5, rel=8.0):
    d = np.ones(N, np.float32)
    for at in times:
        i = int(at * SR); L = min(int(0.4 * SR), N - i)
        if L > 0: d[i:i + L] = np.minimum(d[i:i + L], 1 - depth * np.exp(-t_of(L) * rel))
    return d

# ------------------------------------------------------------------ instruments
def kick(punch=1.0, length=0.45, low=45, high=120, click=0.2):
    n = int(length * SR); t = t_of(n)
    f = low + (high - low) * np.exp(-t * 28 * punch)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return (np.sin(ph) * np.exp(-t * 7) + click * np.sin(ph * 3) * np.exp(-t * 60)).astype(np.float32)

def sub808(freq_from, freq_to, length, glide=0.08):
    n = int(length * SR); t = t_of(n)
    f = freq_to + (freq_from - freq_to) * np.exp(-t / max(glide, 1e-3))
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.tanh(np.sin(ph) * 1.6) * env(n, 0.003, 0.0, 1.0, 0.08)
    return s.astype(np.float32)

def noise(n, seed): return np.random.default_rng(seed).standard_normal(n).astype(np.float32)

def snare(seed, tone=190, length=0.25, bright=1.0):
    n = int(length * SR); t = t_of(n)
    body = np.sin(2 * np.pi * tone * t) * np.exp(-t * 25)
    nz = highpass(noise(n, seed), 1200 * bright) * np.exp(-t * 18)
    return (0.5 * body + 0.9 * nz).astype(np.float32)

def clap(seed):
    n = int(0.3 * SR); t = t_of(n)
    nz = highpass(lowpass(noise(n, seed), 5000), 900)
    e = np.exp(-t * 14)
    for off in (0.0, 0.011, 0.022):
        e += 0.8 * np.exp(-((t - off) ** 2) / 2e-6)
    return (nz * e * 0.9).astype(np.float32)

def hat(seed, open_=False, bright=7000):
    n = int((0.22 if open_ else 0.05) * SR); t = t_of(n)
    return (highpass(noise(n, seed), bright) * np.exp(-t * (14 if open_ else 80)) * 0.6).astype(np.float32)

def rim(seed):
    n = int(0.06 * SR); t = t_of(n)
    return (np.sin(2 * np.pi * 1700 * t) * np.exp(-t * 90) * 0.6 + highpass(noise(n, seed), 3000) * np.exp(-t * 120) * 0.3).astype(np.float32)

def shaker(seed):
    n = int(0.09 * SR); t = t_of(n)
    return (highpass(noise(n, seed), 6000) * np.sin(np.pi * t / t[-1]) ** 2 * 0.4).astype(np.float32)

def epiano(freq, length):
    n = int((length + 0.6) * SR); t = t_of(n)
    trem = 1 + 0.12 * np.sin(2 * np.pi * 4.5 * t)
    s = (np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(2 * np.pi * freq * 2 * t) * np.exp(-t * 3)
         + 0.18 * np.sin(2 * np.pi * freq * 7.1 * t) * np.exp(-t * 18))          # tine bell
    return (s * trem * np.exp(-t * 1.4) * env(n, 0.004, 0, 1, 0.25)).astype(np.float32)

def piano(freq, length, vel=1.0):
    n = int((length + 1.2) * SR); t = t_of(n)
    s = np.zeros(n, np.float32)
    for h, (g, d) in enumerate([(1, 1.2), (0.55, 1.8), (0.3, 2.6), (0.16, 3.4), (0.09, 4.5), (0.05, 6)], 1):
        fh = freq * h * (1 + 0.0004 * h * h)                                      # slight inharmonicity
        s += g * np.sin(2 * np.pi * fh * t) * np.exp(-t * d * (0.7 + freq / 900))
    hammer = highpass(noise(int(0.01 * SR), int(freq)), 2000) * 0.15
    s[: len(hammer)] += hammer
    return (s * vel * env(n, 0.002, 0, 1, 0.3)).astype(np.float32)

def pad(freqs, length, kind="saw", cutoff=1800, attack=0.6, detune=9):
    n = int((length + 1.0) * SR)
    s = np.zeros(n, np.float32)
    for f in freqs:
        for dt, ph in ((-detune, 0.0), (detune, 1.7), (0, 0.6)):
            s += osc(f, n, kind, ph, dt)
    s = lowpass(s / (3 * len(freqs)), cutoff)
    return s * env(n, attack, 0.3, 0.85, 1.0)

def stab(freqs, length=0.18, cutoff=2600):
    n = int((length + 0.05) * SR)
    s = sum(osc(f, n, "saw", 0, d) for f in freqs for d in (-6, 6)) / (2 * len(freqs))
    return lowpass(s, cutoff) * env(n, 0.003, 0.08, 0.5, 0.05)

def pluck_ks(freq, length, bright=0.5, seed=0):
    """Karplus–Strong plucked string (vectorized one period at a time)."""
    n = int((length + 0.4) * SR); P = max(2, int(SR / freq))
    buf = np.random.default_rng(seed).uniform(-1, 1, P).astype(np.float32)
    buf = smooth(buf, 1 + int((1 - bright) * 6))
    out = np.zeros(n, np.float32); decay = 0.996
    for i in range(0, n, P):
        out[i:i + P] = buf[: min(P, n - i)]
        buf = decay * 0.5 * (buf + np.roll(buf, -1))
    return out * env(n, 0.001, 0, 1, 0.2)

def bell(freq, length):
    n = int((length + 1.0) * SR); t = t_of(n)
    s = (np.sin(2 * np.pi * freq * t) + 0.5 * np.sin(2 * np.pi * freq * 2.76 * t) * np.exp(-t * 3)
         + 0.25 * np.sin(2 * np.pi * freq * 5.4 * t) * np.exp(-t * 6))
    return (s * np.exp(-t * 2.2) * env(n, 0.002, 0, 1, 0.3)).astype(np.float32)

def bass(freq, length, kind="sine", cutoff=900):
    n = int((length + 0.05) * SR)
    s = osc(freq, n, kind) if kind != "sine" else osc(freq, n) + 0.3 * osc(freq * 2, n)
    s = lowpass(s, cutoff) if kind != "sine" else s
    return (np.tanh(s * 1.3) * env(n, 0.004, 0.08, 0.8, 0.05)).astype(np.float32)

def slap(freq, length):
    n = int((length + 0.05) * SR); t = t_of(n)
    s = osc(freq, n, "saw"); s = lowpass(s, 600 + 2600 * np.exp(-t[-1] * 0))  # bright then dark below
    s = s * np.exp(-t * 6) + 0.6 * osc(freq, n) * np.exp(-t * 3)
    return (np.tanh(s * 1.5) * env(n, 0.002, 0, 1, 0.04)).astype(np.float32)

def scratch(seed, length=0.07):
    n = int(length * SR); t = t_of(n)
    nz = lowpass(highpass(noise(n, seed), 900), 3500)
    return (nz * np.exp(-t * 45) * 0.8).astype(np.float32)

def crackle(seed):
    r = np.random.default_rng(seed)
    x = np.zeros(N, np.float32)
    idx = r.integers(0, N, int(LEN * 18)); x[idx] = r.uniform(-1, 1, len(idx)) * r.uniform(0.2, 1, len(idx))
    hiss = lowpass(highpass(r.standard_normal(N).astype(np.float32), 2500), 7000) * 0.015
    return np.stack([x * 0.25 + hiss, np.roll(x, 37) * 0.25 + hiss], 1)

def melody(scale, root, bars, beat, seed, density=0.5, octave=12, contour=None):
    """Simple motif from scale degrees; repeats every 2 bars with variation. Returns [(time, midi, len)]."""
    r = np.random.default_rng(seed)
    motif = []
    steps = 8
    last = r.integers(0, 5)
    for k in range(steps * 2):
        if r.random() < density:
            last = int(np.clip(last + r.choice([-2, -1, 1, 1, 2, 0]), 0, 9))
            motif.append((k, last, r.choice([1, 1, 2])))
    notes = []
    for b in range(0, bars, 2):
        for k, deg, ln in motif:
            if b >= 2 and r.random() < 0.2: continue
            m = root + octave + scale[deg % 7] + 12 * (deg // 7)
            notes.append(((b * 4 + k / 2) * beat, m, ln * beat / 2))
    return notes

def master(mix, lp=None, drive=1.4):
    if lp:
        mix = np.stack([lowpass(mix[:, 0], lp), lowpass(mix[:, 1], lp)], 1)
    mix = np.tanh(mix * drive) / np.tanh(drive)
    return (mix * 0.89 / (np.abs(mix).max() + 1e-9)).astype(np.float32)

# ------------------------------------------------------------------ genres
def g_lofi(root, prog, bpm, seed):
    beat = 60 / bpm; bar = 4 * beat; swing = beat * 0.16
    keys, drums, bs = (np.zeros((N, 2), np.float32) for _ in range(3))
    for b in range(int(LEN / bar) + 1):
        t0 = b * bar; ch = chord(root, DORIAN, prog[b % len(prog)], 4, ext=True)
        for i, m in enumerate(ch):                                     # lazy strum
            put(keys, epiano(hz(m), bar * 0.9), t0 + i * 0.018, 0.16, pan=-0.3 + 0.15 * i)
        put(bs, bass(hz(ch[0] - 24), beat * 1.6), t0, 0.5)
        put(bs, bass(hz(ch[0] - 24 + 7), beat * 0.8), t0 + 2.5 * beat, 0.4)
        put(drums, kick(0.7, low=48, high=95, click=0.05), t0, 0.7)
        put(drums, kick(0.7, low=48, high=95, click=0.05), t0 + 2.5 * beat + swing, 0.55)
        for q in (1, 3): put(drums, snare(seed + b + q, 170, 0.3, 0.6), t0 + q * beat, 0.42)
        for k in range(8):
            put(drums, hat(seed + k, bright=5000), t0 + k * beat / 2 + (swing if k % 2 else 0), 0.10 if k % 2 else 0.15, 0.25)
        if b % 2: put(drums, rim(seed), t0 + 3.75 * beat, 0.25, -0.2)
    mix = reverb(keys, 1.6, seed, 0.28) + bs + drums
    mix += crackle(seed) * 0.22
    return master(mix, lp=6500, drive=1.3)

def g_house(root, prog, bpm, seed):
    beat = 60 / bpm; bar = 4 * beat
    st, drums, bs, pd = (np.zeros((N, 2), np.float32) for _ in range(4))
    kicks = []
    for b in range(int(LEN / bar) + 1):
        t0 = b * bar; ch = chord(root, MINOR, prog[b % len(prog)], 3)
        put(pd, pad([hz(m) for m in ch], bar, "saw", 1400, 0.4), t0, 0.12)
        for q in range(4):
            if b >= 1:
                put(drums, kick(1.3, 0.35, 50, 150, 0.3), t0 + q * beat, 0.85); kicks.append(t0 + q * beat)
            put(bs, bass(hz(ch[0] - 24), beat * 0.42, "saw", 700), t0 + q * beat + beat / 2, 0.42)
            put(drums, hat(seed + q, True, 8000), t0 + q * beat + beat / 2, 0.16, 0.3)
            if q in (1, 3) and b >= 1: put(drums, clap(seed + b), t0 + q * beat, 0.35)
        for k in (0.75, 1.5, 2.75, 3.5):                                 # chord stabs
            put(st, stab([hz(m + 12) for m in ch]), t0 + k * beat, 0.22, pan=0.2 if k % 1 else -0.2)
        for k in range(16): put(drums, hat(seed + 40 + k, False, 9000), t0 + k * beat / 4, 0.05, -0.3)
    d = duck_curve(kicks, 0.55)[:, None]
    mix = reverb(st, 1.2, seed, 0.25) * d + pd * d + bs * d + drums
    return master(mix, drive=1.5)

def g_cinematic(root, prog, bpm, seed):
    beat = 60 / bpm; bar = 4 * beat
    pd, pn, hi, sub = (np.zeros((N, 2), np.float32) for _ in range(4))
    for b in range(int(LEN / bar) + 1):
        t0 = b * bar; ch = chord(root, MAJOR, prog[b % len(prog)], 3)
        put(pd, pad([hz(m) for m in ch] + [hz(ch[0] + 12)], bar * 1.1, "saw", 900 + 300 * (b % 3), 1.4, 6), t0, 0.16)
        put(sub, osc(hz(ch[0] - 24), int((bar + 0.5) * SR)) * env(int((bar + 0.5) * SR), 1.0, 0, 1, 1.0), t0, 0.22)
        for k in range(8):                                               # shimmering high arp
            m = ch[k % 3] + 24
            put(hi, bell(hz(m), 0.4) * 0.5, t0 + k * beat / 2, 0.05, pan=-0.5 + (k % 4) * 0.33)
    for at, m, ln in melody(MAJOR, root, int(LEN / bar) + 1, beat, seed, 0.28, 12):
        put(pn, piano(hz(m), ln * 2), at, 0.30, pan=0.1)
    mix = reverb(pd + pn * 0.9 + hi, 3.5, seed, 0.45, 1.6) + sub
    return master(mix, drive=1.2)

def g_trap(root, prog, bpm, seed):
    beat = 60 / bpm; bar = 4 * beat
    drums, b8, bl = (np.zeros((N, 2), np.float32) for _ in range(3))
    r = np.random.default_rng(seed)
    for b in range(int(LEN / bar) + 1):
        t0 = b * bar; deg = prog[b % len(prog)]; m = root - 24 + MINOR[deg % 7]
        put(b8, sub808(hz(m + 12), hz(m), beat * 1.5), t0, 0.7)
        put(b8, sub808(hz(m + 7), hz(m + 3 if b % 2 else m), beat * 1.2, 0.12), t0 + 2.5 * beat, 0.6)
        put(drums, kick(1.0, 0.3, 50, 160, 0.25), t0, 0.6)
        put(drums, kick(1.0, 0.3, 50, 160, 0.25), t0 + 2.5 * beat, 0.5)
        put(drums, clap(seed + b), t0 + 2 * beat, 0.5)
        put(drums, snare(seed + b, 230, 0.2, 1.4), t0 + 2 * beat, 0.25)
        k = 0.0
        while k < 4:                                                     # hi-hats with rolls
            roll = r.random() < 0.18
            step = beat / (6 if roll else 2) if r.random() < 0.85 else beat / 4
            for j in range(3 if roll else 1):
                put(drums, hat(seed + int(k * 50) + j, False, 9000), t0 + (k + j * step / beat) * beat, 0.13, 0.25)
            k += (step / beat) * (3 if roll else 1)
    for at, mm, ln in melody(MINOR, root, int(LEN / bar) + 1, beat, seed + 3, 0.35, 12):
        put(bl, bell(hz(mm), ln), at, 0.14, pan=-0.2)
    mix = reverb(bl, 2.4, seed, 0.4) + b8 + drums
    return master(mix, drive=1.6)

def g_funk(root, prog, bpm, seed):
    beat = 60 / bpm; bar = 4 * beat; s16 = beat / 4
    drums, bs, gt, ky = (np.zeros((N, 2), np.float32) for _ in range(4))
    bass_pat = [(0, 0), (3, 12), (4, 0), (6, 7), (8, 0), (10, 12), (11, 10), (14, 7)]
    for b in range(int(LEN / bar) + 1):
        t0 = b * bar; ch = chord(root, DORIAN if b % 2 else MAJOR, prog[b % len(prog)], 4)
        for st, iv in bass_pat:
            put(bs, slap(hz(ch[0] - 24 + iv), s16 * 1.6), t0 + st * s16, 0.4)
        for st in (2, 6, 10, 14, 15):                                     # muted guitar scratches
            put(gt, scratch(seed + st + b), t0 + st * s16, 0.35, pan=0.45)
        for st in (4, 12):                                                # chord stabs (clean guitar-ish)
            for i, m in enumerate(ch):
                put(gt, pluck_ks(hz(m + 12), 0.2, 0.8, seed + i) * 0.5, t0 + st * s16 + i * 0.006, 0.18, pan=-0.4)
        put(ky, pad([hz(m) for m in ch], bar, "square", 1600, 0.05, 4), t0, 0.06)
        for q in range(4):
            put(drums, kick(1.1, 0.3, 50, 130, 0.2), t0 + q * beat, 0.6 if q in (0, 2) else 0.35)
            if q in (1, 3): put(drums, snare(seed + q + b, 210, 0.22, 1.2), t0 + q * beat, 0.45)
        for k in range(16): put(drums, shaker(seed + k), t0 + k * s16, 0.18 if k % 2 else 0.1, -0.35)
        put(drums, hat(seed, True, 7000), t0 + 3.5 * beat, 0.18, 0.3)
    mix = reverb(gt + ky, 1.0, seed, 0.18) + bs + drums
    return master(mix, drive=1.5)

def g_synthwave(root, prog, bpm, seed):
    beat = 60 / bpm; bar = 4 * beat
    drums, arp, pd, ld = (np.zeros((N, 2), np.float32) for _ in range(4))
    for b in range(int(LEN / bar) + 1):
        t0 = b * bar; ch = chord(root, MINOR, prog[b % len(prog)], 3)
        put(pd, pad([hz(m) for m in ch] + [hz(ch[0] + 12)], bar, "saw", 2200, 0.5, 12), t0, 0.12)
        for k in range(16):                                              # 16th-note octave bass arp
            m = ch[0] - 24 + (12 if k % 2 else 0)
            n = int(beat / 4 * SR)
            put(arp, lowpass(osc(hz(m), n, "saw"), 1300) * env(n, 0.002, 0.05, 0.6, 0.02), t0 + k * beat / 4, 0.32)
        for q in range(4):
            put(drums, kick(1.0, 0.35, 48, 140, 0.15), t0 + q * beat, 0.7 if q in (0, 2) else 0.0)
            if q in (1, 3):
                sn = snare(seed + q + b, 200, 0.5, 0.9)
                g = np.ones(len(sn), np.float32); g[int(0.18 * SR):] = 0.05      # gated
                put(drums, sn * g, t0 + q * beat, 0.5)
        for k in range(8): put(drums, hat(seed + k, False, 8000), t0 + k * beat / 2, 0.08, 0.2)
    for at, m, ln in melody(MINOR, root, int(LEN / bar) + 1, beat, seed + 9, 0.3, 12):
        n = int((ln + 0.2) * SR)
        put(ld, lowpass(osc(hz(m), n, "square", 0, 5) + osc(hz(m), n, "saw", 0, -5), 2400) * env(n, 0.01, 0.1, 0.7, 0.15), at, 0.10)
    mix = reverb(pd + stereo_delay(ld, beat * 0.75, 0.3) + drums * 0.6, 2.2, seed, 0.3) + arp + drums * 0.5
    return master(mix, drive=1.4)

def g_acoustic(root, prog, bpm, seed):
    beat = 60 / bpm; bar = 4 * beat; s8 = beat / 2
    gt, drums, gl, bs = (np.zeros((N, 2), np.float32) for _ in range(4))
    strum = [(0, 1), (2, 1), (3, -1), (5, -1), (6, 1), (7, -1)]           # 8th positions, 1=down -1=up
    for b in range(int(LEN / bar) + 1):
        t0 = b * bar; ch = chord(root, MAJOR, prog[b % len(prog)], 3)
        voicing = [ch[0] - 12, ch[2] - 12, ch[0], ch[1], ch[2], ch[0] + 12]
        for pos, dirn in strum:
            notes = voicing if dirn > 0 else voicing[::-1][:4]
            for i, m in enumerate(notes):
                put(gt, pluck_ks(hz(m), 0.8, 0.55, seed + b + i + pos), t0 + pos * s8 + i * 0.012, 0.11 if dirn > 0 else 0.07,
                    pan=-0.3 + 0.12 * i)
        put(bs, bass(hz(ch[0] - 24), beat * 1.8), t0, 0.35)
        put(bs, bass(hz(ch[2] - 24), beat * 1.8), t0 + 2 * beat, 0.3)
        if b >= 1:
            for q in (0, 2): put(drums, kick(0.6, 0.35, 55, 100, 0.05), t0 + q * beat, 0.55)
            for q in (1, 3): put(drums, clap(seed + q + b), t0 + q * beat, 0.32)
            for k in range(8): put(drums, shaker(seed + k), t0 + k * s8, 0.14, 0.4)
    for at, m, ln in melody(MAJOR, root, int(LEN / bar) + 1, beat, seed + 5, 0.3, 24):
        put(gl, bell(hz(m), 0.6), at, 0.07, pan=0.3)
    mix = reverb(gt + gl, 1.3, seed, 0.2) + bs + drums
    return master(mix, drive=1.3)

GENRES = {"lofi": g_lofi, "house": g_house, "cinematic": g_cinematic, "trap": g_trap,
          "funk": g_funk, "synthwave": g_synthwave, "acoustic": g_acoustic}

# 15 tracks, ordered so neighbours in the rotation are always different genres
TRACKS = [
    ("house",     57, [0, 5, 2, 6], 123),
    ("lofi",      62, [1, 4, 0, 3], 82),
    ("cinematic", 60, [0, 4, 5, 3], 72),
    ("funk",      64, [0, 3, 0, 4], 112),
    ("synthwave", 57, [0, 5, 3, 4], 104),
    ("acoustic",  55, [0, 4, 5, 3], 100),
    ("trap",      62, [0, 5, 3, 6], 140),
    ("lofi",      58, [1, 4, 2, 5], 78),
    ("house",     60, [5, 3, 0, 4], 124),
    ("cinematic", 63, [5, 3, 0, 4], 70),
    ("acoustic",  60, [3, 0, 4, 5], 104),
    ("funk",      62, [0, 4, 3, 4], 108),
    ("synthwave", 64, [0, 6, 5, 6], 100),
    ("trap",      57, [0, 3, 5, 4], 136),
    ("lofi",      65, [0, 3, 1, 4], 86),
]

def write_wav(path, x):
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())

def sfx():
    out = os.path.join(ROOT, "assets", "sfx"); os.makedirs(out, exist_ok=True)
    n = int(0.5 * SR); t = t_of(n)
    nz = noise(n, 3); segs = []
    for k in range(25):
        a, b = k * n // 25, (k + 1) * n // 25
        width = int(40 - 34 * np.sin(np.pi * k / 24))
        segs.append(smooth(nz[a:b] - smooth(nz[a:b], max(2, width)), 2))
    w = np.concatenate(segs) * np.sin(np.pi * t / t[-1]) ** 2 * 0.5
    write_wav(os.path.join(out, "whoosh.wav"), np.stack([w, np.roll(w, 300)], 1))
    n = int(1.8 * SR); t = t_of(n)
    b = sum(np.sin(2 * np.pi * hz(m) * t) * g for m, g in ((72, 0.5), (79, 0.3), (84, 0.25), (88, 0.12)))
    b = (b * np.exp(-t * 2.6) * env(n, 0.005, 0, 1, 0.1)).astype(np.float32) * 0.5
    write_wav(os.path.join(out, "landing.wav"), np.stack([b, b], 1))

if __name__ == "__main__":
    import sys
    only = set(sys.argv[1:])
    out = os.path.join(ROOT, "music"); os.makedirs(out, exist_ok=True)
    for i, (g, root, prog, bpm) in enumerate(TRACKS, 1):
        if only and str(i) not in only: continue
        x = GENRES[g](root, prog, bpm, seed=100 + i)
        tmp = f"/tmp/dc-{i:02d}.wav"; write_wav(tmp, x)
        dst = os.path.join(out, f"dc-{i:02d}.m4a")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-af", "loudnorm=I=-16:TP=-1.5:LRA=9",
                        "-c:a", "aac", "-b:a", "160k", "-metadata", f"title=DealCaddie {g} {i:02d}", dst], check=True)
        os.remove(tmp)
        print(f"dc-{i:02d}  {g:<10} {bpm} bpm")
    sfx()
