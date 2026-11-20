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
import re
import socket
import time
from urllib.parse import unquote, urlparse

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
# Inactive tabs have no fill of their own: they float on the bar as accent text,
# so only the active tab reads as a solid "lit" segment (HUD look).
DIM_BG = 0x11111B      # Mocha crust — same as BAR_BG on purpose
BAR_BG = 0x11111B      # Mocha crust — tab_bar_background
DIM_SEP = 0x45475A     # Mocha surface1 — faint slash between two inactive tabs
ATTENTION = 0xF38BA8   # Mocha red — overrides accent when a tab needs attention
NEW_FG = 0xA6ADC8      # Mocha subtext0 — the "+" button / overflow chip (~8:1 on BAR_BG)
INACTIVE_FG = 0xA6ADC8 # Mocha subtext0 — icon+title of unlit tabs (~8:1 on BAR_BG)
BTN_FG = 0x7F849C      # Mocha overlay1 — min/max buttons (5.1:1 on BAR_BG, AA text)

SEP_HARD = "\ue0bc"  # solid slant: angled cut on both sides of the lit tab
SEP_SOFT = "\ue0bd"  # thin slash between two unlit tabs

# --- Icons (Nerd Font, codepoints verified against the installed font's
# cmap -- see dev-* / md-* / seti-* glyph names in nerd-fonts) --------------

ICON_TERMINAL = "\uf120"   # fa-terminal: bare ">_" (the old dev-terminal glyph is boxed and reads as a blob at 1 cell)
ICON_HOME = ""
ICON_GIT_REPO = "\ue702"   # dev-git: outline mark, legible at 1 cell
ICON_GIT_EXE = ""
ICON_PYTHON = "\U000F0320"  # md-language_python (dev-python reads as a blob at 1 cell)
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
ICON_MUX = "\U000F0BCC"     # md-view_split_vertical -- terminal multiplexers

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
    "pi": ICON_ROBOT,
    "codex": ICON_ROBOT,
    "gemini": ICON_ROBOT,
    "aider": ICON_ROBOT,
    "herdr": ICON_MUX,
    "tmux": ICON_MUX,
    "zellij": ICON_MUX,
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

# Both caches exist because draw_tab runs twice per frame, and at 60fps during
# an animation: without them every frame would query every tab's foreground
# process (a sysctl round-trip each) and listdir() every cwd.
#   tab icon: short TTL, so starting `nvim` updates the icon within a second.
#   cwd icon: longer TTL (a `git init` shows up eventually) + a size cap, since
#   it's keyed by path and would otherwise grow for the life of the process.
TAB_ICON_TTL = 1.0
CWD_ICON_TTL = 30.0
CWD_CACHE_MAX = 256
_tab_icon_cache: dict[tuple[int, str], tuple[float, str]] = {}
_cwd_icon_cache: dict[str, tuple[float, str]] = {}

# --- Title cleanup -------------------------------------------------------------
#
# Programs (herdr, some prompts) title the tab "host: dir". On a laptop the
# host is always this machine, so it's pure noise that eats the tab's width.
# Only *local* host names are stripped: "user@server: dir" from ssh keeps its
# prefix, because there the host is the information.
def _local_hostnames() -> set[str]:
    names = set()
    try:
        full = socket.gethostname().lower()
        names |= {full, full.split(".")[0]}
    except OSError:
        pass
    return {n for n in names if n}


_LOCAL_HOSTS = _local_hostnames()
_LOCAL_SUFFIX = re.compile(r"^[a-z0-9-]+\.(?:lan|local|home|localdomain): ", re.IGNORECASE)


# A leading status glyph some TUIs animate in their title (Claude Code, etc.):
# a braille spinner frame while working, a static star when idle. At one cell
# the braille frames read as a rendering glitch, and they change ~10x a second.
# Stripped here; a spinning one becomes the steady BADGE_BUSY badge instead.
_SPINNER = re.compile(r"^[\u2800-\u28ff]\s+")
_STATUS_GLYPH = re.compile(r"^[\u2800-\u28ff\u2733\u2736\u273b\u273d\u2722\u00b7\u23fa]\s+")


