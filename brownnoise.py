#!/usr/bin/env python3
"""
brownnoise — a tiny retro TUI noise machine driven by SoX.

Controls
  ←/→        select a setting (its full name shows in the center panel)
  ↑/↓        increase / decrease the selected setting
  space      play / pause
  r          reset all settings to defaults
  q / esc    quit

Requires `sox` (provides the `play` binary) on PATH.
"""

import curses
import json
import os
import random
import shutil
import signal
import subprocess
import time

# Persisted state lives next to this script so it survives restarts.
# It's gitignored so it never gets committed.
STATE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".brownnoise_state.json")

# ───────────────────────────── settings model ──────────────────────────────
# Each setting carries a short abbreviation (shown in the top row), a full
# name + description (shown in the central "hover" panel), and the data needed
# to render a bar and turn it into SoX arguments.

NOISE_CHOICES = ["brown", "pink", "white"]


def make_settings():
    """Return a fresh list of settings at their default values."""
    return [
        dict(abbr="NSE", name="NOISE COLOR", type="choice",
             choices=NOISE_CHOICES, idx=0,
             desc="The flavor of noise. Brown is deepest/warmest, pink is "
                  "balanced, white is bright and hissy."),
        dict(abbr="VOL", name="VOLUME", type="num",
             val=0.55, lo=0.0, hi=1.50, step=0.05, unit="x", prec=2,
             desc="Output gain. Above 1.0 boosts past unity — watch your ears."),
        dict(abbr="LPF", name="LOW-PASS CUTOFF", type="num",
             val=1200, lo=200, hi=20000, step=200, unit="Hz", prec=0,
             desc="Rolls off highs above this point. Lower = warmer, more "
                  "muffled and cozy; higher = brighter and airier."),
        dict(abbr="TRM", name="TREMOLO SPEED", type="num",
             val=0.18, lo=0.02, hi=2.00, step=0.02, unit="Hz", prec=2,
             desc="How fast the volume swells, like rolling ocean waves. "
                  "Only audible when Tremolo Depth is above zero."),
        dict(abbr="DEP", name="TREMOLO DEPTH", type="num",
             val=0, lo=0, hi=100, step=5, unit="%", prec=0,
             desc="How deep the wave-like swell goes. 0% is perfectly steady "
                  "noise; higher adds a breathing, ocean wobble."),
        dict(abbr="REV", name="REVERB / ROOM", type="num",
             val=20, lo=0, hi=100, step=5, unit="%", prec=0,
             desc="Room size / reverberance. Adds space and depth, like the "
                  "noise is filling a larger room."),
        dict(abbr="THU", name="THUNDER", type="num",
             val=30, lo=0, hi=100, step=10, unit="%", prec=0,
             desc="Occasional rolling thunder in the distance. 0% is off; "
                  "higher makes rumbles louder and more frequent."),
        dict(abbr="BAL", name="STEREO BALANCE", type="num",
             val=0.0, lo=-1.0, hi=1.0, step=0.1, unit="", prec=1,
             desc="Pans the sound between the left and right channels. "
                  "Center keeps it even on both sides."),
    ]


def fraction(s):
    """Normalized 0..1 position of a setting, for bar rendering."""
    if s["type"] == "choice":
        return s["idx"] / max(1, len(s["choices"]) - 1)
    return (s["val"] - s["lo"]) / (s["hi"] - s["lo"])


def value_text(s):
    """Human-readable current value."""
    if s["type"] == "choice":
        return s["choices"][s["idx"]].upper()
    if s["abbr"] == "BAL":
        v = s["val"]
        if abs(v) < 0.05:
            return "CENTER"
        side = "R" if v > 0 else "L"
        return f"{side} {abs(v)*100:.0f}%"
    if s["prec"] == 0:
        return f"{s['val']:.0f} {s['unit']}".strip()
    return f"{s['val']:.{s['prec']}f} {s['unit']}".strip()


def adjust(s, direction):
    """Bump a setting up (+1) or down (-1) by one step."""
    if s["type"] == "choice":
        s["idx"] = (s["idx"] + direction) % len(s["choices"])
        return
    nv = s["val"] + direction * s["step"]
    nv = max(s["lo"], min(s["hi"], nv))
    # avoid float dust like 0.30000000004
    s["val"] = round(nv, 4)


