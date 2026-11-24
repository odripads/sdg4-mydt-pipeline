"""Write MYDT-style Excel templates in any language, for any set of years.

The workbook carries its own checks, like the real templates: data validation
on every entry cell, a CHECKS sheet with live Excel formulas, locked
pre-filled sheets, and highlighted columns for the new year to complete.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from . import spec

LABELS_PATH = Path(__file__).resolve().parent.parent / "config" / "labels.yaml"
LANGS = ["en", "fr", "es", "pt", "ru"]

BLUE = PatternFill("solid", fgColor="1F4E79")
GREY = PatternFill("solid", fgColor="E7E6E6")
NEW_YEAR = PatternFill("solid", fgColor="FFF2CC")
RED = PatternFill("solid", fgColor="F8CBAD")
GREEN = PatternFill("solid", fgColor="E2EFDA")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


@lru_cache
def labels(lang: str) -> dict:
    with open(LABELS_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)[lang]


def code_label(lang: str, code: str | None) -> str:
    if code is None:
        return ""
    return labels(lang)["codes"].get(code, code)


def _header(ws, title: str, instr: str, ncols: int):
    ws.cell(spec.TITLE_ROW, 1, title).font = Font(bold=True, size=14, color="1F4E79")
    c = ws.cell(spec.INSTR_ROW, 1, instr)
    c.font = Font(italic=True, size=9)
    c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=spec.INSTR_ROW, start_column=1,
                   end_row=spec.INSTR_ROW, end_column=max(ncols, 8))
    ws.row_dimensions[spec.INSTR_ROW].height = 30


def write_data_sheet(wb, sh: spec.SheetSpec, years, values, lang, new_years):
    L = labels(lang)
    ws = wb.create_sheet(sh.name)
    instr = L["instructions"]["data" if sh.editable else "prefilled"]
    _header(ws, L["titles"][sh.name], instr, sh.last_col(years))

    for col, w in zip("ABCD", (10, 42, 8, 18)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = ws.cell(spec.FIRST_DATA_ROW, spec.FIRST_DATA_COL)

    # year row (merged over sex columns) and sex row
    nsex = len(sh.sexes)
    for y in years:
        c0 = sh.col_of(years, y, sh.sexes[0])
        cell = ws.cell(spec.YEAR_ROW, c0, y)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = BLUE
        cell.alignment = Alignment(horizontal="center")
        if nsex > 1:
            ws.merge_cells(start_row=spec.YEAR_ROW, start_column=c0,
                           end_row=spec.YEAR_ROW, end_column=c0 + nsex - 1)
        for sx in sh.sexes:
            c = sh.col_of(years, y, sx)
            ws.column_dimensions[get_column_letter(c)].width = 12
            h = ws.cell(spec.SEX_ROW, c, L["sex"][sx] if sx else L["year"])
            h.font = Font(bold=True, size=9)
            h.alignment = Alignment(horizontal="center", wrap_text=True)
    ws.cell(spec.YEAR_ROW, 1, L["year"]).font = Font(bold=True)

    for i, r in enumerate(sh.rows()):
        row = spec.FIRST_DATA_ROW + i
        d1 = r[sh.dims[0]]
        d2 = r[sh.dims[1]] if len(sh.dims) > 1 else None
        ws.cell(row, 1, d1).font = Font(size=9, color="808080")
        ws.cell(row, 2, code_label(lang, "POP" if sh.name == "POP" else d1))
        ws.cell(row, 3, d2).font = Font(size=9, color="808080")
        ws.cell(row, 4, code_label(lang, d2) if d2 else (d1 if sh.name == "POP" else ""))
        for y in years:
            for sx in sh.sexes:
                c = ws.cell(row, sh.col_of(years, y, sx))
                c.border = BOX
                v = values.get((sh.name, d1, d2, sx, y)) if values else None
                if v is not None:
                    c.value = v
                if sh.editable:
                    c.protection = Protection(locked=False)
                    if y in new_years:
                        c.fill = NEW_YEAR
                else:
                    c.fill = GREY
                c.number_format = "#,##0" if sh.name != "FIN" else "#,##0.0"

    if sh.editable:
        tl = f"{get_column_letter(spec.FIRST_DATA_COL)}{spec.FIRST_DATA_ROW}"
        rng = (f"{tl}:{get_column_letter(sh.last_col(years))}{sh.last_row()}")
        dv = DataValidation(
            type="custom",
            formula1=f'OR(AND(ISNUMBER({tl}),{tl}>=0),{tl}="m",{tl}="a",{tl}="x",{tl}="n")',
            allow_blank=True, showErrorMessage=True,
            errorTitle="UIS", error=L["validation_error"],
        )
        dv.add(rng)
        ws.add_data_validation(dv)
    ws.protection.sheet = True          # unlocked entry cells stay editable
    ws.protection.formatCells = False
    ws.protection.formatColumns = False
    return ws


def checks_layout(years) -> list[dict]:
    """Rows of the CHECKS sheet with the Excel formula for each year column.

    Kept as data so functional tests can compare the workbook's formulas
    against what the spec says they must be.
    """
    age, grade = spec.SHEETS["ENRL_AGE"], spec.SHEETS["ENRL_GRADE"]
    out = []
    row = spec.FIRST_DATA_ROW
    for lv in spec.LEVELS:
        a_rows = age.rows_where(level=lv)
        g_rows = grade.rows_where(level=lv)
        block = {}
        for key in ("AGE_TOT", "GRADE_TOT", "DIFF", "STATUS_AG", "SEXSUM", "STATUS_SX"):
            block[key] = row
            row += 1
        row += 1
        for key, r in block.items():
            f = {}
            for y in years:
                col = get_column_letter(spec.FIRST_DATA_COL + years.index(y))
                t_age = age.col_letter(years, y, "T")
                if key == "AGE_TOT":
                    f[y] = f"=SUM(ENRL_AGE!{t_age}{a_rows[0]}:{t_age}{a_rows[-1]})"
                elif key == "GRADE_TOT":
                    t_gr = grade.col_letter(years, y, "T")
                    f[y] = f"=SUM(ENRL_GRADE!{t_gr}{g_rows[0]}:{t_gr}{g_rows[-1]})"
                elif key == "DIFF":
                    f[y] = f"={col}{block['AGE_TOT']}-{col}{block['GRADE_TOT']}"
                elif key == "SEXSUM":
                    fa, ma = age.col_letter(years, y, "F"), age.col_letter(years, y, "M")
                    rr = lambda c: f"ENRL_AGE!{c}{a_rows[0]}:{c}{a_rows[-1]}"
                    f[y] = f"=SUM({rr(fa)})+SUM({rr(ma)})-SUM({rr(t_age)})"
                elif key == "STATUS_AG":
                    f[y] = f'=IF(ABS({col}{block["DIFF"]})>0,"CHECK","OK")'
                elif key == "STATUS_SX":
                    f[y] = f'=IF(ABS({col}{block["SEXSUM"]})>0,"CHECK","OK")'
            out.append({"row": r, "key": key, "level": lv, "formulas": f})
    return out


def write_checks_sheet(wb, years, lang):
    L = labels(lang)
    ws = wb.create_sheet("CHECKS")
    _header(ws, L["titles"]["CHECKS"], L["instructions"]["checks"], 4 + len(years))
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 48
    ws.cell(spec.YEAR_ROW, 1, L["year"]).font = Font(bold=True)
    for i, y in enumerate(years):
        c = ws.cell(spec.YEAR_ROW, spec.FIRST_DATA_COL + i, y)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = BLUE
        ws.column_dimensions[get_column_letter(spec.FIRST_DATA_COL + i)].width = 12
    for item in checks_layout(years):
        r, key = item["row"], item["key"]
        lab_key = "STATUS" if key.startswith("STATUS") else key
        ws.cell(r, 1, key).font = Font(size=9, color="808080")
        ws.cell(r, 2, L["checks"][lab_key])
        ws.cell(r, 3, item["level"])
        ws.cell(r, 4, code_label(lang, item["level"])).font = Font(size=9)
        for y, f in item["formulas"].items():
            c = ws.cell(r, spec.FIRST_DATA_COL + years.index(y), f)
            c.border = BOX
            c.number_format = "#,##0"
            if key.startswith("STATUS"):
                c.alignment = Alignment(horizontal="center")
                c.font = Font(bold=True)
    last = get_column_letter(spec.FIRST_DATA_COL + len(years) - 1)
    rng = f"E{spec.FIRST_DATA_ROW}:{last}{spec.FIRST_DATA_ROW + 30}"
    ws.conditional_formatting.add(rng, FormulaRule(formula=[f'E{spec.FIRST_DATA_ROW}="CHECK"'], fill=RED))
    ws.conditional_formatting.add(rng, FormulaRule(formula=[f'E{spec.FIRST_DATA_ROW}="OK"'], fill=GREEN))
    ws.protection.sheet = True


def write_template(path, cover: dict, years: list[int], values: dict | None = None,
                   lang: str = "en", metadata: dict | None = None,
                   new_years: list[int] | None = None) -> Path:
    """Build one country workbook.

    values: {(table, dim1, dim2, sex, year): number or code}
    metadata: {table: {SOURCE:..., REF_DATE:..., COVERAGE:..., NOTES:...}}
    """
    L = labels(lang)
    new_years = new_years or []
    wb = Workbook()
    ws = wb.active
    ws.title = "COVER"
    _header(ws, L["titles"]["COVER"], "", 3)
    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 40
    ws.column_dimensions["C"].width = 36
    for i, key in enumerate(spec.COVER_FIELDS):
        r = spec.FIRST_DATA_ROW + i
        ws.cell(r, 1, key).font = Font(size=9, color="808080")
        ws.cell(r, 2, L["cover"][key]).font = Font(bold=True)
        v = cover.get(key)
        c = ws.cell(r, 3, v)
        c.border = BOX
        c.protection = Protection(locked=False)
    ws.protection.sheet = True

    ws = wb.create_sheet("METADATA")
    _header(ws, L["titles"]["METADATA"], "", 5)
    heads = ["TABLE"] + spec.METADATA_FIELDS
    for j, h in enumerate(heads):
        c = ws.cell(spec.SEX_ROW, 1 + j, L["metadata"][h])
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = BLUE
        ws.column_dimensions[get_column_letter(1 + j)].width = 14 if j == 0 else 30
    tables = [s.name for s in spec.DATA_SHEETS if s.editable]
    for i, t in enumerate(tables):
        r = spec.FIRST_DATA_ROW + i
        ws.cell(r, 1, t).font = Font(bold=True)
        for j, field in enumerate(spec.METADATA_FIELDS):
            c = ws.cell(r, 2 + j, (metadata or {}).get(t, {}).get(field))
            c.border = BOX
            c.protection = Protection(locked=False)
    ws.protection.sheet = True

    for sh in spec.DATA_SHEETS:
        write_data_sheet(wb, sh, years, values, lang, new_years)
    write_checks_sheet(wb, years, lang)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def values_from_frame(df) -> dict:
    """Tidy observations (reader/consolidated format) -> writer values dict."""
    out = {}
    for r in df.itertuples(index=False):
        sh = spec.SHEETS.get(r.table)
        if sh is None:
            continue
        dims = [getattr(r, d) for d in sh.dims]
        d1, d2 = dims[0], (dims[1] if len(dims) > 1 else None)
        sex = r.sex if sh.by_sex else None
        v = r.value if r.value == r.value else (r.status if r.status in spec.MISSING_CODES else None)
        if v is not None and not isinstance(v, str) and float(v).is_integer() and r.table != "FIN":
            v = int(v)
        out[(r.table, d1, d2, sex, int(r.year))] = v
    return out
