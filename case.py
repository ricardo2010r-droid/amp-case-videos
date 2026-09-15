#!/usr/bin/env python3
"""
Daily voiced case video: Claude writes a case, Kokoro voices it, case.html is
rendered 9:16, the drone bed is mixed under the voice, and the site emails an
approval link. Nothing posts until that link is clicked.

    python case.py                  # full run
    python case.py --dry-run        # render only, no upload, no email
    python case.py --case sample-case.json --dry-run   # skip Claude

Environment: ANTHROPIC_API_KEY, AMP_SITE, AMP_KEY, CHROME_BIN, KOKORO_DIR
"""
import os, re, sys, json, datetime, subprocess, urllib.request

HERE  = os.path.dirname(os.path.abspath(__file__))
SITE  = os.environ.get("AMP_SITE", "https://automationmatrixpro.com").rstrip("/")
KEY   = os.environ.get("AMP_KEY", "")
MODEL = os.environ.get("AMP_MODEL", "claude-sonnet-5")
KOKORO = os.environ.get("KOKORO_DIR", os.path.join(HERE, ".tts", "model"))
VOICE = "am_michael"
FPS   = os.environ.get("CASE_FPS", "24")
HISTORY = os.path.join(HERE, "history.txt")
OUTRO = "Automation Matrix Pro. Let's build yours."
MOODS = ["deep", "tide", "air", "glass", "circuit", "hollow"]
INDUSTRIES = ["real estate agency", "dental clinic", "accounting firm", "online store",
              "law firm", "gym", "plumbing business", "restaurant", "recruitment agency",
              "insurance broker", "marketing agency", "property manager", "physio clinic",
              "car dealership", "wedding photographer", "software support team",
              "tutoring centre", "builder", "travel agency", "vet clinic", "cleaning company",
              "mortgage broker", "hair salon", "IT services company"]

PROMPT = """Write one short explainer video case for Automation Matrix Pro, an agency that
builds business automations. Industry for today: %(industry)s.

The video follows ONE fictional customer or job through an automated workflow,
step by step, with a voiceover. Return ONLY a JSON object:

{
 "title":   "short hook, 4 to 8 words, e.g. The lead that books itself",
 "steps": [ 5 to 7 step objects, in order ],
 "overview_say": "one line said while the whole flow runs, 12 to 20 words",
 "stat": {"line1": "the assumption, max 34 chars, e.g. 20 enquiries a week × 15 min",
          "value": whole number 2 to 40, "unit": "max 14 chars, e.g. hours back",
          "line3": "max 26 chars, e.g. every single week",
          "say": "the same maths spoken, 14 to 24 words"},
 "caption": "Instagram caption: hook line, blank line, numbered steps using 1️⃣ 2️⃣ style, blank line, the stat, blank line, 'Want this built around the tools you already use? Comment \\"FLOW\\" or tap the link in our bio 👆'",
 "hashtags": "10 to 14 hashtags for this industry and automation, space separated"
}

Each step object:
 "kind":  "trigger" (first step only, exactly once), "agent" (exactly once), "if" (at most once, never last), or "action"
 "label": node name, max 18 chars
 "sub":   small grey text under it, max 18 chars, name the tool if there is one
 "app":   one of %(apps)s, or "" if no product fits
 "icon":  used when app is "": one of form, robot, iff, clock, db, mail, chat, cart, doc, phone, calendar, user, star, chart
 "pill":  big green headline shown over the step, max 18 chars
 "say":   the voiceover for this step, 10 to 22 words, plain spoken English
 "card":  the example data shown above the node, EITHER
          {"head": "max 34 chars", "title": "max 30 chars", "lines": ["Label: value", ...max 3, each max 34 chars], "tags": [max 2 short tags], "quote": "optional, max 40 chars", "score": optional number}
          OR for a step that sends a message: {"to": "name · subject, max 36 chars", "message": "80 to 170 chars", "button": "optional, max 24 chars"}
 agent steps also need "tools": 1 to 3 of {"label": max 16 chars, "sub": optional max 14, "app": as above, "icon": as above}
 if steps also need "branch": the other path, {"label": max 18, "sub": max 18, "app", "icon", "note": max 30 chars}

Rules:
- Every step must be something a real %(industry)s actually does, with real tools.
- The first step's say should set the scene, with a time, e.g. "It's 9:47 at night."
- Exactly one step uses a message card.
- The stat is an illustrative assumption, so phrase it as one ("say twenty a week").
- Say "we", never "I". Say "agent", never "bot". Never say "small business".
- Never name a city, country or region. No em dashes anywhere. No exclamation marks in say lines.
- Do not repeat these recent titles: %(avoid)s
"""


