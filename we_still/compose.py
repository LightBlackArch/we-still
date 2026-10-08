"""Composite a Wallpaper Engine scene wallpaper into one still image (no renderer, no window)."""
import json
import math
import pathlib
import warnings

import numpy as np
from PIL import Image

from .pkg import read_pkg
from .tex import decode_tex

__all__ = ["render", "SceneError"]


class SceneError(Exception):
    """The scene cannot be composited at all."""


def _val(x, props=None):
    """Unwrap {"value":..,"user":..,"script":..} property bindings."""
    if isinstance(x, dict):
        u = x.get("user")
        if isinstance(u, dict):
            u = u.get("name")
        if props and u in props:
            return props[u]
        return x.get("value")
    return x


def _vec(x, n, default, props=None):
    x = _val(x, props)
    if x is None:
        return list(default)
    if isinstance(x, (int, float)):
        return [float(x)] * n
    try:
        v = [float(t) for t in str(x).split()]
    except ValueError:
        return list(default)
    return (v + list(default)[len(v):])[:n]


def _num(x, default, props=None):
    x = _val(x, props)
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _bool(x, props):
    x = _val(x, props)
    return True if x is None else bool(x)


def _mat(origin, ang_z, scale):
    c, s = math.cos(ang_z), math.sin(ang_z)
    return np.array([[c * scale[0], -s * scale[1], origin[0]],
                     [s * scale[0], c * scale[1], origin[1]],
                     [0, 0, 1]], float)


class _Scene:
    def __init__(self, wdir: pathlib.Path):
        self.files = read_pkg(wdir / "scene.pkg") if (wdir / "scene.pkg").exists() else {}
        sj = self.files.get("scene.json")
        if sj is None and (wdir / "scene.json").exists():
            sj = (wdir / "scene.json").read_bytes()
        if sj is None:
            raise SceneError("no scene.json")
        try:
            self.scene = json.loads(sj.decode("utf-8-sig"))
        except ValueError as e:
            raise SceneError("bad scene.json: %s" % e)
        self.props = {}
        try:
            pj = json.loads((wdir / "project.json").read_text("utf-8-sig"))
            for k, v in (pj.get("general", {}).get("properties", {}) or {}).items():
                if isinstance(v, dict) and "value" in v:
                    self.props[k] = v["value"]
        except Exception:
            pass
        self._tex = {}
        self.wdir = wdir

    def json(self, name):
        b = self.files.get(name)
        return json.loads(b.decode("utf-8-sig")) if b else None

    def tex(self, name):
        if name not in self._tex:
            b = self.files.get("materials/%s.tex" % name)
            if b is None:
                raise KeyError("texture %s missing" % name)
            self._tex[name] = decode_tex(b)
        return self._tex[name]


def _layer_image(sc: _Scene, obj):
    """-> (RGBA PIL image or None for solid, blending) for an image object."""
    model = sc.json(obj["image"])
    if model is None:
        return None
    mat = sc.json(model.get("material", ""))
    if not mat:
        return None
    ps = mat["passes"][0]
    blend = ps.get("blending", "translucent")
    texs = ps.get("textures") or []
    if not texs or not texs[0]:
        return None
    return sc.tex(texs[0]), blend


def _effects(sc, obj, img):
    """Apply cheap static effects (opacity, tint). Returns (img, rgb_mul, alpha_mul)."""
    cmul, amul = np.ones(3), 1.0
    for e in obj.get("effects") or []:
        try:
            if not _bool(e.get("visible", True), sc.props):
                continue
            f = e.get("file", "")
            p = (e.get("passes") or [{}])[0]
            cv = p.get("constantshadervalues") or {}
            tx = p.get("textures") or []
            if f.endswith("opacity/effect.json"):
                a = _val(cv.get("alpha"), sc.props)
                if a is None:
                    continue
                amul *= float(a)
                if len(tx) > 1 and tx[1]:
                    m = sc.tex(tx[1]).convert("L").resize(img.size, Image.BILINEAR)
                    al = np.asarray(img.getchannel("A"), np.float32) * np.asarray(m, np.float32) / 255
                    img = img.copy()
                    img.putalpha(Image.fromarray(al.astype(np.uint8)))
            elif f.endswith("tint/effect.json") and not (len(tx) > 1 and tx[1]):
                a = _num(cv.get("alpha"), 1.0, sc.props)
                c = np.array(_vec(cv.get("color"), 3, (1, 1, 1), sc.props))
                cmul = cmul * (1 - a + a * c)
        except Exception as ex:
            warnings.warn("effect %s skipped: %s" % (e.get("file"), ex))
    return img, cmul, amul