def load_state():
    """Build settings from defaults, then overlay any saved values.

    Defensive: a missing or corrupt state file just yields defaults.
    """
    settings = make_settings()
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return settings

    for s in settings:
        v = data.get(s["abbr"])
        if v is None:
            continue
        try:
            if s["type"] == "choice":
                s["idx"] = max(0, min(len(s["choices"]) - 1, int(v)))
            else:
                s["val"] = round(max(s["lo"], min(s["hi"], float(v))), 4)
        except (TypeError, ValueError):
            pass
    return settings


def save_state(settings):
    """Write current values atomically; failures are non-fatal."""
    data = {s["abbr"]: (s["idx"] if s["type"] == "choice" else s["val"])
            for s in settings}
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass


# ─────────────────────────────── sox driver ────────────────────────────────

def build_args(settings):
    """Translate the current settings into `play` arguments."""
    by = {s["abbr"]: s for s in settings}
    noise = {"brown": "brownnoise", "pink": "pinknoise",
             "white": "whitenoise"}[by["NSE"]["choices"][by["NSE"]["idx"]]]

    args = ["play", "-q", "-n", "-c2", "synth", noise]

    depth = by["DEP"]["val"]
    if depth > 0:
        args += ["tremolo", f"{by['TRM']['val']:.2f}", f"{depth:.0f}"]

    args += ["lowpass", f"{by['LPF']['val']:.0f}"]

    rev = by["REV"]["val"]
    if rev > 0:
        args += ["reverb", f"{rev:.0f}"]

    # stereo balance via per-channel gain in remix
    bal = by["BAL"]["val"]
    lg = 1.0 if bal <= 0 else 1.0 - bal
    rg = 1.0 if bal >= 0 else 1.0 + bal
    args += ["remix", f"1v{lg:.2f}", f"2v{rg:.2f}"]

    args += ["vol", f"{by['VOL']['val']:.2f}"]
    return args


class Player:
    """Manages the background `play` process and live-restarts it on change."""

    def __init__(self):
        self.proc = None
        self.playing = False

    def start(self, settings):
        self.stop()
        try:
            self.proc = subprocess.Popen(
                build_args(settings),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,  # own process group so we can kill it
            )
            self.playing = True
        except FileNotFoundError:
            self.playing = False

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                try:
                    self.proc.terminate()
                except ProcessLookupError:
                    pass
        self.proc = None

    def toggle(self, settings):
        if self.playing:
            self.stop()
            self.playing = False
        else:
            self.start(settings)


def _kill(proc):
    """Terminate a process (and its group) if still alive."""
    if proc and proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                proc.terminate()
            except ProcessLookupError:
                pass


def thunder_args(thu):
    """A single randomized rolling-thunder rumble, scaled by THU (0..100).

    Heavy low-pass keeps only the deep rumble; reverb makes it 'roll'; a slow
    tremolo adds the flickering grumble; a fast-ish swell + long decay is the
    shape of a distant thunderclap. Kept deliberately quiet — background only.
    """
    f = thu / 100.0
    dur = random.uniform(3.5, 7.0)
    cutoff = random.randint(70, 150)          # lower = more distant/muffled
    rev = random.randint(65, 95)
    # peak volume stays low so it never dominates the noise bed
    vol = (0.09 + 0.20 * f) * random.uniform(0.75, 1.05)
    fin = random.uniform(0.5, 1.3)            # swell up
    fout = min(dur * random.uniform(0.55, 0.8), dur - fin - 0.1)  # long decay
    return [
        "play", "-q", "-n", "synth", f"{dur:.2f}", "brownnoise",
        "lowpass", str(cutoff), "lowpass", str(cutoff),   # steeper rolloff
        "reverb", str(rev),
        "tremolo", f"{random.uniform(0.35, 0.85):.2f}", str(random.randint(20, 42)),
        "fade", "t", f"{fin:.2f}", f"{dur:.2f}", f"{fout:.2f}",
        "vol", f"{vol:.2f}",
    ]


