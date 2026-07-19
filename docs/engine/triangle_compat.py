"""
Pure-Python stand-in for Shewchuk's ``triangle`` package.

Provides the subset of ``triangle.triangulate`` used by structuralcodes
(fiber integrator + geometry sampling) so Pyodide can run the fiber path
without a native wheel.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
from scipy.spatial import Delaunay
from shapely.geometry import Point, Polygon

__hp_compat__ = True


def _parse_max_area(opts: str) -> float | None:
    """Extract max triangle area from triangle-style option string (``a…``)."""
    if not opts or "a" not in opts:
        return None
    # Prefer the numeric form after 'A' quality flag: …Aa{max_area}…
    m = re.search(r"Aa([0-9.eE+-]+)", opts)
    if m:
        return float(m.group(1))
    m = re.search(r"(?<![A-Za-z])a([0-9.eE+-]+)", opts)
    if m:
        return float(m.group(1))
    return None


def _rings_from_pslg(
    vertices: np.ndarray, segments: np.ndarray
) -> list[np.ndarray]:
    """Recover closed rings from a Planar Straight Line Graph."""
    verts = np.asarray(vertices, dtype=float)
    segs = np.asarray(segments, dtype=int)
    adj: dict[int, list[int]] = {}
    for i, j in segs:
        adj.setdefault(int(i), []).append(int(j))
        adj.setdefault(int(j), []).append(int(i))

    unused = {frozenset((int(i), int(j))) for i, j in segs}
    rings: list[np.ndarray] = []

    while unused:
        a, b = next(iter(unused))
        unused.remove(frozenset((a, b)))
        ring = [a, b]
        prev, cur = a, b
        guard = 0
        while cur != ring[0]:
            nxts = [n for n in adj.get(cur, []) if n != prev]
            if not nxts:
                break
            # Prefer unused edge; if several, take first
            chosen = None
            for n in nxts:
                key = frozenset((cur, n))
                if key in unused:
                    chosen = n
                    break
            if chosen is None:
                chosen = nxts[0]
            key = frozenset((cur, chosen))
            if key in unused:
                unused.remove(key)
            prev, cur = cur, chosen
            ring.append(cur)
            guard += 1
            if guard > len(segs) + 5:
                break
        if len(ring) >= 3:
            rings.append(verts[np.array(ring, dtype=int)])
    return rings


def _polygon_from_tri(tri: dict[str, Any]) -> Polygon:
    verts = np.asarray(tri["vertices"], dtype=float)
    segs = np.asarray(tri["segments"], dtype=int)
    rings = _rings_from_pslg(verts, segs)
    if not rings:
        raise ValueError("triangle_compat: no closed rings in PSLG")

    holes_pts = tri.get("holes")
    if holes_pts is not None and len(holes_pts) > 0:
        holes_pts = np.asarray(holes_pts, dtype=float)
        exterior = max(rings, key=lambda r: float(Polygon(r).area))
        hole_rings: list[np.ndarray] = []
        for ring in rings:
            if np.allclose(ring, exterior):
                continue
            # Match holes list if present; otherwise treat non-exterior as hole
            poly = Polygon(ring)
            if any(poly.contains(Point(h[0], h[1])) for h in holes_pts):
                hole_rings.append(ring)
            elif poly.area < Polygon(exterior).area:
                hole_rings.append(ring)
        return Polygon(exterior, holes=hole_rings)

    # No explicit holes: largest ring is exterior, others are holes
    rings_sorted = sorted(rings, key=lambda r: float(Polygon(r).area), reverse=True)
    exterior = rings_sorted[0]
    hole_rings = rings_sorted[1:]
    return Polygon(exterior, holes=hole_rings)


def _seed_points(poly: Polygon, max_area: float | None) -> np.ndarray:
    """Steiner points inside the polygon for mesh density control."""
    minx, miny, maxx, maxy = poly.bounds
    area = float(poly.area)
    if area <= 0:
        return np.zeros((0, 2))

    target = max_area if max_area and max_area > 0 else area / 40.0
    # ~2 points per target triangle area on a square grid
    spacing = max(np.sqrt(2.0 * target), 1e-9)
    xs = np.arange(minx + 0.5 * spacing, maxx, spacing)
    ys = np.arange(miny + 0.5 * spacing, maxy, spacing)
    if xs.size == 0:
        xs = np.array([(minx + maxx) * 0.5])
    if ys.size == 0:
        ys = np.array([(miny + maxy) * 0.5])
    xx, yy = np.meshgrid(xs, ys)
    candidates = np.column_stack([xx.ravel(), yy.ravel()])
    keep = [poly.contains(Point(p[0], p[1])) for p in candidates]
    return candidates[np.asarray(keep, dtype=bool)]


def _triangle_area(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    return 0.5 * abs(
        a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1])
    )


def _delaunay_inside(
    boundary: np.ndarray, steiner: np.ndarray, poly: Polygon
) -> tuple[np.ndarray, np.ndarray]:
    pts = boundary if steiner.size == 0 else np.vstack([boundary, steiner])
    # Deduplicate nearly coincident points
    pts = np.unique(np.round(pts, decimals=10), axis=0)
    if pts.shape[0] < 3:
        raise ValueError("triangle_compat: fewer than 3 unique points")

    delaunay = Delaunay(pts)
    tris: list[list[int]] = []
    for sim in delaunay.simplices:
        a, b, c = pts[sim[0]], pts[sim[1]], pts[sim[2]]
        cx = (a[0] + b[0] + c[0]) / 3.0
        cy = (a[1] + b[1] + c[1]) / 3.0
        if poly.contains(Point(cx, cy)) or poly.covers(Point(cx, cy)):
            tris.append([int(sim[0]), int(sim[1]), int(sim[2])])
    if not tris:
        # Fallback: keep all simplices (convex cases)
        tris = [[int(s[0]), int(s[1]), int(s[2])] for s in delaunay.simplices]
    return pts, np.asarray(tris, dtype=int)


def _refine_max_area(
    pts: np.ndarray, tris: np.ndarray, poly: Polygon, max_area: float
) -> tuple[np.ndarray, np.ndarray]:
    """Longest-edge bisection until all triangle areas <= max_area."""
    points = pts.tolist()
    triangles = [tuple(int(i) for i in t) for t in tris]
    # Cap refinements so a bad max_area cannot hang the browser
    max_iters = 50_000
    it = 0
    while it < max_iters:
        it += 1
        oversized = None
        for t in triangles:
            a = np.asarray(points[t[0]])
            b = np.asarray(points[t[1]])
            c = np.asarray(points[t[2]])
            if _triangle_area(a, b, c) > max_area * 1.001:
                oversized = (t, a, b, c)
                break
        if oversized is None:
            break
        t, a, b, c = oversized
        edges = [
            (0, 1, float(np.linalg.norm(a - b))),
            (1, 2, float(np.linalg.norm(b - c))),
            (2, 0, float(np.linalg.norm(c - a))),
        ]
        e0, e1, _ = max(edges, key=lambda e: e[2])
        i0, i1 = t[e0], t[e1]
        mid = (
            0.5 * (points[i0][0] + points[i1][0]),
            0.5 * (points[i0][1] + points[i1][1]),
        )
        mid_idx = len(points)
        points.append(mid)
        # Replace every triangle that shares the split edge with two children.
        new_tris: list[tuple[int, int, int]] = []
        edge = frozenset((i0, i1))
        for u, v, w in triangles:
            shared = None
            if frozenset((u, v)) == edge:
                shared = (u, v, w)
            elif frozenset((v, w)) == edge:
                shared = (v, w, u)
            elif frozenset((w, u)) == edge:
                shared = (w, u, v)
            if shared is None:
                new_tris.append((u, v, w))
            else:
                p, q, r = shared
                new_tris.append((p, mid_idx, r))
                new_tris.append((mid_idx, q, r))
        triangles = new_tris

    pts_out = np.asarray(points, dtype=float)
    # Drop triangles whose centroid left the domain after splits on boundary
    kept: list[list[int]] = []
    for t in triangles:
        a, b, c = pts_out[t[0]], pts_out[t[1]], pts_out[t[2]]
        cx = (a[0] + b[0] + c[0]) / 3.0
        cy = (a[1] + b[1] + c[1]) / 3.0
        if poly.contains(Point(cx, cy)) or poly.covers(Point(cx, cy)):
            if _triangle_area(a, b, c) > 1e-18:
                kept.append([t[0], t[1], t[2]])
    return pts_out, np.asarray(kept, dtype=int)


def triangulate(tri: dict[str, Any], opts: str = "") -> dict[str, np.ndarray]:
    """
    Mimic ``triangle.triangulate`` for PSLG inputs used by structuralcodes.

    Supported opts (partial): ``p``, ``q…``, ``A``, ``a{max_area}``, ``o1``.
    Quality angle constraints are ignored; area bound is honored approximately.
    """
    poly = _polygon_from_tri(tri)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty or float(poly.area) <= 0:
        raise ValueError("triangle_compat: empty polygon")

    max_area = _parse_max_area(opts or "")
    boundary = np.asarray(tri["vertices"], dtype=float)
    # Also include ring coordinates from reconstructed polygon (ordered)
    ext = np.asarray(poly.exterior.coords[:-1], dtype=float)
    hole_pts = []
    for interior in poly.interiors:
        hole_pts.append(np.asarray(interior.coords[:-1], dtype=float))
    parts = [boundary, ext, *hole_pts]
    boundary_all = np.vstack(parts)

    steiner = _seed_points(poly, max_area)
    pts, tris = _delaunay_inside(boundary_all, steiner, poly)
    if max_area is not None and max_area > 0 and len(tris):
        pts, tris = _refine_max_area(pts, tris, poly, max_area)

    return {"vertices": pts, "triangles": tris}
