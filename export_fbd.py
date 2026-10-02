# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Suyono Nt. and DeepSeek contributors.
"""CalculiX CGX .fbd exporter - v0.0.31b.

v0.0.31b:
* Solid group: curve TIDAK dikonversi â€” biarkan garis lurus apa adanya.
* 2D (owner=None): tetap busur (per-face).
* Kubus: OK. Silinder: OK (garis lurus).
"""
from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path

from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QFileDialog, QMessageBox

from tools.base import Tool


_USE_LDV_ON_ARC = True
_VERSION = "0.0.31b"


class ExportFBDTool(Tool):
    name = "Export CalculiX FBD v0.0.31b"
    shortcut = None
    uses_snap = False

    def on_activate(self, viewport) -> None:
        scene = getattr(viewport, "scene", None)
        if scene is None:
            QMessageBox.warning(viewport.window(),
                                "Export CalculiX FBD",
                                "No document is open.")
            return
        suggested = _suggested_name(scene)
        path, _sel = QFileDialog.getSaveFileName(
            viewport.window(), "Export CalculiX FBD", suggested,
            "CalculiX FBD (*.fbd);;All files (*)")
        if not path:
            return
        if not path.lower().endswith(".fbd"):
            path += ".fbd"
        try:
            stats = save_fbd(scene, path)
        except Exception as exc:                       # noqa: BLE001
            QMessageBox.critical(viewport.window(),
                                 "Export CalculiX FBD",
                                 f"Export failed:\n\n{exc}")
            return

        p = Path(path)
        try:
            size_kb = p.stat().st_size / 1024.0
            size_str = f"{size_kb:.2f} KB"
        except Exception:
            size_str = "?"

        header_lines = []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.rstrip("\n")
                    if line.startswith("# Write") or line.startswith("# Parameters"):
                        header_lines.append(line)
        except Exception:
            pass

        msg = (
            f"File   : {p.name}\n"
            f"Folder : {p.parent}\n"
            f"Size   : {size_str}\n"
            f"Versi  : v{_VERSION}\n"
            f"\n"
            + "\n".join(header_lines)
        )
        QMessageBox.information(viewport.window(),
                                "Export CalculiX FBD",
                                msg)

    def on_deactivate(self, viewport) -> None:
        pass


def _suggested_name(scene) -> str:
    p = getattr(scene, "path", None) or getattr(scene, "file_path", None)
    return f"{Path(str(p)).stem}.fbd" if p else "model.fbd"


_MIN_FIT_POINTS = 3
_KEY_SCALE = 1.0 / 0.00025


def _iter_meshes_with_owner(scene):
    from core.group import world_mesh
    if hasattr(scene, "loose_mesh"):
        yield scene.loose_mesh, None
    elif hasattr(scene, "mesh"):
        yield scene.mesh, None
    for g in getattr(scene, "groups", []):
        if not scene.entity_visible(g):
            continue
        if getattr(g, "billboard", False):
            continue
        try:
            yield world_mesh(g), g.uid
        except Exception:
            continue


def _mm(v: float) -> float:
    return round(v * 1000.0, 6)


class _Registry:
    __slots__ = ("_ids", "_counter", "_list")

    def __init__(self, target_list=None) -> None:
        self._ids = {}
        self._counter = 1
        self._list = target_list

    def id_of(self, key):
        e = self._ids.get(key)
        if e is not None:
            return e
        n = self._counter
        self._ids[key] = n
        self._counter += 1
        return n

    def peek(self, key):
        return self._ids.get(key)

    def ensure(self, key, factory):
        e = self._ids.get(key)
        if e is not None:
            return e
        n = self._counter
        self._ids[key] = n
        self._counter += 1
        if self._list is not None:
            self._list.append(factory())
        return n


def _make_factory_line(a, b, c):
    def factory():
        return (a, b, c)
    return factory


def _sub3(a, b):
    return QVector3D(a.x() - b.x(), a.y() - b.y(), a.z() - b.z())


