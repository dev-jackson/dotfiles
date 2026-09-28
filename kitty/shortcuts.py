#!/usr/bin/env python3
"""Cheatsheet kitten — shows the keyboard shortcuts that are *actually* active.

Every line is generated from the live config (kitty.conf + kitty's own defaults)
at the moment you press the key, so it can't drift from reality the way a
hand-written list does: add a `map` to kitty.conf and it shows up here.

Bound in kitty.conf:

    map cmd+/ launch --type=overlay --title "atajos de kitty" kitty +kitten shortcuts.py

Closes on *any* key event, press or release -- so holding the shortcut down
peeks at the sheet and releasing dismisses it, while a quick tap leaves it
pinned until the next keystroke (the release lands before this process exists,
so there's nothing to react to). Single instance by design: kitty re-fires a
mapping while the key auto-repeats, and without the lock below each repeat
would stack another cheatsheet on top of the first.
"""

import os
import sys
from typing import Any

from kitty.config import load_config
from kitty.constants import cache_dir, config_dir
from kitty.debug_config import mod_to_names
from kitty.fast_data_types import GLFW_MOD_SUPER
from kitty.rgb import color_from_int
from kittens.tui.handler import Handler
from kittens.tui.loop import Loop
from kittens.tui.operations import clear_screen, set_cursor_visible, styled

# --- Colors (Catppuccin Mocha) ---------------------------------------------
#
# Duplicated from tab_bar.py on purpose: importing that module monkeypatches
# TabManager (fine inside kitty, pointless and side-effecty in a kitten). Color
# objects, not the bare ints tab_bar.py feeds as_rgb(): `styled()` reads a plain
# int as a 256-color palette index (every color silently collapses to 255) and a
# "#rrggbb" string as a *named* color, which raises KeyError.
FG_KEY = color_from_int(0xF9E2AF)     # yellow   — the key combo
FG_LABEL = color_from_int(0xCDD6F4)   # text     — what it does
FG_GROUP = color_from_int(0x89B4FA)   # blue     — group headings
FG_DIM = color_from_int(0x6C7086)     # overlay0 — footer / elided count
FG_TITLE = color_from_int(0x1E1E2E)   # base     — title text on a filled bar
BG_TITLE = color_from_int(0xCBA6F7)   # mauve    — title bar fill

# --- Key rendering ----------------------------------------------------------

# macOS order (⌃⌥⇧⌘) rather than whatever order mod_to_names yields, so combos
# read the way they're printed on menus and keycaps.
MOD_SYMBOLS = (
    ("ctrl", "⌃"),
    ("control", "⌃"),
    ("alt", "⌥"),
    ("opt", "⌥"),
    ("option", "⌥"),
    ("shift", "⇧"),
    ("cmd", "⌘"),
    ("super", "⌘"),
    ("hyper", "✦"),
    ("meta", "◆"),
    ("kitty_mod", "⌃⇧"),
)

KEY_SYMBOLS = {
    "up": "↑", "down": "↓", "left": "←", "right": "→",
    "enter": "⏎", "kp_enter": "⏎", "escape": "⎋", "tab": "⇥",
    "backspace": "⌫", "delete": "⌦", "space": "␣",
    "page_up": "⇞", "page_down": "⇟", "home": "↖", "end": "↘",
    "insert": "INS",
}


def _functional_key_names() -> dict[int, str]:
    """codepoint -> name for kitty's functional keys (0xe000+), e.g. 0xe001 -> enter."""
    import kitty.fast_data_types as f

    out: dict[int, str] = {}
    for attr in dir(f):
        if attr.startswith("GLFW_FKEY_"):
            out[getattr(f, attr)] = attr[len("GLFW_FKEY_"):].lower()
    return out


FKEYS = _functional_key_names()


def _combo(trigger: Any) -> str:
    names = set(mod_to_names(trigger.mods))
    mods = ""
    for name, symbol in MOD_SYMBOLS:
        if name in names:
            names.discard(name)
            if symbol not in mods:
                mods += symbol
    key = FKEYS.get(trigger.key, "")
    if key:
        key = KEY_SYMBOLS.get(key, key.replace("_", " ").upper())
    elif trigger.key == 32:
        key = "␣"
    elif 32 < trigger.key < 0x110000:
        key = chr(trigger.key).upper()
    else:
        key = hex(trigger.key)
    return f"{mods}{key}"