def apps():
    src = open(os.path.join(HERE, "apps.js"), encoding="utf-8").read()
    return re.findall(r'^"([a-z0-9]+)":\{', src, re.M)


def validate(c, known):
    """Return None when the case is renderable, else the reason."""
    try:
        s = c["steps"]
        if "—" in json.dumps(c, ensure_ascii=False):
            return "em dash present"
        if not 5 <= len(s) <= 7:
            return "need 5 to 7 steps"
        kinds = [x["kind"] for x in s]
        if kinds[0] != "trigger" or kinds.count("trigger") != 1:
            return "first step must be the only trigger"
        if kinds.count("agent") != 1:
            return "exactly one agent step"
        if kinds.count("if") > 1 or kinds[-1] == "if":
            return "at most one if, never last"
        if sum(1 for x in s if x.get("card", {}).get("message")) != 1:
            return "exactly one message card"
        for x in s:
            for f, n in (("label", 18), ("sub", 18), ("pill", 18)):
                if len(x.get(f, "")) > n:
                    return f"{f} too long: {x.get(f)}"
            if x.get("app") and x["app"] not in known:
                return f"unknown app {x['app']}"
            w = len(x["say"].split())
            if not 6 <= w <= 26:
                return f"say has {w} words: {x['say']}"
            card = x.get("card") or {}
            if len(card.get("message", "")) > 190:
                return "message too long"
            for l in card.get("lines", []):
                if len(l) > 38:
                    return f"card line too long: {l}"
            if x["kind"] == "agent":
                if not 1 <= len(x.get("tools", [])) <= 3:
                    return "agent needs 1 to 3 tools"
                for t in x["tools"]:
                    if t.get("app") and t["app"] not in known:
                        return f"unknown app {t['app']}"
            if x["kind"] == "if" and not x.get("branch"):
                return "if step needs a branch"
        st = c["stat"]
        if not (isinstance(st["value"], int) and 1 <= st["value"] <= 60):
            return "stat value must be a whole number"
        if len(st["line1"]) > 38 or len(st["line3"]) > 30 or len(st["unit"]) > 16:
            return "stat text too long"
        for k in ("title", "overview_say", "caption", "hashtags"):
            if not str(c[k]).strip():
                return f"empty {k}"
    except Exception as e:
        return f"malformed: {e!r}"
    return None


def ask_claude(industry, avoid, known):
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        sys.exit("ANTHROPIC_API_KEY is not set")
    base = PROMPT % {"industry": industry, "apps": ", ".join(known), "avoid": "; ".join(avoid) or "none"}
    err = ""
    for attempt in range(1, 4):
        msg = base + (f"\n\nYour previous attempt was rejected: {err}. Fix that and return the whole object." if err else "")
        body = json.dumps({"model": MODEL, "max_tokens": 6000,
                           "messages": [{"role": "user", "content": msg}]}).encode()
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body)
        req.add_header("x-api-key", key)
        req.add_header("anthropic-version", "2023-06-01")
        req.add_header("content-type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                payload = json.load(r)
        except Exception as e:
            err = f"API error {e}"
            print("attempt", attempt, err)
            continue
        # never content[0]: a thinking block can come first
        text = next((b.get("text", "") for b in payload.get("content") or [] if b.get("type") == "text"), "")
        m = re.search(r"\{.*\}", text, re.S)
        try:
            case = json.loads(m.group(0)) if m else None
        except Exception as e:
            case, err = None, f"bad JSON {e}"
        if case is not None:
            err = validate(case, known)
            if not err:
                print(f"generated (attempt {attempt}): {case['title']}")
                return case
        print("attempt", attempt, "rejected:", err)
    sys.exit(f"no usable case after 3 attempts: {err}")


def voice_and_time(case, wav_out):
    """Voice every line, then size each scene to its line so nothing is rushed."""
    import numpy as np, soundfile as sf
    from kokoro_onnx import Kokoro
    k = Kokoro(os.path.join(KOKORO, "kokoro-v1.0.onnx"), os.path.join(KOKORO, "voices-v1.0.bin"))
    steps = case["steps"]
    lines = [s["say"] for s in steps] + [case["overview_say"], case["stat"]["say"], OUTRO]
    mins = []
    for s in steps:
        m = 5.5 if s["kind"] == "trigger" else 4.5
        if (s.get("card") or {}).get("message"):
            m = 7.5
        if s["kind"] == "if" and s.get("branch"):
            m = 6.0
        mins.append(m)
    mins += [6.0, 7.0, 5.0]
    clips, timing, t = [], [], 0.0
    for line, m in zip(lines, mins):
        audio, sr = k.create(line, voice=VOICE, speed=1.0, lang="en-us")
        d = max(m, len(audio) / sr + 1.0)
        timing.append([round(t, 2), round(t + d, 2)])
        clips.append((t + 0.3, audio))
        t += d
    total = round(t + 0.5, 2)
    track = np.zeros(int(total * sr) + sr, dtype=np.float32)
    for start, audio in clips:
        s = int(start * sr)
        track[s:s + len(audio)] += audio
    sf.write(wav_out, track[:int(total * sr)], sr)
    case["lines"], case["timing"], case["dur"] = lines, timing, total
    # same formula as case.html, so the drone blooms land on completed steps
    case["beats"] = [max(a + 2.4, a + 0.6 * (b - a)) for a, b in timing[:len(steps)]]
    print(f"voiced {len(lines)} lines, {total}s")


def api(path, data, raw=False, name=None):
    url = f"{SITE}/wp-json/amp/v1/{path}" + (f"?name={name}" if name else "")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("X-AMP-Key", KEY)
    req.add_header("Content-Type", "application/octet-stream" if raw else "application/json")
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode())