def _clean_title(title: str) -> str:
    title = _STATUS_GLYPH.sub("", title)
    head, sep, rest = title.partition(": ")
    if sep and rest and "@" not in head and (
        head.lower() in _LOCAL_HOSTS or _LOCAL_SUFFIX.match(title)
    ):
        title = rest
    if title.startswith(_home):
        title = "~" + title[len(_home):]
    return _abbrev_path(title)


def _abbrev_path(title: str) -> str:
    """fish-style: ~/work/client/api/src -> ~/w/c/a/src. Truncating a long
    path from the right cuts off its last component -- the only part that
    tells tabs apart -- so the middle shrinks instead. Non-paths untouched."""
    if not title.startswith(("/", "~/", "…/")) or " " in title:
        return title
    parts = title.split("/")
    if len(parts) <= 3:
        return title
    head, middle, last = parts[0], parts[1:-1], parts[-1]
    short = [p[:2] if p[:1] in ".-_" else p[:1] for p in middle]
    return "/".join([head, *short, last])

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
# no confirmation and there's no hover to warn otherwise. min/max use BTN_FG:
# quiet, but still AA-legible (DIM_SEP, used before, was ~1.4:1 -- invisible).
WINDOW_BUTTONS = (
    (BTN_MIN, "minimize_macos_window", BTN_FG),
    (BTN_MAX, "toggle_maximized", BTN_FG),
    (BTN_CLOSE, "close_os_window", ATTENTION),
)


def _reset_regions(os_window_id: int) -> None:
    _click_regions[os_window_id] = {"win": [], "tab": []}


def _register(os_window_id: int, kind: str, start: int, end: int, payload: object) -> None:
    _click_regions.setdefault(os_window_id, {"win": [], "tab": []})[kind].append((start, end, payload))


def _icon_for_cwd(cwd: str) -> str:
    now = monotonic()
    cached = _cwd_icon_cache.get(cwd)
    if cached is not None and now - cached[0] < CWD_ICON_TTL:
        return cached[1]
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
    if len(_cwd_icon_cache) >= CWD_CACHE_MAX:
        _cwd_icon_cache.clear()
    _cwd_icon_cache[cwd] = (now, icon)
    return icon


def _icon_for_tab(tab_id: int, title: str = "") -> str:
    # Keyed by title too: a `cd` or a new program retitles the tab, and that
    # must not wait out the TTL behind a stale icon.
    now = monotonic()
    # Spinner frames retitle the tab ~10x a second; they mustn't miss the cache.
    key = (tab_id, _STATUS_GLYPH.sub("", title))
    cached = _tab_icon_cache.get(key)
    if cached is not None and now - cached[0] < TAB_ICON_TTL:
        return cached[1]
    icon = _query_icon_for_tab(tab_id)
    if len(_tab_icon_cache) >= CWD_CACHE_MAX:
        _tab_icon_cache.clear()  # closed tabs' ids never come back
    _tab_icon_cache[key] = (now, icon)
    return icon


def _active_cwd(t) -> str:
    """cwd of a Tab's active window. Prefers the path the shell itself reports
    (OSC 7, sent by kitty's shell integration on every prompt and every cd)
    over asking the OS for the foreground process's cwd. Measured: the tab bar
    repaints when the shell retitles the tab in precmd -- before the prompt is
    marked, so `at_prompt` is still False -- and right then the OS lookup
    returned "/" or nothing (starship/git were the newest processes in the
    group). The HUD lost its branch and the icon its repo on half the prompts.
    The shell's report was right every time, and costs no syscall.
    A program that cds on its own keeps showing the shell's directory, which
    is the one you're actually "in". A cwd reported by a remote shell (kitten
    ssh) carries a foreign host and is skipped."""
    w = getattr(t, "active_window", None)
    url = getattr(getattr(w, "screen", None), "last_reported_cwd", None)
    if url:
        try:
            u = urlparse(url.decode("utf-8", "replace") if isinstance(url, bytes) else url)
            host = (u.hostname or "").lower()
            if u.path and (not host or host == "localhost" or host in _LOCAL_HOSTS
                           or host.split(".")[0] in _LOCAL_HOSTS):
                return unquote(u.path)
        except ValueError:
            pass
    return t.get_cwd_of_active_window() or ""