# --- Action labels ----------------------------------------------------------
#
# Exact `definition` -> label. Anything unlisted falls back to the raw
# definition (see _label): a new mapping is always visible, just untranslated.
LABELS = {
    # Tabs
    "new_tab": "nueva tab",
    "close_tab": "cerrar tab",
    "next_tab": "tab siguiente",
    "previous_tab": "tab anterior",
    "move_tab_forward": "mover tab →",
    "move_tab_backward": "mover tab ←",
    "set_tab_title": "renombrar tab",
    # Ventanas / splits
    "new_window": "nueva ventana",
    "close_window": "cerrar ventana",
    "next_window": "ventana siguiente",
    "previous_window": "ventana anterior",
    "move_window_forward": "mover ventana →",
    "move_window_backward": "mover ventana ←",
    "move_window_to_top": "ventana al frente",
    "focus_visible_window": "elegir ventana visible",
    "swap_with_window": "intercambiar ventanas",
    "start_resizing_window": "modo redimensionar",
    "launch --location=vsplit --cwd=current": "split vertical",
    "launch --location=hsplit --cwd=current": "split horizontal",
    "neighboring_window left": "foco ←",
    "neighboring_window right": "foco →",
    "neighboring_window up": "foco ↑",
    "neighboring_window down": "foco ↓",
    "resize_window narrower": "más angosta",
    "resize_window wider": "más ancha",
    "resize_window taller": "más alta",
    "resize_window shorter": "más baja",
    "layout_action rotate": "rotar splits",
    # OS window
    "new_os_window": "nueva OS window",
    "close_os_window": "cerrar OS window",
    "toggle_maximized": "maximizar",
    "toggle_fullscreen": "pantalla completa",
    "minimize_macos_window": "minimizar",
    "macos_cycle_through_os_windows": "ciclar OS windows",
    "macos_cycle_through_os_windows_backwards": "ciclar OS windows ←",
    "hide_macos_app": "ocultar kitty",
    "hide_macos_other_apps": "ocultar el resto",
    "quit": "salir de kitty",
    # Scroll / scrollback
    "scroll_line_up smooth": "scroll ↑",
    "scroll_line_down smooth": "scroll ↓",
    "scroll_page_up": "página ↑",
    "scroll_page_down": "página ↓",
    "scroll_home": "ir al inicio",
    "scroll_end": "ir al final",
    "scroll_to_prompt -1": "prompt anterior",
    "scroll_to_prompt 1": "prompt siguiente",
    "show_scrollback": "scrollback en pager",
    "show_last_command_output": "salida del último comando",
    "search_scrollback": "buscar en scrollback",
    "clear_terminal to_cursor active": "limpiar pantalla",
    "clear_terminal to_cursor_scroll active": "limpiar (guarda historial)",
    "clear_terminal last_command active": "borrar último comando",
    "clear_terminal scrollback active": "borrar scrollback",
    "clear_terminal reset active": "reset del terminal",
    # Layout / apariencia
    "next_layout": "siguiente layout",
    "change_font_size all +2.0": "fuente +",
    "change_font_size all -2.0": "fuente −",
    "change_font_size all 0": "fuente por defecto",
    "set_background_opacity +0.1": "opacidad +",
    "set_background_opacity -0.1": "opacidad −",
    "set_background_opacity 1": "opacidad 100%",
    "set_background_opacity default": "opacidad por defecto",
    # Selección / portapapeles
    "copy_to_clipboard": "copiar",
    "copy_or_noop": "copiar (si hay selección)",
    "paste_from_clipboard": "pegar",
    "paste_from_selection": "pegar la selección",
    "pass_selection_to_program": "abrir la selección",
    # Hints / otros
    "open_url_with_hints": "elegir un URL",
    "kitten hints --type path": "elegir un path",
    "kitten hints --type path --program -": "path al portapapeles",
    "kitten hints --type line --program -": "línea al portapapeles",
    "kitten hints --type word --program -": "palabra al portapapeles",
    "kitten hints --type hash --program -": "hash git al portapapeles",
    "kitten hints --type linenum": "abrir archivo:línea en el editor",
    "kitten hints --type hyperlink": "abrir un hyperlink",
    "kitten unicode_input": "insertar unicode / emoji",
    "kitten choose-files": "elegir archivo",
    "kitten choose-files --mode=dir": "elegir carpeta",
    "command_palette": "paleta de comandos",
    "kitty_shell window": "shell de kitty",
    "edit_config_file": "editar kitty.conf",
    "load_config_file": "recargar la config",
    "debug_config": "volcar toda la config",
    "show_kitty_doc overview": "docs de kitty",
    "open_url https://sw.kovidgoyal.net/kitty/": "docs de kitty (web)",
    "toggle_macos_secure_keyboard_entry": "secure keyboard entry",
}

