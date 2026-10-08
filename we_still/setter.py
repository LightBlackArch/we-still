"""Detect the desktop and set a still image as wallpaper."""
import os, re, shlex, shutil, subprocess, time
from pathlib import Path

CACHE = Path.home() / ".cache/we-still"
SCHEMA = "org.gnome.desktop.background"
FALLBACK_SIZE = (3840, 2160)


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def detect_desktop():
    d = (os.environ.get("XDG_CURRENT_DESKTOP", "") + ":" + os.environ.get("XDG_SESSION_DESKTOP", "")).lower()
    for name, keys in (("gnome", ("gnome", "unity")), ("kde", ("kde", "plasma")),
                       ("hyprland", ("hyprland",)), ("sway", ("sway",))):
        if any(k in d for k in keys):
            return name
    return "x11"


def commands(desktop, img, which=shutil.which):
    """argv lists to run, in order. Empty list = no usable tool."""
    img = str(img)
    if desktop == "gnome":
        uri = "file://" + img
        return [["gsettings", "set", SCHEMA, k, v] for k, v in
                (("picture-uri", uri), ("picture-uri-dark", uri), ("picture-options", "zoom"))]
    if desktop == "kde":
        return [["plasma-apply-wallpaperimage", img]] if which("plasma-apply-wallpaperimage") else []
    if desktop in ("sway", "hyprland"):
        for tool in ("awww", "swww"):
            if which(tool):
                return [[tool, "img", img]]
        if desktop == "hyprland" and which("hyprctl") and which("hyprpaper"):
            return [["hyprctl", "hyprpaper", "preload", img], ["hyprctl", "hyprpaper", "wallpaper", "," + img]]
        if which("swaybg"):
            q = shlex.quote(img)
            return [["sh", "-c", f"pkill -x swaybg; nohup swaybg -i {q} -m fill >/dev/null 2>&1 &"]]
        return []
    if which("feh"):
        return [["feh", "--bg-fill", img]]
    if which("xwallpaper"):
        return [["xwallpaper", "--zoom", img]]
    return []


def set_image(im, desktop=None):
    """Save PIL image under a fresh name (forces GNOME to reload), set it, prune old ones."""
    desktop = desktop or detect_desktop()
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"current-{time.time_ns()}.png"
    im.save(path)
    cmds = commands(desktop, path)
    if not cmds:
        path.unlink(missing_ok=True)
        raise RuntimeError(f"no wallpaper tool found for desktop {desktop!r}")
    for c in cmds:
        subprocess.run(c, check=True)
    for old in CACHE.glob("current-*"):
        if old != path:
            old.unlink(missing_ok=True)
    return path


def _mutter_size():
    out = _run(["gdbus", "call", "--session", "--dest", "org.gnome.Mutter.DisplayConfig",
                "--object-path", "/org/gnome/Mutter/DisplayConfig",
                "--method", "org.gnome.Mutter.DisplayConfig.GetCurrentState"])
    cur = r"\('\d+x\d+@[^']*', (\d+), (\d+),[^()]*'is-current': <true>"
    # primary logical monitor looks like "..., true, [('CONNECTOR', ..."
    p = re.search(r", true, \[\('([^']+)'", out)
    if p:
        i = out.find(f"(('{p.group(1)}',")
        if i >= 0:
            m = re.search(cur, out[i:])
            if m:
                return int(m[1]), int(m[2])
    m = re.search(cur, out)
    return (int(m[1]), int(m[2])) if m else None


def screen_size(desktop=None):
    """Native pixel size of the primary monitor; 3840x2160 if nothing answers."""
    if (desktop or detect_desktop()) == "gnome" and (s := _mutter_size()):
        return s
    m = re.search(r"(\d+)x(\d+) px.*current", _run(["wlr-randr"]))
    if m:
        return int(m[1]), int(m[2])
    out = _run(["xrandr", "--query"])
    m = re.search(r"^\S+ connected primary (\d+)x(\d+)", out, re.M) or re.search(r"^\S+ connected (\d+)x(\d+)\+", out, re.M)
    return (int(m[1]), int(m[2])) if m else FALLBACK_SIZE
