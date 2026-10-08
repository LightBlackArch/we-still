"""we-still command line: turn a Wallpaper Engine workshop item into a still wallpaper."""
import argparse, configparser, io, json, shutil, subprocess, sys
from pathlib import Path

from . import setter, steam

IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")
WAYPAPER = Path.home() / ".config/waypaper/config.ini"
UNIT_DIR = Path.home() / ".config/systemd/user"


def notify(msg):
    try:
        subprocess.run(["notify-send", "-a", "we-still", "Wallpaper", msg], check=False)
    except OSError:
        pass


def cover(im, size):
    """Scale to cover `size` (aspect kept), then center-crop. Never distorts."""
    from PIL import Image
    W, H = size
    w, h = im.size
    if (w, h) == (W, H):
        return im
    k = max(W / w, H / h)
    nw, nh = max(W, round(w * k)), max(H, round(h * k))
    im = im.resize((nw, nh), Image.LANCZOS)
    l, t = (nw - W) // 2, (nh - H) // 2
    return im.crop((l, t, l + W, t + H))


def biggest_image(folder):
    """Largest readable image in the folder (presets/web items ship their art)."""
    from PIL import Image
    best, area = None, 0
    for f in sorted(folder.rglob("*")):
        if f.suffix.lower() in IMG_EXT + (".gif",) and f.is_file():
            try:
                with Image.open(f) as im:
                    a = im.size[0] * im.size[1]
            except Exception:
                continue
            if a > area:
                best, area = f, a
    return best


def video_frame(video):
    """Sharpest-looking of a few frames, at the video's native resolution."""
    from PIL import Image, ImageStat
    best, score = None, -1
    for t in ("1", "4", "10"):
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", t, "-i", str(video), "-frames:v", "1",
                            "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
        if r.returncode or not r.stdout:
            continue
        im = Image.open(io.BytesIO(r.stdout)).convert("RGB")
        s = sum(ImageStat.Stat(im.convert("L").resize((64, 36))).stddev)
        if s > score:
            best, score = im, s
    return best


def make_still(folder, size):
    """-> (PIL image, how) where how is scene|video|image|preview."""
    from PIL import Image
    try:
        proj = json.loads((folder / "project.json").read_text())
    except (OSError, ValueError):
        proj = {}
    kind = str(proj.get("type", "")).lower()
    im, how = None, "image"
    if kind == "scene":
        try:
            from . import compose
            im, how = compose.render(folder, size), "scene"
        except Exception as e:  # SceneError, ImportError, anything: fall back to shipped art
            print(f"scene render failed ({e}); using best image", file=sys.stderr)
    elif kind == "video" and (folder / str(proj.get("file", ""))).is_file():
        im, how = video_frame(folder / proj["file"]), "video"
    if im is None:
        f = biggest_image(folder)
        if f is None:
            raise FileNotFoundError(f"no image found in {folder}")
        with Image.open(f) as src:
            im = src.convert("RGB")
        how = "preview" if f.stem == "preview" else "image"
    return cover(im.convert("RGB"), size), how


def parse_size(s):
    try:
        w, h = s.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise argparse.ArgumentTypeError("size must look like 3840x2160")


def title(folder):
    try:
        return json.loads((folder / "project.json").read_text()).get("title", folder.name)
    except (OSError, ValueError):
        return folder.name


# --- waypaper config + guard -------------------------------------------------

def exe():
    return shutil.which("we-still") or f"{sys.executable} -m we_still"


def wanted(workshop):
    home = str(Path.home())
    folder = str(workshop)
    if folder.startswith(home + "/"):
        folder = "~" + folder[len(home):]
    return {"backend": "none", "folder": folder, "subfolders": "True", "all_subfolders": "True",
            "post_command": f"{exe()} set $wallpaper"}


def fix_config(path, want):
    """Re-apply keys; writes only when something differs (so a file watcher can't loop)."""
    cp = configparser.ConfigParser(interpolation=None)  # no interpolation: '%' is legal in values
    cp.optionxform = str
    cp.read(path)
    if "Settings" not in cp:
        cp["Settings"] = {}
    changed = [k for k, v in want.items() if cp["Settings"].get(k) != v]
    for k in changed:
        cp["Settings"][k] = want[k]
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            cp.write(f)
    return changed


def guard_units():
    e = exe().replace("%", "%%")
    return {
        "we-still-guard.path": "[Unit]\nDescription=Watch waypaper config for we-still\n\n"
                               "[Path]\nPathChanged=%h/.config/waypaper/config.ini\nUnit=we-still-guard.service\n\n"
                               "[Install]\nWantedBy=default.target\n",
        "we-still-guard.service": "[Unit]\nDescription=Re-apply we-still waypaper settings\n\n"
                                  f"[Service]\nType=oneshot\nExecStart={e} fix-config\n",
    }


