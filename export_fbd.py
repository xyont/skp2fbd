# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Suyono Nt. and DeepSeek contributors.
"""CalculiX CGX .fbd exporter - v0.0.7.

v0.0.7: Semua line ditulis dengan parameter `ldv` (panjang segmen).
"""
from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path

from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QFileDialog, QMessageBox

from tools.base import Tool


# Set True untuk menambahkan `ldv` di akhir setiap line
# (termasuk busur). Set False untuk format lama.
_USE_LDV_ON_ARC = True


class ExportFBDTool(Tool):
    name = "Export CalculiX FBD v0.0.7"
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
            save_fbd(scene, path)
        except Exception as exc:
            QMessageBox.critical(viewport.window(),
                                 "Export CalculiX FBD",
                                 f"Export failed:\n\n{exc}")
            return
        QMessageBox.information(viewport.window(),
                                "Export CalculiX FBD",
                                f"Wrote {Path(path).name}")

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


def _fit_circle_geometric(points):
    """Fit circle 3D di bidang apapun."""
    n = len(points)
    if n < _MIN_FIT_POINTS:
        return None

    p1 = points[0]
    p2 = max(points[1:], key=lambda p: (p - p1).length())
    p3 = max(points, key=lambda p: min(
        (p - p1).length(), (p - p2).length()))

    normal = QVector3D.crossProduct(_sub3(p2, p1), _sub3(p3, p1))
    if normal.length() < 1e-9:
        return None
    normal = normal.normalized()

    u = _sub3(p2, p1).normalized()
    v = QVector3D.crossProduct(normal, u)

    pts_2d = []
    for p in points:
        d = _sub3(p, p1)
        pts_2d.append((QVector3D.dotProduct(d, u),
                       QVector3D.dotProduct(d, v)))

    n_pts = len(pts_2d)
    sx = sy = sxx = syy = sxy = 0.0
    sxz = syz = sz = 0.0
    for (x, y) in pts_2d:
        z = x*x + y*y
        sx += x
        sy += y
        sxx += x*x
        syy += y*y
        sxy += x*y
        sxz += x*z
        syz += y*z
        sz += z

    M = [
        [4*sxx, 4*sxy, 2*sx],
        [4*sxy, 4*syy, 2*sy],
        [2*sx,  2*sy,  n_pts],
    ]
    rhs = [2*sxz, 2*syz, sz]

    def det3(m):
        return (m[0][0]*(m[1][1]*m[2][2] - m[1][2]*m[2][1])
                - m[0][1]*(m[1][0]*m[2][2] - m[1][2]*m[2][0])
                + m[0][2]*(m[1][0]*m[2][1] - m[1][1]*m[2][0]))

    D = det3(M)
    if abs(D) < 1e-15:
        return None

    M1 = [row[:] for row in M]
    M2 = [row[:] for row in M]
    M3 = [row[:] for row in M]
    for i in range(3):
        M1[i][0] = rhs[i]
        M2[i][1] = rhs[i]
        M3[i][2] = rhs[i]

    cx2 = det3(M1) / D
    cy2 = det3(M2) / D
    c = det3(M3) / D

    cx = cx2 / 2.0
    cy = cy2 / 2.0
    r2 = c + cx*cx + cy*cy
    if r2 < 1e-12:
        return None
    radius = math.sqrt(r2)

    center = p1 + u * cx + v * cy
    return center, normal, radius


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


def save_fbd(scene, path) -> None:
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

    # -- 1. curves --
    for mesh, _owner in meshes:
        curve_edges = [e for e in mesh.edges
                       if getattr(e, "curve", None) is not None]
        if not curve_edges:
            continue
        all_pts = []
        seen = set()
        for e in curve_edges:
            for v in (e.v0, e.v1):
                if id(v) not in seen:
                    seen.add(id(v))
                    all_pts.append(v.position)
        if len(all_pts) < 3:
            continue
        fit = _fit_circle_geometric(all_pts)
        if fit is None:
            for e in curve_edges:
                pa = add_point(e.v0.position)
                pb = add_point(e.v1.position)
                lid = line_reg.ensure(
                    ("line", id(e)), _make_factory_line(pa, pb, None))
                edge_to_line[id(e)] = lid
            continue
        center, normal, radius = fit
        cid_pt = add_point(center)
        curve_id = curve_reg.id_of(("center", id(mesh)))
        if curve_id > len(circles):
            circles.append((cid_pt, round(radius * 1000.0, 6)))

        angle_of = _make_angle_fn(center, normal)

        by_cid = defaultdict(list)
        for e in curve_edges:
            cid = getattr(e, "curve", None)
            by_cid[cid].append(e)

        for cid, edges in by_cid.items():
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

            n_edges = len(edges)
            n_arcs = max(1, int(round(n_edges / 3.0)))
            if is_closed and n_arcs < 4:
                n_arcs = 4

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
                if i_start >= n_v or i_end > n_v:
                    continue
                v_a = verts[i_start]
                v_b = verts[i_end] if i_end < n_v else verts[-1]
                pa = add_point(v_a.position)
                pb = add_point(v_b.position)
                lid = line_reg.ensure(
                    ("arc", (cid, k)),
                    _make_factory_line(pa, pb, cid_pt))
                for i in range(i_start, min(i_end, n_v - 1)):
                    if i + 1 >= n_v:
                        break
                    v1 = verts[i]
                    v2 = verts[i + 1]
                    e = mesh.find_edge(v1, v2)
                    if (e is not None
                            and getattr(e, "curve", None) is not None):
                        edge_to_line[id(e)] = lid

    # -- 2. straight edges --
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

    # -- 3. surfaces --
    for mesh, owner in meshes:
        for face in mesh.faces:
            loop_vertices = list(face.loop)
            if len(loop_vertices) < 3:
                continue
            n = len(loop_vertices)

            all_inter = all(_is_intermediate_vertex(v)
                            for v in loop_vertices)
            has_curve = False
            for i in range(n):
                v_a = loop_vertices[i]
                v_b = loop_vertices[(i + 1) % n]
                e = mesh.find_edge(v_a, v_b)
                if e is not None and getattr(e, "curve", None) is not None:
                    has_curve = True
                    break

            skip_intermediate = not (all_inter and has_curve)

            face_lines = []
            for i in range(n):
                v_a = loop_vertices[i]
                v_b = loop_vertices[(i + 1) % n]
                if skip_intermediate:
                    if (_is_intermediate_vertex(v_a)
                            and _is_intermediate_vertex(v_b)):
                        continue
                e = mesh.find_edge(v_a, v_b)
                if e is None:
                    continue
                lid = edge_to_line.get(id(e))
                if lid is None:
                    pa = add_point(v_a.position)
                    pb = add_point(v_b.position)
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


def _write_header(f) -> None:
    f.write("# *****************************************************\n")
    f.write("# *\n")
    f.write("# *  CalculiX CGX fbd-file exported by IngeTrazo (v0.0.7)\n")
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
                # Format baru: busur dengan ldv
                f.write(f"line L{i} P{a} P{b} C{c} ldv\n")
            else:
                # Format lama: busur tanpa ldv
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