def _query_icon_for_tab(tab_id: int) -> str:
    boss = get_boss()
    t = boss.tab_for_id(tab_id) if boss else None
    if t is None:
        return ICON_TERMINAL
    exe = os.path.basename((t.get_exe_of_active_window() or "")).lower()
    if exe and exe not in SHELLS:
        icon = EXE_ICONS.get(exe)
        if icon:
            return icon
    cwd = _active_cwd(t)
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
FADE_DURATION = 0.12     # tab switch crossfade, = the tab-change shader
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
    """Cubic ease-out: most of the distance is covered early, so a 120ms fade
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


def _colors(
    os_window_id: int, tab_id: int, is_active: bool, accent: int, unlit_fg: int | None = None
) -> tuple[int, int]:
    """(fg, bg) for a tab, crossfaded if it's an end of the current switch.

    unlit_fg is the foreground the tab settles on while inactive (defaults to
    its accent). The index uses the accent, icon+title use INACTIVE_FG: only
    the number carries color, so a bar of many tabs isn't a wall of rainbow."""
    off = accent if unlit_fg is None else unlit_fg
    fade = _fade.get(os_window_id)
    if fade is not None:
        t = _frame_t.get(os_window_id, 1.0)
        if t < 1.0:
            _, outgoing, incoming = fade
            if tab_id == incoming:
                return _lerp(off, DARK_FG, t), _lerp(DIM_BG, accent, t)
            if tab_id == outgoing:
                return _lerp(DARK_FG, off, t), _lerp(accent, DIM_BG, t)
    return (DARK_FG, accent) if is_active else (off, DIM_BG)


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


# --- HUD (right-hand status panel) ------------------------------------------
#
# "⎇ branch │ HH:MM" beside the window buttons, for the active tab. It is the
# lowest-priority element of the bar: the planner drops it before it would
# fold a single tab away. Cheap by construction:
#   - branch: read straight from .git/HEAD (no `git` subprocess), cached per
#     cwd for HUD_GIT_TTL, so animation frames never touch the disk;
#   - clock: one non-repeating timer per minute boundary repaints the bar.
#     The text only changes on that boundary, so the bar's width never moves
#     mid-animation (the hard constraint from the Animation section).

ICON_BRANCH = "\ue725"   # dev-git_branch
HUD_SEP = "│"
HUD_GIT_TTL = 2.0
HUD_BRANCH_MAX = 18
HUD_ICON_FG = 0xCBA6F7   # Mocha mauve — branch glyph
HUD_TEXT_FG = 0xA6ADC8   # Mocha subtext0
HUD_CLOCK_FG = 0xCDD6F4  # Mocha text

_git_cache: dict[str, tuple[float, str]] = {}
_clock_timer: int | None = None
_seen_tabs: set[int] = set()
NEW_TAB_SETTLE = 2.0


def _repaint_all(timer_id: int) -> None:
    boss = get_boss()
    if boss is not None:
        for os_window_id in list(boss.os_window_map):
            mark_tab_bar_dirty(os_window_id, True)
        wakeup_main_loop()