# Group heading -> prefixes of `definition` that belong to it, in display order.
# First group whose prefix matches wins, so more specific prefixes go first.
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("TABS", ("new_tab", "close_tab", "next_tab", "previous_tab", "goto_tab",
              "move_tab", "select_tab", "detach_tab", "set_tab_title")),
    ("VENTANAS Y SPLITS", ("new_window", "close_window", "next_window", "previous_window",
                           "move_window", "focus_visible_window", "neighboring_window",
                           "resize_window", "start_resizing_window", "swap_with_window",
                           "detach_window", "launch", "nth_window", "first_window",
                           "second_window", "third_window", "fourth_window", "fifth_window",
                           "sixth_window", "seventh_window", "eighth_window", "ninth_window",
                           "tenth_window")),
    ("OS WINDOW", ("new_os_window", "close_os_window", "toggle_maximized", "toggle_fullscreen",
                   "minimize_macos_window", "macos_cycle", "hide_macos", "quit")),
    ("SCROLL Y SCROLLBACK", ("scroll_", "show_scrollback", "show_last_command_output",
                             "search_scrollback", "clear_terminal")),
    ("LAYOUT Y APARIENCIA", ("next_layout", "goto_layout", "layout_action", "change_font_size",
                             "set_background_opacity")),
    ("SELECCIÓN", ("copy_", "paste_", "pass_selection_to_program")),
)
OTHER_GROUP = "OTROS"

# This kitten's own mapping, recognised so it lists as "esta ayuda" instead of
# the whole `launch --type=overlay ... kitty +kitten shortcuts.py` command line.
SELF = "shortcuts.py"

# Actions worth hiding: numeric window jumps are 10 near-identical lines that
# push more useful bindings off the sheet. ⌘1 is discoverable from ⌘2 anyway.
NUMBERED_WINDOWS = {
    f"{n}_window" for n in
    ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth")
}


# Longest label rendered. Unlabeled actions fall back to their raw definition,
# and a single long one (a `launch ...` command line) would otherwise widen the
# column enough to cost a whole column of the sheet.
LABEL_MAX = 38


def _label(definition: str) -> str:
    if SELF in definition:
        return "esta ayuda"
    label = LABELS.get(definition, definition)
    return label if len(label) <= LABEL_MAX else label[: LABEL_MAX - 1] + "…"


def _group_of(definition: str) -> str:
    if SELF in definition:  # a `launch ...`, but it belongs with the meta actions
        return OTHER_GROUP
    for title, prefixes in GROUPS:
        if definition.startswith(prefixes):
            return title
    return OTHER_GROUP


def _combo_seq(kd: Any) -> str:
    """Whole trigger, including chords: ⌃⇧P F for `map ctrl+shift+p>f ...`."""
    return " ".join(_combo(sk) for sk in kd.full_key_sequence_to_trigger)


def _prefers(new: Any, old: Any) -> bool:
    """True if `new` is the nicer binding to advertise for an action than `old`.

    Most defaults are bound twice (⌘↑ and ⌃⇧K both scroll a line up). Showing
    both doubles the sheet, so keep one: single keystroke over chord, then the
    ⌘ one on macOS (what the menus and the rest of the OS teach), then the one
    with fewer modifiers.
    """
    if old is None:
        return True
    if len(new.full_key_sequence_to_trigger) != len(old.full_key_sequence_to_trigger):
        return len(new.full_key_sequence_to_trigger) < len(old.full_key_sequence_to_trigger)
    if sys.platform == "darwin":
        new_cmd = bool(new.trigger.mods & GLFW_MOD_SUPER)
        old_cmd = bool(old.trigger.mods & GLFW_MOD_SUPER)
        if new_cmd != old_cmd:
            return new_cmd
    return bin(new.trigger.mods).count("1") < bin(old.trigger.mods).count("1")


