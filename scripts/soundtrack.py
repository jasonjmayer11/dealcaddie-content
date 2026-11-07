#!/usr/bin/env python3
"""Add the soundtrack to a finished reel: one of DealCaddie's original tracks (music/dc-*.m4a,
composed by scripts/make_music.py), a soft whoosh on each beat change and a chime on the end card.

Rotation: each run picks the next track (twice-daily slots), so consecutive reels never repeat.
Override with env MUSIC_TRACK=dc-07 (or "none" for a silent reel)."""
import datetime, glob, os, subprocess, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SR = 44100

def _decode(path):
    raw = subprocess.check_output(["ffmpeg", "-loglevel", "error", "-i", path, "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"])
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).copy()

def pick_track(variant=0):
    tracks = sorted(glob.glob(os.path.join(ROOT, "music", "dc-*.m4a")))
    want = os.environ.get("MUSIC_TRACK", "").strip()
    if want.lower() == "none" or not tracks:
        return None
    if want:
        hit = [t for t in tracks if os.path.basename(t).startswith(want)]
        if hit: return hit[0]
    # 3 positions a day (investor reel, agent reel, showcase/feature) x 15 tracks: no repeats within
    # a day and the whole library cycles every 5 days. Variant comes from the caller (MUSIC_VARIANT).
    now = datetime.datetime.utcnow()
    days = (now - datetime.datetime(2026, 1, 1)).days
    v = int(os.environ.get("MUSIC_VARIANT", variant) or 0)
    return tracks[(days * 3 + v) * 7 % len(tracks)]        # x7 (coprime to 15) so neighbours differ in mood

def add_soundtrack(mp4, beat_starts, duration):
    track = pick_track()
    if not track:
        print("soundtrack: none"); return None
    n = int(duration * SR) + 1
    music = _decode(track)
    if len(music) < n:                                    # loop if a reel ever runs longer than the track
        music = np.tile(music, (n // len(music) + 1, 1))
    mix = music[:n] * 0.8
    t = np.arange(n) / SR
    mix *= np.clip(t / 0.3, 0, 1)[:, None]                         # fade in
    mix *= np.clip((duration - t) / 1.6, 0, 1)[:, None]            # fade out
    sfx = os.path.join(ROOT, "assets", "sfx")
    whoosh, landing = _decode(os.path.join(sfx, "whoosh.wav")), _decode(os.path.join(sfx, "landing.wav"))
    def put(sig, at, gain):
        i = max(0, int(at * SR)); j = min(n, i + len(sig))
        if j > i: mix[i:j] += sig[: j - i] * gain
    for s in beat_starts[1:-1]:
        put(whoosh, s - 0.22, 0.30)
    if len(beat_starts) > 1:
        put(landing, beat_starts[-1] + 0.15, 0.32)
    mix = np.tanh(mix * 1.2) / np.tanh(1.2)
    wav = mp4 + ".wav"
    with wave.open(wav, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype("<i2").tobytes())
    tmp = mp4 + ".tmp.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp4, "-i", wav, "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-af", "loudnorm=I=-15:TP=-1.5:LRA=9",
                    "-shortest", "-movflags", "+faststart", tmp], check=True)
    os.replace(tmp, mp4); os.remove(wav)
    name = os.path.basename(track).rsplit(".", 1)[0]
    print("soundtrack:", name)
    return name
