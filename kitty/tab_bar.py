#!/usr/bin/env python3
"""Custom kitty tab bar — accessible + "personality" per tab.

Each tab shows: {index} {contextual icon} {title}

- index is always visible: a colorblind-safe, collision-free identifier that
  doesn't depend on color or icon at all.
- icon reflects what's actually running in the tab (exe) or, failing that,
  what kind of project the cwd belongs to (Android/Node/Rust/Go/Python/git/
  home) — real "personality" instead of a decorative fixed glyph.
- color is a secondary cue only: a rotating Catppuccin Mocha accent, ordered
  to keep red and green (the pair most confused by red-green color vision
  deficiency) far apart in the rotation.
- the active tab is additionally bold and filled, so activity never depends
  on color alone.

Switching tabs is animated (see the "Animation" section below); the animation
is decoration only, every cue above still reads on a single static frame.

The bar lays itself out (see "Layout planning"): the window controls and the
"+" are reserved at the right edge first and never disappear, and the tabs
degrade to fit what's left -- title, then index+icon, then folded away behind a
chip that opens kitty's tab picker.

Enabled via `tab_bar_style custom` in kitty.conf.
"""

import os

from kitty.fast_data_types import (
    Screen,
    add_timer,
    get_boss,
    mark_tab_bar_dirty,
    monotonic,
    remove_timer,
    wakeup_main_loop,
    wcswidth,
)
from kitty.tab_bar import DrawData, ExtraData, TabBarData, as_rgb

# --- Colors (Catppuccin Mocha) ---------------------------------------------

# Rotation reordered vs. a naive hue wheel so red and green never sit next to
# each other in tab order -- the pair most confused under deuteranopia /
# protanopia. Color is a secondary cue here (index + icon carry the primary
# signal), but there's no reason to make it worse than it has to be.
PALETTE = [
    0x89B4FA,  # blue
    0xFAB387,  # peach
    0x94E2D5,  # teal
    0xCBA6F7,  # mauve
    0xF9E2AF,  # yellow
    0xA6E3A1,  # green
    0xF5C2E7,  # pink
    0xF38BA8,  # red
]

DARK_FG = 0x1E1E2E     # Mocha base — text color on filled accent tabs
DIM_BG = 0x181825      # Mocha mantle — background of inactive tabs
BAR_BG = 0x11111B      # Mocha crust — tab_bar_background
DIM_SEP = 0x313244     # Mocha surface0 — faint separator between two inactive tabs
ATTENTION = 0xF38BA8   # Mocha red — overrides accent when a tab needs attention
NEW_FG = 0x7F849C      # Mocha overlay1 — the "+" button (5.1:1 on BAR_BG, AA text)

SEP_HARD = ""  # solid powerline right-pointing triangle (around active tab)
SEP_SOFT = ""  # thin right-pointing chevron (between two inactive tabs)

# --- Icons (Nerd Font, codepoints verified against the installed font's
# cmap -- see dev-* / md-* / seti-* glyph names in nerd-fonts) --------------

ICON_TERMINAL = ""
ICON_HOME = ""
ICON_GIT_REPO = ""
ICON_GIT_EXE = ""
ICON_PYTHON = ""
ICON_NODE = ""
ICON_DOCKER = ""
ICON_RUST = ""
ICON_GO = ""
ICON_ANDROID = ""
ICON_VIM = ""
ICON_NEOVIM = ""
ICON_SSH = "\U000F08C0"
ICON_ROBOT = "\U000F06A9"   # Claude / AI agent CLIs
ICON_MONITOR = ""     # htop/btop/top

# OS-window controls + per-tab close, drawn by us since hide_window_decorations
# hides macOS's own traffic lights. Codepoints checked against nerd-fonts'
# glyphnames.json (md-window_minimize/md-window_maximize/md-close/md-close_circle).
BTN_MIN = "\U000F05B0"    # md-window_minimize
BTN_MAX = "\U000F05AF"    # md-window_maximize
BTN_CLOSE = "\U000F0156"  # md-close
TAB_CLOSE = "\U000F0156"  # md-close (flat -- same glyph as BTN_CLOSE, low-key)
BTN_NEW = "\U000F0415"    # md-plus -- new tab, drawn right after the last tab
ICON_MORE = "\U000F01D9"  # md-dots_horizontal -- the "N tabs folded away" chip

