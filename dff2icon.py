import argparse
import math
import shutil
import threading
import os
import struct
import sys
import time
import traceback

import zlib

import numpy as np
from scipy import ndimage as ndi
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
STAGES = {
    "memuat model": (0.0, 0.05),
    "membaca tekstur": (0.05, 0.15),
    "rasterisasi": (0.15, 0.65),
    "pewarnaan dan garis": (0.65, 0.97),
    "menyimpan": (0.97, 1.0),
}
SHORT = {"memuat model": "model", "membaca tekstur": "tekstur", "rasterisasi": "raster", "pewarnaan dan garis": "warna", "menyimpan": "simpan"}
LAST_RES = None


class Progress:
    def __init__(self):
        self.on = False
        self.stage = ""
        self.frac = None
        self.t_stage = 0.0
        self.t0 = 0.0
        self.label = ""
        self.idx = 0
        self.total = 1
        self.times = []
        self.stop = threading.Event()
        self.thread = None
        self.active = False

    def set(self, name, frac=None):
        self.stage = name
        self.frac = frac
        self.t_stage = time.time()

    def overall(self):
        lo, hi = STAGES.get(self.stage, (0.0, 1.0))
        if self.frac is not None:
            p = self.frac
        else:
            p = 0.92 * (1.0 - math.exp(-(time.time() - self.t_stage) / 5.0))
        return lo + (hi - lo) * min(max(p, 0.0), 1.0)

    def line(self, tick):
        cols = shutil.get_terminal_size((60, 20)).columns
        ov = self.overall()
        bw = max(6, min(22, cols - 35))
        fill = int(ov * bw)
        bar = "█" * fill + ("▶" if fill < bw else "") + "·" * max(0, bw - fill - 1)
        eta = ""
        if self.times:
            avg = sum(self.times) / len(self.times)
            left = avg * (self.total - self.idx + 1 - ov)
            eta = " ~%d:%02d" % (int(left) // 60, int(left) % 60)
        txt = "%s [%s] %3d%% %s [%d/%d]%s" % (SPIN[tick % len(SPIN)], bar, int(ov * 100), SHORT.get(self.stage, self.stage), self.idx, self.total, eta)
        return txt[:cols - 1]

    def run(self):
        tick = 0
        while not self.stop.is_set():
            sys.stdout.write("\r\033[K" + self.line(tick))
            sys.stdout.flush()
            tick += 1
            self.stop.wait(0.1)

    def start(self, label, idx, total):
        self.label, self.idx, self.total = label, idx, total
        self.t0 = time.time()
        self.active = True
        self.set("memuat model")
        if self.on:
            self.stop.clear()
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def finish(self):
        if not self.active:
            return
        self.active = False
        if self.thread is not None:
            self.stop.set()
            self.thread.join()
            self.thread = None
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
        self.times.append(time.time() - self.t0)


PROG = Progress()


def ansi_preview(res, cols=56):
    a = res.astype(np.float32)
    if a.ndim == 2:
        rgb = np.repeat(a[..., None], 3, -1)
        al = np.ones(a.shape, np.float32)
    elif a.shape[2] == 4:
        rgb = a[..., :3]
        al = a[..., 3] / 255.0
    else:
        rgb = a
        al = np.ones(a.shape[:2], np.float32)
    ys, xs = np.where(al > 0.05)
    if len(ys):
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        rgb, al = rgb[y0:y1, x0:x1], al[y0:y1, x0:x1]
    comp = rgb * al[..., None] + np.array([28.0, 30.0, 34.0], np.float32) * (1.0 - al[..., None])
    h, w = comp.shape[:2]
    rows = max(2, int(round(h * cols / w / 2)) * 2)
    z = np.clip(ndi.zoom(comp, (rows / h, cols / w, 1), order=1), 0, 255)
    out = []
    for r in range(0, rows, 2):
        out.append("".join("\033[38;2;%d;%d;%dm\033[48;2;%d;%d;%dm▀" % (int(t[0]), int(t[1]), int(t[2]), int(b[0]), int(b[1]), int(b[2])) for t, b in zip(z[r], z[r + 1])) + "\033[0m")
    return "\n".join(out)



SKIP_WORDS = ("muzzle", "flash", "_vlo", "_dam", "lod", "shadow", "collision")
SUPERSAMPLE = 6
REF_W = 512
REF_H = 265
WEAPON_FRAC_W = 300.0 / 512.0
WEAPON_FRAC_H = 0.55
OUTLINE = 6.5
LINE = 1.3
MIN_LEN = 26
CAV_MIN = 16
DEPTH_THR = 0.0045
ANG_THR = 62
CAV_THR = 0.017
REF_LENGTH = 0.994


DROP_TOL = 0.002
DROP_RULES = {
    "micro_uzi": [
        ("micro_uzi", (-0.045, 0.003, 0.036), (0.162, 0.020, 0.082)),
        ("micro_uzi", (0.158, 0.004, 0.029), (0.184, 0.013, 0.051)),
        ("micro_uzi", (0.158, 0.004, 0.010), (0.185, 0.007, 0.039)),
        ("micro_uzi", (0.176, 0.002, -0.071), (0.192, 0.037, 0.048)),
    ],
}


def drop_parts(parts, path):
    rules = DROP_RULES.get(os.path.splitext(os.path.basename(path))[0].lower())
    if not rules:
        return parts
    out = []
    for p in parts:
        mine = [(np.array(lo), np.array(hi)) for n, lo, hi in rules if n == p["name"]]
        if not mine:
            out.append(p)
            continue
        V, T = p["V"], p["T"]
        key = np.round(V / 1e-5).astype(np.int64)
        _, inv = np.unique(key, axis=0, return_inverse=True)
        inv = inv.ravel()
        t = inv[T]
        n = int(inv.max()) + 1
        g = coo_matrix((np.ones(len(T) * 3), (np.r_[t[:, 0], t[:, 1], t[:, 2]], np.r_[t[:, 1], t[:, 2], t[:, 0]])), shape=(n, n))
        nc, lab = connected_components(g, directed=False)
        tl = lab[t[:, 0]]
        kill = np.zeros(len(T), bool)
        for c in range(nc):
            m = tl == c
            vv = V[np.unique(T[m])]
            lo, hi = vv.min(0), vv.max(0)
            if any(np.all(np.abs(lo - a) <= DROP_TOL) and np.all(np.abs(hi - b) <= DROP_TOL) for a, b in mine):
                kill |= m
        if not kill.any():
            out.append(p)
            continue
        T2 = T[~kill]
        if len(T2) == 0:
            continue
        used = np.unique(T2)
        remap = np.full(len(V), -1, np.int64)
        remap[used] = np.arange(len(used))
        q = dict(p)
        q["V"] = V[used]
        q["T"] = remap[T2]
        q["M"] = p["M"][~kill]
        q["uv"] = p["uv"][used] if p["uv"] is not None else None
        out.append(q)
    return out


def dilate_disk(mask, r):
    return ndi.distance_transform_edt(~mask) <= r


def box_resize(a, k):
    h, w = a.shape
    return a.reshape(h // k, k, w // k, k).mean((1, 3), dtype=np.float32)


def write_png(path, arr):
    if arr.ndim == 2:
        ctype, h, w = 0, arr.shape[0], arr.shape[1]
    else:
        ctype, h, w = (2 if arr.shape[2] == 3 else 6), arr.shape[0], arr.shape[1]
    raw = np.ascontiguousarray(arr).reshape(h, -1)
    rows = np.zeros((h, raw.shape[1] + 1), np.uint8)
    rows[:, 1:] = raw

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(rows.tobytes(), 6))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def kids(d, o, end):
    while o + 12 <= end:
        t, s, v = struct.unpack_from("<III", d, o)
        yield t, s, o + 12, v
        o += 12 + s


def unpack_ver(v):
    if v & 0xFFFF0000:
        return (((v >> 14) & 0x3FF00) + 0x30000) | ((v >> 16) & 0x3F)
    return v << 8


def rgb565(c):
    r = ((c >> 11) & 31) * 255 // 31
    g = ((c >> 5) & 63) * 255 // 63
    b = (c & 31) * 255 // 31
    return np.stack([r, g, b], -1).astype(np.uint8)


def decode_dxt(data, w, h, kind):
    bw, bh = (w + 3) // 4, (h + 3) // 4
    bs = 8 if kind == 1 else 16
    blocks = np.frombuffer(data, np.uint8, bw * bh * bs).reshape(bh, bw, bs)
    off = 0 if kind == 1 else 8
    c0 = blocks[..., off].astype(np.uint16) | (blocks[..., off + 1].astype(np.uint16) << 8)
    c1 = blocks[..., off + 2].astype(np.uint16) | (blocks[..., off + 3].astype(np.uint16) << 8)
    bits = (blocks[..., off + 4].astype(np.uint32) | (blocks[..., off + 5].astype(np.uint32) << 8)
            | (blocks[..., off + 6].astype(np.uint32) << 16) | (blocks[..., off + 7].astype(np.uint32) << 24))
    p0 = rgb565(c0).astype(np.int32)
    p1 = rgb565(c1).astype(np.int32)
    pal = np.zeros((bh, bw, 4, 3), np.int32)
    pal[..., 0, :] = p0
    pal[..., 1, :] = p1
    four = (c0 > c1) | (kind != 1)
    pal[..., 2, :] = np.where(four[..., None], (2 * p0 + p1) // 3, (p0 + p1) // 2)
    pal[..., 3, :] = np.where(four[..., None], (p0 + 2 * p1) // 3, 0)
    alpha_t = np.where(four, 255, 0)
    out = np.zeros((bh, bw, 4, 4, 4), np.uint8)
    sh = np.arange(16, dtype=np.uint32) * 2
    idx = ((bits[..., None] >> sh) & 3).astype(np.int64)
    rgb = np.take_along_axis(pal, idx[..., None].repeat(3, -1), axis=2).reshape(bh, bw, 4, 4, 3)
    out[..., :3] = rgb.astype(np.uint8)
    if kind == 1:
        a = np.take_along_axis(np.broadcast_to(np.stack([np.full_like(alpha_t, 255)] * 3 + [alpha_t], -1), (bh, bw, 4)), idx, axis=2)
        out[..., 3] = a.reshape(bh, bw, 4, 4).astype(np.uint8)
    elif kind == 3:
        ab = blocks[..., :8].reshape(bh, bw, 8).astype(np.uint32)
        nib = np.zeros((bh, bw, 16), np.uint8)
        for i in range(8):
            nib[..., 2 * i] = ab[..., i] & 15
            nib[..., 2 * i + 1] = ab[..., i] >> 4
        out[..., 3] = (nib * 17).reshape(bh, bw, 4, 4)
    else:
        a0 = blocks[..., 0].astype(np.int32)
        a1 = blocks[..., 1].astype(np.int32)
        ab = np.zeros((bh, bw), np.uint64)
        for i in range(6):
            ab |= blocks[..., 2 + i].astype(np.uint64) << np.uint64(8 * i)
        sh3 = np.arange(16, dtype=np.uint64) * np.uint64(3)
        ai = ((ab[..., None] >> sh3) & np.uint64(7)).astype(np.int64)
        tab = np.zeros((bh, bw, 8), np.int32)
        tab[..., 0] = a0
        tab[..., 1] = a1
        gt = a0 > a1
        for k in range(1, 7):
            tab[..., k + 1] = np.where(gt, ((7 - k) * a0 + k * a1) // 7, 0)
        for k in range(1, 5):
            tab[..., k + 1] = np.where(gt, tab[..., k + 1], ((5 - k) * a0 + k * a1) // 5)
        tab[..., 6] = np.where(gt, tab[..., 6], 0)
        tab[..., 7] = np.where(gt, tab[..., 7], 255)
        out[..., 3] = np.take_along_axis(tab, ai, axis=2).reshape(bh, bw, 4, 4).astype(np.uint8)
    img = out.transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return img[:h, :w]


def load_txd(path, wanted=None):
    d = open(path, "rb").read()
    root = next(kids(d, 0, len(d)))
    if root[0] != 0x16:
        raise ValueError("bukan TXD")
    tex = {}
    for t, s, p, v in kids(d, root[2], root[2] + root[1]):
        if t != 0x15:
            continue
        st = next(kids(d, p, p + s))
        q = st[2]
        name = d[q + 8:q + 40].split(b"\0")[0].decode("latin1").lower()
        if wanted is not None and name not in wanted:
            continue
        rf, d3d, w, h, depth, lv, rtype, flags = struct.unpack_from("<IIHHBBBB", d, q + 72)
        q += 72 + 16
        try:
            if rf & 0x2000:
                pal = np.frombuffer(d, np.uint8, 1024, q).reshape(256, 4)
                q += 1024
            elif rf & 0x4000:
                pal = np.frombuffer(d, np.uint8, 64, q).reshape(16, 4)
                q += 64
            else:
                pal = None
            size = struct.unpack_from("<I", d, q)[0]
            q += 4
            raw = d[q:q + size]
            if d3d in (0x31545844, 0x33545844, 0x35545844):
                kind = {0x31545844: 1, 0x33545844: 3, 0x35545844: 5}[d3d]
                img = decode_dxt(raw, w, h, kind)
            elif pal is not None and (rf & 0x2000):
                idx = np.frombuffer(raw, np.uint8, w * h).reshape(h, w)
                img = np.dstack([pal[idx][..., 2], pal[idx][..., 1], pal[idx][..., 0], pal[idx][..., 3]])
            else:
                fmt = rf & 0xF00
                if fmt in (0x500, 0x600):
                    n = 4 if depth == 32 else 3
                    a = np.frombuffer(raw, np.uint8, w * h * n).reshape(h, w, n)
                    img = np.dstack([a[..., 2], a[..., 1], a[..., 0], a[..., 3] if n == 4 else np.full((h, w), 255, np.uint8)])
                else:
                    continue
            tex[name] = np.ascontiguousarray(img)
        except Exception:
            continue
    return tex


def find_textures(dff_path, wanted):
    PROG.set("membaca tekstur")
    folder = os.path.dirname(os.path.abspath(dff_path))
    base = os.path.splitext(os.path.basename(dff_path))[0].lower()
    txds = sorted(f for f in os.listdir(folder) if f.lower().endswith(".txd"))
    txds.sort(key=lambda f: 0 if os.path.splitext(f)[0].lower() == base else 1)
    tex = {}
    for f in txds:
        try:
            t = load_txd(os.path.join(folder, f), wanted)
        except Exception:
            continue
        for k, v in t.items():
            tex.setdefault(k, v)
    return tex


def read_frames(d, p, s):
    items = list(kids(d, p, p + s))
    st = items[0]
    n = struct.unpack_from("<I", d, st[2])[0]
    q = st[2] + 4
    frames = []
    for i in range(n):
        f = struct.unpack_from("<12fiI", d, q)
        frames.append((np.array(f[:9]).reshape(3, 3), np.array(f[9:12]), f[12]))
        q += 56
    names = [""] * n
    exts = [x for x in items[1:] if x[0] == 3]
    for i, e in enumerate(exts[:n]):
        for t, s2, p2, _ in kids(d, e[2], e[2] + e[1]):
            if t == 0x253F2FE:
                names[i] = d[p2:p2 + s2].split(b"\0")[0].decode("latin1")
    return frames, names


def read_str(d, p, s):
    return d[p:p + s].split(b"\0")[0].decode("latin1").lower()


def read_geometry(d, p, s, v):
    ver = unpack_ver(v)
    items = list(kids(d, p, p + s))
    st = items[0]
    q = st[2]
    flags, nt, nv, nm = struct.unpack_from("<IIII", d, q)
    q += 16
    if flags & 0x01000000:
        raise ValueError("native geometry (PS2/Xbox) tidak didukung")
    if ver < 0x34000:
        q += 12
    if flags & 8:
        q += 4 * nv
    nuv = (flags >> 16) & 0xFF
    if nuv == 0:
        nuv = 2 if flags & 0x80 else (1 if flags & 4 else 0)
    uv = None
    if nuv:
        uv = np.frombuffer(d, "<f4", nv * 2 * nuv, q).reshape(nuv, nv, 2)[0].astype(np.float64)
    q += 8 * nv * nuv
    tr = np.frombuffer(d, "<u2", nt * 4, q).reshape(nt, 4)
    q += 8 * nt
    tris = tr[:, [1, 0, 3]].astype(np.int64)
    mat = tr[:, 2].astype(np.int64)
    q += 16
    hv, hn = struct.unpack_from("<II", d, q)
    q += 8
    V = np.frombuffer(d, "<f4", nv * 3, q).reshape(nv, 3).astype(np.float64)
    mats = []
    for t, s2, p2, v2 in items[1:]:
        if t != 8:
            continue
        sub = list(kids(d, p2, p2 + s2))
        cnt = struct.unpack_from("<I", d, sub[0][2])[0]
        idx = list(struct.unpack_from("<%di" % cnt, d, sub[0][2] + 4))
        chunks = [x for x in sub[1:] if x[0] == 7]
        ci = 0
        for i in range(cnt):
            if idx[i] >= 0 and idx[i] < len(mats):
                mats.append(mats[idx[i]])
                continue
            if ci >= len(chunks):
                mats.append((None, np.ones(4)))
                continue
            t3, s3, p3, v3 = chunks[ci]
            ci += 1
            inner = list(kids(d, p3, p3 + s3))
            fl, col, un, textured = struct.unpack_from("<IIII", d, inner[0][2])
            rgba = np.array([col & 255, (col >> 8) & 255, (col >> 16) & 255, (col >> 24) & 255], np.float64) / 255.0
            name = None
            if textured:
                for t4, s4, p4, v4 in inner[1:]:
                    if t4 == 6:
                        strs = [x for x in kids(d, p4, p4 + s4) if x[0] == 2]
                        if strs:
                            name = read_str(d, strs[0][2], strs[0][1])
            mats.append((name, rgba))
    return V, tris, mat, uv, mats


def load_dff(path, keep_all=False):
    d = open(path, "rb").read()
    root = next(kids(d, 0, len(d)))
    if root[0] != 0x10:
        raise ValueError("bukan file DFF (clump tidak ditemukan)")
    frames, names, geoms, atomics = [], [], [], []
    for t, s, p, v in kids(d, root[2], root[2] + root[1]):
        if t == 0xE:
            frames, names = read_frames(d, p, s)
        elif t == 0x1A:
            for t2, s2, p2, v2 in kids(d, p, p + s):
                if t2 == 0xF:
                    geoms.append(read_geometry(d, p2, s2, v2))
        elif t == 0x14:
            st = next(kids(d, p, p + s))
            fi, gi, _, _ = struct.unpack_from("<IIII", d, st[2])
            atomics.append((fi, gi))
    cache = {}

    def world(i, depth=0):
        if i in cache:
            return cache[i]
        R, P, par = frames[i]
        if par < 0 or par == i or par >= len(frames) or depth > 64:
            res = (R, P)
        else:
            Rp, Pp = world(par, depth + 1)
            res = (R @ Rp, P @ Rp + Pp)
        cache[i] = res
        return res

    parts = []
    for fi, gi in atomics:
        name = names[fi].lower() if fi < len(names) else ""
        if not keep_all and any(w in name for w in SKIP_WORDS):
            continue
        if gi >= len(geoms):
            continue
        V, T, M, uv, mats = geoms[gi]
        if len(T) == 0:
            continue
        R, P = world(fi) if fi < len(frames) else (np.eye(3), np.zeros(3))
        parts.append(dict(V=V @ R + P, T=T, M=M, uv=uv, mats=mats, name=name))
    if not parts:
        raise ValueError("tidak ada geometri yang bisa dirender")
    return parts


def pick_axes(parts, spec):
    allv = np.vstack([p["V"] for p in parts])
    ext = allv.max(0) - allv.min(0)
    if spec:
        m = {"x": 0, "y": 1, "z": 2}
        return tuple(m[c] for c in spec.lower())
    if ext[0] >= ext[1] and ext[0] >= ext[2]:
        return (0, 2, 1)
    h = int(np.argmax(ext))
    dd = int(np.argmin(ext))
    v = 3 - h - dd
    return (h, v, dd)


TILT_MIN = 5.0
TILT_BIAS = 2.5
ELONG_MIN = 3.5


def principal_angle(parts, axes):
    h, v, _ = axes
    ws, cs = [], []
    for p in parts:
        P = p["V"][:, [h, v]]
        T = p["T"]
        a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
        area = 0.5 * np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1]))
        ws.append(area)
        cs.append((a + b + c) / 3)
    w = np.concatenate(ws)
    c = np.vstack(cs)
    if w.sum() <= 0:
        return 0.0, 1.0
    m = (c * w[:, None]).sum(0) / w.sum()
    d = c - m
    C = (d.T * w) @ d / w.sum()
    ev, evec = np.linalg.eigh(C)
    ang = float(np.degrees(np.arctan2(evec[1, 1], evec[0, 1])))
    if ang > 90:
        ang -= 180
    if ang < -90:
        ang += 180
    return ang, float(np.sqrt(max(ev[1], 1e-18) / max(ev[0], 1e-18)))


def rotate_parts(parts, axes, deg):
    t = np.radians(deg)
    c, s = np.cos(t), np.sin(t)
    h, v, _ = axes
    out = []
    for p in parts:
        V = p["V"].copy()
        a, b = V[:, h].copy(), V[:, v].copy()
        V[:, h] = c * a - s * b
        V[:, v] = s * a + c * b
        q = dict(p)
        q["V"] = V
        out.append(q)
    return out


def rasterize(parts, axes, flip, scale, pad, with_uv=False):
    h, v, dp = axes
    maps = []
    for p in parts:
        V = p["V"]
        hh, vv, dd = V[:, h].copy(), V[:, v].copy(), V[:, dp].copy()
        if flip:
            hh, dd = -hh, -dd
        maps.append(np.stack([hh, vv, dd], 1))
    allm = np.vstack(maps)
    hmin, vmax = allm[:, 0].min(), allm[:, 1].max()
    W = int((allm[:, 0].max() - hmin) * scale) + 2 * pad + 2
    H = int((vmax - allm[:, 1].min()) * scale) + 2 * pad + 2
    zb = np.full((H, W), np.inf, np.float32)
    idb = np.full((H, W), -1, np.int32)
    ntri = max(1, sum(len(p["T"]) for p in parts))
    ndone = 0
    PROG.set("rasterisasi", 0.0)
    nb = np.zeros((H, W, 3), np.float16)
    uvb = np.zeros((H, W, 2), np.float32) if with_uv else None
    for pi, (p, M3) in enumerate(zip(parts, maps)):
        sx = (M3[:, 0] - hmin) * scale + pad
        sy = (vmax - M3[:, 1]) * scale + pad
        dz = M3[:, 2]
        T = p["T"]
        uv = (p["uv"] if p["uv"] is not None else np.zeros((len(M3), 2))) if with_uv else None
        e1 = M3[T[:, 1]] - M3[T[:, 0]]
        e2 = M3[T[:, 2]] - M3[T[:, 0]]
        N = np.cross(e1, e2)
        ln = np.linalg.norm(N, axis=1)
        ln[ln == 0] = 1
        N = (N / ln[:, None]).astype(np.float16)
        for ti in range(len(T)):
            if ti & 255 == 0:
                PROG.frac = (ndone + ti) / ntri
            a, b, c = T[ti]
            x0, y0, x1, y1, x2, y2 = sx[a], sy[a], sx[b], sy[b], sx[c], sy[c]
            den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(den) < 1e-9:
                continue
            minx = max(int(np.floor(min(x0, x1, x2))), 0)
            maxx = min(int(np.ceil(max(x0, x1, x2))), W - 1)
            miny = max(int(np.floor(min(y0, y1, y2))), 0)
            maxy = min(int(np.ceil(max(y0, y1, y2))), H - 1)
            if maxx < minx or maxy < miny:
                continue
            gx, gy = np.meshgrid(np.arange(minx, maxx + 1) + 0.5, np.arange(miny, maxy + 1) + 0.5)
            l0 = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / den
            l1 = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / den
            l2 = 1 - l0 - l1
            m = (l0 >= -1e-6) & (l1 >= -1e-6) & (l2 >= -1e-6)
            if not m.any():
                continue
            dep = l0 * dz[a] + l1 * dz[b] + l2 * dz[c]
            sub = zb[miny:maxy + 1, minx:maxx + 1]
            upd = m & (dep < sub)
            if not upd.any():
                continue
            sub[upd] = dep[upd]
            idb[miny:maxy + 1, minx:maxx + 1][upd] = pi * 8 + int(p["M"][ti])
            nb[miny:maxy + 1, minx:maxx + 1][upd] = N[ti]
            if with_uv:
                uu = l0 * uv[a, 0] + l1 * uv[b, 0] + l2 * uv[c, 0]
                vv = l0 * uv[a, 1] + l1 * uv[b, 1] + l2 * uv[c, 1]
                uvb[miny:maxy + 1, minx:maxx + 1, 0][upd] = uu[upd]
                uvb[miny:maxy + 1, minx:maxx + 1, 1][upd] = vv[upd]
        ndone += len(T)
    PROG.set("pewarnaan dan garis")
    return zb, idb, nb, uvb


def silhouette_glow(mask, ls, wid, gap, pw, stg, thr, sgn):
    f = 2
    H, W = mask.shape
    ms = mask[::f, ::f]
    dist, idx = ndi.distance_transform_edt(ms, return_indices=True)
    rr = np.arange(ms.shape[0], dtype=np.int32)[:, None]
    cc = np.arange(ms.shape[1], dtype=np.int32)[None, :]
    dr = (idx[0] - rr).astype(np.float32)
    dc = (idx[1] - cc).astype(np.float32)
    del idx
    dist = dist.astype(np.float32) * f
    face = (dc * ls[0] + dr * ls[1]) / np.maximum(dist / f, 1e-6)
    del dr, dc
    t = np.clip(1.0 - (dist - gap) / wid, 0.0, 1.0)
    t = (t ** pw) * stg * np.clip((sgn * face - thr) / 0.5, 0.0, 1.0)
    del dist, face
    t *= ms
    full = np.repeat(np.repeat(t, f, 0), f, 1)[:H, :W]
    if full.shape != (H, W):
        full = np.pad(full, ((0, H - full.shape[0]), (0, W - full.shape[1])))
    full = ndi.gaussian_filter(full, f * 0.8)
    return (full * mask).astype(np.float32)


def stylize(zb, idb, nb, k, unit, rel, fill, transparent, out_w, out_h, color=None, outline_u=None, line_u=None, min_len_u=None, ang_thr=None, depth_scale=None, ink=None, ink_line=None, drop=None, hl=None, glow=None, halo=None, box=None):
    depth_thr = DEPTH_THR * rel * (1.0 if depth_scale is None else depth_scale)
    cav_thr = CAV_THR * rel
    outline = (OUTLINE if outline_u is None else outline_u) * unit
    line = (LINE if line_u is None else line_u) * unit
    min_len = (MIN_LEN if min_len_u is None else min_len_u) * unit
    cav_min = CAV_MIN * unit
    m0 = int((outline + 6) * k)
    zb = np.pad(zb, m0, constant_values=np.inf)
    idb = np.pad(idb, m0, constant_values=-1)
    nb = np.pad(nb, ((m0, m0), (m0, m0), (0, 0)))
    if color is not None:
        color = np.pad(color, ((m0, m0), (m0, m0), (0, 0)))
    H, W = zb.shape
    eh, ew = (-H) % k, (-W) % k
    if eh or ew:
        zb = np.pad(zb, ((0, eh), (0, ew)), constant_values=np.inf)
        idb = np.pad(idb, ((0, eh), (0, ew)), constant_values=-1)
        nb = np.pad(nb, ((0, eh), (0, ew), (0, 0)))
        if color is not None:
            color = np.pad(color, ((0, eh), (0, ew), (0, 0)))
        H, W = zb.shape
    mask = idb >= 0
    ys, xs = np.where(mask)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    zf = np.where(mask, zb, 1e3).astype(np.float32)
    dxp = np.abs(zf[:, 1:] - zf[:, :-1])
    dyp = np.abs(zf[1:, :] - zf[:-1, :])
    de = np.zeros((H, W), bool)
    de[:, 1:] |= (dxp > depth_thr) & (dxp < 100)
    de[1:, :] |= (dyp > depth_thr) & (dyp < 100)
    del dxp, dyp, zf
    cosang = np.cos(np.radians(ANG_THR if ang_thr is None else ang_thr))
    ne = np.zeros((H, W), bool)
    dotx = (nb[:, 1:].astype(np.float32) * nb[:, :-1].astype(np.float32)).sum(-1)
    ne[:, 1:] |= (dotx < cosang) & mask[:, 1:] & mask[:, :-1]
    del dotx
    doty = (nb[1:].astype(np.float32) * nb[:-1].astype(np.float32)).sum(-1)
    ne[1:, :] |= (doty < cosang) & mask[1:, :] & mask[:-1, :]
    del doty, nb
    ie = np.zeros((H, W), bool)
    ie[:, 1:] |= (idb[:, 1:] != idb[:, :-1]) & mask[:, 1:] & mask[:, :-1]
    ie[1:, :] |= (idb[1:, :] != idb[:-1, :]) & mask[1:, :] & mask[:-1, :]
    edges = (de | ne | ie) & mask
    del de, ne, ie
    lab, n = ndi.label(edges, structure=np.ones((3, 3)))
    cnt = np.bincount(lab.ravel())
    keep = cnt >= min_len * k
    keep[0] = False
    edges = keep[lab]
    del lab
    r = max(1, int(round(line * k / 2)))
    el = dilate_disk(edges, r)
    hlm = None
    glw = None
    if (hl is not None or glow is not None) and color is not None:
        src = edges | ~mask
        dist, idx = ndi.distance_transform_edt(~src, return_indices=True)
        del src
        rr = np.arange(H, dtype=np.int32)[:, None]
        cc2 = np.arange(W, dtype=np.int32)[None, :]
        dr = (idx[0] - rr).astype(np.float32)
        dc = (idx[1] - cc2).astype(np.float32)
        isedge = mask[idx[0], idx[1]]
        del idx
        ls = np.array([LIGHT[0], -LIGHT[1]], np.float32)
        ls /= np.linalg.norm(ls)
        face = (dc * ls[0] + dr * ls[1]) / np.maximum(dist, 1e-6)
        del dr, dc
        dist = dist.astype(np.float32)
        if hl is not None:
            g_e, g_s, wid, hthr = hl[:4]
            ca, cb, tb = ((255.0, 255.0, 255.0), None, 0.0) if len(hl) == 4 else hl[4:7]
            lo = np.where(isedge, r + g_e * unit * k, g_s * unit * k)
            hi = lo + wid * unit * k
            band = mask & ~el & (dist > lo) & (dist <= hi)
            hla = band & (face > hthr)
            hlb = (band & (face < -tb)) if cb is not None else None
            hlm = (hla, hlb, ca, cb)
            del lo, hi, band
        if glow is not None:
            g_e, g_s, pa, pb = glow
            lo = np.where(isedge, r + g_e * unit * k, g_s * unit * k).astype(np.float32)
            layers = []
            for prm, sgn in ((pa, 1.0), (pb, -1.0)):
                if prm is None:
                    continue
                col, wid, pw, stg, inner, thr = prm
                if inner == 0.0:
                    t = silhouette_glow(mask, ls, wid * unit * k, g_s * unit * k, pw, stg, thr, sgn)
                else:
                    t = np.clip(1.0 - (dist - lo) / (wid * unit * k), 0.0, 1.0)
                    t = (t ** pw) * stg
                    t *= np.where(isedge, inner, 1.0).astype(np.float32)
                    t *= np.clip((sgn * face - thr) / 0.5, 0.0, 1.0)
                    t *= mask
                layers.append((t, col))
            del lo
            glw = layers
        del dist, face, isedge
    del edges
    win = int(14 * k)
    zmin = ndi.minimum_filter(np.where(mask, zb, 1e3), size=win | 1)
    cav = mask & ((zb - zmin) > cav_thr) & (zmin < 100)
    del zmin
    cav = ndi.binary_opening(cav, iterations=max(1, int(k)))
    cl, cn = ndi.label(cav)
    cc = np.bincount(cl.ravel())
    ck = cc >= (cav_min * k * k)
    ck[0] = False
    cav = ck[cl]
    del cl
    ro = int(round(outline * k))
    sil = dilate_disk(mask, ro)
    sil = ndi.binary_closing(sil, iterations=1) | sil
    if color is None:
        img = np.zeros((H, W), np.float32)
        img[mask] = fill
        img[(el | cav) & mask] = 0
        pre = box_resize(np.where(sil, img, 0).astype(np.float32), k)
    else:
        img = np.zeros((H, W, 3), np.float32)
        if ink is not None:
            img[:] = np.array(ink, np.float32)
        img[mask] = color[mask]
        if glw is not None:
            for t, col in glw:
                t3 = np.clip(t, 0.0, 1.0)[..., None]
                img = img * (1.0 - t3) + np.array(col, np.float32) * t3
            del glw, t3
        if box is not None:
            bmin, bmax, tlo, thi, bkeep = box[:5]
            bcore = box[5] if len(box) > 5 else None
            sc = float(k * k) * unit * unit
            dk = mask & ~el & ~cav & (color[..., 0] < 100)
            blab, bn = ndi.label(dk)
            del dk
            barea = np.bincount(blab.ravel(), minlength=bn + 1)
            bok = (barea >= bmin * sc) & (barea <= bmax * sc)
            bok &= ((np.arange(bn + 1, dtype=np.int64) * 40503 % 997) / 997.0) < bkeep
            bok[0] = False
            btone = tlo + ((np.arange(bn + 1, dtype=np.int64) * 2654435761 % 1000) / 1000.0) * (thi - tlo)
            bval = np.where(bok, btone, 0.0).astype(np.float32)
            bt = bval[blab]
            bsel = bt > 0
            if bcore is None:
                img[bsel] = bt[bsel][:, None]
            else:
                bdd = ndi.distance_transform_edt(bsel)
                bcm = bsel & (bdd > bcore * unit * k)
                img[bcm] = bt[bcm][:, None]
                del bdd, bcm
            del blab, barea, bok, btone, bval, bt, bsel
        img[(el | cav) & mask] = 0 if ink_line is None else np.array(ink_line, np.float32)
        if hlm is not None:
            img[hlm[0] & ~cav] = np.array(hlm[2], np.float32)
            if hlm[1] is not None:
                img[hlm[1] & ~cav] = np.array(hlm[3], np.float32)
            del hlm
        pre = np.dstack([box_resize(np.where(sil, img[..., c], 0).astype(np.float32), k) for c in range(3)])
    alp = box_resize(sil.astype(np.float32), k)
    sh, sw = pre.shape[:2]
    cx = (x0 + x1) / 2 / k
    cy = (y0 + y1) / 2 / k
    ox = int(round(out_w / 2 - cx))
    oy = int(round(out_h / 2 - cy))
    sx0, sy0 = max(0, -ox), max(0, -oy)
    dx0, dy0 = max(0, ox), max(0, oy)
    w = min(sw - sx0, out_w - dx0)
    h = min(sh - sy0, out_h - dy0)
    pc = np.zeros((out_h, out_w) + pre.shape[2:], np.float32)
    ac = np.zeros((out_h, out_w), np.float32)
    pc[dy0:dy0 + h, dx0:dx0 + w] = pre[sy0:sy0 + h, sx0:sx0 + w]
    ac[dy0:dy0 + h, dx0:dx0 + w] = alp[sy0:sy0 + h, sx0:sx0 + w]
    if color is not None and drop is not None:
        ddx, ddy, dal, dbl = drop
        ix, iy = int(round(ddx)), int(round(ddy))
        sa = np.roll(ac, (iy, ix), (0, 1))
        if iy > 0:
            sa[:iy] = 0
        elif iy < 0:
            sa[iy:] = 0
        if ix > 0:
            sa[:, :ix] = 0
        elif ix < 0:
            sa[:, ix:] = 0
        if dbl > 0:
            sa = ndi.gaussian_filter(sa, dbl)
        ac = ac + sa * dal * (1.0 - ac)
        del sa
    if color is not None and halo is not None:
        hcol, layers = halo
        keep_a = 1.0 - ac
        hal = np.zeros_like(ac)
        for sig, stg in layers:
            gl = ndi.gaussian_filter(ac, sig * unit)
            hal = 1.0 - (1.0 - hal) * (1.0 - np.clip(gl * 2.0 * stg, 0.0, 1.0))
        hal = hal * keep_a
        pc = pc + np.array(hcol, np.float32) * hal[..., None]
        ac = ac + hal
        del hal, keep_a
    if color is not None:
        a3 = ac[..., None]
        if transparent:
            g = np.where(a3 > 1e-4, pc / np.maximum(a3, 1e-4), 0)
            g = np.clip(g, 0, 255).astype(np.uint8)
            a8 = np.clip(ac * 255 + 0.5, 0, 255).astype(np.uint8)
            return np.dstack([g, a8])
        return np.clip(pc + 255 * (1 - a3), 0, 255).astype(np.uint8)
    if transparent:
        g = np.where(ac > 1e-4, pc / np.maximum(ac, 1e-4), 0)
        g = np.clip(g, 0, 255).astype(np.uint8)
        a8 = np.clip(ac * 255 + 0.5, 0, 255).astype(np.uint8)
        return np.dstack([g, g, g, a8])
    g = np.clip(pc + 255 * (1 - ac), 0, 255).astype(np.uint8)
    return g


LIGHT = np.array([-0.5, 0.7, -0.55], np.float32)
LIGHT /= np.linalg.norm(LIGHT)
TOON_OUTLINE = 2.4
TOON_LINE = 0.9
TOON_MIN_LEN = 8
TOON_ANG = 28
TOON_DEPTH = 0.25


def blur_masked(a, mask, sigma):
    m = mask.astype(np.float32)
    if a.ndim == 3:
        num = np.dstack([ndi.gaussian_filter(a[..., c] * m, sigma) for c in range(a.shape[2])])
    else:
        num = ndi.gaussian_filter(a * m, sigma)
    den = ndi.gaussian_filter(m, sigma)
    den = np.maximum(den, 1e-4)
    return num / (den[..., None] if a.ndim == 3 else den)


def toon_shade(idb, nb, zb, albedo, k, rel=1.0, bands=(-0.05, 0.32, 0.74), rim_px=1.15, dark_p=11, light_p=94, tone_target=0.5, sat_boost=1.12, rim_mix=0.4, nblur=0.3, fine_s=0.4):
    mask = idb >= 0
    n = nb.astype(np.float32)
    n[..., :] *= np.where(n[..., 2] > 0, -1.0, 1.0)[..., None]
    n = blur_masked(n, mask, nblur * k)
    ln = np.linalg.norm(n, axis=-1, keepdims=True)
    n = n / np.maximum(ln, 1e-6)
    ndl = (n * LIGHT).sum(-1)
    Hv = LIGHT + np.array([0, 0, -1], np.float32)
    Hv /= np.linalg.norm(Hv)
    spec = np.clip((n * Hv).sum(-1), 0, 1) ** 24
    band = np.zeros(idb.shape, np.int32)
    band[ndl > bands[0]] = 1
    band[ndl > bands[1]] = 2
    band[ndl > bands[2]] = 3
    band[spec > 0.55] = 4
    zf = np.where(mask, zb, 1e3).astype(np.float32)
    bd = np.zeros(idb.shape, bool)
    dx = np.abs(zf[:, 1:] - zf[:, :-1])
    dy = np.abs(zf[1:, :] - zf[:-1, :])
    bd[:, 1:] |= (dx > DEPTH_THR * rel)
    bd[1:, :] |= (dy > DEPTH_THR * rel)
    bd[:, 1:] |= idb[:, 1:] != idb[:, :-1]
    bd[1:, :] |= idb[1:, :] != idb[:-1, :]
    bd |= ~mask
    bdist = ndi.distance_transform_edt(~bd)
    rim = mask & (bdist < rim_px * k) & (ndl > 0.2) & (n[..., 1] > 0.15)
    band[rim] = 4
    alb = blur_masked(albedo, mask, 3.0 * k)
    lum = alb.mean(-1)
    fine = blur_masked(albedo, mask, fine_s * k).mean(-1)
    ratio = fine / np.maximum(lum, 1e-4)
    keep = band < 4
    darkm = np.zeros(idb.shape, bool)
    lightm = np.zeros(idb.shape, bool)
    for code in np.unique(idb[mask]):
        sel = idb == code
        if sel.sum() < 200:
            continue
        lo_t, hi_t = np.percentile(ratio[sel], [dark_p, light_p])
        darkm |= sel & (ratio < lo_t)
        lightm |= sel & (ratio > hi_t)
    band = np.where(keep & darkm, np.maximum(band - 1, 0), band)
    band = np.where(keep & lightm, np.minimum(band + 1, 3), band)
    g = min(tone_target / max(float(np.percentile(lum[mask], 90)), 1e-3), 6.0)
    base = np.clip(alb * g, 0, 1)
    gray = base.mean(-1, keepdims=True)
    base = np.clip(gray + (base - gray) * sat_boost, 0, 1)
    mult = np.array([0.34, 0.6, 0.88, 1.12, 1.12], np.float32)[band][..., None]
    col = np.clip(base * mult, 0, 1)
    isrim = (band == 4)[..., None]
    col = np.where(isrim, col + (1 - col) * rim_mix, col)
    out = col * 255
    out[~mask] = 0
    return out.astype(np.float32)


SHADOW_DARK = 88.0
SHADOW_LO = -0.50
SHADOW_HI = 0.42
SHADOW_NBLUR = 1.3
SHADOW_REACH = 0.09
SHADOW_CAST = 0.8
SHADOW_BEVEL = 0.95
SHADOW_BEVEL_REACH = 0.048
SHADOW_SOFT = 1.6
SHADOW_DOWN = 2
SHADOW_WIDTH_SMOOTH = 5.0
SHADOW_RAMP = 3.0
SHADOW_EDGE_SMOOTH = 7.0
SHADOW_FACE_LO = 0.0
SHADOW_FACE_HI = 0.75
SHADOW_CUT_LO = 0.38
SHADOW_CUT_HI = 0.60


def smoothstep(x, lo, hi):
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def shifted(zp, pad, dr, dc, h, w):
    return zp[pad + dr:pad + dr + h, pad + dc:pad + dc + w]


def edge_band(mr, rel, s, q):
    m = mr.astype(np.float32)
    g = ndi.gaussian_filter(m, SHADOW_EDGE_SMOOTH * q)
    gy, gx = np.gradient(g)
    ln = np.maximum(np.sqrt(gx * gx + gy * gy), 1e-9)
    ny, nx = -gy / ln, -gx / ln
    dist, idx = ndi.distance_transform_edt(mr, return_indices=True)
    br, bc = idx[0], idx[1]
    del idx
    away = np.array([-LIGHT[0], LIGHT[1]], np.float32)
    away = away / np.linalg.norm(away)
    facing = nx[br, bc] * away[0] + ny[br, bc] * away[1]
    del br, bc, nx, ny, g, gx, gy, ln
    wgt = smoothstep(facing, SHADOW_FACE_LO, SHADOW_FACE_HI)
    del facing
    wgt = blur_masked(wgt.astype(np.float32), mr, SHADOW_WIDTH_SMOOTH * q)
    width = SHADOW_BEVEL_REACH * rel * s * wgt
    del wgt
    return np.clip((width - dist) / (SHADOW_RAMP * q) + 0.5, 0.0, 1.0) * mr


def cast_shadow(zb, mask, k, rel, scale):
    f = SHADOW_DOWN
    q = 3.0 / f
    H, W = mask.shape
    hh, ww = H // f * f, W // f * f
    mr = mask[:hh, :ww].reshape(hh // f, f, ww // f, f).mean((1, 3), dtype=np.float32) > 0.5
    s = scale / f
    bev = edge_band(mr, rel, s, q)
    soft = ndi.gaussian_filter(bev, SHADOW_SOFT * q)
    soft = ndi.zoom(soft, f, order=1, mode='nearest', grid_mode=True)
    full = np.zeros(mask.shape, np.float32)
    h2, w2 = min(H, soft.shape[0]), min(W, soft.shape[1])
    full[:h2, :w2] = soft[:h2, :w2]
    return full


def shadow_shade(idb, nb, zb, k, rel, scale):
    mask = idb >= 0
    n = nb.astype(np.float32)
    n *= np.where(n[..., 2] > 0, -1.0, 1.0)[..., None]
    n = blur_masked(n, mask, SHADOW_NBLUR * k)
    ln = np.linalg.norm(n, axis=-1, keepdims=True)
    n /= np.maximum(ln, 1e-6)
    ndl = (n * LIGHT).sum(-1)
    del n, ln
    lit = smoothstep(ndl, SHADOW_LO, SHADOW_HI)
    del ndl
    cs = cast_shadow(zb, mask, k, rel, scale)
    cs = smoothstep(cs, SHADOW_CUT_LO, SHADOW_CUT_HI)
    lit = lit * (1.0 - cs)
    del cs
    gray = SHADOW_DARK + (255.0 - SHADOW_DARK) * lit
    gray[~mask] = 0
    return np.repeat(gray.astype(np.float32)[..., None], 3, -1)


VICE_OUTLINE = 3.0
VICE_LINE = 1.0
VICE_MIN_LEN = 8
VICE_ANG = 26
VICE_DEPTH = 0.22
VICE_INK = (20.0, 6.0, 42.0)
VICE_INK_LINE = (46.0, 14.0, 92.0)
VICE_STOPS = ((0.0, (30.0, 214.0, 230.0)), (0.40, (52.0, 200.0, 236.0)), (0.64, (150.0, 156.0, 244.0)), (0.86, (226.0, 118.0, 236.0)), (1.0, (240.0, 100.0, 226.0)))
VICE_TINT = (56.0, 20.0, 126.0)
VICE_BANDS = (-0.12, 0.28, 0.70)
VICE_RIM_PX = 1.5
VICE_DETAIL = 0.10
VICE_VARY = 0.06
VICE_SHADOW_DX = 0.0
VICE_SHADOW_DY = 4.0
VICE_SHADOW_ALPHA = 0.92
VICE_SHADOW_BLUR = 0.6


def vice_gradient(mask, k):
    H, W = mask.shape
    cols = mask.sum(0).astype(np.float32)
    xs = np.where(cols > 0)[0]
    x0, x1 = int(xs[0]), int(xs[-1])
    ys = np.where(mask.any(1))[0]
    y0, y1 = int(ys[0]), int(ys[-1])
    span = max(x1 - x0, 1)
    seg = max(int(span * 0.22), 1)
    left = cols[x0:x0 + seg].mean()
    right = cols[x1 - seg + 1:x1 + 1].mean()
    tx = (np.arange(W, dtype=np.float32) - x0) / span
    if left >= right:
        tx = 1.0 - tx
    ty = (np.arange(H, dtype=np.float32) - y0) / max(y1 - y0, 1)
    t = np.clip(0.88 * tx[None, :] + 0.12 * ty[:, None], 0.0, 1.0)
    pos = np.array([s[0] for s in VICE_STOPS], np.float32)
    cl = np.array([s[1] for s in VICE_STOPS], np.float32)
    out = np.empty((H, W, 3), np.float32)
    for c in range(3):
        out[..., c] = np.interp(t, pos, cl[:, c])
    return out


def vice_shade(idb, nb, zb, k, rel):
    mask = idb >= 0
    n = nb.astype(np.float32)
    n[..., :] *= np.where(n[..., 2] > 0, -1.0, 1.0)[..., None]
    n = blur_masked(n, mask, 0.3 * k)
    ln = np.linalg.norm(n, axis=-1, keepdims=True)
    n = n / np.maximum(ln, 1e-6)
    ndl = (n * LIGHT).sum(-1)
    Hv = LIGHT + np.array([0, 0, -1], np.float32)
    Hv /= np.linalg.norm(Hv)
    spec = np.clip((n * Hv).sum(-1), 0, 1) ** 24
    ny = n[..., 1].copy()
    del n, ln
    band = np.zeros(idb.shape, np.int32)
    band[ndl > VICE_BANDS[0]] = 1
    band[ndl > VICE_BANDS[1]] = 2
    band[ndl > VICE_BANDS[2]] = 3
    coarse = blur_masked(ndl, mask, 2.6 * k)
    fine = ndl - coarse
    del coarse
    band = np.where(fine < -VICE_DETAIL, np.maximum(band - 1, 0), band)
    band = np.where(fine > VICE_DETAIL, np.minimum(band + 1, 3), band)
    del fine
    band[spec > 0.55] = 4
    zf = np.where(mask, zb, 1e3).astype(np.float32)
    bd = np.zeros(idb.shape, bool)
    dx = np.abs(zf[:, 1:] - zf[:, :-1])
    dy = np.abs(zf[1:, :] - zf[:-1, :])
    bd[:, 1:] |= (dx > DEPTH_THR * rel)
    bd[1:, :] |= (dy > DEPTH_THR * rel)
    bd[:, 1:] |= idb[:, 1:] != idb[:, :-1]
    bd[1:, :] |= idb[1:, :] != idb[:-1, :]
    bd |= ~mask
    del dx, dy, zf
    bdist = ndi.distance_transform_edt(~bd)
    del bd
    rim = mask & (bdist < VICE_RIM_PX * k) & (ndl > 0.15) & (ny > 0.1)
    del bdist, ndl, ny, spec
    band[rim] = 4
    del rim
    base = vice_gradient(mask, k)
    vary = np.ones(idb.shape, np.float32)
    for code in np.unique(idb[mask]):
        vary[idb == code] = 1.0 + (((int(code) * 37) % 11) - 5) / 5.0 * VICE_VARY
    base = np.clip(base * vary[..., None], 0, 255)
    del vary
    mul = np.array([0.62, 0.82, 1.0, 1.0, 1.0], np.float32)[band][..., None]
    wt = np.array([0.42, 0.16, 0.0, 0.0, 0.0], np.float32)[band][..., None]
    ww = np.array([0.0, 0.0, 0.0, 0.26, 0.60], np.float32)[band][..., None]
    del band
    col = base * mul
    del base, mul
    col = col + (np.array(VICE_TINT, np.float32) - col) * wt
    col = col + (255.0 - col) * ww
    col[~mask] = 0
    return np.clip(col, 0, 255).astype(np.float32)


GTA_OUTLINE = 2.2
GTA_LINE = 0.9
GTA_MIN_LEN = 7
GTA_ANG = 30
GTA_DEPTH = 0.22
GTA_TONES = (130.0, 130.0, 130.0, 130.0, 112.0, 86.0)
GTA_LIT = 12.0
GTA_DARK = 14.0
GTA_HL = (0.35, 0.2, 0.75, 0.30)


def gta_shade(idb, nb, k):
    mask = idb >= 0
    n = nb.astype(np.float32)
    n[..., :] *= np.where(n[..., 2] > 0, -1.0, 1.0)[..., None]
    n = blur_masked(n, mask, 0.3 * k)
    ln = np.linalg.norm(n, axis=-1, keepdims=True)
    n = n / np.maximum(ln, 1e-6)
    ndl = (n * LIGHT).sum(-1)
    del n, ln
    g = np.zeros(idb.shape, np.float32)
    for code in np.unique(idb[mask]):
        g[idb == code] = GTA_TONES[(int(code) * 7 + int(code) // 8) % len(GTA_TONES)]
    g = g + np.where(ndl > 0.45, GTA_LIT, 0.0) - np.where(ndl < -0.2, GTA_DARK, 0.0)
    del ndl
    g[~mask] = 0
    g = np.clip(g, 0, 255)
    return np.repeat(g[..., None], 3, -1).astype(np.float32)


GTA6_RIM_A = (44.0, 232.0, 255.0)
GTA6_RIM_B = (236.0, 58.0, 190.0)
GTA6_RIM_LINE = (232.0, 252.0, 255.0)
GTA6_GLOW = (0.1, 0.1, None, (GTA6_RIM_B, 5.6, 1.4, 1.0, 0.0, 0.30))
GTA6_SHEEN_LO = 0.90
GTA6_SHEEN_HI = 0.955
GTA6_CORE_LO = 0.945
GTA6_CORE_HI = 0.975
GTA6_SHEEN_STR = 0.9
GTA6_SOFT_LO = 0.89
GTA6_SOFT_HI = 0.93
GTA6_SOFT_STR = 0.3
GTA6_CORE_STR = 0.75
GTA6_SHEEN_CORE = (214.0, 250.0, 255.0)
GTA6_HL = (0.3, 0.2, 0.35, 0.5, GTA6_RIM_LINE, None, 0.0)
GTA6_SHADOW = (34.0, 10.0, 74.0)
GTA6_LIGHT = (96.0, 214.0, 255.0)
GTA6_GRADE = 0.30
GTA6_NOTEX_DARK = 0.38


def gta6_grade(rgb, mask, dark=1.0):
    rgb = rgb * dark
    lum = (rgb.mean(-1) / 255.0)[..., None]
    tint = np.array(GTA6_SHADOW, np.float32) * (1.0 - lum) + np.array(GTA6_LIGHT, np.float32) * lum
    out = rgb * (1.0 - GTA6_GRADE) + tint * GTA6_GRADE
    out[~mask] = 0
    return np.clip(out, 0, 255).astype(np.float32)


def gta6_sheen(rgb, idb, nb, k):
    f = 2
    H, W = idb.shape
    m = idb[::f, ::f] >= 0
    n = nb[::f, ::f].astype(np.float32)
    n *= np.where(n[..., 2] > 0, -1.0, 1.0)[..., None]
    n = blur_masked(n, m, 1.0 * k / f)
    ln = np.linalg.norm(n, axis=-1, keepdims=True)
    n /= np.maximum(ln, 1e-6)
    Hv = LIGHT + np.array([0, 0, -1], np.float32)
    Hv /= np.linalg.norm(Hv)
    sp = (n * Hv).sum(-1)
    del n, ln
    a = smoothstep(sp, GTA6_SHEEN_LO, GTA6_SHEEN_HI) * m
    c = smoothstep(sp, GTA6_CORE_LO, GTA6_CORE_HI) * m
    q = smoothstep(sp, GTA6_SOFT_LO, GTA6_SOFT_HI) * m
    del sp

    def up(x):
        x = np.repeat(np.repeat(x, f, 0), f, 1)[:H, :W]
        if x.shape != (H, W):
            x = np.pad(x, ((0, H - x.shape[0]), (0, W - x.shape[1])))
        return ndi.gaussian_filter(x.astype(np.float32), f * 0.7)

    a = up(a)[..., None] * GTA6_SHEEN_STR
    a = a + up(q)[..., None] * GTA6_SOFT_STR * (1.0 - a)
    del q
    c = up(c)[..., None] * GTA6_CORE_STR
    out = rgb * (1.0 - a) + np.array(GTA6_RIM_A, np.float32) * a
    del a
    out = out * (1.0 - c) + np.array(GTA6_SHEEN_CORE, np.float32) * c
    out[idb < 0] = 0
    return np.clip(out, 0, 255).astype(np.float32)


SLEEK_OUTLINE = 1.7
SLEEK_LINE = 0.95
SLEEK_MIN_LEN = 7
SLEEK_ANG = 30
SLEEK_DEPTH = 0.22
SLEEK_INK = (234.0, 234.0, 234.0)
SLEEK_INK_LINE = (232.0, 232.0, 232.0)
SLEEK_TONES = (136.0, 148.0, 160.0, 172.0)
SLEEK_LIT = 12.0
SLEEK_DARK = 14.0
SLEEK_LIT_AT = 0.45
SLEEK_DARK_AT = -0.2
SLEEK_NBLUR = 0.3
SLEEK_HALO_COLOR = (255.0, 255.0, 255.0)
SLEEK_HALO = ((0.7, 0.50), (2.0, 0.22))


def sleek_shade(idb, nb, k):
    mask = idb >= 0
    n = nb.astype(np.float32)
    n[..., :] *= np.where(n[..., 2] > 0, -1.0, 1.0)[..., None]
    n = blur_masked(n, mask, SLEEK_NBLUR * k)
    ln = np.linalg.norm(n, axis=-1, keepdims=True)
    n = n / np.maximum(ln, 1e-6)
    ndl = (n * LIGHT).sum(-1)
    del n, ln
    g = np.zeros(idb.shape, np.float32)
    for code in np.unique(idb[mask]):
        g[idb == code] = SLEEK_TONES[(int(code) * 5 + int(code) // 8) % len(SLEEK_TONES)]
    g = g + SLEEK_LIT * smoothstep(ndl, SLEEK_LIT_AT - 0.15, SLEEK_LIT_AT + 0.15) - SLEEK_DARK * smoothstep(-ndl, -SLEEK_DARK_AT - 0.15, -SLEEK_DARK_AT + 0.15)
    del ndl
    g[~mask] = 0
    g = np.clip(g, 0, 255)
    return np.repeat(g[..., None], 3, -1).astype(np.float32)


RE_OUTLINE = 1.0
RE_LINE = 0.8
RE_MIN_LEN = 7
RE_ANG = 30
RE_DEPTH = 0.22
RE_INK = (172.0, 172.0, 172.0)
RE_INK_LINE = (150.0, 150.0, 150.0)
RE_LIGHT_TONE = 74.0
RE_BUSY_TONE = 84.0
RE_DARK_TONE = 30.0
RE_LIT = 12.0
RE_SHADE = 12.0
RE_LIT_AT = 0.45
RE_SHADE_AT = -0.2
RE_NBLUR = 0.3
RE_SMALL = 0.02
RE_LIGHT_MAX = 0.12
RE_BOX_MIN = 5.0
RE_BOX_MAX = 150.0
RE_BOX_KEEP = 1.0
RE_BOX_TONE = (176.0, 206.0)
RE_BOX_CORE = 1.1
RE_BOX = None
RE_BUSY = True
RE_BUSY_MIN_FRAC = 0.05
RE_BUSY_MAX_FRAC = 0.25
RE_BUSY_RATIO = 1.4
RE_BUSY_ANG = 35
RE_DARK_HINT = ("mag", "clip", "grip", "stock", "handle", "butt", "wood", "scope", "lens")
RE_LIGHT_HINT = ("bolt", "slide", "barrel", "trigger", "bullet", "shell", "ammo", "sight", "hammer", "muzzle", "action", "rail")
RE_HALO_COLOR = (255.0, 255.0, 255.0)
RE_HALO = ()


RE_REAR_ZONE = 0.42
RE_REAR_MAX = 0.07
RE_REAR_PIECE = 0.04


def split_parts(parts):
    out = []
    for p in parts:
        V, T = p["V"], p["T"]
        key = np.round(V / 1e-5).astype(np.int64)
        _, inv = np.unique(key, axis=0, return_inverse=True)
        inv = inv.ravel()
        t = inv[T]
        n = int(inv.max()) + 1
        g = coo_matrix((np.ones(len(T) * 3), (np.r_[t[:, 0], t[:, 1], t[:, 2]], np.r_[t[:, 1], t[:, 2], t[:, 0]])), shape=(n, n))
        nc, lab = connected_components(g, directed=False)
        if nc <= 1:
            out.append(p)
            continue
        tl = lab[t[:, 0]]
        for c in range(nc):
            m = tl == c
            T2 = T[m]
            used = np.unique(T2)
            remap = np.full(len(V), -1, np.int64)
            remap[used] = np.arange(len(used))
            q = dict(p)
            q["V"] = V[used]
            q["T"] = remap[T2]
            q["M"] = p["M"][m]
            q["uv"] = p["uv"][used] if p["uv"] is not None else None
            out.append(q)
    return out


def re_shade(idb, nb, k, parts=None, swap=False):
    mask = idb >= 0
    n = nb.astype(np.float32)
    n[..., :] *= np.where(n[..., 2] > 0, -1.0, 1.0)[..., None]
    n = blur_masked(n, mask, RE_NBLUR * k)
    ln = np.linalg.norm(n, axis=-1, keepdims=True)
    n = n / np.maximum(ln, 1e-6)
    ndl = (n * LIGHT).sum(-1)
    edg = None
    if RE_BUSY:
        ca = np.cos(np.radians(RE_BUSY_ANG))
        edg = np.zeros(idb.shape, bool)
        edg[:, 1:] |= ((n[:, 1:] * n[:, :-1]).sum(-1) < ca) & mask[:, 1:] & mask[:, :-1]
        edg[1:, :] |= ((n[1:] * n[:-1]).sum(-1) < ca) & mask[1:, :] & mask[:-1, :]
    del n, ln
    codes, cnt = np.unique(idb[mask], return_counts=True)
    total = float(cnt.sum())
    islight = np.zeros(idb.shape, bool)
    isbusy = np.zeros(idb.shape, bool)
    used = 0.0
    entries = []
    for code, c in zip(codes, cnt):
        nm = ""
        if parts is not None and int(code) // 8 < len(parts):
            pp = parts[int(code) // 8]
            mi = int(code) % 8
            nm = pp["name"] + " " + ((pp["mats"][mi][0] or "") if mi < len(pp["mats"]) else "")
        if any(w in nm for w in RE_LIGHT_HINT):
            islight |= idb == code
            used += c / total
            continue
        if any(w in nm for w in RE_DARK_HINT):
            continue
        cm = idb == code
        lab, nl = ndi.label(cm)
        sizes = np.bincount(lab.ravel(), minlength=nl + 1)
        tiny = (sizes / total) < RE_SMALL
        tiny[0] = False
        islight |= tiny[lab]
        for li in np.where((sizes / total >= RE_SMALL) & (np.arange(nl + 1) > 0))[0]:
            cmk = lab == li
            dens = float(edg[cmk].sum()) / sizes[li] if edg is not None else 0.0
            entries.append((sizes[li] / total, cmk, dens))
        del lab, cm
    entries.sort(key=lambda x: x[0])
    chosen = [False] * len(entries)
    for i, (frac, cmk, dens) in enumerate(entries):
        if used + frac <= RE_LIGHT_MAX:
            islight |= cmk
            used += frac
            chosen[i] = True
    if used == 0.0 and entries:
        islight |= entries[0][1]
        chosen[0] = True
    busy = [(e[2], i) for i, e in enumerate(entries) if RE_BUSY_MIN_FRAC <= e[0] <= RE_BUSY_MAX_FRAC]
    if RE_BUSY and len(busy) > 1:
        dens = sorted(b[0] for b in busy)
        med = dens[len(dens) // 2]
        top = max(busy, key=lambda b: b[0])
        if top[0] >= RE_BUSY_RATIO * max(med, 1e-9):
            isbusy = entries[top[1]][1].copy()
            islight |= isbusy
            chosen[top[1]] = True
    if RE_REAR_MAX > 0 and islight.any():
        cols = np.where(mask.any(0))[0]
        c0, c1 = float(cols[0]), float(cols[-1])
        lc = float(np.where(islight.any(0))[0].mean())
        front_right = lc > (c0 + c1) / 2
        span = max(c1 - c0, 1.0)
        rear_used = 0.0
        for i in sorted(range(len(entries)), key=lambda j: entries[j][0]):
            frac, cmk, dens = entries[i]
            if chosen[i] or frac > RE_REAR_PIECE:
                continue
            cc = float(np.where(cmk.any(0))[0].mean())
            t = (c1 - cc) / span if not front_right else (cc - c0) / span
            if t < RE_REAR_ZONE and rear_used + frac <= RE_REAR_MAX:
                islight |= cmk
                rear_used += frac
    del entries, edg
    if swap:
        islight = mask & ~islight
        isbusy = np.zeros(idb.shape, bool)
    g = np.where(islight, np.where(isbusy, RE_BUSY_TONE, RE_LIGHT_TONE), RE_DARK_TONE).astype(np.float32)
    amp = np.where(islight, 1.0, 0.6).astype(np.float32)
    g = g + amp * (RE_LIT * smoothstep(ndl, RE_LIT_AT - 0.15, RE_LIT_AT + 0.15) - RE_SHADE * smoothstep(-ndl, -RE_SHADE_AT - 0.15, -RE_SHADE_AT + 0.15))
    del ndl, amp, islight, isbusy
    g[~mask] = 0
    g = np.clip(g, 0, 255)
    return np.repeat(g[..., None], 3, -1).astype(np.float32)


PIXEL_U = 3.0
PIXEL_MERGE = 26.0
PIXEL_BANDS = (-0.05, 0.32, 0.74)
PIXEL_MULT = (0.62, 0.82, 1.0, 1.2)
PIXEL_TONE = 0.55
PIXEL_SAT = 1.1
PIXEL_RIM = 1.3
PIXEL_LINE = (18.0, 18.0, 22.0)
PIXEL_OUTLINE = (8.0, 8.0, 10.0)
PIXEL_LINE_DEPTH = 2.5
PIXEL_LINE_MIN = 3


def kmeans_palette(x, kk, iters=14):
    n = len(x)
    kk = max(1, min(kk, n))
    order = np.argsort(x.mean(1))
    cen = x[order[((np.arange(kk) + 0.5) / kk * n).astype(np.int64)]].astype(np.float64)
    lab = np.zeros(n, np.int64)
    for _ in range(iters):
        d = ((x[:, None, :] - cen[None, :, :]) ** 2).sum(-1)
        lab = d.argmin(1)
        for j in range(kk):
            m = lab == j
            if m.any():
                cen[j] = x[m].mean(0)
    return cen, lab


def pixel_art(idb, nb, zb, albedo, k, unit, rel):
    p = max(2, int(round(PIXEL_U * unit)))
    c = p * k
    mask = idb >= 0
    ys, xs = np.where(mask)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    gh = (y1 - y0 + c - 1) // c + 4
    gw = (x1 - x0 + c - 1) // c + 4
    H, W = gh * c, gw * c
    oy, ox = 2 * c - 0, 2 * c - 0
    def put(a, fill):
        out = np.full((H, W) + a.shape[2:], fill, a.dtype)
        out[oy:oy + (y1 - y0), ox:ox + (x1 - x0)] = a[y0:y1, x0:x1]
        return out
    mk = put(mask, False)
    idc = put(idb, -1)
    zc = put(np.where(mask, zb, np.inf).astype(np.float32), np.inf)
    cov = mk.reshape(gh, c, gw, c).mean((1, 3), dtype=np.float32)
    S = cov >= 0.5
    cnt = np.maximum(mk.reshape(gh, c, gw, c).sum((1, 3)).astype(np.float32), 1.0)
    alb = np.zeros((gh, gw, 3), np.float32)
    for ch in range(3):
        a = put(albedo[..., ch].astype(np.float32), 0.0)
        a = a * mk
        alb[..., ch] = a.reshape(gh, c, gw, c).sum((1, 3)) / cnt
        del a
    n = nb.astype(np.float32)
    n *= np.where(n[..., 2] > 0, -1.0, 1.0)[..., None]
    ndl_hi = (n * LIGHT).sum(-1)
    del n
    ndl_hi = put(np.where(mask, ndl_hi, 0.0).astype(np.float32), 0.0)
    ndl = ndl_hi.reshape(gh, c, gw, c).sum((1, 3)) / cnt
    del ndl_hi
    zcell = zc.reshape(gh, c, gw, c).min((1, 3))
    zcell = np.where(S, zcell, np.inf)
    icell = idc.reshape(gh, c, gw, c).max((1, 3))
    del mk, idc, zc
    lum = alb.mean(-1)
    g = min(PIXEL_TONE / max(float(np.percentile(lum[S], 90)), 1e-3), 4.0)
    base = np.clip(alb * g, 0, 1)
    gray = base.mean(-1, keepdims=True)
    base = np.clip(gray + (base - gray) * PIXEL_SAT, 0, 1) * 255.0
    col = base.copy()
    for code in np.unique(icell[S]):
        m = S & (icell == code)
        pts = base[m]
        if len(pts) < 8:
            col[m] = pts.mean(0)
            continue
        cen, lab = kmeans_palette(pts, 2)
        if np.linalg.norm(cen[0] - cen[-1]) < PIXEL_MERGE:
            col[m] = pts.mean(0)
        else:
            col[m] = cen[lab]
    band = np.zeros((gh, gw), np.int64)
    band[ndl > PIXEL_BANDS[0]] = 1
    band[ndl > PIXEL_BANDS[1]] = 2
    band[ndl > PIXEL_BANDS[2]] = 3
    band = ndi.median_filter(np.where(S, band, 2), size=3, mode="nearest")
    col = col * np.array(PIXEL_MULT, np.float32)[band][..., None]

    zf = np.where(S, zcell, 1e3)
    thr = DEPTH_THR * rel * PIXEL_LINE_DEPTH
    line = np.zeros((gh, gw), bool)
    for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        zn = np.roll(zf, (dy, dx), (0, 1))
        sn = np.roll(S, (dy, dx), (0, 1))
        idn = np.roll(icell, (dy, dx), (0, 1))
        both = S & sn
        far = (zcell - zn) > thr
        diffid = (icell != idn) & ((zcell > zn) | ((zcell == zn) & (icell > idn)))
        line |= both & (far | diffid)
    lab2, nl2 = ndi.label(line, structure=np.ones((3, 3)))
    sz = np.bincount(lab2.ravel())
    keepl = sz >= PIXEL_LINE_MIN
    keepl[0] = False
    line = keepl[lab2]

    up = np.roll(S, 1, 0)
    up[0] = False
    rim = S & ~up & ~line
    col = np.where(rim[..., None], np.minimum(col * PIXEL_RIM + 14.0, 255.0), col)
    col[line] = np.array(PIXEL_LINE, np.float32)
    ring = ndi.binary_dilation(S, structure=ndi.generate_binary_structure(2, 1)) & ~S
    col[ring] = np.array(PIXEL_OUTLINE, np.float32)
    alpha = (S | ring).astype(np.float32) * 255.0
    art = np.dstack([np.clip(col, 0, 255), alpha])
    return art, p


def shade_albedo(parts, idb, uvb, tex):
    H, W = idb.shape
    rgb = np.zeros((H, W, 3), np.float32)
    for code in np.unique(idb):
        if code < 0:
            continue
        pi, mi = divmod(int(code), 8)
        mats = parts[pi]["mats"]
        name, col = mats[mi] if mi < len(mats) else (None, np.ones(4))
        sel = idb == code
        if name and name in tex:
            im = tex[name]
            th, tw = im.shape[:2]
            u = uvb[sel, 0]
            v = uvb[sel, 1]
            xi = np.floor((u - np.floor(u)) * tw).astype(np.int64) % tw
            yi = np.floor((v - np.floor(v)) * th).astype(np.int64) % th
            c = im[yi, xi, :3].astype(np.float32) / 255.0
        else:
            c = np.full((int(sel.sum()), 3), 0.8, np.float32)
        rgb[sel] = np.clip(c * col[:3].astype(np.float32), 0, 1)
    return rgb


def make_icon(path, out, width, axes_spec, flip, keep_all, fill, transparent, rotate=0.0, straighten=False, style="abu", keep_stock=False, re_swap=False):
    PROG.set("memuat model")
    parts = load_dff(path, keep_all)
    if not keep_stock:
        parts = drop_parts(parts, path)
    axes = pick_axes(parts, axes_spec)
    note = ""
    turn = rotate
    if straighten:
        ang, elong = principal_angle(parts, axes)
        tilt = ang - TILT_BIAS
        if abs(tilt) > TILT_MIN and elong >= ELONG_MIN:
            turn += -tilt
            note = f"diluruskan {-tilt:+.1f} derajat"
    if turn:
        parts = rotate_parts(parts, axes, turn)
    allv = np.vstack([p["V"] for p in parts])
    length = float(allv[:, axes[0]].max() - allv[:, axes[0]].min())
    height = float(allv[:, axes[1]].max() - allv[:, axes[1]].min())
    if length <= 0:
        raise ValueError("dimensi model nol")
    unit = width / REF_W
    out_w = int(width)
    out_h = int(round(REF_H * unit))
    tw = min(WEAPON_FRAC_W * out_w, WEAPON_FRAC_H * out_h * length / max(height, 1e-6))
    scale = SUPERSAMPLE * tw / length
    pad = 2
    rel = length / REF_LENGTH
    if style == "kartun":
        wanted = set(m[0] for p in parts for m in p["mats"] if m[0])
        tex = find_textures(path, wanted)
        if not tex:
            raise ValueError("file .txd tidak ditemukan di folder DFF (dibutuhkan untuk --style kartun)")
        zb, idb, nb, uvb = rasterize(parts, axes, flip, scale, pad, True)
        albedo = shade_albedo(parts, idb, uvb, tex)
        del uvb, tex
        rgb = toon_shade(idb, nb, zb, albedo, SUPERSAMPLE, rel)
        del albedo
        res = stylize(zb, idb, nb, SUPERSAMPLE, unit, rel, fill, transparent, out_w, out_h, rgb, TOON_OUTLINE, TOON_LINE, TOON_MIN_LEN, TOON_ANG, TOON_DEPTH)
    elif style == "gta6":
        wanted = set(m[0] for p in parts for m in p["mats"] if m[0])
        tex = find_textures(path, wanted)
        notex = not tex
        if notex:
            note = "tanpa .txd, warna dasar netral"
        zb, idb, nb, uvb = rasterize(parts, axes, flip, scale, pad, True)
        albedo = shade_albedo(parts, idb, uvb, tex)
        del uvb, tex
        rgb = toon_shade(idb, nb, zb, albedo, SUPERSAMPLE, rel)
        del albedo
        rgb = gta6_grade(rgb, idb >= 0, GTA6_NOTEX_DARK if notex else 1.0)
        rgb = gta6_sheen(rgb, idb, nb, SUPERSAMPLE)
        res = stylize(zb, idb, nb, SUPERSAMPLE, unit, rel, fill, transparent, out_w, out_h, rgb, TOON_OUTLINE, TOON_LINE, TOON_MIN_LEN, TOON_ANG, TOON_DEPTH, None, None, None, GTA6_HL, GTA6_GLOW)
    elif style == "gta":
        zb, idb, nb, uvb = rasterize(parts, axes, flip, scale, pad)
        rgb = gta_shade(idb, nb, SUPERSAMPLE)
        res = stylize(zb, idb, nb, SUPERSAMPLE, unit, rel, fill, transparent, out_w, out_h, rgb, GTA_OUTLINE, GTA_LINE, GTA_MIN_LEN, GTA_ANG, GTA_DEPTH, None, None, None, GTA_HL)
    elif style == "sleek":
        zb, idb, nb, uvb = rasterize(parts, axes, flip, scale, pad)
        rgb = sleek_shade(idb, nb, SUPERSAMPLE)
        res = stylize(zb, idb, nb, SUPERSAMPLE, unit, rel, fill, transparent, out_w, out_h, rgb, SLEEK_OUTLINE, SLEEK_LINE, SLEEK_MIN_LEN, SLEEK_ANG, SLEEK_DEPTH, SLEEK_INK, SLEEK_INK_LINE, None, None, None, (SLEEK_HALO_COLOR, SLEEK_HALO))
    elif style == "pixel":
        wanted = set(m[0] for p in parts for m in p["mats"] if m[0])
        tex = find_textures(path, wanted)
        if not tex:
            note = "tanpa .txd, warna dasar netral"
        zb, idb, nb, uvb = rasterize(parts, axes, flip, scale, pad, True)
        albedo = shade_albedo(parts, idb, uvb, tex)
        del uvb, tex
        art, pp = pixel_art(idb, nb, zb, albedo, SUPERSAMPLE, unit, rel)
        del albedo, zb, idb, nb
        big = np.repeat(np.repeat(art, pp, 0), pp, 1)
        ah, aw = big.shape[:2]
        res = np.zeros((out_h, out_w, 4), np.float32)
        oy, ox = (out_h - ah) // 2, (out_w - aw) // 2
        sy0, sx0 = max(0, -oy), max(0, -ox)
        dy0, dx0 = max(0, oy), max(0, ox)
        hh, ww = min(ah - sy0, out_h - dy0), min(aw - sx0, out_w - dx0)
        res[dy0:dy0 + hh, dx0:dx0 + ww] = big[sy0:sy0 + hh, sx0:sx0 + ww]
        del big
        if transparent:
            res = res.astype(np.uint8)
        else:
            a3 = res[..., 3:] / 255.0
            res = np.clip(res[..., :3] * a3 + 255 * (1 - a3), 0, 255).astype(np.uint8)
    elif style == "re":
        parts = split_parts(parts)
        zb, idb, nb, uvb = rasterize(parts, axes, flip, scale, pad)
        rgb = re_shade(idb, nb, SUPERSAMPLE, parts, re_swap)
        res = stylize(zb, idb, nb, SUPERSAMPLE, unit, rel, fill, transparent, out_w, out_h, rgb, RE_OUTLINE, RE_LINE, RE_MIN_LEN, RE_ANG, RE_DEPTH, RE_INK, RE_INK_LINE, None, None, None, (RE_HALO_COLOR, RE_HALO) if RE_HALO else None, RE_BOX)
    elif style == "vice":
        zb, idb, nb, uvb = rasterize(parts, axes, flip, scale, pad)
        rgb = vice_shade(idb, nb, zb, SUPERSAMPLE, rel)
        drop = (VICE_SHADOW_DX * unit, VICE_SHADOW_DY * unit, VICE_SHADOW_ALPHA, VICE_SHADOW_BLUR * unit)
        res = stylize(zb, idb, nb, SUPERSAMPLE, unit, rel, fill, transparent, out_w, out_h, rgb, VICE_OUTLINE, VICE_LINE, VICE_MIN_LEN, VICE_ANG, VICE_DEPTH, VICE_INK, VICE_INK_LINE, drop)
    elif style == "bayangan":
        zb, idb, nb, uvb = rasterize(parts, axes, flip, scale, pad)
        rgb = shadow_shade(idb, nb, zb, SUPERSAMPLE, rel, scale)
        res = stylize(zb, idb, nb, SUPERSAMPLE, unit, rel, fill, transparent, out_w, out_h, rgb)
    else:
        zb, idb, nb, uvb = rasterize(parts, axes, flip, scale, pad)
        res = stylize(zb, idb, nb, SUPERSAMPLE, unit, rel, fill, transparent, out_w, out_h)
    global LAST_RES
    LAST_RES = res
    PROG.set("menyimpan")
    write_png(out, res)
    return note


def main():
    ap = argparse.ArgumentParser(description="Ubah model senjata DFF menjadi ikon bergaya HUD (abu-abu atau kartun berwarna dari TXD)")
    ap.add_argument("input", help="file .dff atau folder induk (subfolder ikut ditelusuri)")
    ap.add_argument("output", help="folder tujuan PNG")
    ap.add_argument("--width", type=int, default=1024, help="lebar ikon (default 1024, tinggi mengikuti rasio 512x265)")
    ap.add_argument("--axes", default="", help="sumbu mendatar, atas, kedalaman, contoh xzy (default otomatis)")
    ap.add_argument("--flip", action="store_true", help="lihat dari sisi sebaliknya")
    ap.add_argument("--keep-all", action="store_true", help="jangan buang bagian bernama muzzle/flash/lod")
    ap.add_argument("--fill", type=int, default=208, help="abu isian 0-255 (default 208)")
    ap.add_argument("--white", action="store_true", help="latar putih, bukan transparan")
    ap.add_argument("--rotate", type=float, default=0.0, help="putar manual (derajat, positif = berlawanan arah jarum jam)")
    ap.add_argument("--straighten", action="store_true", help="luruskan otomatis senjata panjang yang miring (default mati)")
    ap.add_argument("--no-straighten", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--style", choices=["abu", "kartun", "bayangan", "vice", "gta", "gta6", "sleek", "re", "pixel"], default="abu", help="abu = hitam-abu polos (default), kartun = berwarna dari file .txd di folder yang sama, bayangan = putih dengan bayangan abu realistis, vice = gradasi pink-biru laut ala Vice City dengan bayangan hitam di bawahnya, gta = abu-abu detail ala GTA IV/V dengan highlight putih, gta6 = seperti kartun dengan highlight pink dan biru ala GTA VI, sleek = putih-abu detail dengan outline putih dan cahaya putih tipis ala HUD senjata modern, pixel = seni piksel berwarna dari file .txd (outline hitam, warna bertingkat), re = ala Resident Evil: campuran abu terang (logam) dan abu gelap arang (polimer) dengan garis tipis terang")
    ap.add_argument("--keep-stock", action="store_true", help="jangan buang bagian popor/tali yang menutupi (mis. micro_uzi)")
    ap.add_argument("--re-swap", action="store_true", help="khusus --style re: balik pembagian abu terang dan gelap")
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--no-anim", action="store_true", help="matikan animasi progres di terminal")
    ap.add_argument("--preview", action="store_true", help="tampilkan pratinjau berwarna di terminal setelah tiap ikon jadi")
    ap.add_argument("--mirror", action="store_true", help="pertahankan struktur subfolder di folder tujuan")
    a = ap.parse_args()
    if os.path.isdir(a.input):
        files = []
        out_abs = os.path.abspath(a.output)
        for root, dirs, fs in os.walk(a.input):
            dirs.sort()
            if os.path.abspath(root).startswith(out_abs):
                continue
            for f in sorted(fs):
                if f.lower().endswith(".dff"):
                    files.append(os.path.join(root, f))
        base = a.input
    else:
        files = [a.input]
        base = os.path.dirname(os.path.abspath(a.input))
    if not files:
        print("tidak ada file .dff")
        return 1
    os.makedirs(a.output, exist_ok=True)
    outs = {}
    used = set()
    for f in files:
        name = os.path.splitext(os.path.basename(f))[0]
        if a.mirror:
            rel = os.path.relpath(os.path.dirname(os.path.abspath(f)), os.path.abspath(base))
            folder = a.output if rel == "." else os.path.join(a.output, rel)
            cand = os.path.join(folder, name + ".png")
        else:
            cand = os.path.join(a.output, name + ".png")
            if cand.lower() in used:
                parent = os.path.basename(os.path.dirname(os.path.abspath(f)))
                cand = os.path.join(a.output, parent + "_" + name + ".png")
            n = 2
            while cand.lower() in used:
                cand = os.path.join(a.output, f"{parent}_{name}_{n}.png")
                n += 1
        used.add(cand.lower())
        outs[f] = cand
    PROG.on = sys.stdout.isatty() and not a.no_anim
    ok, bad = 0, []
    for i, f in enumerate(files, 1):
        out = outs[f]
        name = os.path.relpath(f, base)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if a.skip_existing and os.path.exists(out):
            print(f"[{i}/{len(files)}] {name} dilewati")
            continue
        t0 = time.time()
        PROG.start(name, i, len(files))
        try:
            note = make_icon(f, out, a.width, a.axes, a.flip, a.keep_all, a.fill, not a.white, a.rotate, a.straighten and not a.no_straighten, a.style, a.keep_stock, a.re_swap)
            PROG.finish()
            ok += 1
            print(f"[{i}/{len(files)}] {name} selesai {time.time() - t0:.1f}s {note}")
            if a.preview and LAST_RES is not None:
                print(ansi_preview(LAST_RES, max(20, min(56, shutil.get_terminal_size((60, 20)).columns - 1))))
        except Exception as e:
            PROG.finish()
            bad.append((name, str(e)))
            print(f"[{i}/{len(files)}] {name} GAGAL: {e}")
            if os.environ.get("DFF2ICON_DEBUG"):
                traceback.print_exc()
    print(f"selesai: {ok} berhasil, {len(bad)} gagal")
    for n, e in bad:
        print(f"  {n}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
