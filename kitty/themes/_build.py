"""Build the predefined themes in this directory from upstream kitty-themes.

    uv run --with coloraide python themes/_build.py <kitty-themes>/themes

Each theme gets the same measured treatment Catppuccin Mocha got:
  * every ANSI hue (colors 1-6, 9-14) >= 4.5:1 on the background, reached by
    moving OKLCH lightness only -- hue and chroma, i.e. the theme's identity,
    stay put;
  * color8 (dim text: comments, autosuggestions) between 3.0 and 4.8:1 --
    readable but clearly secondary;
  * bright white (color15) never darker than white (color7);
  * cursor >= 3:1 and selection text >= 4.5:1.
Plus the UI colors kitty.conf used to hard-code for Mocha (tab bar, borders,
bell, scrollbar, cursor trail), derived from each theme with the ratios
Mocha's hand-picked values have, and a `## tab_palette:` line tab_bar.py reads
for its accent rotation.

catppuccin-mocha-ajustado.conf is hand-tuned (see its header) and only gets
checked here, never rewritten.
"""
import os
import re
import sys

from coloraide import Color

HERE = os.path.dirname(os.path.abspath(__file__))
HUES = [1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14]

# (output file, upstream file, display name)
THEMES = [
    ("tokyo-night-ajustado.conf", "tokyo_night_night.conf", "Tokyo Night Ajustado"),
    ("rose-pine-ajustado.conf", "rose-pine.conf", "Rosé Pine Ajustado"),
    ("gruvbox-dark-ajustado.conf", "gruvbox-dark-hard.conf", "Gruvbox Dark Ajustado"),
    ("kanagawa-ajustado.conf", "kanagawa.conf", "Kanagawa Ajustado"),
    ("nord-ajustado.conf", "Nord.conf", "Nord Ajustado"),
    ("catppuccin-latte-ajustado.conf", "Catppuccin-Latte.conf", "Catppuccin Latte Ajustado"),
]


def parse(path):
    meta, vals = {}, {}
    for line in open(path, encoding="utf-8"):
        m = re.match(r"##\s*(\w+):\s*(.*)", line)
        if m:
            meta[m.group(1)] = m.group(2).strip()
            continue
        m = re.match(r"\s*(\w+)\s+(#[0-9a-fA-F]{6})\b", line)
        if m:
            vals[m.group(1)] = m.group(2).lower()
    return meta, vals


def lum(h):
    return Color(h).luminance()