def install_guard():
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    changed = False
    for name, text in guard_units().items():
        f = UNIT_DIR / name
        if not f.exists() or f.read_text() != text:
            f.write_text(text)
            changed = True
    if changed:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "--now", "we-still-guard.path"], check=False)
    return changed


# --- commands ----------------------------------------------------------------

def cmd_set(a):
    folder = steam.resolve(a.target)
    im, how = make_still(folder, a.size or setter.screen_size())
    path = setter.set_image(im)
    print(f"{folder.name} {how} {path}")
    notify(f"Only the preview is available for {title(folder)}" if how == "preview"
           else f"Set: {title(folder)}")


def cmd_render(a):
    folder = steam.resolve(a.target)
    im, how = make_still(folder, a.size or setter.screen_size())
    im.save(a.output)
    print(f"{folder.name} {how} {a.output}")


def cmd_all(a):
    size = a.size or setter.screen_size()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    bad = 0
    for d in steam.workshop_dirs():
        for f in sorted(d.iterdir()):
            if not f.is_dir():
                continue
            try:
                im, how = make_still(f, size)
                im.save(out / f"{f.name}.png")
                print(f"{f.name} {how}")
            except Exception as e:
                bad += 1
                print(f"{f.name} FAILED: {e}", file=sys.stderr)
    return 1 if bad else 0


def cmd_setup(a):
    dirs = steam.workshop_dirs()
    if not dirs:
        print("no Wallpaper Engine workshop folder found (is it installed + any wallpaper subscribed?)", file=sys.stderr)
        return 1
    changed = fix_config(WAYPAPER, wanted(dirs[0]))
    print("waypaper config:", ", ".join(changed) if changed else "already correct")
    print("guard units:", "installed" if install_guard() else "already installed")


def cmd_fix_config(a):
    dirs = steam.workshop_dirs()
    if dirs:
        fix_config(WAYPAPER, wanted(dirs[0]))


def cmd_doctor(a):
    bad = 0

    def line(ok, what, extra=""):
        nonlocal bad
        bad += not ok
        print(f"{'ok     ' if ok else 'MISSING'} {what} {extra}")

    line(bool(shutil.which("ffmpeg")), "ffmpeg (video wallpapers)")
    for mod in ("PIL", "numpy"):
        try:
            __import__(mod)
            line(True, mod)
        except ImportError:
            line(False, mod)
    try:
        from . import compose  # noqa: F401
        line(True, "scene renderer")
    except ImportError:
        line(False, "scene renderer (we_still.compose)")
    d = setter.detect_desktop()
    line(bool(setter.commands(d, "x.png")), f"wallpaper tool for {d}")
    dirs = steam.workshop_dirs()
    line(bool(dirs), "steam workshop dir", str(dirs[0]) if dirs else "")
    line(WAYPAPER.exists(), "waypaper config", str(WAYPAPER))
    if dirs and WAYPAPER.exists():
        cp = configparser.ConfigParser(interpolation=None)
        cp.optionxform = str
        cp.read(WAYPAPER)
        stale = [k for k, v in wanted(dirs[0]).items() if cp["Settings"].get(k) != v] if "Settings" in cp else ["all"]
        line(not stale, "waypaper settings", ("differ: " + ", ".join(stale) + " (run: we-still setup)") if stale else "")
    print("screen size:", "x".join(map(str, setter.screen_size())))
    return 1 if bad else 0


def build_parser():
    p = argparse.ArgumentParser(prog="we-still", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("set", help="set wallpaper from a workshop id, folder or file inside it")
    s.add_argument("target")
    s.add_argument("--size", type=parse_size)
    s.set_defaults(fn=cmd_set)
    s = sub.add_parser("render", help="write the still to a file")
    s.add_argument("target")
    s.add_argument("-o", "--output", required=True)
    s.add_argument("--size", type=parse_size)
    s.set_defaults(fn=cmd_render)
    s = sub.add_parser("all", help="render every workshop item into a folder")
    s.add_argument("--out", required=True)
    s.add_argument("--size", type=parse_size)
    s.set_defaults(fn=cmd_all)
    sub.add_parser("setup", help="configure waypaper + install the guard").set_defaults(fn=cmd_setup)
    sub.add_parser("fix-config", help="(used by the guard)").set_defaults(fn=cmd_fix_config)
    sub.add_parser("doctor", help="check dependencies").set_defaults(fn=cmd_doctor)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a) or 0
    except (FileNotFoundError, RuntimeError, subprocess.CalledProcessError) as e:
        print(f"we-still: {e}", file=sys.stderr)
        return 1
