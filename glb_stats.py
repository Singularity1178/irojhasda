"""Dump per-file technical stats for every .glb under this folder.

Standalone (numpy is the only dependency). Reads the glTF JSON chunk and walks
accessors/bufferViews without decoding images, so it is fast even on 10 MB files.

    python glb_stats.py            # table of every .glb in . and model/
    python glb_stats.py --md       # markdown table (pasteable)
    python glb_stats.py Ako.glb    # specific files
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

COMP = {5120: "i8", 5121: "u8", 5122: "i16", 5123: "u16", 5125: "u32", 5126: "f32"}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}


def read_glb(path: Path):
    """Return (json_dict, bin_chunk_size)."""
    data = path.read_bytes()
    magic, ver, _total = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF":
        raise ValueError(f"{path.name}: not a binary glTF (.glb)")
    off, js, bin_len = 12, None, 0
    while off + 8 <= len(data):
        clen, ctype = struct.unpack_from("<II", data, off)
        off += 8
        chunk = data[off:off + clen]
        off += clen
        if ctype == 0x4E4F534A:
            js = json.loads(chunk.decode("utf-8"))
        elif ctype == 0x004E4942:
            bin_len += clen
    if js is None:
        raise ValueError(f"{path.name}: no JSON chunk")
    return js, {"version": ver, "json": len(json.dumps(js)), "bin": bin_len, "file": len(data)}


def image_bytes_size(j, img):
    """Size in bytes of an image, following bufferView or data: uri."""
    if "bufferView" in img:
        bv = j["bufferViews"][img["bufferView"]]
        return bv.get("byteLength", 0)
    uri = img.get("uri", "")
    if uri.startswith("data:"):
        head, _, b64 = uri.partition(",")
        return int(head.split(";base64")[-1].split("=")[-1] or 0) or len(b64) * 3 // 4
    return 0


def local_mat(node):
    """glTF stores matrices column-major: element[col * 4 + row]."""
    m = node.get("matrix")
    if m:
        return m
    t = node.get("translation", [0, 0, 0])
    r = node.get("rotation", [0, 0, 0, 1])
    sx, sy, sz = node.get("scale", [1, 1, 1])
    x, y, z, w = r
    # rotation, row-major
    r0, r1, r2 = 1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)
    r3, r4, r5 = 2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)
    r6, r7, r8 = 2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)
    # T * R * S, then translation into the 4th column
    return [
        r0 * sx, r1 * sy, r2 * sz, t[0],
        r3 * sx, r4 * sy, r5 * sz, t[1],
        r6 * sx, r7 * sy, r8 * sz, t[2],
        0.0, 0.0, 0.0, 1.0,
    ]


def mul(a, b):
    """4x4 column-major multiply a @ b."""
    out = [0.0] * 16
    for c in range(4):
        for r in range(4):
            out[c * 4 + r] = sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4))
    return out


def stats(path: Path) -> dict:
    j, chunks = read_glb(path)
    nodes = j.get("nodes", [])
    meshes = j.get("meshes", [])
    skins = j.get("skins", [])
    anims = j.get("animations", [])
    mats = j.get("materials", [])
    texs = j.get("textures", [])
    imgs = j.get("images", [])
    accessors = j.get("accessors", [])
    skinset = {s.get("mesh") for s in skins}
    joints = sum(len(s.get("joints", [])) for s in skins)

    prims = tris = verts = 0
    morph_targets = 0
    for m in meshes:
        for p in m.get("primitives", []):
            prims += 1
            morph_targets = max(morph_targets, len(p.get("targets", [])))
            pos = accessors[p["attributes"]["POSITION"]]["count"] if "POSITION" in p["attributes"] else 0
            verts += pos
            mode = p.get("mode", 4)
            if mode == 4:
                idx = p.get("indices")
                tris += accessors[idx]["count"] // 3 if idx is not None else pos // 3
            elif mode in (5, 6):
                tris += max(pos - 2, 0)

    anim_names = []
    dur = 0.0
    for a in anims:
        anim_names.append(a.get("name") or "(unnamed)")
        for ch in a.get("channels", []):
            smp = a["samplers"][ch["sampler"]]
            inp = accessors[smp["input"]]
            lo, hi = inp.get("min"), inp.get("max")
            if lo is not None and hi is not None:
                dur = max(dur, hi[0] - lo[0])
    rate = max((a.get("extras", {}) or {}).get("gltf_animation_extension_runtime_sampler_rate", 1.0)
               for a in anims) if anims else 1.0

    # world-space bounds: accessor min/max is the mesh's local bind-pose AABB, so
    # multiplying by the owning node's world transform gives a usable figure even
    # for skinned meshes (which have no static world bounds of their own).
    scene = j.get("scene", 0)
    roots = (j.get("scenes") or [{}])[scene].get("nodes", list(range(len(nodes))))
    world = {}
    stack = list(roots)
    while stack:
        n_idx = stack.pop()
        n = nodes[n_idx]
        world[n_idx] = mul(local_mat(n), world[n_idx]) if n_idx in world else local_mat(n)
        stack.extend(n.get("children", []))

    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for n_idx, n in nodes and enumerate(nodes):
        if "mesh" not in n:
            continue
        mtx = world.get(n_idx)
        if mtx is None:
            continue
        for p in meshes[n["mesh"]].get("primitives", []):
            acc = accessors[p["attributes"]["POSITION"]] if "POSITION" in p["attributes"] else None
            if not acc or "min" not in acc or "max" not in acc:
                continue
            amin, amax = acc["min"], acc["max"]
            for x in (amin[0], amax[0]):
                for y in (amin[1], amax[1]):
                    for z in (amin[2], amax[2]):
                        c = (x, y, z, 1.0)
                        wx = sum(mtx[k * 4 + 0] * c[k] for k in range(4))
                        wy = sum(mtx[k * 4 + 1] * c[k] for k in range(4))
                        wz = sum(mtx[k * 4 + 2] * c[k] for k in range(4))
                        for i, v in enumerate((wx, wy, wz)):
                            lo[i] = min(lo[i], v)
                            hi[i] = max(hi[i], v)
    if lo[0] == float("inf"):
        lo, hi = [0.0] * 3, [0.0] * 3

    # Body-only Y extent (the skinned "*_Body" mesh). More honest than the
    # whole-file bounds, which include detached props (Iroha's tank is 3.99u).
    body = ""
    body_y = hi[1] - lo[1]
    for n in nodes:
        if "mesh" not in n or not (n.get("name") or "").endswith("_Body"):
            continue
        ys = [accessors[pr["attributes"]["POSITION"]]["max"][1]
              - accessors[pr["attributes"]["POSITION"]]["min"][1]
              for pr in meshes[n["mesh"]].get("primitives", [])
              if "POSITION" in pr["attributes"]]
        if ys:
            body, body_y = n["name"], max(ys)

    img_bytes = sum(image_bytes_size(j, im) for im in imgs)
    uv = sum(1 for im in imgs if "EXT_texture_webp" in j.get("extensionsUsed", [])
             or (im.get("mimeType", "").endswith("webp")))
    ext = ", ".join(j.get("extensionsUsed", []) or []) or "-"
    needs = ", ".join(j.get("extensionsRequired", []) or []) or "-"
    ex = j.get("extras", {}) or {}
    vrm = ex.get("vrm") or (j.get("asset", {}).get("copyright", "") or "")

    return {
        "name": path.stem,
        "path": str(path.relative_to(HERE)),
        "file_mb": chunks["file"] / 1e6,
        "mesh_mb": chunks["bin"] / 1e6,
        "tex_mb": img_bytes / 1e6,
        "generator": (j.get("asset", {}).get("generator") or "-")[:34],
        "meshes": len(meshes),
        "prims": prims,
        "tris": tris,
        "verts": verts,
        "nodes": len(nodes),
        "skinned": len(skinset),
        "joints": joints,
        "morph": morph_targets,
        "anims": len(anims),
        "anim_s": round(dur / rate, 2) if anims else 0.0,
        "anim_names": anim_names,
        "mats": len(mats),
        "tex": len(texs),
        "imgs": len(imgs),
        "webp": uv,
        "height": hi[1] - lo[1],
        "body_y": body_y,
        "body": body,
        "w": hi[0] - lo[0],
        "d": hi[2] - lo[2],
        "ymin": lo[1],
        "ext": ext,
        "req": needs,
        "vrm": vrm,
    }


COLS = [
    ("name", "Model"), ("file_mb", "MB"), ("mesh_mb", "Geom MB"), ("tex_mb", "Tex MB"),
    ("meshes", "Meshes"), ("prims", "Prims"), ("tris", "Tris"), ("verts", "Verts"),
    ("anims", "Anims"), ("anim_s", "Anim s"), ("joints", "Joints"), ("mats", "Mats"),
    ("imgs", "Tex"), ("body_y", "Body Y"),
]


def render(rows, md=False):
    def fmt(v):
        if isinstance(v, float):
            return f"{v:.2f}"
        if isinstance(v, int):
            return f"{v:,}"
        return str(v)

    head = [c[1] for c in COLS]
    body = [[fmt(r[c[0]]) for c in COLS] for r in rows]
    widths = [max(len(head[i]), *(len(r[i]) for r in body)) for i in range(len(head))]
    out = []
    if md:
        out.append("| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(head)) + " |")
        out.append("|" + "|".join("-" * (w + 2) for w in widths) + "|")
        for r in body:
            out.append("| " + " | ".join(r[i].ljust(widths[i]) for i in range(len(head))) + " |")
    else:
        out.append("  ".join(h.ljust(widths[i]) for i, h in enumerate(head)))
        out.append("  ".join("-" * widths[i] for i in range(len(head))))
        for r in body:
            out.append("  ".join(r[i].ljust(widths[i]) for i in range(len(head))))
    return "\n".join(out)


def find_glbs(paths):
    if paths:
        out = []
        for p in paths:
            p = Path(p)
            out.extend(sorted(p.glob("*.glb")) if p.is_dir() else [p])
        return out
    found = list(HERE.glob("*.glb")) + list((HERE / "model").glob("*.glb"))
    return sorted(found, key=lambda q: str(q).lower())


def main():
    ap = argparse.ArgumentParser(description="Technical stats for .glb files")
    ap.add_argument("files", nargs="*", help="glb files or folders (default: . and model/)")
    ap.add_argument("--md", action="store_true", help="markdown table output")
    ap.add_argument("--detail", action="store_true", help="per-file extras (ext, anim names, tool)")
    a = ap.parse_args()

    paths = find_glbs(a.files)
    if not paths:
        print("no .glb found", file=sys.stderr)
        return 1

    rows = []
    for p in paths:
        try:
            rows.append(stats(p))
        except Exception as e:  # noqa: BLE001
            print(f"!! {p.name}: {e}", file=sys.stderr)

    print(render(rows, a.md))
    if a.detail:
        print()
        for r in rows:
            print(f"{r['name']}  [{r['path']}]")
            print(f"  generator : {r['generator']}")
            print(f"  extensions: {r['ext']}")
            print(f"  required  : {r['req']}")
            print(f"  bounds    : W {r['w']:.2f} x D {r['d']:.2f} x H {r['height']:.2f} "
                  f"(feet y={r['ymin']:.2f})")
            print(f"  body mesh : {r['body'] or '-'}  Y extent {r['body_y']:.3f}")
            print(f"  skinned   : {r['skinned']} meshes / {r['joints']} joints / "
                  f"{r['morph']} morph targets")
            print(f"  anims     : {r['anims']} ({r['anim_s']}s) {r['anim_names']}")
            print(f"  textures  : {r['imgs']} images ({r['webp']} webp)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())