def _git_branch(cwd: str) -> str:
    now = monotonic()
    cached = _git_cache.get(cwd)
    if cached is not None and now - cached[0] < HUD_GIT_TTL:
        return cached[1]
    branch = ""
    d = cwd
    try:
        while d:
            dot_git = os.path.join(d, ".git")
            if os.path.isdir(dot_git):
                head_path = os.path.join(dot_git, "HEAD")
            elif os.path.isfile(dot_git):
                # worktree / submodule: ".git" is a file pointing at the gitdir
                with open(dot_git) as f:
                    gitdir = f.read().strip().removeprefix("gitdir: ")
                head_path = os.path.join(os.path.join(d, gitdir), "HEAD")
            else:
                parent = os.path.dirname(d)
                if parent == d:
                    break
                d = parent
                continue
            with open(head_path) as f:
                head = f.read().strip()
            branch = head.removeprefix("ref: refs/heads/") if head.startswith("ref: ") else head[:7]
            break
    except OSError:
        branch = ""
    if len(_git_cache) >= CWD_CACHE_MAX:
        _git_cache.clear()
    _git_cache[cwd] = (now, branch)
    return branch


def _hud_segments(tab_id: int) -> list[tuple[str, int]]:
    boss = get_boss()
    t = boss.tab_for_id(tab_id) if boss else None
    cwd = _active_cwd(t) if t is not None else ""
    segs: list[tuple[str, int]] = []
    branch = _git_branch(cwd) if cwd else ""
    if branch:
        segs += [(f" {ICON_BRANCH} ", HUD_ICON_FG), (f"{_truncate_middle(branch, HUD_BRANCH_MAX)} ", HUD_TEXT_FG),
                 (HUD_SEP, DIM_SEP)]
    segs.append((f" {time.strftime('%H:%M')} ", HUD_CLOCK_FG))
    return segs