def _fit_circle_3pts(p1, p2, p3):
    v1 = _sub3(p2, p1)
    v2 = _sub3(p3, p1)
    normal = QVector3D.crossProduct(v1, v2)
    if normal.length() < 1e-9:
        return None
    normal = normal.normalized()
    u = v1.normalized()
    v = QVector3D.crossProduct(normal, u)

    def to_2d(p):
        d = _sub3(p, p1)
        return (QVector3D.dotProduct(d, u),
                QVector3D.dotProduct(d, v))

    ax, ay = to_2d(p1)
    bx, by = to_2d(p2)
    cx, cy = to_2d(p3)
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-15:
        return None
    ux = ((ax*ax + ay*ay) * (by - cy)
          + (bx*bx + by*by) * (cy - ay)
          + (cx*cx + cy*cy) * (ay - by)) / d
    uy = ((ax*ax + ay*ay) * (cx - bx)
          + (bx*bx + by*by) * (ax - cx)
          + (cx*cx + cy*cy) * (bx - ax)) / d
    r2 = (ax - ux)**2 + (ay - uy)**2
    if r2 < 1e-12:
        return None
    radius = math.sqrt(r2)
    center = p1 + u * ux + v * uy
    return center, normal, radius


def _fit_circle_geometric(points):
    n = len(points)
    if n < 3:
        return None
    if n == 3:
        return _fit_circle_3pts(points[0], points[1], points[2])

    xs = [p.x() for p in points]
    ys = [p.y() for p in points]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0

    def ang_idx(i):
        p = points[i]
        return math.atan2(p.y() - cy, p.x() - cx)

    sorted_idx = sorted(range(n), key=ang_idx)
    i1 = sorted_idx[0]
    i2 = sorted_idx[n // 3]
    i3 = sorted_idx[2 * n // 3]

    if i1 == i2 or i2 == i3 or i1 == i3:
        p1 = points[0]
        p2 = points[n // 2]
        line_dir = _sub3(p2, p1)
        line_len = line_dir.length()
        if line_len < 1e-9:
            return None
        line_dir_n = line_dir / line_len
        best_dist = -1.0
        p3 = None
        for p in points:
            d = _sub3(p, p1)
            proj = QVector3D.dotProduct(d, line_dir_n)
            perp = d - line_dir_n * proj
            dist = perp.length()
            if dist > best_dist:
                best_dist = dist
                p3 = p
        if p3 is None or best_dist < 1e-9:
            return None
        return _fit_circle_3pts(p1, p2, p3)

    return _fit_circle_3pts(points[i1], points[i2], points[i3])


def _make_angle_fn(center, normal):
    ref = QVector3D(1.0, 0.0, 0.0)
    if abs(normal.x()) > 0.9:
        ref = QVector3D(0.0, 1.0, 0.0)
    u = (ref - normal * QVector3D.dotProduct(ref, normal)).normalized()
    v = QVector3D.crossProduct(normal, u)

    def angle_of(p):
        d = p - center
        return math.atan2(QVector3D.dotProduct(d, v),
                          QVector3D.dotProduct(d, u))
    return angle_of


def _angle_ccw(p, center):
    d_x = p.x() - center.x()
    d_y = p.y() - center.y()
    a = math.atan2(d_y, d_x)
    if a < 0:
        a += 2 * math.pi
    return a


def _build_curve_adj(mesh):
    adj = defaultdict(list)
    for e in mesh.edges:
        if getattr(e, 'curve', None) is None:
            continue
        adj[id(e.v0)].append(e)
        adj[id(e.v1)].append(e)
    return adj


def _build_radial_adj(mesh):
    adj = defaultdict(list)
    for e in mesh.edges:
        if getattr(e, 'curve', None) is not None:
            continue
        if getattr(e, 'hidden', False):
            continue
        adj[id(e.v0)].append(e)
        adj[id(e.v1)].append(e)
    return adj


def _is_intermediate_v26(v, curve_adj, radial_adj):
    n_curve = len(curve_adj.get(id(v), []))
    n_radial = len(radial_adj.get(id(v), []))
    return n_curve == 2 and n_radial == 0


def _vertex_edge_count(v):
    try:
        e = v.edges
        return len(e) if not callable(e) else len(e())
    except Exception:
        return 0


def _vertex_face_count(v):
    try:
        f = v.faces
        return len(f) if not callable(f) else len(f())
    except Exception:
        return 0


def _is_intermediate_vertex(v) -> bool:
    return _vertex_edge_count(v) == 2 and _vertex_face_count(v) == 1


def _order_curve_vertices(edges, verts):
    adj = defaultdict(list)
    for e in edges:
        adj[id(e.v0)].append((e.v1, e))
        adj[id(e.v1)].append((e.v0, e))

    endpoints = [v for v in verts if len(adj[id(v)]) == 1]
    if len(endpoints) >= 2:
        start_v = endpoints[0]
    else:
        start_v = verts[0]

    ordered = [start_v]
    visited = {id(start_v)}
    current = start_v
    max_iter = len(verts) + 5
    for _ in range(max_iter):
        next_v = None
        for (nb, _e) in adj[id(current)]:
            if id(nb) not in visited:
                next_v = nb
                break
        if next_v is None:
            break
        ordered.append(next_v)
        visited.add(id(next_v))
        current = next_v
    return ordered


# v0.0.31b: _trace_chains dan _process_all_curves TIDAK dipakai
# (kita biarkan curve edge sebagai garis lurus untuk solid group)


def _process_face_curves(face, mesh, point_reg, line_reg, lines,
                         curve_reg, circles, add_point, edge_to_line):
    """Proses busur untuk 1 face (dipakai untuk model 2D)."""
    loop = list(face.loop)
    n = len(loop)
    if n < 3:
        return

    curve_edges = []
    for i in range(n):
        va = loop[i]
        vb = loop[(i + 1) % n]
        e = mesh.find_edge(va, vb)
        if e is not None and getattr(e, 'curve', None) is not None:
            curve_edges.append(e)

    if not curve_edges:
        return

    by_cid = defaultdict(list)
    for e in curve_edges:
        cid = getattr(e, "curve", None)
        by_cid[cid].append(e)

    for cid, edges in by_cid.items():
        cid_pts = []
        seen_cid = set()
        for e in edges:
            for v in (e.v0, e.v1):
                if id(v) not in seen_cid:
                    seen_cid.add(id(v))
                    cid_pts.append(v.position)

        if len(cid_pts) < 3:
            for e in edges:
                pa = add_point(e.v0.position)
                pb = add_point(e.v1.position)
                lid = line_reg.ensure(
                    ("line", id(e)), _make_factory_line(pa, pb, None))
                edge_to_line[id(e)] = lid
            continue

        fit = _fit_circle_geometric(cid_pts)
        if fit is None:
            for e in edges:
                pa = add_point(e.v0.position)
                pb = add_point(e.v1.position)
                lid = line_reg.ensure(
                    ("line", id(e)), _make_factory_line(pa, pb, None))
                edge_to_line[id(e)] = lid
            continue

        center, normal, radius = fit
        cid_pt = add_point(center)

        center_idx = None
        for i, (c, _r) in enumerate(circles, start=1):
            if c == cid_pt:
                center_idx = i
                break
        if center_idx is None:
            circles.append((cid_pt, round(radius * 1000.0, 6)))
            center_idx = len(circles)

        vset = {}
        for e in edges:
            vset[id(e.v0)] = e.v0
            vset[id(e.v1)] = e.v1
        verts_all = list(vset.values())
        if len(verts_all) < 2:
            continue

        verts = _order_curve_vertices(edges, verts_all)
        if len(verts) < 2:
            continue

        adj_local = defaultdict(list)
        for e in edges:
            adj_local[id(e.v0)].append(e)
            adj_local[id(e.v1)].append(e)

        endpoint_count = sum(1 for v in verts
                             if len(adj_local[id(v)]) == 1)
        if endpoint_count >= 2:
            is_closed = False
        elif endpoint_count == 0:
            is_closed = True
        else:
            is_closed = False

        if is_closed:
            n_arcs = 4
        else:
            n_edges = len(edges)
            n_arcs = max(1, int(round(n_edges / 6.0)))

        n_v = len(verts)
        boundaries = []
        for k in range(n_arcs + 1):
            idx = int(round(k * n_v / n_arcs)) % n_v
            boundaries.append(idx)
        if not is_closed:
            boundaries[-1] = n_v - 1

        for k in range(n_arcs):
            i_start = boundaries[k]
            i_end = boundaries[k + 1]
            if i_start >= n_v:
                continue
            if i_end <= i_start:
                i_end = n_v
            v_a = verts[i_start]
            v_b = verts[i_end] if i_end < n_v else verts[0]
            pa = add_point(v_a.position)
            pb = add_point(v_b.position)
            lid = line_reg.ensure(
                ("arc", (id(face), cid, k)),
                _make_factory_line(pa, pb, center_idx))
            for i in range(i_start, i_end):
                if i >= n_v:
                    break
                v1 = verts[i]
                v2 = verts[(i + 1) % n_v]
                e = mesh.find_edge(v1, v2)
                if (e is not None
                        and getattr(e, "curve", None) is not None):
                    edge_to_line[id(e)] = lid


def _process_ring(face, mesh, point_reg, line_reg, lines, curve_reg,
                  circles, add_point, edge_to_line):
    """Proses ring penuh via hole_loops: 4 sektor."""
    outer = list(face.loop)
    holes = list(getattr(face, 'hole_loops', []) or [])
    if not holes:
        return None
    hole = list(holes[0])

    outer_edges = []
    for i in range(len(outer)):
        va = outer[i]
        vb = outer[(i + 1) % len(outer)]
        e = mesh.find_edge(va, vb)
        if e is not None and getattr(e, 'curve', None) is not None:
            outer_edges.append(e)

    hole_edges = []
    for i in range(len(hole)):
        va = hole[i]
        vb = hole[(i + 1) % len(hole)]
        e = mesh.find_edge(va, vb)
        if e is not None and getattr(e, 'curve', None) is not None:
            hole_edges.append(e)

    if not outer_edges or not hole_edges:
        return None

    outer_pts = []
    seen_o = set()
    for e in outer_edges:
        for v in (e.v0, e.v1):
            if id(v) not in seen_o:
                seen_o.add(id(v))
                outer_pts.append(v.position)
    fit_o = _fit_circle_geometric(outer_pts)
    if fit_o is None:
        return None
    center_o, normal_o, radius_o = fit_o
    cid_pt_o = add_point(center_o)

    hole_pts = []
    seen_i = set()
    for e in hole_edges:
        for v in (e.v0, e.v1):
            if id(v) not in seen_i:
                seen_i.add(id(v))
                hole_pts.append(v.position)
    fit_i = _fit_circle_geometric(hole_pts)
    if fit_i is None:
        return None
    center_i, normal_i, radius_i = fit_i
    cid_pt_i = add_point(center_i)

    center_idx_o = None
    for i, (cid, _r) in enumerate(circles, start=1):
        if cid == cid_pt_o:
            center_idx_o = i
            break
    if center_idx_o is None:
        circles.append((cid_pt_o, round(radius_o * 1000.0, 6)))
        center_idx_o = len(circles)

    center_idx_i = None
    for i, (cid, _r) in enumerate(circles, start=1):
        if cid == cid_pt_i:
            center_idx_i = i
            break
    if center_idx_i is None:
        circles.append((cid_pt_i, round(radius_i * 1000.0, 6)))
        center_idx_i = len(circles)

    verts_o = _order_curve_vertices(outer_edges, outer)
    verts_i = _order_curve_vertices(hole_edges, hole)

    if len(verts_o) < 2 or len(verts_i) < 2:
        return None

    a_o0 = _angle_ccw(verts_o[0].position, center_o)
    a_o1 = _angle_ccw(verts_o[1].position, center_o)
    diff_o = (a_o1 - a_o0) % (2 * math.pi)
    dir_o = 1 if diff_o < math.pi else -1

    a_i0 = _angle_ccw(verts_i[0].position, center_i)
    a_i1 = _angle_ccw(verts_i[1].position, center_i)
    diff_i = (a_i1 - a_i0) % (2 * math.pi)
    dir_i = 1 if diff_i < math.pi else -1

    if dir_o != dir_i:
        verts_i = list(reversed(verts_i))

    a_o0 = _angle_ccw(verts_o[0].position, center_o)
    best_idx = 0
    best_diff = 1e9
    for i, v in enumerate(verts_i):
        a_i = _angle_ccw(v.position, center_i)
        diff = abs(a_i - a_o0)
        if diff > math.pi:
            diff = 2 * math.pi - diff
        if diff < best_diff:
            best_diff = diff
            best_idx = i
    verts_i = verts_i[best_idx:] + verts_i[:best_idx]

    n_arcs = 4

    n_v_o = len(verts_o)
    n_v_i = len(verts_i)

    outer_starts = []
    inner_starts = []
    for k in range(n_arcs):
        idx_o = int(round(k * (n_v_o - 1) / n_arcs)) % n_v_o
        idx_i = int(round(k * (n_v_i - 1) / n_arcs)) % n_v_i
        outer_starts.append(verts_o[idx_o])
        inner_starts.append(verts_i[idx_i])

    for k in range(n_arcs):
        k_next = (k + 1) % n_arcs
        v_a = outer_starts[k]
        v_b = outer_starts[k_next]
        pa = add_point(v_a.position)
        pb = add_point(v_b.position)
        lid = line_reg.ensure(
            ("arc_outer", (id(face), k)),
            _make_factory_line(pa, pb, center_idx_o))
        idx_a = int(round(k * (n_v_o - 1) / n_arcs)) % n_v_o
        idx_b = int(round((k + 1) * (n_v_o - 1) / n_arcs)) % n_v_o
        if idx_b <= idx_a:
            idx_b += n_v_o
        for i in range(idx_a, idx_b):
            ii = i % n_v_o
            i2 = (i + 1) % n_v_o
            v1 = verts_o[ii]
            v2 = verts_o[i2]
            e = mesh.find_edge(v1, v2)
            if e is not None and getattr(e, 'curve', None) is not None:
                edge_to_line[id(e)] = lid

    for k in range(n_arcs):
        k_next = (k + 1) % n_arcs
        v_a = inner_starts[k]
        v_b = inner_starts[k_next]
        pa = add_point(v_a.position)
        pb = add_point(v_b.position)
        lid = line_reg.ensure(
            ("arc_inner", (id(face), k)),
            _make_factory_line(pa, pb, center_idx_i))
        idx_a = int(round(k * (n_v_i - 1) / n_arcs)) % n_v_i
        idx_b = int(round((k + 1) * (n_v_i - 1) / n_arcs)) % n_v_i
        if idx_b <= idx_a:
            idx_b += n_v_i
        for i in range(idx_a, idx_b):
            ii = i % n_v_i
            i2 = (i + 1) % n_v_i
            v1 = verts_i[ii]
            v2 = verts_i[i2]
            e = mesh.find_edge(v1, v2)
            if e is not None and getattr(e, 'curve', None) is not None:
                edge_to_line[id(e)] = lid

    for k in range(n_arcs):
        v_a = outer_starts[k]
        v_b = inner_starts[k]
        pa = add_point(v_a.position)
        pb = add_point(v_b.position)
        line_reg.ensure(
            ("radial", (id(face), k)),
            _make_factory_line(pa, pb, None))

    sectors = []
    for k in range(n_arcs):
        k_next = (k + 1) % n_arcs
        sec_keys = [
            ("arc_outer", (id(face), k)),
            ("radial", (id(face), k_next)),
            ("arc_inner", (id(face), k)),
            ("radial", (id(face), k)),
        ]
        sectors.append(sec_keys)
    return sectors


def save_fbd(scene, path) -> dict:
    meshes = list(_iter_meshes_with_owner(scene))
    point_reg = _Registry()
    line_reg = _Registry()
    curve_reg = _Registry()
    group_reg = _Registry()
    points = []
    lines = []
    circles = []
    all_surfaces = []
    edge_to_line = {}

    line_reg._list = lines

    def add_point(p):
        key = ("pt",
               round(p.x() * _KEY_SCALE),
               round(p.y() * _KEY_SCALE),
               round(p.z() * _KEY_SCALE))
        pid = point_reg.id_of(key)
        if pid > len(points):
            points.append((_mm(p.x()), _mm(p.y()), _mm(p.z())))
        return pid

    # -- 1. straight edges (global) --
    for mesh, _owner in meshes:
        for e in mesh.edges:
            if getattr(e, "curve", None) is not None:
                continue
            if getattr(e, "hidden", False):
                continue
            pa = add_point(e.v0.position)
            pb = add_point(e.v1.position)
            lid = line_reg.ensure(
                ("line", id(e)), _make_factory_line(pa, pb, None))
            edge_to_line[id(e)] = lid

    # -- 2. curves untuk SOLID GROUP: TIDAK diproses (biarkan garis lurus) --
    # v0.0.31b: khusus solid group (owner != None), curve edge ditulis
    # sebagai garis lurus (ldv), bukan busur.
    for mesh, owner in meshes:
        if owner is None:
            continue
        # Tulis curve edge solid group sebagai garis lurus
        for e in mesh.edges:
            if getattr(e, "curve", None) is None:
                continue
            if getattr(e, "hidden", False):
                continue
            pa = add_point(e.v0.position)
            pb = add_point(e.v1.position)
            # key pakai id(e) + "line" â€” bukan "arc"
            lid = line_reg.ensure(
                ("line", id(e)), _make_factory_line(pa, pb, None))
            edge_to_line[id(e)] = lid

    # -- 3. surfaces --
    for mesh, owner in meshes:
        # 2D: per-face (proses curve jadi busur)
        if owner is None:
            for face in mesh.faces:
                _process_face_curves(
                    face, mesh, point_reg, line_reg, lines,
                    curve_reg, circles, add_point, edge_to_line)

        curve_adj = _build_curve_adj(mesh)
        radial_adj = _build_radial_adj(mesh)
        for face in mesh.faces:
            loop = list(face.loop)
            n = len(loop)
            if n < 3:
                continue

            holes = getattr(face, 'hole_loops', []) or []
            if holes:
                ring_sectors = _process_ring(
                    face, mesh, point_reg, line_reg, lines,
                    curve_reg, circles, add_point, edge_to_line)
                if ring_sectors:
                    for sec in ring_sectors:
                        sec_lids = []
                        for key in sec:
                            lid = line_reg.peek(key)
                            if lid is not None:
                                sec_lids.append(lid)
                        if len(sec_lids) == 4:
                            all_surfaces.append(
                                {"owner": owner, "gsurs": [sec_lids]})
                continue

            all_inter = all(
                _is_intermediate_v26(v, curve_adj, radial_adj)
                for v in loop)
            has_curve = False
            for i in range(n):
                va = loop[i]
                vb = loop[(i + 1) % n]
                e = mesh.find_edge(va, vb)
                if e is not None and getattr(e, 'curve', None) is not None:
                    has_curve = True
                    break

            skip_intermediate = not (all_inter and has_curve)

            face_lines = []
            for i in range(n):
                v_a = loop[i]
                v_b = loop[(i + 1) % n]
                if skip_intermediate:
                    if (_is_intermediate_v26(v_a, curve_adj, radial_adj)
                            and _is_intermediate_v26(v_b, curve_adj, radial_adj)):
                        continue
                e = mesh.find_edge(v_a, v_b)
                if e is None:
                    continue
                lid = edge_to_line.get(id(e))
                if lid is None:
                    pa = add_point(v_a.position)
                    pb = add_point(v_b.position)
                    # v0.0.31b: untuk solid group, curve jadi garis lurus
                    if owner is not None:
                        key = ("line", id(e))
                    else:
                        is_curve = getattr(e, "curve", None) is not None
                        key = ("arc" if is_curve else "line", id(e))
                    lid = line_reg.ensure(
                        key, _make_factory_line(pa, pb, None))
                    edge_to_line[id(e)] = lid
                face_lines.append(lid)

            seen = set()
            deduped = []
            for lid in face_lines:
                if lid not in seen:
                    seen.add(lid)
                    deduped.append(lid)
            if deduped:
                all_surfaces.append({"owner": owner, "gsurs": [deduped]})

    # -- 4. volumes --
    owner_surfaces = defaultdict(list)
    for i, surf in enumerate(all_surfaces, start=1):
        if surf.get("owner") is not None:
            owner_surfaces[surf["owner"]].append(i)
    volumes = []
    for g in getattr(scene, "groups", []):
        if not scene.entity_visible(g):
            continue
        surf_ids = owner_surfaces.get(g.uid)
        if not surf_ids:
            continue
        gid = group_reg.id_of(g.uid)
        volumes.append({"id": gid, "surfaces": surf_ids})

    # -- 5. Remove dangling points --
    used = set()
    for entry in lines:
        used.add(entry[0])
        used.add(entry[1])
        if entry[2] is not None:
            used.add(entry[2])
    for cid, _r in circles:
        used.add(cid)

    mapping = {}
    new_points = []
    for old_id in sorted(used):
        if 1 <= old_id <= len(points):
            new_id = len(new_points) + 1
            mapping[old_id] = new_id
            new_points.append(points[old_id - 1])

    new_lines = []
    for entry in lines:
        a = mapping.get(entry[0])
        b = mapping.get(entry[1])
        c = mapping.get(entry[2]) if entry[2] is not None else None
        if a is None or b is None:
            continue
        if entry[2] is not None and c is None:
            continue
        new_lines.append((a, b, c))

    new_circles = []
    for cid, r in circles:
        new_cid = mapping.get(cid)
        if new_cid is not None:
            new_circles.append((new_cid, r))

    lines = new_lines
    circles = new_circles
    points = new_points

    # -- 6. write --
    with open(Path(path), "w", encoding="utf-8") as f:
        _write_header(f)
        _write_points(f, points)
        _write_curves(f, circles, points)
        _write_lines(f, lines)
        _write_surfaces(f, all_surfaces)
        _write_volumes(f, volumes, len(all_surfaces))
        _write_text(f)

    return {
        "n_points": len(points),
        "n_lines": len(lines),
        "n_surfaces": len(all_surfaces),
        "n_circles": len(circles),
        "n_volumes": len(volumes),
    }


def _write_header(f) -> None:
    f.write("# *****************************************************\n")
    f.write("# *\n")
    f.write("# *  CalculiX CGX fbd-file exported by IngeTrazo (v0.0.31b)\n")
    f.write("# *\n")
    f.write("# *****************************************************/\n\n")
    f.write("# Parameters :\n")
    f.write("valu ldv 4\n\n")


def _write_points(f, points) -> None:
    f.write(f"# Write {len(points)} points\n")
    for i, (x, y, z) in enumerate(points, start=1):
        f.write(f"pnt P{i} {x:.2f} {y:.2f} {z:.2f}\n")
    f.write("\n")


def _write_curves(f, circles, points) -> None:
    if not circles:
        return
    f.write(f"# Write {len(circles)} circle centre(s)\n")
    for i, (cid, _r) in enumerate(circles, start=1):
        x, y, z = points[cid - 1]
        f.write(f"pnt C{i} {x:.2f} {y:.2f} {z:.2f}\n")
    f.write("\n")


def _write_lines(f, lines) -> None:
    f.write(f"# Write {len(lines)} lines\n")
    for i, entry in enumerate(lines, start=1):
        if entry[2] is not None:
            a, b, c = entry
            if _USE_LDV_ON_ARC:
                f.write(f"line L{i} P{a} P{b} C{c} ldv\n")
            else:
                f.write(f"line L{i} P{a} P{b} C{c}\n")
        else:
            a, b = entry[0], entry[1]
            f.write(f"line L{i} P{a} P{b} ldv\n")
    f.write("\n")


def _write_surfaces(f, surfaces) -> None:
    f.write(f"# Write {len(surfaces)} Surfaces\n")
    total_gsur = 0
    for i, surf in enumerate(surfaces, start=1):
        gsurs = surf.get("gsurs") or []
        if not gsurs:
            continue
        gsur_ids = []
        for g in gsurs:
            if not g:
                continue
            total_gsur += 1
            f.write(f"gsur A{total_gsur} + blend ")
            for lid in g:
                f.write(f"+ L{lid} ")
            f.write("\n")
            gsur_ids.append(total_gsur)
        if gsur_ids:
            f.write(f"seta S{i} s ")
            for gid in gsur_ids:
                f.write(f"A{gid} ")
            f.write("\n")
    f.write("\n")


def _write_volumes(f, volumes, n_surfaces) -> None:
    f.write(f"# Write {len(volumes)} volumes\n")
    next_id = n_surfaces + 1
    for v in volumes:
        f.write(f"seta V{v['id']} s ")
        for sid in v["surfaces"]:
            f.write(f"S{sid} ")
        f.write("\n")
        f.write(f"body B{next_id} V{v['id']}\n")
        next_id += 1
    f.write("\n")


def _write_text(f) -> None:
    f.write("plot p all\n")
    f.write("plus l all\n")
    f.write("plus s all\n")
    f.write("plus ba all\n\n")
    f.write("#/merg p all\n")
    f.write("#/merg l all\n")
    f.write("#/merg s all\n\n")
    f.write("#/div all auto 2. 10. 0.5\n")
    f.write("#/elty all te10 / he20r / tr6 / qu8r\n")
    f.write("#/mesh all\n\n")
    f.write("#/send all abq\n\n")
    f.write("prnt se\n\n")
    f.write("#/neigh all 0.1 abq con tie\n\n")
    f.write("#/seta Support A0x\n")
    f.write("#/comp Support do\n")
    f.write("#/send Support abq spc 123\n\n")
    f.write("#/seta A0x\n")
    f.write("#/comp Load do\n")
    f.write("#/comp Load do\n")
    f.write("#/send Support abq pres 1.0\n")