def thunder_gap(thu):
    """Seconds until the next rumble. More THU -> more frequent."""
    f = thu / 100.0
    lo = 38 - 28 * f      # 38s (faint) -> 10s (stormy)
    hi = 85 - 52 * f      # 85s         -> 33s
    return random.uniform(lo, hi)


class Thunder:
    """Fires randomized thunder rumbles as independent background processes,
    timed off the main loop. Mixes with the noise bed via the OS audio mixer."""

    def __init__(self):
        self.proc = None
        self.next_t = None   # None => (re)schedule a fresh first strike

    def update(self, thu, now, playing):
        # reap a finished rumble
        if self.proc and self.proc.poll() is not None:
            self.proc = None

        # off, or main playback paused -> silence thunder and re-arm later
        if not playing or thu <= 0:
            _kill(self.proc)
            self.proc = None
            self.next_t = None
            return

        if self.next_t is None:                  # first strike after a beat
            self.next_t = now + random.uniform(6, 16)
            return

        if now >= self.next_t and self.proc is None:
            try:
                self.proc = subprocess.Popen(
                    thunder_args(thu),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except FileNotFoundError:
                pass
            self.next_t = now + thunder_gap(thu)

    def stop(self):
        _kill(self.proc)
        self.proc = None


# ─────────────────────────────── theming ───────────────────────────────────
# A brown / amber / tan palette when the terminal supports 256 colors,
# with a graceful fallback to the basic 8.

P = {}  # name -> curses color_pair attr


def init_palette():
    curses.start_color()
    try:
        curses.use_default_colors()
    except curses.error:
        pass

    if curses.COLORS >= 256:
        # xterm-256 indices: deep browns -> warm tans -> bright amber
        spec = {
            "frame":   (130, -1),   # sienna
            "dim":     (94,  -1),   # dark brown
            "label":   (180, -1),   # tan
            "hi":      (215, 52),   # amber on dark maroon (selected chip)
            "title":   (208, -1),   # pumpkin
            "accent":  (222, -1),   # light goldenrod
            "barfull": (173, -1),   # copper
            "barempty":(58,  -1),   # olive-brown
            "good":    (107, -1),   # muted green (PLAYING)
            "value":   (223, -1),   # wheat
            # noise-color swatches — earthy variations that sit in the palette
            "n_brown": (130, -1),   # sienna — matches the frame
            "n_pink":  (175, -1),   # dusty rose / clay pink
            "n_white": (230, -1),   # warm cream (white, but not cold)
        }
        # animated waveform gradient
        wave = [94, 130, 166, 173, 208, 215, 222]
    else:
        spec = {
            "frame":   (curses.COLOR_YELLOW, -1),
            "dim":     (curses.COLOR_YELLOW, -1),
            "label":   (curses.COLOR_YELLOW, -1),
            "hi":      (curses.COLOR_BLACK, curses.COLOR_YELLOW),
            "title":   (curses.COLOR_RED, -1),
            "accent":  (curses.COLOR_YELLOW, -1),
            "barfull": (curses.COLOR_RED, -1),
            "barempty":(curses.COLOR_YELLOW, -1),
            "good":    (curses.COLOR_GREEN, -1),
            "value":   (curses.COLOR_YELLOW, -1),
            "n_brown": (curses.COLOR_YELLOW, -1),
            "n_pink":  (curses.COLOR_MAGENTA, -1),
            "n_white": (curses.COLOR_WHITE, -1),
        }
        wave = [curses.COLOR_RED, curses.COLOR_YELLOW]

    n = 1
    for name, (fg, bg) in spec.items():
        try:
            curses.init_pair(n, fg, bg)
        except curses.error:
            curses.init_pair(n, curses.COLOR_YELLOW, -1)
        P[name] = curses.color_pair(n)
        n += 1

    P["_wave"] = []
    for c in wave:
        try:
            curses.init_pair(n, c, -1)
        except curses.error:
            curses.init_pair(n, curses.COLOR_YELLOW, -1)
        P["_wave"].append(curses.color_pair(n))
        n += 1


def addstr(win, y, x, text, attr=0):
    """Bounds-safe addstr."""
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x >= w:
        return
    if x < 0:
        text = text[-x:]
        x = 0
    text = text[: max(0, w - x - 1)]
    try:
        win.addstr(y, x, text, attr)
    except curses.error:
        pass


# ─────────────────────────────── rendering ─────────────────────────────────

TITLE = [
    "▄▄▄ ▄▄  ▄▄▄  ▄ ▄ ▄ ▄   ▄ ▄  ▄▄▄ ▄ ▄▄▄ ▄▄▄",
    "BROWN NOISE MACHINE",
]

WAVE_CHARS = "▁▂▃▄▅▆▇█▇▆▅▄▃▂"


def bar(frac, width, full_attr, empty_attr, win, y, x):
    filled = int(round(frac * width))
    filled = max(0, min(width, filled))
    addstr(win, y, x, "█" * filled, full_attr)
    addstr(win, y, x + filled, "░" * (width - filled), empty_attr)


def noise_attr(s):
    """Color pair for the currently-selected noise color."""
    return P["n_" + s["choices"][s["idx"]]]


def draw_setting_bar(s, width, win, y, x):
    """Render a setting's bar. Noise color shows as a full colored swatch;
    everything else is a normal fill-level bar."""
    if s["abbr"] == "NSE":
        addstr(win, y, x, "█" * width, noise_attr(s))
    else:
        bar(fraction(s), width, P["barfull"], P["barempty"], win, y, x)


def draw(win, settings, sel, player, t):
    win.erase()
    h, w = win.getmaxyx()
    BW = max(48, w - 2)          # box width: fill the terminal, 1-col margin
    x0 = max(0, (w - BW) // 2)
    y = 1

    fr = P["frame"]
    # ── top border + title ──
    addstr(win, y, x0, "╔" + "═" * (BW - 2) + "╗", fr); y += 1
    addstr(win, y, x0, "║", fr)
    addstr(win, y, x0 + BW - 1, "║", fr)
    addstr(win, y, x0 + 2, "♪ BROWN NOISE MACHINE", P["title"] | curses.A_BOLD)
    controls = "←→ select  ↑↓ adjust  space play  r reset  q quit"
    addstr(win, y, x0 + BW - 2 - len(controls), controls, P["dim"])
    y += 1
    addstr(win, y, x0, "╠" + "═" * (BW - 2) + "╣", fr); y += 1

    # ── settings row (abbreviations + mini bars) ──
    inner = BW - 4
    slot = inner // len(settings)
    row_y = y
    for by in (row_y, row_y + 1):     # close the side borders on both rows
        addstr(win, by, x0, "║", fr)
        addstr(win, by, x0 + BW - 1, "║", fr)
    for i, s in enumerate(settings):
        cx = x0 + 2 + i * slot + (slot - 3) // 2
        selected = (i == sel)
        if selected:
            addstr(win, row_y, cx - 1, f" {s['abbr']} ",
                   P["hi"] | curses.A_BOLD)
        else:
            addstr(win, row_y, cx, s["abbr"], P["label"])
        # mini bar beneath
        mb = max(3, slot - 3)
        bx = x0 + 2 + i * slot + (slot - mb) // 2
        draw_setting_bar(s, mb, win, row_y + 1, bx)
    y = row_y + 2
    addstr(win, y, x0, "╠" + "═" * (BW - 2) + "╣", fr); y += 1

    # ── central "hover" panel: name inline with description + big bar ──
    cur = settings[sel]
    prefix = f"◀ {cur['name']} ▶ "
    avail = BW - 6
    # wrap description, reserving room for the inline name on the first line
    words = cur["desc"].split()
    line, lines = "", []
    for word in words:
        limit = avail - len(prefix) if not lines else avail
        if line and len(line) + len(word) + 1 > limit:
            lines.append(line); line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    for i, ln in enumerate(lines[:2]):
        addstr(win, y, x0, "║", fr); addstr(win, y, x0 + BW - 1, "║", fr)
        if i == 0:
            addstr(win, y, x0 + 3, prefix, P["accent"] | curses.A_BOLD)
            addstr(win, y, x0 + 3 + len(prefix), ln, P["dim"])
        else:
            addstr(win, y, x0 + 3, ln, P["dim"])
        y += 1

    # big value bar
    addstr(win, y, x0, "║", fr); addstr(win, y, x0 + BW - 1, "║", fr)
    big_w = BW - 22
    addstr(win, y, x0 + 3, "[", P["frame"])
    draw_setting_bar(cur, big_w, win, y, x0 + 4)
    addstr(win, y, x0 + 4 + big_w, "]", P["frame"])
    addstr(win, y, x0 + 6 + big_w, value_text(cur),
           P["value"] | curses.A_BOLD)
    y += 1
    addstr(win, y, x0, "╠" + "═" * (BW - 2) + "╣", fr); y += 1

    # ── status + animated waveform ──
    addstr(win, y, x0, "║", fr); addstr(win, y, x0 + BW - 1, "║", fr)
    if player.playing:
        addstr(win, y, x0 + 3, "▶ PLAYING", P["good"] | curses.A_BOLD)
        wstart = x0 + 14
        wwidth = BW - 16
        waves = P["_wave"]
        # The wave shape scrolls in height over time, but each column's COLOR
        # is fixed to its position and never moves. With the colors stationary,
        # the eye reads the motion as the bars rising and falling in place
        # rather than the pattern sliding sideways.
        shift = int(t * 1.6)
        for k in range(wwidth):
            ch = WAVE_CHARS[(k + shift) % len(WAVE_CHARS)]
            attr = waves[k % len(waves)]
            addstr(win, y, wstart + k, ch, attr)
    else:
        addstr(win, y, x0 + 3, "❚❚ PAUSED", P["dim"] | curses.A_BOLD)
        addstr(win, y, x0 + 14, "─" * (BW - 16), P["barempty"])
    y += 1

    addstr(win, y, x0, "╚" + "═" * (BW - 2) + "╝", fr)

    win.noutrefresh()
    curses.doupdate()


# ──────────────────────────────── main loop ────────────────────────────────

def run(stdscr):
    curses.curs_set(0)
    curses.cbreak()
    stdscr.keypad(True)
    stdscr.timeout(120)  # ms; drives the animation frame rate
    init_palette()

    settings = load_state()
    sel = 0
    player = Player()
    player.start(settings)
    thunder = Thunder()

    dirty = False
    last_change = 0.0
    start = time.monotonic()

    while True:
        now = time.monotonic()
        draw(stdscr, settings, sel, player, now - start)

        # background thunder: timed, randomized, independent of the noise bed
        thu = next(s["val"] for s in settings if s["abbr"] == "THU")
        thunder.update(thu, now, player.playing)

        # live-restart audio shortly after the last change (debounce so that
        # holding an arrow key doesn't spawn a swarm of processes)
        if dirty and (now - last_change) > 0.13:
            if player.playing:
                player.start(settings)
            save_state(settings)
            dirty = False

        try:
            ch = stdscr.getch()
        except KeyboardInterrupt:
            break

        if ch == -1:
            continue
        if ch in (ord("q"), ord("Q"), 27):  # q or esc
            break
        elif ch in (curses.KEY_LEFT, ord("h")):
            sel = (sel - 1) % len(settings)
        elif ch in (curses.KEY_RIGHT, ord("l")):
            sel = (sel + 1) % len(settings)
        elif ch in (curses.KEY_UP, ord("k")):
            adjust(settings[sel], +1)
            dirty = True; last_change = time.monotonic()
        elif ch in (curses.KEY_DOWN, ord("j")):
            adjust(settings[sel], -1)
            dirty = True; last_change = time.monotonic()
        elif ch == ord(" "):
            player.toggle(settings)
        elif ch in (ord("r"), ord("R")):
            settings = make_settings()
            dirty = True; last_change = time.monotonic()

    save_state(settings)
    thunder.stop()
    player.stop()


def main():
    if shutil.which("play") is None:
        raise SystemExit(
            "error: `play` not found. Install SoX first:  brew install sox")
    try:
        curses.wrapper(run)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
