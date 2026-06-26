# 🟤 Brown Noise Machine

A tiny retro terminal noise machine driven by [SoX](http://sox.sourceforge.net/).
Zero Python dependencies — just the standard-library `curses` and the `sox`
binary you already `brew install`ed.

```
brew install sox      # provides the `play` binary used under the hood
```

## Run

```bash
./brn
# or
python3 brownnoise.py
```

For a global command:

```bash
ln -s "$PWD/brn" /opt/homebrew/bin/brn   # then just run: brn
```

## Controls

| Key            | Action                                                  |
|----------------|---------------------------------------------------------|
| `←` / `→`      | Select a setting (its full name shows in the center)    |
| `↑` / `↓`      | Increase / decrease the selected setting                |
| `space`        | Play / pause                                            |
| `r`            | Reset everything to defaults                            |
| `q` / `esc`    | Quit                                                    |

`hjkl` work as vim-style aliases for the arrows.

## Settings

Each setting shows as a 3-letter abbreviation in the top row; the selected one
expands to its full name and a description in the central panel.

| Abbr  | Name             | What it does                                            |
|-------|------------------|---------------------------------------------------------|
| `NSE` | Noise Color      | brown (deep/warm) · pink (balanced) · white (bright)    |
| `VOL` | Volume           | Output gain (can boost past 1.0×)                       |
| `LPF` | Low-pass Cutoff  | Rolls off highs — lower = warmer/muffled                |
| `TRM` | Tremolo Speed    | Rate of the ocean-wave swell (needs Depth > 0)          |
| `DEP` | Tremolo Depth    | How deep the wave swell goes (0% = steady)              |
| `REV` | Reverb / Room    | Room size / space                                       |
| `THU` | Thunder          | Occasional distant rolling thunder (0% = off)           |
| `BAL` | Stereo Balance   | Pan between left and right                              |

Thunder runs as a separate, randomized `play` process that fires low-passed,
reverb-soaked brown-noise rumbles on a timer and mixes with the noise bed via
the OS audio mixer. Higher `THU` = louder and more frequent. It only plays
while the main bed is playing, and stops when you pause.

Changes **live-restart** the audio stream automatically (with a short debounce
so holding an arrow key feels smooth).

## How it works

The settings are compiled into a single `play` command, e.g.:

```bash
play -q -n -c2 synth brownnoise tremolo 0.18 30 lowpass 1200 reverb 20 \
     remix 1v1.00 2v0.80 vol 0.55
```