def _blend(canvas, x0, y0, prem, mode):
    """prem: float32 HxWx4 premultiplied RGBA 0..1; canvas float32 HxWx3."""
    h, w = prem.shape[:2]
    X0, Y0 = max(x0, 0), max(y0, 0)
    X1, Y1 = min(x0 + w, canvas.shape[1]), min(y0 + h, canvas.shape[0])
    if X1 <= X0 or Y1 <= Y0:
        return False
    p = prem[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0]
    d = canvas[Y0:Y1, X0:X1]
    rgb, a = p[..., :3], p[..., 3:]
    if mode == "additive":
        out = d + rgb
    elif mode == "screen":
        out = d + rgb - d * rgb
    elif mode == "multiply":
        out = d * (1 - a) + rgb * d
    else:
        out = rgb + d * (1 - a)
    canvas[Y0:Y1, X0:X1] = np.clip(out, 0, 1)
    return True


def _draw(canvas, img, M, size, cmul, amul, mode, H):
    """Draw RGBA/None(solid via img=Image 1x1) with world matrix M (y-up) and local size."""
    sx, sy = math.hypot(M[0, 0], M[1, 0]), math.hypot(M[0, 1], M[1, 1])
    ang = math.atan2(M[1, 0], M[0, 0])
    flip = -1 if M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0] < 0 else 1
    cx, cy = M[0, 2], H - M[1, 2]
    Wd, Hd = size[0] * sx, size[1] * sy
    if Wd < 0.5 or Hd < 0.5:
        return False
    # pre-shrink so bicubic sampling does not alias
    tw, th = img.size
    nw, nh = min(tw, max(1, round(Wd))), min(th, max(1, round(Hd)))
    prem = img.convert("RGBa")
    if (nw, nh) != (tw, th):
        prem = prem.resize((nw, nh), Image.LANCZOS)
    rx, ry = prem.size[0] / Wd, prem.size[1] / Hd
    c, s = math.cos(ang), math.sin(ang)
    # canvas offset (dx,dy) -> local lx,ly ; y-down canvas, visual CCW rotation
    half = [(-Wd / 2, -Hd / 2), (Wd / 2, -Hd / 2), (Wd / 2, Hd / 2), (-Wd / 2, Hd / 2)]
    pts = [(cx + lx * c + ly * s, cy - lx * s + ly * c) for lx, ly in half]
    x0 = max(int(math.floor(min(p[0] for p in pts))), 0)
    y0 = max(int(math.floor(min(p[1] for p in pts))), 0)
    x1 = min(int(math.ceil(max(p[0] for p in pts))), canvas.shape[1])
    y1 = min(int(math.ceil(max(p[1] for p in pts))), canvas.shape[0])
    if x1 <= x0 or y1 <= y0:
        return False
    # u = pw/2 + flip*rx*(dx c - dy s) ; v = ph/2 + ry*(dx s + dy c) with dx=X-cx, dy=Y-cy
    pw, ph = prem.size
    a, b = flip * rx * c, -flip * rx * s
    d, e = ry * s, ry * c
    # sample at pixel centres
    X, Y = x0 + 0.5 - cx, y0 + 0.5 - cy
    cc = pw / 2 + a * X + b * Y - 0.5 + 0.0
    ff = ph / 2 + d * X + e * Y - 0.5 + 0.0
    out = prem.transform((x1 - x0, y1 - y0), Image.AFFINE, (a, b, cc + 0.5, d, e, ff + 0.5), Image.BICUBIC)
    arr = np.asarray(out, np.float32) / 255  # RGBa: already premultiplied
    arr[..., :3] *= cmul.astype(np.float32)
    arr *= amul
    return _blend(canvas, x0, y0, arr, mode)


