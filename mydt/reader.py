"""Read a submitted template into tidy observations.

The reader does not trust fixed column positions. It reads the year and sex
headers and the row codes from the sheet itself, so templates with a different
set of years, or in any language, parse the same way. Every value keeps the
cell address it came from, so QC flags can point countries to the exact cell.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from . import spec

OBS_COLUMNS = ["iso3", "survey_year", "table", "level", "age", "grade", "item",
               "sex", "year", "value", "status", "raw", "cell", "source"]
SEX_RE = re.compile(r"\((F|M|T)\)\s*$")
ISO3_RE = re.compile(r"[A-Z]{3}")


@dataclass
class Submission:
    path: Path
    cover: dict
    data: pd.DataFrame
    metadata: pd.DataFrame
    years: list[int]
    missing_sheets: list[str] = field(default_factory=list)

    @property
    def iso3(self) -> str:
        """Validated ISO3 code, or '' if the cover page holds anything else."""
        return clean_iso3(self.cover.get("ISO3"))

    @property
    def key(self) -> str:
        """Identifier used for flags and file names; never collides with a real ISO3."""
        return self.iso3 or "INVALID_" + safe_name(self.path.stem)


def clean_iso3(v) -> str:
    s = str(v or "").strip().upper()
    return s if ISO3_RE.fullmatch(s) else ""


def safe_name(s: str) -> str:
    """Anything used in a file name: letters, digits, _ and - only."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(s))[:40] or "unknown"


def parse_value(v):
    """Return (value, status). status: '' ok, a missing code, 'blank' or 'invalid'."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return float("nan"), "blank"
    if isinstance(v, bool):
        return float("nan"), "invalid"
    if isinstance(v, (int, float)):
        return float(v), ""
    s = str(v).strip()
    if s.lower() in spec.MISSING_CODES:
        return float("nan"), s.lower()
    return float("nan"), "invalid"


def _header_map(ws, sh: spec.SheetSpec) -> list[tuple[int, int, str | None]]:
    """[(column, year, sex)] read from the header rows; merged year cells are forward-filled."""
    out, year = [], None
    for c in range(spec.FIRST_DATA_COL, ws.max_column + 1):
        yv = ws.cell(spec.YEAR_ROW, c).value
        if yv not in (None, ""):
            try:
                year = int(yv)
            except (TypeError, ValueError):
                break
        if year is None:
            continue
        sex = None
        if sh.by_sex:
            m = SEX_RE.search(str(ws.cell(spec.SEX_ROW, c).value or ""))
            if not m:
                continue
            sex = m.group(1)
        out.append((c, year, sex))
    return out


def read_template(path) -> Submission:
    path = Path(path)
    wb = load_workbook(path, data_only=False)

    cover = {}
    if "COVER" in wb.sheetnames:
        ws = wb["COVER"]
        for r in range(spec.FIRST_DATA_ROW, ws.max_row + 1):
            key = ws.cell(r, 1).value
            if key:
                cover[str(key).strip()] = ws.cell(r, 3).value
    iso3 = clean_iso3(cover.get("ISO3"))
    try:
        survey_year = int(cover.get("SURVEY_YEAR"))
    except (TypeError, ValueError):
        survey_year = None

    meta_rows = []
    if "METADATA" in wb.sheetnames:
        ws = wb["METADATA"]
        for r in range(spec.FIRST_DATA_ROW, ws.max_row + 1):
            t = ws.cell(r, 1).value
            if t:
                row = {"table": str(t).strip()}
                for j, f in enumerate(spec.METADATA_FIELDS):
                    row[f] = ws.cell(r, 2 + j).value
                meta_rows.append(row)

    recs, years, missing = [], set(), []
    for sh in spec.DATA_SHEETS:
        if sh.name not in wb.sheetnames:
            missing.append(sh.name)
            continue
        ws = wb[sh.name]
        cols = _header_map(ws, sh)
        years.update(y for _, y, _ in cols)
        for r in range(spec.FIRST_DATA_ROW, ws.max_row + 1):
            d1 = ws.cell(r, 1).value
            if d1 in (None, ""):
                continue
            d2 = ws.cell(r, 3).value
            dims = {sh.dims[0]: str(d1).strip()}
            if len(sh.dims) > 1:
                dims[sh.dims[1]] = None if d2 is None else str(d2).strip()
            for c, y, sx in cols:
                raw = ws.cell(r, c).value
                val, status = parse_value(raw)
                recs.append({
                    "iso3": iso3, "survey_year": survey_year, "table": sh.name,
                    "level": dims.get("level"), "age": dims.get("age"),
                    "grade": dims.get("grade"), "item": dims.get("item"),
                    "sex": sx, "year": y, "value": val, "status": status,
                    "raw": None if raw is None else str(raw),
                    "cell": f"{sh.name}!{get_column_letter(c)}{r}",
                    "source": "country_template",
                })
    data = pd.DataFrame.from_records(recs, columns=OBS_COLUMNS)
    meta = pd.DataFrame(meta_rows, columns=["table"] + spec.METADATA_FIELDS)
    return Submission(path, cover, data, meta, sorted(years), missing)


def read_folder(folder) -> list[Submission]:
    return [read_template(p) for p in sorted(Path(folder).glob("*.xlsx"))
            if not p.name.startswith("~$")]