def main():
    dry = "--dry-run" in sys.argv
    day = (datetime.date.today() - datetime.date(2026, 1, 1)).days
    stamp = datetime.date.today().isoformat()
    known = apps()
    history = open(HISTORY, encoding="utf-8").read().splitlines() if os.path.exists(HISTORY) else []

    if "--case" in sys.argv:
        case = json.load(open(sys.argv[sys.argv.index("--case") + 1], encoding="utf-8"))
        why = validate(case, known)
        if why:
            sys.exit(f"case invalid: {why}")
    else:
        industry = INDUSTRIES[day % len(INDUSTRIES)]
        print("industry:", industry)
        case = ask_claude(industry, history[-40:], known)

    voice = os.path.join(HERE, "case-voice.wav")
    voice_and_time(case, voice)
    with open(os.path.join(HERE, "case-data.js"), "w", encoding="utf-8") as fh:
        fh.write("window.CASE=" + json.dumps(case, ensure_ascii=False) + ";\n")

    silent = os.path.join(HERE, "case-silent.mp4")
    subprocess.run(["bash", os.path.join(HERE, "render-case.sh"), silent, str(case["dur"]), FPS], check=True)

    beats = os.path.join(HERE, "case-beats.json")
    json.dump({"dur": case["dur"], "beats": case["beats"]}, open(beats, "w"))
    bed = os.path.join(HERE, "case-bed.wav")
    subprocess.run([sys.executable, os.path.join(HERE, "ambience.py"), beats, bed, MOODS[day % len(MOODS)]], check=True)

    out = os.path.join(HERE, f"case-{stamp}.mp4")
    # bed at 0.05, ducked under the voice; no loudnorm, it pumps the bed in the gaps
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", silent, "-i", voice, "-i", bed, "-filter_complex",
                    "[2:a]volume=0.05[bed];[1:a]asplit[v1][v2];"
                    "[bed][v1]sidechaincompress=threshold=0.02:ratio=6:attack=20:release=400[duck];"
                    "[duck][v2]amix=inputs=2:duration=first:normalize=0[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", out], check=True)
    print("video:", out)

    caption = (case["caption"].strip() + "\n\nWe build it. You run it.\n"
               "Every automation comes with a 30-day guarantee: it works, or you get your money back.\n"
               "automationmatrixpro.com\n\n" + case["hashtags"].strip())
    open(os.path.join(HERE, "case-caption.txt"), "w", encoding="utf-8").write(caption)
    if dry:
        print("--- dry run, nothing uploaded ---\n" + caption)
        return
    if not KEY:
        sys.exit("AMP_KEY is not set")
    with open(out, "rb") as fh:
        up = api("upload", fh.read(), raw=True, name=os.path.basename(out))
    print("uploaded:", up["url"])
    res = api("case-pending", json.dumps({"video_url": up["url"], "caption": caption, "title": case["title"]}).encode())
    print("approval:", res)
    if not res.get("mail"):
        sys.exit("approval email was not sent")
    with open(HISTORY, "a", encoding="utf-8") as fh:
        fh.write(case["title"] + "\n")


if __name__ == "__main__":
    main()