# Foreground process (by basename, lowercase) -> icon. Checked first: this is
# literally what's running right now, the strongest "personality" signal.
EXE_ICONS = {
    "claude": ICON_ROBOT,
    "ssh": ICON_SSH,
    "mosh-client": ICON_SSH,
    "vim": ICON_VIM,
    "vi": ICON_VIM,
    "nvim": ICON_NEOVIM,
    "python": ICON_PYTHON,
    "python3": ICON_PYTHON,
    "ipython": ICON_PYTHON,
    "node": ICON_NODE,
    "npm": ICON_NODE,
    "npx": ICON_NODE,
    "yarn": ICON_NODE,
    "pnpm": ICON_NODE,
    "docker": ICON_DOCKER,
    "docker-compose": ICON_DOCKER,
    "git": ICON_GIT_EXE,
    "lazygit": ICON_GIT_EXE,
    "tig": ICON_GIT_EXE,
    "cargo": ICON_RUST,
    "rustc": ICON_RUST,
    "go": ICON_GO,
    "htop": ICON_MONITOR,
    "btop": ICON_MONITOR,
    "top": ICON_MONITOR,
}

# Shells: when the foreground process is just the login shell, fall back to
# reading the cwd for project markers instead of showing a generic glyph.
SHELLS = {"zsh", "bash", "fish", "sh", "-zsh", "-bash", "-fish"}

# cwd marker file/dir -> icon, checked in priority order (first match wins).
CWD_MARKERS = [
    ("AndroidManifest.xml", ICON_ANDROID),
    ("gradlew", ICON_ANDROID),
    ("settings.gradle.kts", ICON_ANDROID),
    ("settings.gradle", ICON_ANDROID),
    ("build.gradle.kts", ICON_ANDROID),
    ("build.gradle", ICON_ANDROID),
    ("Cargo.toml", ICON_RUST),
    ("go.mod", ICON_GO),
    ("package.json", ICON_NODE),
    ("pyproject.toml", ICON_PYTHON),
    ("requirements.txt", ICON_PYTHON),
    ("setup.py", ICON_PYTHON),
    ("Dockerfile", ICON_DOCKER),
    ("docker-compose.yml", ICON_DOCKER),
    ("docker-compose.yaml", ICON_DOCKER),
]

_home = os.path.expanduser("~")
_cwd_icon_cache: dict[str, str] = {}

# --- Clickable regions (window buttons + per-tab close) --------------------
#
# kitty has no public API for clickable regions in a custom tab bar (see
# https://github.com/kovidgoyal/kitty/discussions/4447). The workaround: while
# drawing, record the cell-column span of everything that should react to a
# click; a monkeypatch of TabManager.handle_tab_bar_mouse (bottom of this
# file) consults this table before falling back to kitty's normal handling.
_click_regions: dict[int, dict[str, list]] = {}

# Window buttons: (glyph, boss method invoked on click, draw color). Close is
# tinted with ATTENTION (Mocha red) since it closes the whole OS window with
# no confirmation and there's no hover to warn otherwise; min/max stay a
# calm DIM_SEP so the destructive one is the only one that stands out.
WINDOW_BUTTONS = (
    (BTN_MIN, "minimize_macos_window", DIM_SEP),
    (BTN_MAX, "toggle_maximized", DIM_SEP),
    (BTN_CLOSE, "close_os_window", ATTENTION),
)


def _reset_regions(os_window_id: int) -> None:
    _click_regions[os_window_id] = {"win": [], "tab": []}


def _register(os_window_id: int, kind: str, start: int, end: int, payload: object) -> None:
    _click_regions.setdefault(os_window_id, {"win": [], "tab": []})[kind].append((start, end, payload))


def _icon_for_cwd(cwd: str) -> str:
    cached = _cwd_icon_cache.get(cwd)
    if cached is not None:
        return cached
    icon = ICON_TERMINAL
    try:
        entries = set(os.listdir(cwd))
    except OSError:
        entries = set()
    for marker, marker_icon in CWD_MARKERS:
        if marker in entries:
            icon = marker_icon
            break
    else:
        if ".git" in entries:
            icon = ICON_GIT_REPO
        elif os.path.normpath(cwd) == os.path.normpath(_home):
            icon = ICON_HOME
    _cwd_icon_cache[cwd] = icon
    return icon


