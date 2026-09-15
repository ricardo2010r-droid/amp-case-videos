#!/usr/bin/env python3
"""
Synthesise the reel's soundtrack: a continuous futuristic meditation drone.

    python ambience.py beats.json out.wav [mood]

beats.json is what video.html publishes in <body data-beats>, i.e.
{"dur": 16, "beats": [0.96, 4.16, ...]} - one timestamp per completed step.

This is deliberately NOT a sequence of sounds. It is one unbroken pad that
breathes for the whole clip: a low drone, detuned partials beating slowly
against each other, and a high shimmer that drifts. Completed steps do not
get a blip; they get a slow bloom in the shimmer, so the track reacts to the
animation without ever breaking the continuity.

There are six moods, rotated per post so the feed does not sound identical
every day. They are a fixed, listened-to list rather than random parameters,
for the same reason the colour themes are: a combination nobody has heard
should never publish itself.

Everything is generated from maths with the standard library. There is no
audio file to licence, host or lose.
"""
import json, math, struct, sys, wave

SR = 44100

# A stack of perfect fifths and octaves over a low root. No third, so it stays
# open and unresolved instead of sounding like a chord in a key.
ROOT = 55.0
PARTIALS = [
    # (ratio, gain, lfo rate Hz, lfo phase, lfo depth)
    (1.0,  0.50, 0.043, 0.00, 0.25),   # sub
    (2.0,  0.34, 0.057, 1.20, 0.30),   # octave
    (3.0,  0.20, 0.071, 2.40, 0.38),   # fifth above
    (4.0,  0.13, 0.037, 0.70, 0.34),
    (6.0,  0.075, 0.091, 3.10, 0.45),
    (8.0,  0.045, 0.063, 1.90, 0.45),
]
# Airy top end. Kept separate because the step blooms lift exactly this layer.
SHIMMER = [(12.0, 0.030, 0.107, 0.4), (16.0, 0.022, 0.083, 2.2),
           (24.0, 0.013, 0.129, 4.1)]

DETUNE = 0.0017          # ~3 cents, gives a slow breathing beat
FADE_IN, FADE_OUT = 2.5, 3.0

# Each mood bends the same template rather than defining its own stack, so all
# six stay balanced against each other and none can come out thin or harsh.
#   root   fundamental in Hz, the single biggest change in character
#   detune width of the beating between paired oscillators
#   rate   multiplier on every LFO, i.e. how fast the pad breathes
#   shim   multiplier on the airy top layer
#   depth  multiplier on how far each partial swells
#   extra  additional (ratio, gain) partials layered on top
#   sparse drop the upper partials for an emptier sound
MOODS = {
    "deep":    dict(root=49.00, detune=0.0011, rate=0.70, shim=0.70, depth=1.00),
    "tide":    dict(root=55.00, detune=0.0026, rate=0.55, shim=1.00, depth=1.35),
    "air":     dict(root=65.40, detune=0.0020, rate=1.00, shim=1.60, depth=1.00),
    "glass":   dict(root=58.27, detune=0.0022, rate=1.25, shim=1.90, depth=0.90,
                    extra=[(4.5, 0.055)]),          # adds a ninth: brighter, unresolved
    "circuit": dict(root=61.74, detune=0.0009, rate=1.60, shim=0.60, depth=0.80,
                    extra=[(2.667, 0.10)]),         # adds a fourth: more mechanical
    "hollow":  dict(root=51.91, detune=0.0014, rate=0.80, shim=0.45, depth=1.10,
                    sparse=True),
}
MOOD_ORDER = ["deep", "tide", "air", "glass", "circuit", "hollow"]


def bloom(beats, t):
    """Slow swell after each completed step. Long attack, long release."""
    v = 0.0
    for b in beats:
        d = t - b
        if -0.6 < d < 5.0:
            # rises over ~1.1s, falls away over ~3s, never a transient
            a = 1.0 / (1.0 + math.exp(-(d + 0.2) * 4.2))
            v += a * math.exp(-max(0.0, d) / 1.9)
    return min(v, 2.2)


def main():
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    out = sys.argv[2]
    name = sys.argv[3] if len(sys.argv) > 3 else MOOD_ORDER[0]
    if name.isdigit():
        name = MOOD_ORDER[int(name) % len(MOOD_ORDER)]
    if name not in MOODS:
        sys.exit(f"unknown mood {name!r}, expected one of {', '.join(MOOD_ORDER)}")
    m = MOODS[name]

    root   = m["root"]
    detune = m["detune"]
    partials = [pt for pt in PARTIALS if not (m.get("sparse") and pt[0] >= 6)]
    for ratio, gain in m.get("extra", []):
        # slot the extra partial in with an LFO that does not line up with the rest
        partials.append((ratio, gain, 0.049 * ratio, ratio, 0.40))

    dur = float(spec["dur"])
    beats = sorted(set(round(float(b), 3) for b in spec["beats"]))

    n = int(dur * SR)
    buf = [0.0] * n

    # Pre-roll the phase accumulators so every partial starts at zero crossing.
    for ratio, gain, rate, phase, depth in partials:
        f = root * ratio
        rate *= m["rate"]
        depth = min(0.85, depth * m["depth"])
        for spread in (1.0, 1.0 + detune):
            w = 2 * math.pi * f * spread / SR
            lw = 2 * math.pi * rate / SR
            for i in range(n):
                # amplitude drifts slowly and independently per partial
                lfo = 1.0 - depth + depth * (0.5 + 0.5 * math.sin(lw * i + phase))
                buf[i] += gain * 0.5 * lfo * math.sin(w * i)

    # bloom is the same curve for every shimmer partial, so evaluate it once
    swell = [1.0 + 1.6 * bloom(beats, i / SR) for i in range(n)]

    for ratio, gain, rate, phase in SHIMMER:
        f = root * ratio
        gain *= m["shim"]
        rate *= m["rate"]
        for spread in (1.0, 1.0 + detune * 2):
            w = 2 * math.pi * f * spread / SR
            lw = 2 * math.pi * rate / SR
            for i in range(n):
                lfo = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(lw * i + phase))
                # the only thing the workflow steps touch
                buf[i] += gain * 0.5 * lfo * swell[i] * math.sin(w * i)

    # Long fades so the loop never clicks in or out.
    peak = max(abs(v) for v in buf) or 1.0
    frames = bytearray()
    for i, v in enumerate(buf):
        t = i / SR
        fade = min(1.0, t / FADE_IN, max(0.0, (dur - t) / FADE_OUT))
        v = math.tanh(v / peak * 1.15) * fade * 0.62
        frames += struct.pack("<h", max(-32767, min(32767, int(v * 32767))))

    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(frames))
    print(f"ambience[{name}]: {dur}s drone, {len(beats)} step blooms -> {out}")


if __name__ == "__main__":
    main()