def collect() -> list[tuple[str, list[tuple[str, str]]]]:
    """[(group title, [(combo, label), ...]), ...] straight from the live config."""
    opts = load_config(os.path.join(config_dir, "kitty.conf"))
    best: dict[str, Any] = {}
    for mode in opts.keyboard_modes.values():
        for definitions in mode.keymap.values():
            for kd in definitions:
                definition = kd.definition
                if not definition or definition in NUMBERED_WINDOWS:
                    continue
                if _prefers(kd, best.get(definition)):
                    best[definition] = kd

    grouped: dict[str, list[tuple[str, str]]] = {}
    for definition, kd in best.items():
        grouped.setdefault(_group_of(definition), []).append((_combo_seq(kd), _label(definition)))

    order = [title for title, _ in GROUPS] + [OTHER_GROUP]
    out = []
    for title in order:
        rows = grouped.get(title)
        if rows:
            out.append((title, sorted(rows, key=lambda r: r[1])))
    return out


# --- Layout -----------------------------------------------------------------

COL_GAP = 3
MIN_LABEL = 22  # narrowest label column worth squeezing an extra column out of


Cell = tuple[str, str] | None


Groups = list[tuple[str, list[tuple[str, str]]]]

MIN_ROWS_AFTER_HEADING = 2  # a heading alone at the foot of a column reads as a bug


def _widths(groups: Groups) -> tuple[int, int]:
    key_w = label_w = 0
    for _, rows in groups:
        for combo, label in rows:
            key_w = max(key_w, len(combo))
            label_w = max(label_w, len(label))
    return key_w, label_w


def _placed(grid: list[list[Cell]]) -> int:
    return sum(1 for column in grid for cell in column if cell and cell[1])


def _flow(groups: Groups, columns: int, target: int, hard: bool) -> tuple[list[list[Cell]], int] | None:
    """Fill `columns` columns of `target` lines with the groups, in order.

    A group too long for what's left of a column continues in the next one under
    a "(sigue)" heading, so a column never opens with an orphaned list whose
    heading is stranded to its left. hard=False gives up (None) the moment the
    content wants more than `columns` columns -- that's what lets the caller
    search for the shortest columns that still show everything; hard=True fills
    what it can and reports how many rows got dropped.
    """
    grid: list[list[Cell]] = [[]]
    total = sum(len(rows) for _, rows in groups)
    for heading, rows in groups:
        idx = 0
        first = True
        while first or idx < len(rows):
            column = grid[-1]
            room = target - len(column)
            if room < 1 + MIN_ROWS_AFTER_HEADING and idx < len(rows):
                if len(grid) == columns:
                    return (grid, total - _placed(grid)) if hard else None
                grid.append([])
                continue
            column.append((heading if first else f"{heading} (sigue)", ""))
            take = min(room - 1, len(rows) - idx)
            column.extend(rows[idx:idx + take])
            idx += take
            first = False
            if idx < len(rows):
                if len(grid) == columns:
                    return (grid, total - _placed(grid)) if hard else None
                grid.append([])
            elif len(column) < target:
                column.append(None)  # blank line between groups
    return grid, 0