def _icon_for_tab(tab_id: int) -> str:
    boss = get_boss()
    t = boss.tab_for_id(tab_id) if boss else None
    if t is None:
        return ICON_TERMINAL
    exe = os.path.basename((t.get_exe_of_active_window() or "")).lower()
    if exe and exe not in SHELLS:
        icon = EXE_ICONS.get(exe)
        if icon:
            return icon
    cwd = t.get_cwd_of_active_window() or ""
    return _icon_for_cwd(cwd) if cwd else ICON_TERMINAL


def _accent(index: int) -> int:
    return PALETTE[(index - 1) % len(PALETTE)]


# --- Animation ---------------------------------------------------------------
#
# kitty has no animation API for tab bars: draw_tab only runs when kitty decides
# the bar is dirty, so an animation has to drive its own frames. add_timer gives
# the clock and mark_tab_bar_dirty forces the redraw -- and it repaints the bar
# strip alone, not the windows underneath, which is what makes this cheap. The
# timer is removed the moment nothing is animating, so an idle kitty costs
# exactly zero extra frames (nothing here pulses forever).
#
# Hard constraint: draw_tab runs twice per frame, once to measure widths
# (extra_data.for_layout) and once to draw. Anything that changes a tab's width
# between frames makes kitty re-lay-out the bar mid-animation and the whole
# thing judders. So every effect below is either color-only or a glyph swap
# inside a cell that was already reserved -- the measured width is identical on
# every frame of every animation.

FRAME = 1 / 60
FADE_DURATION = 0.16     # tab switch crossfade
PULSE_PERIOD = 0.2       # one attention pulse
PULSE_COUNT = 3
PULSE_DIM = 0.55         # dimmest point of a pulse, as a fraction of full
# One extra frame of liveness after an animation's nominal end, so its final
# frame is drawn at t == 1.0 exactly. Without it the bar keeps the
# second-to-last frame's colors indefinitely -- a few percent off the settled
# ones, which is the kind of thing you only notice as "the colors look wrong".
GRACE = FRAME * 2

# Partial block glyphs, thinnest to full. All single-width, which is what lets
# the accent bar animate inside the prefix's existing leading space.
BLOCKS = "▏▎▍▌▋▊▉█"

_active_tab: dict[int, int] = {}                 # os_window_id -> active tab id
_fade: dict[int, tuple[float, int, int]] = {}    # os_window_id -> (start, from, to)
_attn: dict[int, dict[int, float]] = {}          # os_window_id -> tab id -> pulse start
_frame_t: dict[int, float] = {}                  # os_window_id -> eased progress, this frame
_timer: int | None = None


def _lerp(a: int, b: int, t: float) -> int:
    """Interpolate two 0xRRGGBB ints per channel. Plain sRGB: the endpoints here
    are close enough in luminance that the extra cost of a linear-light round
    trip buys nothing visible."""
    if t <= 0.0:
        return a
    if t >= 1.0:
        return b
    r = round(((a >> 16) & 0xFF) + ((((b >> 16) & 0xFF) - ((a >> 16) & 0xFF)) * t))
    g = round(((a >> 8) & 0xFF) + ((((b >> 8) & 0xFF) - ((a >> 8) & 0xFF)) * t))
    bl = round((a & 0xFF) + (((b & 0xFF) - (a & 0xFF)) * t))
    return (r << 16) | (g << 8) | bl


def _scale(color: int, factor: float) -> int:
    r = round(((color >> 16) & 0xFF) * factor)
    g = round(((color >> 8) & 0xFF) * factor)
    b = round((color & 0xFF) * factor)
    return (r << 16) | (g << 8) | b


def _ease_out(t: float) -> float:
    """Cubic ease-out: most of the distance is covered early, so a 160ms fade
    still feels instant to the hand that pressed the key."""
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return 1.0 - (1.0 - t) ** 3


def _start_timer() -> None:
    global _timer
    if _timer is None:
        _timer = add_timer(_tick, FRAME, True)