def _norm_blend(b):
    b = (b or "").lower()
    return b if b in ("additive", "screen", "multiply") else "normal"


def _render_native(wdir):
    sc = _Scene(wdir)
    g = sc.scene.get("general", {})
    op = g.get("orthogonalprojection") or {}
    W, H = int(_num(op.get("width"), 1920)), int(_num(op.get("height"), 1080))
    clear = [c for c in _vec(g.get("clearcolor"), 3, (0, 0, 0), sc.props)]
    canvas = np.empty((H, W, 3), np.float32)
    canvas[:] = np.array(clear, np.float32)
    objs = {o.get("id"): o for o in sc.scene.get("objects", [])}
    cache = {}

    def world(o):
        i = o.get("id")
        if i in cache:
            return cache[i]
        m = _mat(_vec(o.get("origin"), 3, (0, 0, 0), sc.props)[:2],
                 math.radians(_vec(o.get("angles"), 3, (0, 0, 0), sc.props)[2]),
                 _vec(o.get("scale"), 3, (1, 1, 1), sc.props)[:2])
        par = objs.get(o.get("parent"))
        vis = _bool(o.get("visible", True), sc.props)
        if par is not None and par is not o:
            pm, pv = world(par)
            m, vis = pm @ m, vis and pv
        cache[i] = (m, vis)
        return cache[i]

    drawn = 0
    for o in sc.scene.get("objects", []):
        try:
            if "image" not in o or not o["image"]:
                continue
            M, vis = world(o)
            if not vis:
                continue
            alpha = _num(o.get("alpha"), 1.0, sc.props)
            color = np.array(_vec(o.get("color"), 3, (1, 1, 1), sc.props))
            bright = _num(o.get("brightness"), 1.0, sc.props)
            li = _layer_image(sc, o) if o["image"] in sc.files else None
            if li is None:
                if not o["image"].endswith("solidlayer.json"):
                    continue
                size = _vec(o.get("size"), 2, (W, H), sc.props)
                img, mode = Image.new("RGBA", (4, 4), (255, 255, 255, 255)), "normal"
            else:
                img, mode = li
                mode = _norm_blend(mode)
                size = _vec(o.get("size"), 2, img.size, sc.props) if o.get("size") else list(img.size)
            img, cm, am = _effects(sc, o, img)
            cm = cm * color * bright
            if _draw(canvas, img, M, size, cm, am * alpha, mode, H):
                drawn += 1
        except Exception as ex:  # one bad layer never kills the render
            warnings.warn("layer %r skipped: %s: %s" % (o.get("name"), type(ex).__name__, ex))
    if not drawn:
        raise SceneError("no drawable image layers")
    return Image.fromarray((canvas * 255 + 0.5).astype(np.uint8), "RGB")


def cover_crop(img: Image.Image, size) -> Image.Image:
    """Scale to cover `size` (keeping aspect), then centre-crop to exactly `size`."""
    tw, th = size
    w, h = img.size
    k = max(tw / w, th / h)
    nw, nh = max(tw, round(w * k)), max(th, round(h * k))
    if (nw, nh) != (w, h):
        img = img.resize((nw, nh), Image.LANCZOS)
    l, t = (nw - tw) // 2, (nh - th) // 2
    return img.crop((l, t, l + tw, t + th))


def render(wallpaper_dir, size=None) -> Image.Image:
    """Composite the scene in `wallpaper_dir` (scene.pkg + project.json) to an RGB image.

    size=None -> the scene's own projection size; else (w, h) via cover-scale + centre-crop.
    Raises SceneError if the scene cannot be composited.
    """
    wdir = pathlib.Path(wallpaper_dir)
    try:
        img = _render_native(wdir)
    except SceneError:
        raise
    except Exception as e:
        raise SceneError("%s: %s" % (type(e).__name__, e))
    return cover_crop(img, tuple(size)) if size else img
