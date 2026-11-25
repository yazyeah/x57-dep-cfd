#!/usr/bin/env python3
"""
X-57 DEP Aircraft Geometry Auditor & Level Metric STL Exporter for the coursework workspace.

Reads original coursework files READ-ONLY:
  - <coursework>\\CW1-X-57.glb
  - <coursework>\\CW1--X-57_metool.stl

Writes outputs strictly inside:
  - <workspace>\\01_geometry\\
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

COURSEWORK_ROOT = Path(__file__).resolve().parents[2]
INPUT_GLB = COURSEWORK_ROOT / "CW1-X-57.glb"
INPUT_STL = COURSEWORK_ROOT / "CW1--X-57_metool.stl"
OUT_DIR = Path(__file__).resolve().parents[1] / "01_geometry"
IN2M = 0.0254


def quat_to_matrix(q: List[float]) -> np.ndarray:
    qx, qy, qz, qw = q
    return np.array([
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw),     2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw),     1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw),     2 * (qy * qz + qx * qw),     1 - 2 * (qx * qx + qy * qy)],
    ], dtype=np.float64)


def write_binary_stl(path: Path, tris: np.ndarray, header_text: str) -> None:
    v0 = tris[:, 0, :]
    v1 = tris[:, 1, :]
    v2 = tris[:, 2, :]
    n = np.cross(v1 - v0, v2 - v0)
    norms = np.linalg.norm(n, axis=1, keepdims=True)
    norms = np.where(norms > 1e-12, norms, 1.0)
    n = (n / norms).astype(np.float32)

    dt = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
    out = np.empty(len(tris), dtype=dt)
    out["n"] = n
    out["v"] = tris.astype(np.float32)
    out["attr"] = 0

    hdr = header_text.encode("ascii", errors="ignore")[:80].ljust(80, b"\x00")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(hdr)
        f.write(struct.pack("<I", len(tris)))
        f.write(out.tobytes())


def detect_propellers(cent: np.ndarray, verts: np.ndarray) -> List[Dict[str, Any]]:
    bands = [
        ("HLP-1", 0.68, 1.20, 5400, 5),
        ("HLP-2", 1.25, 1.78, 5400, 5),
        ("HLP-3", 1.82, 2.35, 5400, 5),
        ("HLP-4", 2.40, 2.94, 5400, 5),
        ("HLP-5", 2.98, 3.52, 5400, 5),
        ("HLP-6", 3.55, 4.10, 5400, 5),
        ("WT-1",  4.20, 5.55, 2700, 3),
    ]
    props: List[Dict[str, Any]] = []
    for name, z0, z1, rpm, n_blades in bands:
        if name.startswith("HLP"):
            m = (cent[:, 2] >= z0) & (cent[:, 2] <= z1) & (cent[:, 0] < -0.55) & (cent[:, 1] > -0.35) & (cent[:, 1] < 0.35)
            sub_v = verts[m].reshape(-1, 3)
            x_min = float(sub_v[:, 0].min())
            nose_m = sub_v[:, 0] < (x_min + 0.04)
            y_axis = float(np.median(sub_v[nose_m, 1]))
            z_axis = float(np.median(sub_v[nose_m, 2]))
            r_yz = np.hypot(sub_v[:, 1] - y_axis, sub_v[:, 2] - z_axis)
            r_tip = float(np.percentile(r_yz, 99.9))
            tip_m = r_yz > (0.85 * r_tip)
            x_disk = float(np.median(sub_v[tip_m, 0]))
            hub_m = (np.abs(sub_v[:, 0] - x_disk) < 0.03) & (r_yz < 0.12)
            r_hub = float(np.percentile(r_yz[hub_m], 85)) if hub_m.any() else 0.06
        else:
            m = (cent[:, 2] >= z0) & (cent[:, 2] <= z1) & (cent[:, 0] < -0.55) & (cent[:, 1] > -0.75) & (cent[:, 1] < 0.75)
            sub_v = verts[m].reshape(-1, 3)
            x_min = float(sub_v[:, 0].min())
            nose_m = sub_v[:, 0] < (x_min + 0.05)
            y_axis = float(np.median(sub_v[nose_m, 1]))
            z_axis = float(np.median(sub_v[nose_m, 2]))
            r_yz = np.hypot(sub_v[:, 1] - y_axis, sub_v[:, 2] - z_axis)
            r_tip = float(np.percentile(r_yz, 99.9))
            tip_m = r_yz > (0.85 * r_tip)
            x_disk = float(np.median(sub_v[tip_m, 0]))
            hub_m = (np.abs(sub_v[:, 0] - x_disk) < 0.05) & (r_yz < 0.22)
            r_hub = float(np.percentile(r_yz[hub_m], 85)) if hub_m.any() else 0.13

        props.append({
            "name": name,
            "nominal_rpm": rpm,
            "blade_count": n_blades,
            "x_disk_m": round(x_disk, 5),
            "y_axis_m": round(y_axis, 5),
            "z_axis_m": round(z_axis, 5),
            "r_tip_m": round(r_tip, 5),
            "r_hub_est_m": round(r_hub, 5),
            "diameter_m": round(2.0 * r_tip, 5),
            "swept_annulus_area_m2": round(float(np.pi * (r_tip ** 2 - r_hub ** 2)), 5),
            "spinner_nose_x_m": round(x_min, 5),
        })
    return props


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect X-57 GLB/STL and export restored level metric STL")
    parser.add_argument("--export-level-stl", action="store_true")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(INPUT_GLB, "rb") as f:
        f.seek(12)
        c0_len, _ = struct.unpack("<I4s", f.read(8))
        gltf = json.loads(f.read(c0_len).decode("utf-8"))

    q = gltf["nodes"][0].get("rotation", [0.0, 0.0, 0.0, 1.0])
    R = quat_to_matrix(q)

    with open(INPUT_STL, "rb") as f:
        f.seek(80)
        ntri = struct.unpack("<I", f.read(4))[0]
        raw = f.read()
    dt = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
    data = np.frombuffer(raw, dtype=dt)
    tris_raw_in = data["v"].astype(np.float64)

    tris_level_in = np.einsum("ijk,kl->ijl", tris_raw_in, R)
    tris_level_m = tris_level_in * IN2M
    verts_m = tris_level_m.reshape(-1, 3)
    cent_m = tris_level_m.mean(axis=1)

    if args.export_level_stl:
        full_stl = OUT_DIR / "x57_full_level_meters.stl"
        write_binary_stl(full_stl, tris_level_m, "X-57 Maxwell Full Aircraft Level Metric (m)")
        print(f"[GeometryAudit] Exported full metric STL: {full_stl} ({len(tris_level_m):,} tris)")

        half_mask = tris_level_m[:, :, 2].max(axis=1) >= -0.002
        half_tris = tris_level_m[half_mask].copy()
        half_tris[:, :, 2] = np.maximum(half_tris[:, :, 2], 0.0)
        half_stl = OUT_DIR / "x57_half_starboard_raw_meters.stl"
        write_binary_stl(half_stl, half_tris, "X-57 Maxwell Starboard Half (z>=0) Level Metric (m)")
        print(f"[GeometryAudit] Exported starboard half metric STL: {half_stl} ({len(half_tris):,} tris)")
    else:
        props = detect_propellers(cent_m, tris_level_m)
        print(f"[GeometryAudit] Verified {ntri:,} tris, symmetry mismatch={abs(verts_m[:,2].max()+verts_m[:,2].min()):.6f} m, props={len(props)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