def _live(os_window_id: int) -> bool:
    now = monotonic()
    alive = False
    fade = _fade.get(os_window_id)
    if fade is not None:
        if now - fade[0] < FADE_DURATION + GRACE:
            alive = True
        else:
            _fade.pop(os_window_id, None)
    # Finished pulses are deliberately *not* dropped here: the recorded start
    # time is also the "this tab already pulsed" marker that stops it firing
    # again on every repaint. draw_tab clears it when attention goes away.
    starts = _attn.get(os_window_id)
    if starts:
        limit = PULSE_PERIOD * PULSE_COUNT + GRACE
        if any(now - start < limit for start in starts.values()):
            alive = True
    return alive


def _tick(timer_id: int) -> None:
    global _timer
    alive = False
    for os_window_id in {*_fade, *_attn}:
        if _live(os_window_id):
            # The second argument is the dirty flag itself -- passing False
            # here marks the bar *clean* and the animation never renders.
            mark_tab_bar_dirty(os_window_id, True)
            alive = True
    if alive:
        # Marking dirty only queues the repaint; without kicking the main loop
        # it lands whenever kitty next wakes for its own reasons. Measured on
        # kitty 0.47: nearly twice the frames actually delivered per fade.
        wakeup_main_loop()
    else:
        remove_timer(timer_id)
        _timer = None


def _sync(os_window_id: int) -> None:
    """Once per drawn frame: notice a tab switch and freeze this frame's clock.

    The active tab is read from the boss rather than inferred from `is_active`
    while walking the tabs, because the outgoing tab may be drawn *before* the
    incoming one -- inferring would leave it a frame behind and make it pop
    instead of fade.
    """
    boss = get_boss()
    tab_manager = boss.os_window_map.get(os_window_id) if boss else None
    active = getattr(tab_manager, "active_tab", None) if tab_manager is not None else None
    current = getattr(active, "id", None)
    if current is not None:
        previous = _active_tab.get(os_window_id)
        _active_tab[os_window_id] = current
        if previous is not None and previous != current:
            _fade[os_window_id] = (monotonic(), previous, current)
            _start_timer()
    fade = _fade.get(os_window_id)
    # Every tab in a frame shares one `t`. Sampling the clock per tab instead
    # would smear a frame across a millisecond of drift, and the powerline
    # separator (drawn from its neighbour's color) would never quite match.
    _frame_t[os_window_id] = _ease_out((monotonic() - fade[0]) / FADE_DURATION) if fade else 1.0


def _colors(os_window_id: int, tab_id: int, is_active: bool, accent: int) -> tuple[int, int]:
    """(fg, bg) for a tab, crossfaded if it's an end of the current switch."""
    fade = _fade.get(os_window_id)
    if fade is not None:
        t = _frame_t.get(os_window_id, 1.0)
        if t < 1.0:
            _, outgoing, incoming = fade
            if tab_id == incoming:
                return _lerp(accent, DARK_FG, t), _lerp(DIM_BG, accent, t)
            if tab_id == outgoing:
                return _lerp(DARK_FG, accent, t), _lerp(accent, DIM_BG, t)
    return (DARK_FG, accent) if is_active else (accent, DIM_BG)


def _attention_color(os_window_id: int, tab_id: int) -> int:
    """ATTENTION, pulsed a few times when the tab first raises its hand, then
    steady. A tab that stays unattended shouldn't keep the GPU awake for it."""
    starts = _attn.setdefault(os_window_id, {})
    start = starts.get(tab_id)
    if start is None:
        start = starts[tab_id] = monotonic()
        _start_timer()
    elapsed = monotonic() - start
    if elapsed >= PULSE_PERIOD * PULSE_COUNT:
        return ATTENTION
    # Triangle wave starting and ending bright, so the pulse dips rather than
    # flashes on -- the tab is always at least readable.
    phase = (elapsed % PULSE_PERIOD) / PULSE_PERIOD
    return _lerp(_scale(ATTENTION, PULSE_DIM), ATTENTION, abs(1.0 - 2.0 * phase))


def _fill_glyph(os_window_id: int, is_active: bool) -> str:
    """The accent bar the incoming tab fills from the left, drawn into the
    prefix's existing leading space -- one cell, always, so width never moves.
    It vanishes on its own at the end of the fade: by then the tab background
    *is* the accent, so a full block in the accent color is already invisible."""
    if not is_active or _fade.get(os_window_id) is None:
        return " "
    t = _frame_t.get(os_window_id, 1.0)
    if t >= 1.0:
        return " "
    return BLOCKS[min(len(BLOCKS) - 1, int(t * len(BLOCKS)))]


