#!/usr/bin/env python3
"""Swap a finished reel's soundtrack for another DealCaddie track (keeps the whoosh/chime timing).

Usage: MUSIC_TRACK=dc-07 python3 scripts/rescore.py reel.mp4 "0,3.33,7.27,12.97,16.70"
beats = start time of every beat; the last one is the end card. Used when a batch built on
one day would otherwise share tracks."""
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from soundtrack import add_soundtrack

mp4, beats = sys.argv[1], [float(x) for x in sys.argv[2].split(",") if x.strip()]
dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                     "-of", "csv=p=0", mp4]).decode().strip())
name = add_soundtrack(mp4, beats, dur)
if not name or not os.environ.get("MUSIC_TRACK", "").startswith(name[:5]):
    sys.exit(f"rescore failed: got {name}")
