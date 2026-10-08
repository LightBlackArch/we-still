import configparser, json, subprocess, tempfile
from pathlib import Path
from unittest import mock

from PIL import Image

from we_still import cli, setter, steam

VDF = '''"libraryfolders"
{
\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t\t"apps"\n\t\t{\n\t\t\t"431960"\t\t"1"\n\t\t}\n\t}
\t"1"\n\t{\n\t\t"path"\t\t"%s"\n\t}
}
'''


def fake_tree(t):
    home, lib2 = t / "home", t / "lib2"
    root = home / ".local/share/Steam"
    (root / "steamapps").mkdir(parents=True)
    (root / "steamapps/libraryfolders.vdf").write_text(VDF % (root, lib2))
    for lib, wid in ((root, "111"), (lib2, "222")):
        (lib / "steamapps/workshop/content/431960" / wid).mkdir(parents=True)
    return home, root, lib2


def test_vdf_parse():
    d = steam.parse_vdf(VDF % ("/a", "/b"))
    assert d["libraryfolders"]["0"]["path"] == "/a"
    assert d["libraryfolders"]["0"]["apps"]["431960"] == "1"
    assert d["libraryfolders"]["1"]["path"] == "/b"


def test_steam_resolution():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        home, root, lib2 = fake_tree(t)
        dirs = steam.workshop_dirs(home)
        assert [d.parent.parent.parent.parent for d in dirs] == [root, lib2]  # root first, vdf library second
        assert steam.resolve("222", home) == lib2 / "steamapps/workshop/content/431960/222"
        w = root / "steamapps/workshop/content/431960/111"
        (w / "preview.jpg").write_bytes(b"x")
        assert steam.resolve(str(w / "preview.jpg")) == w.resolve()  # waypaper passes the file
        assert steam.resolve(str(w)) == w.resolve()
        try:
            steam.resolve("999", home)
            assert False
        except FileNotFoundError:
            pass


def test_cover_crop_math():
    wide = Image.new("RGB", (400, 100), "red")
    wide.paste("blue", (150, 0, 250, 100))  # centre block must survive the crop
    out = cli.cover(wide, (160, 90))
    assert out.size == (160, 90)
    assert out.getpixel((80, 45)) == (0, 0, 255) and out.getpixel((2, 45)) == (255, 0, 0)
    assert cli.cover(Image.new("RGB", (100, 400)), (160, 90)).size == (160, 90)
    assert cli.cover(Image.new("RGB", (4000, 3000)), (1920, 1080)).size == (1920, 1080)
    assert cli.cover(Image.new("RGB", (3, 3)), (7, 5)).size == (7, 5)


def test_make_still_falls_back_to_biggest_image():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / "project.json").write_text(json.dumps({"type": "web"}))
        Image.new("RGB", (64, 64)).save(t / "preview.jpg")
        Image.new("RGB", (900, 500)).save(t / "art.png")
        im, how = cli.make_still(t, (320, 180))
        assert (im.size, how) == ((320, 180), "image")
        (t / "art.png").unlink()
        assert cli.make_still(t, (320, 180))[1] == "preview"


def cmds(desktop, have):
    return setter.commands(desktop, "/c/x.png", which=lambda n: n if n in have else None)


def test_setter_commands():
    g = cmds("gnome", ())
    assert ["gsettings", "set", setter.SCHEMA, "picture-uri", "file:///c/x.png"] in g
    assert ["gsettings", "set", setter.SCHEMA, "picture-uri-dark", "file:///c/x.png"] in g
    assert g[-1][-2:] == ["picture-options", "zoom"]
    assert cmds("kde", ("plasma-apply-wallpaperimage",)) == [["plasma-apply-wallpaperimage", "/c/x.png"]]
    assert cmds("kde", ()) == []
    assert cmds("sway", ("swww", "swaybg")) == [["swww", "img", "/c/x.png"]]
    assert cmds("sway", ("awww", "swww")) == [["awww", "img", "/c/x.png"]]
    assert "swaybg -i /c/x.png" in cmds("sway", ("swaybg",))[0][-1]
    assert cmds("hyprland", ("hyprctl", "hyprpaper"))[1] == ["hyprctl", "hyprpaper", "wallpaper", ",/c/x.png"]
    assert cmds("x11", ("feh", "xwallpaper")) == [["feh", "--bg-fill", "/c/x.png"]]
    assert cmds("x11", ("xwallpaper",)) == [["xwallpaper", "--zoom", "/c/x.png"]]
    assert cmds("x11", ()) == []