# --- Layout planning ---------------------------------------------------------
#
# kitty hands each tab a budget (max_tab_length) but never guarantees the tabs
# *sum* to <= screen.columns: its measuring pass draws every tab with cursor.x
# reset to 0, so nothing stops the drawing pass from running off the right edge.
# Our prefix ("{index} {icon} ") doesn't truncate either, so a dozen-odd tabs
# overflow a normal window and whatever is drawn last -- the "+" and the window
# buttons -- falls off it. That's why they used to just vanish.
#
# So the bar is laid out here instead: reserve the right-hand controls first,
# spend what's left on tabs, and degrade the tabs (full title -> index+icon ->
# folded away behind a "⋯N" chip that opens kitty's tab picker) until they
# fit. kitty's max_tab_length is deliberately ignored.
#
# The plan is computed once per frame during the for_layout pass -- which always
# runs, and always before the drawing pass -- and reused while drawing, so both
# passes measure identical widths. That also keeps the hard constraint above:
# the plan only changes when the active tab or the window size does, never
# between two frames of the same fade.

TITLE_MAX = 28   # one long title shouldn't eat the room its neighbours need
TITLE_MIN = 4    # a title shorter than this is noise; stay compact instead
TITLE_ACTIVE = 18  # the active tab keeps this much title even if it costs a neighbour

_plans: dict[int, dict | None] = {}


def _right_width(draw_new: bool, buttons) -> int:
    # wcswidth, not len(): Nerd Font glyphs can render double-width, and an
    # under-count here would leave the cluster short of the true right edge.
    w = wcswidth("".join(f" {glyph} " for glyph, *_ in buttons))
    return w + (wcswidth(f" {BTN_NEW} ") if draw_new else 0)


RIGHT_W = _right_width(True, WINDOW_BUTTONS)


def _tab_text(index: int, icon: str, title: str) -> str:
    """The exact cells a tab draws after its one-cell accent bar. Single source
    of truth: the planner measures this string, draw_tab draws that string."""
    return f"{index} {icon} {title} " if title else f"{index} {icon} "


def _truncate(title: str, budget: int) -> str:
    """Truncate to a *cell* budget. wcswidth per character rather than len():
    a CJK or emoji title counts double and would otherwise overflow its tab."""
    if budget <= 0:
        return ""
    if wcswidth(title) <= budget:
        return title
    out, w = "", 0
    for ch in title:
        cw = wcswidth(ch)
        if w + cw > budget - 1:
            break
        out += ch
        w += cw
    return f"{out}…"


def _frame_tabs(os_window_id: int):
    """This frame's TabBarData for every tab. kitty stores it on the TabBar
    before either pass runs, which is what lets tab 1 plan for all of them.
    Returning None makes draw_tab fall back to the old unplanned path rather
    than crash, should a future kitty rename the attribute."""
    boss = get_boss()
    tab_manager = boss.os_window_map.get(os_window_id) if boss else None
    tabs = getattr(getattr(tab_manager, "tab_bar", None), "last_laid_out_tabs", None)
    return list(tabs) if tabs else None


