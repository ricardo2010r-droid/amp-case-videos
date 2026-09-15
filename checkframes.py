#!/usr/bin/env python3
"""
Print the indices of frames that came out blank.

Headless Chrome occasionally returns an all-black screenshot when the machine is
briefly loaded, and because it happens in runs you get a black hole in the middle
of the video rather than one odd frame. render.sh calls this and re-renders only
the frames named here.

    python checkframes.py <frames-dir>
"""
import os, sys
from PIL import Image

d = sys.argv[1]
bad = []
for name in sorted(os.listdir(d)):
    if not name.endswith(".png"):
        continue
    path = os.path.join(d, name)
    try:
        im = Image.open(path).convert("L")
        # Every good frame has white-ish text on it, so the brightest pixel is
        # high. A blank render has almost nothing above black.
        if im.getextrema()[1] < 40:
            bad.append(int(name[2:6]))
    except Exception:
        bad.append(int(name[2:6]))

print(" ".join(str(b) for b in bad))