def test_set_image_runs_commands_and_prunes():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / "current-old.png").write_bytes(b"x")
        with mock.patch.object(setter, "CACHE", t), mock.patch("subprocess.run") as run:
            p = setter.set_image(Image.new("RGB", (4, 4)), "gnome")
        assert p.exists() and not (t / "current-old.png").exists()
        assert run.call_count == 3 and run.call_args_list[0].args[0][:3] == ["gsettings", "set", setter.SCHEMA]


def test_detect_desktop():
    for env, want in (("GNOME", "gnome"), ("ubuntu:GNOME", "gnome"), ("KDE", "kde"), ("Hyprland", "hyprland"),
                      ("sway", "sway"), ("", "x11")):
        with mock.patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": env, "XDG_SESSION_DESKTOP": ""}):
            assert setter.detect_desktop() == want


def test_screen_size_parsing():
    xr = "Screen 0: minimum 16 x 16\neDP-1 connected primary 2560x1440+0+0 (normal) 1mm x 1mm\nHDMI-1 connected 1920x1080+2560+0\n"
    with mock.patch.object(setter, "_run", side_effect=lambda c: xr if c[0] == "xrandr" else ""):
        assert setter.screen_size("x11") == (2560, 1440)
    with mock.patch.object(setter, "_run", return_value=""):
        assert setter.screen_size("x11") == (3840, 2160)
    mut = ("(uint32 1, [(('HDMI-1', 'A', 'B', 'C'), [('1920x1080@60.0', 1920, 1080, 60.0, 1.0, [1.0], {'is-current': <true>})], {}), "
           "(('eDP-1', 'L', 'E', 'N'), [('3840x2160@60.0', 3840, 2160, 60.0, 1.0, [1.0, 2.0], {}), "
           "('2560x1440@60.0', 2560, 1440, 60.0, 1.0, [1.0], {'is-current': <true>})], {})], "
           "[(0, 0, 1.0, uint32 0, false, [('HDMI-1', 'A', 'B', 'C')], {}), (1920, 0, 1.0, uint32 0, true, [('eDP-1', 'L', 'E', 'N')], {})], {})")
    with mock.patch.object(setter, "_run", return_value=mut):
        assert setter.screen_size("gnome") == (2560, 1440)  # primary's mode, not the first monitor's


def test_fix_config_idempotent_with_percent():
    with tempfile.TemporaryDirectory() as t:
        p = Path(t) / "waypaper/config.ini"
        p.parent.mkdir()
        p.write_text("[Settings]\nbackend = swww\npost_command = echo 100%% $wallpaper\nlanguage = en\nsort = 50%x\n")
        want = {"backend": "none", "folder": "~/w", "subfolders": "True", "all_subfolders": "True",
                "post_command": "we-still set $wallpaper && echo 100% done"}
        assert set(cli.fix_config(p, want)) == set(want)
        cp = configparser.ConfigParser(interpolation=None)
        cp.read(p)
        assert cp["Settings"]["post_command"] == want["post_command"]
        assert cp["Settings"]["sort"] == "50%x" and cp["Settings"]["language"] == "en"
        before, mtime = p.read_text(), p.stat().st_mtime_ns
        assert cli.fix_config(p, want) == []
        assert p.read_text() == before and p.stat().st_mtime_ns == mtime  # no write -> watcher can't loop


def test_guard_units():
    u = cli.guard_units()
    assert "fix-config" in u["we-still-guard.service"] and "config.ini" in u["we-still-guard.path"]


def test_cli_parsing():
    p = cli.build_parser()
    a = p.parse_args(["set", "123", "--size", "1920x1080"])
    assert (a.fn, a.target, a.size) == (cli.cmd_set, "123", (1920, 1080))
    a = p.parse_args(["render", "/x/preview.jpg", "-o", "o.png"])
    assert (a.fn, a.output, a.size) == (cli.cmd_render, "o.png", None)
    assert p.parse_args(["all", "--out", "d"]).out == "d"
    for c in ("setup", "doctor", "fix-config"):
        assert p.parse_args([c]).cmd == c
    for bad in (["render", "1"], ["set", "1", "--size", "big"], []):
        try:
            p.parse_args(bad)
            assert False, bad
        except SystemExit:
            pass


if __name__ == "__main__":  # works without pytest: python3 tests/test_integration.py
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