def _plan(draw_data: DrawData, columns: int) -> dict | None:
    os_window_id = draw_data.os_window_id
    tabs = _frame_tabs(os_window_id)
    if not tabs:
        return None
    n = len(tabs)
    active = next((i for i, t in enumerate(tabs) if t.is_active), 0)

    icons = []
    for t in tabs:
        icon = _icon_for_tab(t.tab_id)
        if t.needs_attention and not t.is_active:
            icon = draw_data.tab_activity_symbol or icon
        icons.append(icon)
    compact = [1 + wcswidth(_tab_text(i + 1, icons[i], "")) for i in range(n)]
    close_w = wcswidth(f"{TAB_CLOSE} ")
    # Worst case chip width (as many digits as there are tabs), so reserving it
    # can't shift once the real hidden count is known -- a one-cell overshoot
    # just lands in the padding before the right-hand cluster.
    chip_w = wcswidth(f" {ICON_MORE}{n} ")
    # Reserved up front rather than left to the title pass below: compact tabs
    # are cheap enough that a bar full of them eats every last cell, and a bar
    # where even the active tab is a bare number is worse than one that folds
    # a few more tabs away.
    active_title = _truncate(tabs[active].title or "", TITLE_ACTIVE)
    active_cost = wcswidth(active_title) + 1 + close_w if active_title else 0

    # The right-hand controls are only shed in a bar too narrow to hold even one
    # compact tab beside them. Close goes last of the three: it's the only one
    # with no keyboard equivalent bound in kitty.conf.
    needs_chip = sum(compact) + max(0, n - 1) + active_cost > columns - RIGHT_W
    reserve = chip_w if needs_chip else 0
    draw_new, buttons = True, WINDOW_BUTTONS
    for draw_new, buttons in (
        (True, WINDOW_BUTTONS),
        (False, WINDOW_BUTTONS),
        (False, WINDOW_BUTTONS[-1:]),
        (False, ()),
    ):
        if columns - _right_width(draw_new, buttons) - reserve >= compact[active]:
            break
    right_w = _right_width(draw_new, buttons)
    budget = columns - right_w - reserve

    widths = compact[:]
    hidden = [False] * n

    def total() -> int:
        visible = [i for i in range(n) if not hidden[i]]
        return sum(widths[i] for i in visible) + max(0, len(visible) - 1)

    # Fold away the tabs furthest from the active one first (ties: the later
    # one, so the bar keeps its leading tabs). The active tab is never folded.
    for i in sorted(range(n), key=lambda i: (-abs(i - active), -i)):
        if total() + active_cost <= budget:
            break
        if i != active:
            hidden[i] = True

    texts = [_tab_text(i + 1, icons[i], "") for i in range(n)]
    closes = [False] * n
    # Spend whatever is left on titles, nearest the active tab first (the active
    # tab itself wins the tie), so "a few expanded" falls out of the budget
    # rather than being a fixed count. `continue`, not `break`: a tab further
    # out with a short title can still fit after a long one didn't.
    for i in sorted(range(n), key=lambda i: (abs(i - active), i)):
        if hidden[i]:
            continue
        extra_close = close_w if tabs[i].is_active else 0
        room = budget - total() - 1 - extra_close
        if room < TITLE_MIN:
            continue
        title = _truncate(tabs[i].title or "", min(TITLE_MAX, room))
        if not title:
            continue
        texts[i] = _tab_text(i + 1, icons[i], title)
        widths[i] = 1 + wcswidth(texts[i]) + extra_close
        closes[i] = tabs[i].is_active

    visible = [i for i in range(n) if not hidden[i]]
    # Each visible tab needs its *next visible* neighbour, not extra_data's, or
    # the powerline seam would take its color from a tab that isn't drawn.
    following: dict[int, tuple | None] = {}
    for k, i in enumerate(visible):
        j = visible[k + 1] if k + 1 < len(visible) else None
        following[tabs[i].tab_id] = None if j is None else (
            j + 1, tabs[j].tab_id, tabs[j].needs_attention, tabs[j].is_active
        )
    hidden_n = n - len(visible)
    return {
        "columns": columns,
        "text": {tabs[i].tab_id: texts[i] for i in visible},
        "close": {tabs[i].tab_id: closes[i] for i in visible},
        "following": following,
        "chip": f" {ICON_MORE}{hidden_n} " if hidden_n else "",
        "chip_attention": any(
            hidden[i] and tabs[i].needs_attention and not tabs[i].is_active for i in range(n)
        ),
        "draw_new": draw_new,
        "buttons": tuple(buttons),
        "right_w": right_w,
    }


