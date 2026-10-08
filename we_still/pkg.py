"""Reader for Wallpaper Engine scene.pkg files."""
import struct


def parse_pkg(data: bytes) -> dict:
    """bytes of a scene.pkg -> {name: bytes}."""
    pos = 0

    def u32():
        nonlocal pos
        v = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        return v

    def string():
        nonlocal pos
        n = u32()
        if n > 4096:
            raise ValueError("bad pkg string length")
        s = data[pos:pos + n].decode("utf-8", "replace")
        pos += n
        return s

    if not string().startswith("PKGV"):
        raise ValueError("not a scene.pkg")
    count = u32()
    if count > 100000:
        raise ValueError("bad pkg entry count")
    entries = [(string(), u32(), u32()) for _ in range(count)]
    base = pos
    return {n: data[base + o:base + o + s] for n, o, s in entries}


def read_pkg(path) -> dict:
    with open(path, "rb") as f:
        return parse_pkg(f.read())