def cr(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def mix(a, b, t):
    """t of the way from a to b, in sRGB (what the eye sees on screen)."""
    return Color(a).mix(b, t, space="srgb").to_string(hex=True)


def shift_l(h, dl):
    c = Color(h).convert("oklch")
    c["lightness"] = min(1.0, max(0.0, c["lightness"] + dl))
    return c.convert("srgb").fit("srgb").to_string(hex=True)


def reach(h, bg, lo, hi=99.0):
    """Nudge h's OKLCH lightness away from / toward bg until lo <= cr <= hi."""
    dark_bg = lum(bg) < 0.2
    away = 0.004 if dark_bg else -0.004
    for _ in range(250):
        r = cr(h, bg)
        if r < lo:
            h = shift_l(h, away)
        elif r > hi:
            h = shift_l(h, -away)
        else:
            break
    return h


def build(src, out, name):
    meta, v = parse(src)
    bg, fg = v["background"], v["foreground"]
    dark = lum(bg) < 0.2
    notes = []
    for i in HUES:
        k = f"color{i}"
        before = cr(v[k], bg)
        if before < 4.5:
            v[k] = reach(v[k], bg, 4.5)
            notes.append(f"{k} {before:.2f}->{cr(v[k], bg):.2f}:1")
    before = cr(v["color8"], bg)
    if not 3.0 <= before <= 4.8:
        v["color8"] = reach(v["color8"], bg, 3.0, 4.8)
        notes.append(f"color8 (dim) {before:.2f}->{cr(v['color8'], bg):.2f}:1")
    if cr(v["color15"], bg) < cr(v["color7"], bg):
        v["color15"] = fg
        notes.append("color15 = foreground (bright white was dimmer than white)")
    cur = v.get("cursor", fg)
    if cr(cur, bg) < 3.0:
        v["cursor"] = reach(cur, bg, 4.5)
        notes.append(f"cursor {cr(cur, bg):.2f}->{cr(v['cursor'], bg):.2f}:1")
    sbg = v.get("selection_background", mix(fg, bg, 0.7))
    sfg = v.get("selection_foreground", fg)
    if cr(sfg, sbg) < 4.5:
        before = cr(sfg, sbg)
        sfg = fg if cr(fg, sbg) >= cr(bg, sbg) else bg
        if cr(sfg, sbg) < 4.5:
            # Neither text color clears 4.5 on this selection color: move the
            # selection's lightness away from the text instead.
            sbg = reach(sbg, sfg, 4.5)
        notes.append(f"selection text {before:.2f}->{cr(sfg, sbg):.2f}:1")
    v["selection_background"], v["selection_foreground"] = sbg, sfg

    # UI colors, at the ratios Mocha's hand-picked ones sit at.
    bar = shift_l(bg, -0.04 if dark else -0.035)
    ui = {
        "tab_bar_background": bar,
        "tab_bar_margin_color": bar,
        "active_border_color": mix(v["color4"], bg, 0.4),
        "inactive_border_color": mix(fg, bg, 0.77),
        "visual_bell_color": mix(fg, bg, 0.68),
        "scrollbar_handle_color": mix(fg, bg, 0.25),
        "scrollbar_track_color": mix(fg, bg, 0.88),
        "cursor_trail_color": v["color5"],
    }
    # Tab accents: blue, magenta, cyan, yellow, green first (red last, and
    # never next to green); brights only fill in. Duplicates dropped -- some
    # themes (Rosé Pine) reuse the same hex for normal and bright, which made
    # tabs 6-7 repeat tabs 2-3.
    palette = []
    for i in (4, 5, 6, 3, 2, 13, 14, 1, 12, 11, 10, 9):
        if v[f"color{i}"] not in palette:
            palette.append(v[f"color{i}"])
    palette = palette[:8]

    keys = ["foreground", "background", "selection_foreground", "selection_background",
            "cursor", "cursor_text_color", "url_color"] + [f"color{i}" for i in range(16)]
    lines = [
        "# vim:ft=kitty",
        "",
        f"## name:     {name}",
        f"## author:   {meta.get('author', '?')} (adjusted in dotfiles)",
        f"## license:  {meta.get('license', '?')}",
        f"## upstream: {meta.get('upstream', '?')}",
        "## blurb:    " + " ".join(filter(None, [meta.get("blurb", "").strip(),
            f"Ajustado para legibilidad ({len(notes)} cambios medidos)." if notes
            else "Ya era legible; sin cambios de color."])),
        "",
        # Single '#': kitten themes treats every '##' line after blurb as more
        # blurb, which dumped these notes (and the palette) into its preview.
        "# tab_palette: " + " ".join(palette),
    ] + [f"# - {n}" for n in notes] + [
        "",
        "# Generated by _build.py -- edit there, not here.",
        "",
    ]
    lines += [f"{k:<24}{v[k]}" for k in keys if k in v]
    lines += ["", "# UI (derived, see _build.py)"] + [f"{k:<24}{c}" for k, c in ui.items()]
    open(os.path.join(HERE, out), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return notes


def check(path):
    _, v = parse(path)
    bg = v["background"]
    return {
        "ansi_min": round(min(cr(v[f"color{i}"], bg) for i in HUES), 2),
        "dim8": round(cr(v["color8"], bg), 2),
        "cursor": round(cr(v.get("cursor", v["foreground"]), bg), 2),
        "selection": round(cr(v["selection_foreground"], v["selection_background"]), 2),
        "white_ok": cr(v["color15"], bg) >= cr(v["color7"], bg),
    }


if __name__ == "__main__":
    upstream = sys.argv[1]
    for out, src, name in THEMES:
        notes = build(os.path.join(upstream, src), out, name)
        print(f"{name:<28} {check(os.path.join(HERE, out))}  {notes}")
    print(f"{'Catppuccin Mocha Ajustado':<28} {check(os.path.join(HERE, 'catppuccin-mocha-ajustado.conf'))}")