def draw_tab(
    draw_data: DrawData,
    screen: Screen,
    tab: TabBarData,
    before: int,
    max_tab_length: int,
    index: int,
    is_last: bool,
    extra_data: ExtraData,
) -> int:
    os_window_id = draw_data.os_window_id
    if index == 1:
        if not extra_data.for_layout:
            _reset_regions(os_window_id)
            _sync(os_window_id)
        cached = _plans.get(os_window_id)
        if extra_data.for_layout or cached is None or cached["columns"] != screen.columns:
            _plans[os_window_id] = _plan(draw_data, screen.columns)
    plan = _plans.get(os_window_id)

    if plan is None:
        # Unplanned fallback (see _frame_tabs): one tab at a time, kitty's own
        # per-tab budget, and the right-hand cluster only if it happens to fit.
        icon = _icon_for_tab(tab.tab_id)
        if tab.needs_attention and not tab.is_active:
            icon = draw_data.tab_activity_symbol or icon
        close_reserve = wcswidth(f"{TAB_CLOSE} ") if tab.is_active else 0
        room = max_tab_length - wcswidth(_tab_text(index, icon, "")) - 1 - close_reserve
        text = _tab_text(index, icon, _truncate(tab.title or "", room))
        draw_close = tab.is_active
        following = None
        if extra_data.next_tab is not None:
            nt = extra_data.next_tab
            following = (index + 1, nt.tab_id, nt.needs_attention, nt.is_active)
    else:
        text = plan["text"].get(tab.tab_id)
        draw_close = plan["close"].get(tab.tab_id, False)
        following = plan["following"].get(tab.tab_id)

    # text is None => this tab is folded into the overflow chip. It draws
    # nothing and reports zero width, which also gives it an empty CellRange, so
    # a click can never land on it.
    if text is not None:
        accent = _accent(index)
        attention = tab.needs_attention and not tab.is_active
        if attention:
            accent = _attention_color(os_window_id, tab.tab_id)
        else:
            # Forget the pulse so the tab pulses again next time it needs attention.
            _attn.get(os_window_id, {}).pop(tab.tab_id, None)

        fg, bg = _colors(os_window_id, tab.tab_id, tab.is_active, accent)
        screen.cursor.bold = tab.is_active
        # Drawn in two pieces only so the accent bar can carry its own
        # foreground; the rest is byte-identical to what the planner measured.
        bar = _fill_glyph(os_window_id, tab.is_active)
        screen.cursor.fg = as_rgb(accent)
        screen.cursor.bg = as_rgb(bg)
        screen.draw(bar)
        screen.cursor.fg = as_rgb(fg)
        screen.draw(text)
        screen.cursor.bold = False

        if draw_close:
            close_start = screen.cursor.x
            screen.cursor.fg = as_rgb(fg)
            screen.cursor.bg = as_rgb(bg)
            screen.draw(f"{TAB_CLOSE} ")
            if not extra_data.for_layout:
                _register(os_window_id, "tab", close_start, screen.cursor.x, tab.tab_id)

        if following is not None:
            next_index, next_id, next_attention, next_active = following
            # The neighbour's *animated* background, not its settled one: the
            # separator is drawn on this tab's pass, so reading the raw accent
            # would leave the seam a full transition out of step during a fade.
            next_accent = _accent(next_index)
            if next_attention and not next_active:
                next_accent = _attention_color(os_window_id, next_id)
            next_bg = _colors(os_window_id, next_id, next_active, next_accent)[1]
            if bg != next_bg:
                # Hard triangle: only ever touches the active tab, so the seam
                # always transitions cleanly between the two real segment colors.
                screen.cursor.fg = as_rgb(bg)
                screen.cursor.bg = as_rgb(next_bg)
                screen.draw(SEP_HARD)
            else:
                # Two inactive tabs in a row: a faint hairline instead of a loud
                # accent-colored triangle between them.
                screen.cursor.fg = as_rgb(DIM_SEP)
                screen.cursor.bg = as_rgb(DIM_BG)
                screen.draw(SEP_SOFT)

    if is_last:
        # Runs whether or not this tab drew anything: the chip and the
        # right-hand cluster belong to the bar, not to the last tab.
        chip = plan["chip"] if plan is not None else ""
        right_w = plan["right_w"] if plan is not None else RIGHT_W
        draw_new = plan["draw_new"] if plan is not None else True
        buttons = plan["buttons"] if plan is not None else WINDOW_BUTTONS
        if extra_data.for_layout:
            # Just reserve the width (kitty's recommended measurement-pass
            # behavior) instead of padding to the real screen edge below --
            # cursor.x is reset to 0 per tab during measurement, so padding to
            # screen.columns here would wrongly report this tab as wanting to
            # be nearly full-width.
            screen.cursor.x += wcswidth(chip) + right_w
        else:
            if chip:
                chip_start = screen.cursor.x
                # A folded-away tab still has to be able to raise its hand, so
                # the chip carries the attention color (id -1: the chip is not
                # a tab, it just borrows the pulse bookkeeping).
                chip_fg = _attention_color(os_window_id, -1) if plan["chip_attention"] else NEW_FG
                screen.cursor.fg = as_rgb(chip_fg)
                screen.cursor.bg = as_rgb(BAR_BG)
                screen.draw(chip)
                _register(os_window_id, "win", chip_start, screen.cursor.x, "select_tab")
            if plan is None or not plan["chip_attention"]:
                _attn.get(os_window_id, {}).pop(-1, None)
            # Guaranteed >= 0 by the planner; clamped anyway so an unplanned
            # fallback frame can't wrap the bar onto itself.
            pad = max(0, screen.columns - screen.cursor.x - right_w)
            if pad:
                screen.cursor.fg = screen.cursor.bg = 0
                screen.draw(" " * pad)
            if draw_new:
                # Pinned beside the window cluster rather than trailing the last
                # tab, so it stays at the same pixel as tabs come and go.
                # Brighter than min/max on purpose: it's the only button here
                # that isn't discoverable some other way.
                new_start = screen.cursor.x
                screen.cursor.fg = as_rgb(NEW_FG)
                screen.cursor.bg = as_rgb(BAR_BG)
                screen.draw(f" {BTN_NEW} ")
                _register(os_window_id, "win", new_start, screen.cursor.x, "new_tab")
            for glyph, action, color in buttons:
                start = screen.cursor.x
                screen.cursor.fg = as_rgb(color)
                screen.cursor.bg = as_rgb(BAR_BG)
                screen.draw(f" {glyph} ")
                _register(os_window_id, "win", start, screen.cursor.x, action)

    screen.cursor.fg = screen.cursor.bg = 0
    return screen.cursor.x


