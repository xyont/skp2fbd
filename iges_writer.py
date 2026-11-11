# SPDX-License-Identifier: GPL-3.0-or-later
"""IGES writer untuk IngeTrazo.

Port Python dari IxMilia.Iges:
  - IgesFileWriter.cs   (format baris, section, wrapping)
  - IgesFile.cs         (Global Section, default values)
  - IgesEntity.cs       (AddDirectoryAndParameterLines, status number)
  - IgesPoint.cs        (struct 3D)
  - IgesVector.cs       (struct 3D)
  - IgesLine.cs         (entity 110)
  - IgesCircularArc.cs  (entity 100)
  - IgesPointEntity.cs  (entity 116) — wrapper untuk IgesPoint

Entity didukung: Point (116), Line (110), Circular Arc (100).
Unit default: millimeter (flag 2). Versi IGES default: 5.3 (11).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Konstanta (port dari IgesFile.cs)
# ---------------------------------------------------------------------------
MAX_DATA_LENGTH = 72
MAX_PARAMETER_LENGTH = 64

DEFAULT_FIELD_DELIMITER = ","
DEFAULT_RECORD_DELIMITER = ";"


class IgesUnitType:
    INCH = 1
    MILLIMETER = 2


class IgesVersion:
    V5_1 = 9
    V5_2 = 10
    V5_3 = 11


class IgesLineBounding:
    BOUND_ON_BOTH_SIDES = 0
    BOUND_ON_START = 1
    UNBOUNDED = 2


# ---------------------------------------------------------------------------
# IgesPoint & IgesVector (port struct C#)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class IgesPoint:
    X: float
    Y: float
    Z: float

    @staticmethod
    def origin() -> "IgesPoint":
        return IgesPoint(0.0, 0.0, 0.0)


@dataclass(frozen=True)
class IgesVector:
    X: float
    Y: float
    Z: float

    @property
    def length_squared(self) -> float:
        return self.X * self.X + self.Y * self.Y + self.Z * self.Z

    @property
    def length(self) -> float:
        return math.sqrt(self.length_squared)

    @property
    def is_zero_vector(self) -> bool:
        return self.X == 0.0 and self.Y == 0.0 and self.Z == 0.0

    def normalize(self) -> "IgesVector":
        return self / self.length

    def cross(self, v: "IgesVector") -> "IgesVector":
        return IgesVector(
            self.Y * v.Z - self.Z * v.Y,
            self.Z * v.X - self.X * v.Z,
            self.X * v.Y - self.Y * v.X,
        )

    def dot(self, v: "IgesVector") -> float:
        return self.X * v.X + self.Y * v.Y + self.Z * v.Z

    def __neg__(self) -> "IgesVector":
        return IgesVector(-self.X, -self.Y, -self.Z)

    def __add__(self, v: "IgesVector") -> "IgesVector":
        return IgesVector(self.X + v.X, self.Y + v.Y, self.Z + v.Z)

    def __sub__(self, v: "IgesVector") -> "IgesVector":
        return IgesVector(self.X - v.X, self.Y - v.Y, self.Z - v.Z)

    def __mul__(self, s: float) -> "IgesVector":
        return IgesVector(self.X * s, self.Y * s, self.Z * s)

    def __truediv__(self, s: float) -> "IgesVector":
        return IgesVector(self.X / s, self.Y / s, self.Z / s)


# ---------------------------------------------------------------------------
# Serializer parameter (port dari IgesFileWriter.cs)
# ---------------------------------------------------------------------------
def _param_to_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value == 0.0:
            value = 0.0
        s = repr(value)
        if not any(c in s for c in ".eEdD"):
            s += "."
        return s
    if isinstance(value, datetime):
        return _param_to_str(value.strftime("%Y%m%d.%H%M%S"))
    if isinstance(value, str):
        if not value:
            return ""
        return f"{len(value)}H{value}"  # Hollerith
    raise TypeError(f"Unsupported parameter type: {type(value)}")


def _add_parameters_to_list(parameters: list,
                            string_list: list[str],
                            field_delim: str = DEFAULT_FIELD_DELIMITER,
                            record_delim: str = DEFAULT_RECORD_DELIMITER,
                            max_length: int = MAX_DATA_LENGTH,
                            line_suffix: str | None = None,
                            comment: str | None = None) -> int:
    """Port dari IgesFileWriter.AddParametersToStringList."""
    suffix_len = len(line_suffix) if line_suffix else 0
    sb: list[str] = []
    sb_len = 0
    added = 0

    def flush_line():
        nonlocal sb, sb_len, added
        pad = max_length - sb_len - suffix_len
        if pad > 0:
            sb.append(" " * pad)
        if line_suffix:
            sb.append(line_suffix)
        string_list.append("".join(sb))
        sb = []
        sb_len = 0
        added += 1

    n = len(parameters)
    for i, param in enumerate(parameters):
        delim = record_delim if i == n - 1 else field_delim
        param_str = _param_to_str(param) + delim
        if sb_len + len(param_str) + suffix_len <= max_length:
            sb.append(param_str)
            sb_len += len(param_str)
        elif len(param_str) + suffix_len <= max_length:
            flush_line()
            sb.append(param_str)
            sb_len += len(param_str)
        else:
            remaining = param_str
            while remaining:
                allowed = max_length - sb_len - suffix_len
                if len(remaining) <= allowed:
                    sb.append(remaining)
                    sb_len += len(remaining)
                    remaining = ""
                else:
                    sb.append(remaining[:allowed])
                    sb_len += allowed
                    flush_line()
                    remaining = remaining[allowed:]

    if comment:
        comment = (comment.replace("\\", "\\\\")
                          .replace("\n", "\\n").replace("\r", "\\r")
                          .replace("\t", "\\t").replace("\v", "\\v")
                          .replace("\f", "\\f"))
        remaining = comment
        while remaining:
            allowed = max_length - sb_len - suffix_len
            if len(remaining) <= allowed:
                sb.append(remaining)
                sb_len += len(remaining)
                remaining = ""
            else:
                sb.append(remaining[:allowed])
                sb_len += allowed
                flush_line()
                remaining = remaining[allowed:]

    if sb:
        flush_line()
    return added


# ---------------------------------------------------------------------------
# Helper Directory Entry
# ---------------------------------------------------------------------------
def _pad_int8(value: int) -> str:
    return f"{value:>8d}"[:8]


def _pad_str8(value: str | None) -> str:
    s = "" if value is None else str(value)
    return s[:8].ljust(8)


def _status_number(blank: int = 0, subordinate: int = 0,
                   use_flag: int = 0, hierarchy: int = 0) -> str:
    """Port GetStatusNumber: format 'BBSSUUHH' 8 digit."""
    return f"{blank:02d}{subordinate:02d}{use_flag:02d}{hierarchy:02d}"


# ---------------------------------------------------------------------------
# Entity classes
# ---------------------------------------------------------------------------
class IgesEntity:
    """Base entity (port dari IgesEntity abstrak)."""
    entity_type: int = 0

    def __init__(self):
        # Status number: BBSSUUHH (blank, subordinate, use flag, hierarchy)
        self.blank_status = 0
        self.subordinate_switch = 0
        self.entity_use_flag = 0
        self.hierarchy = 0
        self.line_weight = 0
        self.color = 0
        self.form_number = 0
        self.entity_label: str | None = None
        self.entity_subscript = 0
        self.comment: str | None = None

    def get_referenced_entities(self) -> list:
        """Entity lain yang direferensikan (untuk binder). Default kosong."""
        return []

    def write_parameters(self) -> list:
        """Parameter tanpa entity_type. Ditambahkan otomatis oleh writer."""
        raise NotImplementedError

    def directory_fields(self) -> list:
        """18 field directory (2 baris × 9 field 8-char)."""
        return [
            self.entity_type,   # 1: entity type
            0,                  # 2: parameter pointer (diisi nanti)
            0,                  # 3: structure
            0,                  # 4: line font
            0,                  # 5: level
            0,                  # 6: view
            0,                  # 7: transformation matrix
            0,                  # 8: label display
            _status_number(self.blank_status, self.subordinate_switch,
                           self.entity_use_flag, self.hierarchy),  # 9: status
            self.line_weight,   # 10: line weight
            self.color,         # 11: color
            0,                  # 12: param line count (diisi nanti)
            self.form_number,   # 13: form number
            0,                  # 14: reserved
            0,                  # 15: reserved
            self.entity_label,  # 16: entity label
            self.entity_subscript,  # 17: subscript
            0,                  # 18: reserved
        ]


class IgesPointEntity(IgesEntity):
    """Entity 116: Point."""
    entity_type = 116

    def __init__(self, point: IgesPoint):
        super().__init__()
        self.point = point

    def write_parameters(self) -> list:
        # IGES 116: X, Y, Z, PTR(subfigure), PTR(view)
        return [self.point.X, self.point.Y, self.point.Z, 0, 0]


class IgesLine(IgesEntity):
    """Entity 110: Line."""
    entity_type = 110

    def __init__(self, p1: IgesPoint, p2: IgesPoint,
                 bounding: int = IgesLineBounding.BOUND_ON_BOTH_SIDES):
        super().__init__()
        self.p1 = p1
        self.p2 = p2
        self.form_number = bounding

    def write_parameters(self) -> list:
        return [self.p1.X, self.p1.Y, self.p1.Z,
                self.p2.X, self.p2.Y, self.p2.Z]


class IgesCircularArc(IgesEntity):
    """Entity 100: Circular Arc (planar, sejajar XY).

    Port dari IxMilia.Iges.Entities.IgesCircularArc.
    Mensyaratkan `center.Z == start.Z == end.Z`.
    """
    entity_type = 100

    def __init__(self, center: IgesPoint, start: IgesPoint, end: IgesPoint):
        super().__init__()
        if center.Z != start.Z or center.Z != end.Z:
            raise ValueError("All z values must be equal")
        self.plane_displacement = center.Z
        self.center = IgesPoint(center.X, center.Y, 0.0)
        self.start_point = IgesPoint(start.X, start.Y, 0.0)
        self.end_point = IgesPoint(end.X, end.Y, 0.0)

    def write_parameters(self) -> list:
        # IGES 100: ZT, X1, Y1, X2, Y2, X3, Y3
        return [
            self.plane_displacement,
            self.center.X, self.center.Y,
            self.start_point.X, self.start_point.Y,
            self.end_point.X, self.end_point.Y,
        ]


# ---------------------------------------------------------------------------
# WriterState + Binder (port dari WriterState & IgesWriterBinder)
# ---------------------------------------------------------------------------
class IgesWriterBinder:
    def __init__(self, entity_map: dict):
        self._entity_map = entity_map

    def get_entity_id(self, entity) -> int:
        if entity is None:
            return 0
        if entity not in self._entity_map:
            raise ValueError(
                "Entity not found. Did you forget to override "
                "get_referenced_entities()?")
        return self._entity_map[entity]


class _WriterState:
    def __init__(self, entity_map: dict, directory_lines: list,
                 parameter_lines: list, field_delim: str, record_delim: str):
        self.entity_map = entity_map
        self.directory_lines = directory_lines
        self.parameter_lines = parameter_lines
        self.field_delim = field_delim
        self.record_delim = record_delim
        self.writer_binder = IgesWriterBinder(entity_map)

    def report_referenced_entities(self, entities: list) -> None:
        for e in entities:
            if e is None:
                continue
            if e in self.entity_map:
                continue
            self.get_or_write_entity_index(e)

    def get_or_write_entity_index(self, entity) -> int:
        if entity in self.entity_map:
            return self.entity_map[entity]
        return entity.add_directory_and_parameter_lines(self)


# ---------------------------------------------------------------------------
# AddDirectoryAndParameterLines (method pada entity)
# ---------------------------------------------------------------------------
def _add_directory_and_parameter_lines(self: IgesEntity,
                                       writer_state: _WriterState) -> int:
    """Port dari IgesEntity.AddDirectoryAndParameterLines."""
    # 1. Report entity yang direferensikan
    writer_state.report_referenced_entities(self.get_referenced_entities())

    # 2. Bangun parameter (entity_type + write_parameters)
    parameters: list = [self.entity_type]
    parameters.extend(self.write_parameters())

    # 3. Hitung directory index & parameter index berikutnya
    next_directory_index = len(writer_state.directory_lines) + 1
    next_parameter_index = len(writer_state.parameter_lines) + 1

    # 4. Tambahkan parameter lines, suffix = f" {next_directory_index:7d}"
    line_count = _add_parameters_to_list(
        parameters,
        writer_state.parameter_lines,
        field_delim=writer_state.field_delim,
        record_delim=writer_state.record_delim,
        line_suffix=f" {next_directory_index:7d}",
        comment=self.comment,
    )

    # 5. Update directory fields dengan param pointer & line count
    fields = self.directory_fields()
    fields[1] = next_parameter_index   # parameter pointer
    fields[11] = line_count            # parameter line count
    writer_state.directory_lines.append("".join(_pad_int8(f) for f in fields[0:9]))
    writer_state.directory_lines.append(
        "".join(_pad_str8(f) for f in fields[9:18]))

    # 6. Daftarkan entity di map
    writer_state.entity_map[self] = next_directory_index
    return next_directory_index


# Pasang sebagai method
IgesEntity.add_directory_and_parameter_lines = _add_directory_and_parameter_lines


# ---------------------------------------------------------------------------
# IgesFile (port dari IgesFile.cs)
# ---------------------------------------------------------------------------
class IgesFile:
    def __init__(self):
        self.field_delimiter = DEFAULT_FIELD_DELIMITER
        self.record_delimiter = DEFAULT_RECORD_DELIMITER
        self.identification = None
        self.full_file_name = None
        self.system_identifier = None
        self.system_version = None
        self.integer_size = 32
        self.single_size = 8
        self.decimal_digits = 23
        self.double_magnitude = 11
        self.double_precision = 52
        self.identifier = None
        self.model_space_scale = 1.0
        self.model_units = IgesUnitType.INCH
        self.custom_model_units = None
        self.max_line_weight_graduations = 0
        self.max_line_weight = 1.0
        self.time_stamp = datetime.now()
        self.minimum_resolution = 1.0e-10
        self.max_coordinate_value = 0.0
        self.author = None
        self.organization = None
        self.iges_version = IgesVersion.V5_3
        self.drafting_standard = 0
        self.modified_time = datetime.now()
        self.application_protocol = None
        self.entities: list[IgesEntity] = []

    def add(self, entity: IgesEntity) -> None:
        self.entities.append(entity)

    def save(self, path) -> None:
        path = Path(path)
        start_lines: list[str] = [" " * MAX_DATA_LENGTH]
        global_lines: list[str] = []
        dir_lines: list[str] = []
        param_lines: list[str] = []

        entity_map: dict = {}
        writer_state = _WriterState(entity_map, dir_lines, param_lines,
                                    self.field_delimiter, self.record_delimiter)

        # Tulis semua entity
        for entity in self.entities:
            if entity not in entity_map:
                entity.add_directory_and_parameter_lines(writer_state)

        # Global Section
        global_fields = [
            self.field_delimiter, self.record_delimiter,
            self.identification, self.full_file_name,
            self.system_identifier, self.system_version,
            self.integer_size, self.single_size, self.decimal_digits,
            self.double_magnitude, self.double_precision, self.identifier,
            self.model_space_scale, self.model_units, self.custom_model_units,
            self.max_line_weight_graduations, self.max_line_weight,
            self.time_stamp, self.minimum_resolution, self.max_coordinate_value,
            self.author, self.organization,
            self.iges_version, self.drafting_standard,
            self.modified_time, self.application_protocol,
        ]
        _add_parameters_to_list(
            global_fields, global_lines,
            field_delim=self.field_delimiter,
            record_delim=self.record_delimiter,
        )

        # Tulis ke file
        with open(path, "w", encoding="ascii", newline="\n") as f:
            _write_section(f, "S", start_lines)
            _write_section(f, "G", global_lines)
            _write_section(f, "D", dir_lines)
            _write_section(f, "P", param_lines)
            term = (f"S{len(start_lines):7d}G{len(global_lines):7d}"
                    f"D{len(dir_lines):7d}P{len(param_lines):7d}")
            f.write(_make_file_line("T", term, 1))


# ---------------------------------------------------------------------------
# Helper penulisan section
# ---------------------------------------------------------------------------
def _make_file_line(section: str, line: str, line_number: int) -> str:
    if line is None:
        line = ""
    if len(line) > MAX_DATA_LENGTH:
        raise ValueError(f"IGES line is too long ({len(line)} > {MAX_DATA_LENGTH})")
    return f"{line:<72}{section}{line_number:>7d}\n"


def _write_section(f, section: str, lines: list[str]) -> None:
    for i, line in enumerate(lines, start=1):
        f.write(_make_file_line(section, line, i))


# ---------------------------------------------------------------------------
# API tingkat tinggi
# ---------------------------------------------------------------------------
def save_iges(entities: list[IgesEntity], path,
              author: str = "", organization: str = "") -> dict:
    f = IgesFile()
    f.model_units = IgesUnitType.MILLIMETER
    f.custom_model_units = "MM"
    f.author = author or None
    f.organization = organization or None
    f.full_file_name = str(Path(path).name)
    f.system_identifier = "IngeTrazo"
    f.system_version = "1.0"
    f.identification = "IngeTrazo export"

    for e in entities:
        f.add(e)
    f.save(path)

    return {
        "n_points": sum(1 for e in entities if isinstance(e, IgesPointEntity)),
        "n_lines": sum(1 for e in entities if isinstance(e, IgesLine)),
        "n_arcs": sum(1 for e in entities if isinstance(e, IgesCircularArc)),
        "total": len(entities),
    }