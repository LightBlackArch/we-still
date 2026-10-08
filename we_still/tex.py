"""Decode Wallpaper Engine .tex textures (RePKG layout) to PIL RGBA."""
import io
import struct

import numpy as np
from PIL import Image


def lz4_block(src: bytes, size: int) -> bytes:
    """Pure-python LZ4 block decompressor."""
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        tok = src[i]; i += 1
        ll = tok >> 4
        if ll == 15:
            while True:
                b = src[i]; i += 1; ll += b
                if b != 255:
                    break
        out += src[i:i + ll]; i += ll
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8); i += 2
        ml = tok & 15
        if ml == 15:
            while True:
                b = src[i]; i += 1; ml += b
                if b != 255:
                    break
        ml += 4
        if off >= ml:
            s = len(out) - off
            out += out[s:s + ml]
        else:
            for _ in range(ml):
                out.append(out[-off])
    return bytes(out[:size]) if size else bytes(out)


def _rgb565(c):
    r = ((c >> 11) & 31) * 255 // 31
    g = ((c >> 5) & 63) * 255 // 63
    b = (c & 31) * 255 // 31
    return np.stack([r, g, b], -1).astype(np.uint8)


def _dxt(data, w, h, kind):
    bw, bh = (w + 3) // 4, (h + 3) // 4
    bs = 8 if kind == 1 else 16
    blk = np.frombuffer(data, np.uint8, bw * bh * bs).reshape(bh * bw, bs)
    cb = blk[:, -8:]
    c0 = cb[:, 0].astype(np.uint32) | (cb[:, 1].astype(np.uint32) << 8)
    c1 = cb[:, 2].astype(np.uint32) | (cb[:, 3].astype(np.uint32) << 8)
    p0, p1 = _rgb565(c0).astype(np.int32), _rgb565(c1).astype(np.int32)
    four = (c0 > c1) | (kind != 1)
    p2 = np.where(four[:, None], (2 * p0 + p1) // 3, (p0 + p1) // 2)
    p3 = np.where(four[:, None], (p0 + 2 * p1) // 3, 0)
    pal = np.stack([p0, p1, p2, p3], 1)  # N,4,3
    bits = cb[:, 4:8].astype(np.uint32)
    bits = bits[:, 0] | (bits[:, 1] << 8) | (bits[:, 2] << 16) | (bits[:, 3] << 24)
    idx = (bits[:, None] >> (2 * np.arange(16, dtype=np.uint32))) & 3  # N,16
    rgb = np.take_along_axis(pal, idx[:, :, None].astype(np.int64), 1)
    a = np.full((len(blk), 16), 255, np.int32)
    if kind == 1:
        a[(~four)[:, None] & (idx == 3)] = 0
    elif kind == 3:
        ab = blk[:, :8].astype(np.uint32)
        for k in range(16):
            a[:, k] = ((ab[:, k // 2] >> (4 * (k % 2))) & 15) * 17
    else:
        a0, a1 = blk[:, 0].astype(np.int32), blk[:, 1].astype(np.int32)
        v = np.zeros(len(blk), np.uint64)
        for k in range(6):
            v |= blk[:, 2 + k].astype(np.uint64) << np.uint64(8 * k)
        ai = (v[:, None] >> (3 * np.arange(16, dtype=np.uint64))) & np.uint64(7)
        ai = ai.astype(np.int64)
        t = np.zeros((len(blk), 8), np.int32)
        t[:, 0], t[:, 1] = a0, a1
        g = (a0 > a1)[:, None]
        for k in range(1, 7):
            t[:, k + 1] = np.where(g[:, 0], ((7 - k) * a0 + k * a1) // 7,
                                   np.where(k <= 4, ((5 - k) * a0 + k * a1) // 5, 0))
        t[:, 6] = np.where(g[:, 0], t[:, 6], 0)
        t[:, 7] = np.where(g[:, 0], t[:, 7], 255)
        a = np.take_along_axis(t, ai, 1)
    px = np.concatenate([rgb, a[:, :, None]], 2).astype(np.uint8)  # N,16,4
    px = px.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return px[:h, :w]


def _cstr(d, p):
    e = d.index(b"\0", p)
    return d[p:e].decode("latin1"), e + 1


def decode_tex(data: bytes) -> Image.Image:
    """Return the largest mip of a .tex as an RGBA image (cropped to real image size)."""
    m1, p = _cstr(data, 0)
    m2, p = _cstr(data, p)
    if m1 != "TEXV0005" or m2 != "TEXI0001":
        raise ValueError("not a TEX: %r %r" % (m1, m2))
    fmt, flags, tw, th, iw, ih, _ = struct.unpack_from("<7i", data, p); p += 28
    magic, p = _cstr(data, p)
    nimg, = struct.unpack_from("<i", data, p); p += 4
    fif = -1
    if magic == "TEXB0003":
        fif, = struct.unpack_from("<i", data, p); p += 4
    elif magic == "TEXB0004":
        fif, mp4 = struct.unpack_from("<2i", data, p); p += 8
        if fif == -1 and mp4 == 1:
            raise ValueError("video texture")
    elif magic not in ("TEXB0001", "TEXB0002"):
        raise ValueError("unknown " + magic)
    nmip, = struct.unpack_from("<i", data, p); p += 4
    best = None
    for _ in range(nmip):
        if magic == "TEXB0001":
            w, h = struct.unpack_from("<2i", data, p); p += 8
            lz, usz = 0, 0
        else:
            w, h, lz, usz = struct.unpack_from("<4i", data, p); p += 16
        n, = struct.unpack_from("<i", data, p); p += 4
        raw = data[p:p + n]; p += n
        if best is None:
            best = (w, h, lz, usz, raw)
        break  # first mip is the largest
    w, h, lz, usz, raw = best
    if lz:
        raw = lz4_block(raw, usz)
    if fif != -1:
        return Image.open(io.BytesIO(raw)).convert("RGBA")
    if fmt == 0:
        arr = np.frombuffer(raw, np.uint8, w * h * 4).reshape(h, w, 4)
    elif fmt in (4, 6, 7):
        arr = _dxt(raw, w, h, {4: 5, 6: 3, 7: 1}[fmt])
    elif fmt == 8:  # RG88 -> luminance+alpha-ish: keep R,G
        rg = np.frombuffer(raw, np.uint8, w * h * 2).reshape(h, w, 2)
        arr = np.dstack([rg[..., 0], rg[..., 0], rg[..., 0], rg[..., 1]])
    elif fmt == 9:  # R8
        r = np.frombuffer(raw, np.uint8, w * h).reshape(h, w)
        arr = np.dstack([r, r, r, np.full_like(r, 255)])
    else:
        raise ValueError("unsupported tex format %d" % fmt)
    img = Image.fromarray(np.ascontiguousarray(arr), "RGBA")
    if (iw, ih) != (w, h) and 0 < iw <= w and 0 < ih <= h:
        img = img.crop((0, 0, iw, ih))
    return img