# --- Mouse click handling ---------------------------------------------------
#
# kitty has no public hook for clicks on custom tab-bar content (see
# https://github.com/kovidgoyal/kitty/discussions/4447), so intercept clicks
# at the TabManager level: a press/release inside a region we recorded above
# is swallowed and dispatched to our action; anything else (motion/drag,
# middle-click, clicks outside our regions) falls through to kitty's normal
# handling unchanged. This depends on TabManager.handle_tab_bar_mouse's
# signature (kitty 0.47.2, kitty/tabs.py) -- if a future kitty renames or
# reshapes it, this patch becomes a no-op fallthrough rather than crashing.
from kitty.fast_data_types import GLFW_MOUSE_BUTTON_LEFT, GLFW_PRESS, GLFW_RELEASE  # noqa: E402
from kitty.tabs import TabManager  # noqa: E402

_original_handle_tab_bar_mouse = TabManager.handle_tab_bar_mouse


def _hit_test(tab_manager: TabManager, x: float, y: float) -> tuple[str, object] | None:
    tb = tab_manager.tab_bar
    if not tb.laid_out_once:
        return None
    g = tb.window_geometry
    if not (g.left <= x < g.right and g.top <= y < g.bottom):
        return None
    col = int((x - g.left) // tb.cell_width)
    regions = _click_regions.get(tab_manager.os_window_id)
    if not regions:
        return None
    for start, end, action in regions["win"]:
        if start <= col < end:
            return ("win", action)
    for start, end, tab_id in regions["tab"]:
        if start <= col < end:
            return ("tab", tab_id)
    return None


def _handle_tab_bar_mouse_with_buttons(
    self: TabManager, x: float, y: float, button: int, modifiers: int, action: int
) -> None:
    if button == GLFW_MOUSE_BUTTON_LEFT and action in (GLFW_PRESS, GLFW_RELEASE):
        hit = _hit_test(self, x, y)
        if hit is not None:
            if action == GLFW_RELEASE:
                kind, payload = hit
                boss = get_boss()
                if kind == "win":
                    if payload == "toggle_maximized":
                        boss.toggle_maximized(self.os_window_id)
                    else:
                        getattr(boss, payload)()
                else:
                    t = self.tab_for_id(payload)
                    if t is not None:
                        boss.close_tab(t)
            return  # swallow press+release inside our regions either way
    _original_handle_tab_bar_mouse(self, x, y, button, modifiers, action)


TabManager.handle_tab_bar_mouse = _handle_tab_bar_mouse_with_buttons
