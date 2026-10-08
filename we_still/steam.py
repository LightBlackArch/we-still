"""Find Steam Wallpaper Engine (app 431960) workshop folders."""
import re
from pathlib import Path

APP = "431960"
ROOTS = (
    "~/.steam/root", "~/.local/share/Steam", "~/.steam/steam",
    "~/.var/app/com.valvesoftware.Steam/.local/share/Steam",
    "~/.var/app/com.valvesoftware.Steam/.steam/root",
)


def parse_vdf(text):
    """Valve KeyValues -> nested dict (enough for libraryfolders.vdf)."""
    stack = [{}]
    key = None
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"|([{}])', text):
        s, brace = m.groups()
        if brace == "{":
            d = {}
            stack[-1][key] = d
            stack.append(d)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
        elif key is None:
            key = s
        else:
            stack[-1][key] = s.replace("\\\\", "\\")
            key = None
    return stack[0]


def libraries(home=None):
    """Every Steam library root (existing dirs, deduped by real path)."""
    seen, out = set(), []

    def add(p):
        p = Path(p).expanduser()
        if p.is_dir() and p.resolve() not in seen:
            seen.add(p.resolve())
            out.append(p)

    roots = [Path(r.replace("~", str(home), 1)) if home else Path(r).expanduser() for r in ROOTS]
    for root in roots:
        add(root)
        for vdf in (root / "steamapps/libraryfolders.vdf", root / "config/libraryfolders.vdf"):
            try:
                data = parse_vdf(vdf.read_text(errors="replace"))
            except OSError:
                continue
            for entry in data.get("libraryfolders", {}).values():
                if isinstance(entry, dict) and "path" in entry:
                    add(entry["path"])
    return out


def workshop_dirs(home=None):
    return [d for lib in libraries(home) if (d := lib / "steamapps/workshop/content" / APP).is_dir()]


def resolve(arg, home=None):
    """Workshop id, wallpaper dir, or a file inside one (waypaper's preview.jpg) -> wallpaper dir."""
    p = Path(arg).expanduser()
    if p.exists():
        return (p.parent if p.is_file() else p).resolve()
    if arg.isdigit():
        for d in workshop_dirs(home):
            if (d / arg).is_dir():
                return d / arg
    raise FileNotFoundError(f"no wallpaper found for {arg!r}")