def _pack(groups: Groups, columns: int, body: int) -> tuple[list[list[Cell]], int]:
    """Groups into columns: the shortest columns that still show everything."""
    total = sum(len(rows) + 2 for _, rows in groups)
    for target in range(max(1 + MIN_ROWS_AFTER_HEADING, -(-total // columns)), body + 1):
        packed = _flow(groups, columns, target, hard=False)
        if packed is not None:
            return packed
    # Doesn't fit at any height (small window): show what fits, count the rest.
    return _flow(groups, columns, body, hard=True) or ([[]], total)


def render(width: int, height: int) -> list[str]:
    """The whole sheet, as ready-to-write lines (no trailing newlines)."""
    groups = collect()
    key_w, natural_w = _widths(groups)
    # Trade label width for columns: a narrower label that buys another column
    # shows strictly more shortcuts, and labels are the part that survives being
    # shortened (the combos are the whole point of the sheet). MIN_LABEL is where
    # trimming stops being worth it.
    columns, label_w = 1, max(4, min(natural_w, width - 4 - key_w))
    for cols in range(2, len(groups) + 1):
        # width - 2: one column of left margin, one kept free at the right edge
        # so a full-width line never leaves the cursor in pending-wrap state.
        avail = (width - 2 - (cols - 1) * COL_GAP) // cols - key_w - 2
        if avail < MIN_LABEL:
            break
        columns, label_w = cols, min(natural_w, avail)
    col_w = key_w + 2 + label_w

    # Body height: title bar + blank + blank + footer eat 4 lines.
    body = max(3, height - 4)
    grid, elided = _pack(groups, columns, body)
    lines: list[list[Cell]] = []
    for r in range(max(len(c) for c in grid)):
        lines.append([col[r] if r < len(col) else None for col in grid])

    out = []
    title = " atajos de kitty "
    out.append(styled(title.ljust(width - 1), fg=FG_TITLE, bg=BG_TITLE, bold=True))
    out.append("")
    for row in lines:
        cells = []
        for cell in row:
            if cell is None:
                cells.append(" " * col_w)
            elif cell[1] == "":  # group heading
                cells.append(styled(cell[0][:col_w].ljust(col_w), fg=FG_GROUP, bold=True))
            else:
                combo, label = cell
                if len(label) > label_w:
                    label = label[: max(1, label_w - 1)] + "…"
                cells.append(
                    styled(combo.rjust(key_w), fg=FG_KEY)
                    + "  "
                    + styled(label.ljust(label_w), fg=FG_LABEL)
                )
        out.append(" " + (" " * COL_GAP).join(cells).rstrip())
    footer = "cualquier tecla cierra"
    if elided:
        extra = f"  ·  +{elided} más en ⌥⌘, (debug_config)"
        footer += extra if len(footer) + len(extra) <= width - 2 else f"  ·  +{elided}"
    out.append("")
    out.append(" " + styled(footer[: width - 2], fg=FG_DIM, italic=True))
    return out


# --- Single instance --------------------------------------------------------

LOCK = os.path.join(cache_dir(), "shortcuts-kitten.pid")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _take_lock() -> bool:
    """False if another cheatsheet already owns the screen (key auto-repeat)."""
    for _ in range(2):
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                with open(LOCK) as f:
                    pid = int(f.read().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            if pid and pid != os.getpid() and _alive(pid):
                return False
            try:  # stale: owner died without cleaning up
                os.unlink(LOCK)
            except OSError:
                return False
            continue
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return True
    return False


def _release_lock() -> None:
    try:
        with open(LOCK) as f:
            if int(f.read().strip() or 0) != os.getpid():
                return
    except (OSError, ValueError):
        return
    try:
        os.unlink(LOCK)
    except OSError:
        pass


# --- Kitten -----------------------------------------------------------------


class Cheatsheet(Handler):

    def initialize(self) -> None:
        # No keyboard-protocol setup needed: the kitten TUI already pushes
        # progressive enhancement flags 31, and bit 2 of those is "report event
        # types" -- so key *releases* reach on_key_event and letting go of the
        # shortcut dismisses the sheet.
        self.write(set_cursor_visible(False))
        self.draw_screen()

    def finalize(self) -> None:
        self.write(set_cursor_visible(True))

    def draw_screen(self) -> None:
        self.write(clear_screen())
        for line in render(self.screen_size.cols, self.screen_size.rows):
            self.print(line)

    def on_resize(self, screen_size: Any) -> None:
        self.draw_screen()

    # Any key event closes: a RELEASE ends a hold-to-peek, a PRESS ends a
    # tap-to-pin. on_text/on_interrupt/on_eot cover terminals or modes where
    # the key protocol isn't in effect.
    def on_key_event(self, key_event: Any, in_bracketed_paste: bool = False) -> None:
        self.quit_loop(0)

    def on_text(self, text: str, in_bracketed_paste: bool = False) -> None:
        self.quit_loop(0)

    def on_interrupt(self) -> None:
        self.quit_loop(0)

    def on_eot(self) -> None:
        self.quit_loop(0)

    def on_term(self) -> None:
        self.quit_loop(0)


def main(args: list[str]) -> None:
    if not _take_lock():
        return
    try:
        Loop().loop(Cheatsheet())
    finally:
        _release_lock()


if __name__ == "__main__":
    main(sys.argv)