def _truncate_middle(name: str, budget: int) -> str:
    """feature/una-rama-muy-larga-de-verdad -> feature/…de-verdad. A branch's
    end is what tells it apart, and its "type/" prefix is what you scan for;
    cutting from the right threw both kinds of information away."""
    if wcswidth(name) <= budget or not name.isascii():
        return _truncate(name, budget)
    head = name[: name.find("/") + 1] if 0 < name.find("/") < budget // 2 else ""
    tail = budget - len(head) - 1
    if not head:
        head, tail = name[: (budget - 1) // 2], budget - 1 - (budget - 1) // 2
    return f"{head}…{name[-tail:]}"


def _clock_tick(timer_id: int) -> None:
    global _clock_timer
    _clock_timer = None
    boss = get_boss()
    if boss is not None:
        for os_window_id in list(boss.os_window_map):
            mark_tab_bar_dirty(os_window_id, True)
        wakeup_main_loop()
    _schedule_clock()


def _schedule_clock() -> None:
    """Fire just after the next minute boundary, then reschedule: 1 repaint a
    minute instead of a polling timer."""
    global _clock_timer
    if _clock_timer is None:
        _clock_timer = add_timer(_clock_tick, 60.05 - (time.time() % 60), False)


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


# --- Status badges -------------------------------------------------------------
#
# Drawn after a tab's text, in their own color: state you'd otherwise have to
# switch tabs to discover. Each badge's width depends only on its state (a
# percentage is always padded to 3 digits), so a running progress bar never
# changes the tab's width between updates and never re-lays-out the bar.

BADGE_ZOOM = "\U000F004C"   # md-arrow_expand_all -- splits hidden by zoom
BADGE_ERROR = "\U000F0028"  # md-alert_circle -- progress reported an error
BADGE_BUSY = "\U000F0772"   # md-loading -- indeterminate progress ("…" read as a cut title)
BADGE_ACTIVITY = "•"    # new output in a tab you're not looking at
PROGRESS_FG = 0x94E2D5       # Mocha teal
ZOOM_FG = 0xF9E2AF           # Mocha yellow


def _badge(t, boss) -> tuple[str, int]:
    """(text, color) of the most important badge for a tab, or ("", 0)."""
    tab = boss.tab_for_id(t.tab_id) if boss else None
    # 1. progress (OSC 9;4): a build/download running in that tab
    if tab is not None and getattr(tab, "last_focused_window_with_progress_id", 0):
        w = boss.window_id_map.get(tab.last_focused_window_with_progress_id)
        state = getattr(getattr(getattr(w, "progress", None), "state", None), "name", "")
        if state == "error":
            return f"{BADGE_ERROR} ", ATTENTION
        if state == "indeterminate":
            return f"{BADGE_BUSY} ", PROGRESS_FG
        if t.num_of_windows_with_progress:
            pct = int(t.total_progress / t.num_of_windows_with_progress)
            return f"{pct:>3}% ", PROGRESS_FG
    # 1b. a TUI animating a spinner in its title is busy, same as above
    if _SPINNER.match(t.title or ""):
        return f"{BADGE_BUSY} ", PROGRESS_FG
    # 2. background output since you last looked: the actionable one
    if t.has_activity_since_last_focus and not t.is_active and not t.needs_attention:
        return f"{BADGE_ACTIVITY} ", 0
    # 3. zoomed split: the other panes are out of sight, keep them in mind
    if t.layout_name == "stack" and t.num_window_groups > 1:
        return f"{BADGE_ZOOM}{t.num_window_groups} ", ZOOM_FG
    return "", 0


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
        icon = _icon_for_tab(t.tab_id, t.title or "")
        if t.needs_attention and not t.is_active:
            icon = draw_data.tab_activity_symbol or icon
        icons.append(icon)
    boss = get_boss()
    # A new tab's first frame is drawn before its shell has reported a cwd, so
    # its icon and the HUD branch can be the parent's. One repaint once the
    # shell has settled fixes that without waiting for the next clock tick.
    fresh = [t.tab_id for t in tabs if t.tab_id not in _seen_tabs]
    if fresh:
        _seen_tabs.update(fresh)
        add_timer(_repaint_all, NEW_TAB_SETTLE, False)
    badges = [_badge(t, boss) for t in tabs]
    badge_w = [wcswidth(b[0]) for b in badges]
    compact = [1 + wcswidth(_tab_text(i + 1, icons[i], "")) + badge_w[i] for i in range(n)]
    close_w = wcswidth(f"{TAB_CLOSE} ")
    # Worst case chip width (as many digits as there are tabs), so reserving it
    # can't shift once the real hidden count is known -- a one-cell overshoot
    # just lands in the padding before the right-hand cluster.
    chip_w = wcswidth(f" {ICON_MORE}{n} ")
    # Reserved up front rather than left to the title pass below: compact tabs
    # are cheap enough that a bar full of them eats every last cell, and a bar
    # where even the active tab is a bare number is worse than one that folds
    # a few more tabs away.
    titles = [_clean_title(t.title or "") for t in tabs]
    active_title = _truncate(titles[active], TITLE_ACTIVE)
    active_cost = wcswidth(active_title) + 1 + close_w if active_title else 0

    # The right-hand controls are only shed in a bar too narrow to hold even one
    # compact tab beside them. Close goes last of the three: it's the only one
    # with no keyboard equivalent bound in kitty.conf.
    # n, not n - 1: every visible tab draws one separator cell after itself
    # (the last one an angled cap back into the bar).
    needs_chip = sum(compact) + n + active_cost > columns - RIGHT_W
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

    # The HUD only claims space a bar with every tab visible (compact, plus the
    # active tab's title) can spare; it's the first thing to go, before any tab
    # folds. Reserved ahead of the title pass so titles can't squeeze it out.
    hud = _hud_segments(tabs[active].tab_id)
    hud_w = sum(wcswidth(text) for text, _ in hud)
    if not needs_chip and sum(compact) + n + active_cost <= budget - hud_w:
        budget -= hud_w
        right_w += hud_w
    else:
        hud = []

    widths = compact[:]
    hidden = [False] * n

    def total() -> int:
        visible = [i for i in range(n) if not hidden[i]]
        return sum(widths[i] for i in visible) + len(visible)

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
        title = _truncate(titles[i], min(TITLE_MAX, room))
        if not title:
            continue
        texts[i] = _tab_text(i + 1, icons[i], title)
        widths[i] = 1 + wcswidth(texts[i]) + badge_w[i] + extra_close
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
        "badge": {tabs[i].tab_id: badges[i] for i in visible},
        "close": {tabs[i].tab_id: closes[i] for i in visible},
        "following": following,
        "chip": f" {ICON_MORE}{hidden_n} " if hidden_n else "",
        "chip_attention": any(
            hidden[i] and tabs[i].needs_attention and not tabs[i].is_active for i in range(n)
        ),
        "draw_new": draw_new,
        "buttons": tuple(buttons),
        "right_w": right_w,
        "hud": hud,
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
        icon = _icon_for_tab(tab.tab_id, tab.title or "")
        if tab.needs_attention and not tab.is_active:
            icon = draw_data.tab_activity_symbol or icon
        close_reserve = wcswidth(f"{TAB_CLOSE} ") if tab.is_active else 0
        room = max_tab_length - wcswidth(_tab_text(index, icon, "")) - 1 - close_reserve
        text = _tab_text(index, icon, _truncate(_clean_title(tab.title or ""), room))
        draw_close = tab.is_active
        badge = _badge(tab, get_boss())
        following = None
        if extra_data.next_tab is not None:
            nt = extra_data.next_tab
            following = (index + 1, nt.tab_id, nt.needs_attention, nt.is_active)
    else:
        text = plan["text"].get(tab.tab_id)
        badge = plan["badge"].get(tab.tab_id, ("", 0))
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
        # kitty pre-applies active_tab_font_style (default bold-italic) before
        # calling draw_tab; upright reads crisper and keeps the HUD upright too.
        screen.cursor.italic = False
        screen.cursor.bold = tab.is_active
        # Drawn in two pieces only so the accent bar can carry its own
        # foreground; the rest is byte-identical to what the planner measured.
        bar = _fill_glyph(os_window_id, tab.is_active)
        screen.cursor.fg = as_rgb(accent)
        screen.cursor.bg = as_rgb(bg)
        screen.draw(bar)
        # Index in the accent, the rest in a neutral tone -- except a tab that
        # needs attention, which stays fully red so it can't be missed.
        rest_fg = fg if attention else _colors(
            os_window_id, tab.tab_id, tab.is_active, accent, INACTIVE_FG
        )[0]
        head, _, tail = text.partition(" ")
        screen.cursor.fg = as_rgb(fg)
        screen.draw(head)
        screen.cursor.fg = as_rgb(rest_fg)
        screen.draw(" " + tail)
        badge_text, badge_color = badge
        if badge_text:
            # On the lit tab every badge uses the dark text color: an accent on
            # an accent fill would vanish. 0 means "use the tab's accent".
            screen.cursor.fg = as_rgb(fg if tab.is_active else (badge_color or accent))
            screen.draw(badge_text)
        screen.cursor.bold = False

        if draw_close:
            close_start = screen.cursor.x
            screen.cursor.fg = as_rgb(rest_fg)
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
        else:
            # Last visible tab: one angled cap back into the bar, so the lit
            # tab is a parallelogram on both sides. Always one cell (a blank
            # for an unlit tab) -- the planner counts it.
            screen.cursor.fg = as_rgb(bg)
            screen.cursor.bg = as_rgb(BAR_BG)
            screen.draw(SEP_HARD if bg != BAR_BG else " ")

    if is_last:
        screen.cursor.italic = False
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
            hud = plan.get("hud", []) if plan is not None else []
            for text, color in hud:
                screen.cursor.fg = as_rgb(color)
                screen.cursor.bg = as_rgb(BAR_BG)
                screen.draw(text)
            if hud:
                _schedule_clock()
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
# signature (checked against kitty 0.49.1 and 0.51.0, kitty/tabs.py) -- if a future kitty renames or
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
