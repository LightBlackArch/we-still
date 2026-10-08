"""Plain-assert checks. Run: python3 tests/test_compose.py [--real]"""
import json, pathlib, struct, sys, tempfile, time, warnings
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from PIL import Image
from we_still.pkg import parse_pkg
from we_still.tex import decode_tex, lz4_block
from we_still.compose import render, cover_crop, SceneError

STEAM = pathlib.Path.home() / ".steam/root/steamapps/workshop/content/431960"


def make_tex(w, h, rgba):
    z = lambda s: s.encode() + b"\0"
    raw = bytes(rgba) * (w * h)
    return (z("TEXV0005") + z("TEXI0001") + struct.pack("<7i", 0, 0, w, h, w, h, 0)
            + z("TEXB0002") + struct.pack("<2i", 1, 1) + struct.pack("<4i", w, h, 0, len(raw))
            + struct.pack("<i", len(raw)) + raw)


def make_pkg(files):
    s = lambda t: struct.pack("<I", len(t)) + t.encode()
    table, body = b"", b""
    for n, b in files.items():
        table += s(n) + struct.pack("<2I", len(body), len(b)); body += b
    return s("PKGV0023") + struct.pack("<I", len(files)) + table + body


def fake_scene(d):
    scene = {"general": {"orthogonalprojection": {"width": 400, "height": 200}, "clearcolor": "0 0 0"},
             "objects": [{"id": 1, "image": "models/a.json", "origin": "200 100 0", "size": "100 100"}]}
    files = {"scene.json": json.dumps(scene).encode(),
             "models/a.json": b'{"material":"materials/a.json"}',
             "materials/a.json": b'{"passes":[{"blending":"translucent","textures":["a"]}]}',
             "materials/a.tex": make_tex(4, 4, (255, 0, 0, 255))}
    (d / "scene.pkg").write_bytes(make_pkg(files))
    (d / "project.json").write_text('{"type":"scene"}')
    return files


def test_synthetic():
    assert lz4_block(bytes([0x50]) + b"hello", 5) == b"hello"
    with tempfile.TemporaryDirectory() as t:
        d = pathlib.Path(t); files = fake_scene(d)
        assert parse_pkg((d / "scene.pkg").read_bytes()) == files
        assert decode_tex(files["materials/a.tex"]).getpixel((0, 0)) == (255, 0, 0, 255)
        im = render(d)
        assert im.size == (400, 200) and im.mode == "RGB"
        assert im.getpixel((200, 100)) == (255, 0, 0) and im.getpixel((10, 10)) == (0, 0, 0)
        for sz in [(200, 200), (1920, 1080), (100, 400)]:
            o = render(d, sz); assert o.size == sz, (o.size, sz)
        assert cover_crop(Image.new("RGB", (400, 200)), (100, 100)).size == (100, 100)
        (d / "scene.pkg").write_bytes(make_pkg({"x": b""}))
        try: render(d); assert False
        except SceneError: pass
    print("synthetic OK")


def real():
    ok = 0; n = 0
    for d in sorted(STEAM.iterdir()):
        try:
            if json.loads((d / "project.json").read_text("utf-8-sig")).get("type", "").lower() != "scene": continue
        except Exception: continue
        n += 1; t = time.time()
        try:
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always"); im = render(d)
            ok += 1; print("OK  ", d.name, im.size, "%.1fs" % (time.time() - t), "warn=%d" % len(w))
        except Exception as e:
            print("FAIL", d.name, type(e).__name__, e, "%.1fs" % (time.time() - t))
    print("%d/%d OK" % (ok, n))


if __name__ == "__main__":
    test_synthetic()
    if "--real" in sys.argv: real()
