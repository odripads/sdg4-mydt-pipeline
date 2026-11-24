"""Prepare next cycle's templates and test them.

update_template: add the new reference year, keep a rolling window of years,
pre-fill earlier years from the validated database and population from the
reference file, in any of the five languages.

test_template: functional test of a built workbook. Checks the year headers,
that every CHECKS formula points at the right ranges, that data validation and
protection are in place, and that pre-filled values read back exactly. If
LibreOffice is installed, it also recalculates the workbook and compares the
Excel formulas' results with the Python checks.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from . import spec
from .reader import read_template
from .template import checks_layout, values_from_frame, write_template


def update_template(obs: pd.DataFrame, pop: pd.DataFrame, cover: dict, survey_year: int,
                    out_path, lang="en", window: int = 5, metadata: dict | None = None) -> Path:
    new_year = survey_year - 1                     # survey year t collects data for t-1
    years = list(range(new_year - window + 1, new_year + 1))
    o = obs[(obs.iso3 == cover["ISO3"]) & obs.year.isin(years) & (obs.table != "POP")]
    o = o[o.value.notna() | o.status.isin(list(spec.MISSING_CODES))]
    p = pop[(pop.iso3 == cover["ISO3"]) & pop.year.isin(years)].assign(
        table="POP", level=None, grade=None, item=None, status="")
    values = values_from_frame(pd.concat([o, p], ignore_index=True))
    cover = {**cover, "SURVEY_YEAR": survey_year, "LANG": lang, "SUBMIT_DATE": None}
    return write_template(out_path, cover, years, values, lang, metadata, new_years=[new_year])


def test_template(path, expected_years: list[int] | None = None,
                  expected_values: dict | None = None, recalc: bool = True) -> pd.DataFrame:
    path = Path(path)
    res = []
    ok = lambda name, passed, detail="": res.append({"test": name, "passed": bool(passed), "detail": detail})
    wb = load_workbook(path)

    needed = ["COVER", "METADATA", *spec.SHEETS, "CHECKS"]
    missing = [s for s in needed if s not in wb.sheetnames]
    ok("all sheets present", not missing, ", ".join(missing))

    sub = read_template(path)
    years = sub.years
    if expected_years:
        ok("year columns", years == expected_years, f"found {years}")
    ok("years consecutive", years == list(range(years[0], years[-1] + 1)), f"{years}")

    ws = wb["CHECKS"]
    bad = []
    for item in checks_layout(years):
        for y, f in item["formulas"].items():
            got = ws.cell(item["row"], spec.FIRST_DATA_COL + years.index(y)).value
            if got != f:
                bad.append(f"{item['key']} {item['level']} {y}: {got} != {f}")
    ok("CHECKS formulas reference correct ranges", not bad, "; ".join(bad[:3]))

    for sh in spec.DATA_SHEETS:
        w = wb[sh.name]
        if sh.editable:
            dv = w.data_validations.dataValidation
            ok(f"{sh.name}: data validation on entry cells", len(dv) >= 1)
            c = w.cell(spec.FIRST_DATA_ROW, spec.FIRST_DATA_COL)
            ok(f"{sh.name}: entry cells unlocked", not c.protection.locked)
        else:
            c = w.cell(spec.FIRST_DATA_ROW, spec.FIRST_DATA_COL)
            ok(f"{sh.name}: pre-filled sheet locked", w.protection.sheet and c.protection.locked)

    if expected_values:
        got = values_from_frame(sub.data[sub.data.value.notna() | sub.data.status.isin(list(spec.MISSING_CODES))])
        diff = [k for k, v in expected_values.items() if got.get(k) != v]
        ok("pre-filled values read back exactly", not diff, f"{len(diff)} differ, e.g. {diff[:2]}")

    if recalc and shutil.which("soffice"):
        res.extend(recalc_check(path, sub))
    return pd.DataFrame(res)


def recalc_check(path: Path, sub) -> list[dict]:
    """Recalculate in LibreOffice and compare CHECKS results with Python sums."""
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run(["soffice", "--headless", "--calc", "--convert-to", "xlsx", "--outdir", tmp, str(path)],
                           capture_output=True, text=True, timeout=180)
        conv = Path(tmp) / path.name
        if r.returncode != 0 or not conv.exists():
            return [{"test": "LibreOffice recalculation", "passed": False, "detail": r.stderr[-200:]}]
        ws = load_workbook(conv, data_only=True)["CHECKS"]
        d = sub.data[sub.data.value.notna()]
        bad = []
        for item in checks_layout(sub.years):
            if item["key"] not in ("AGE_TOT", "GRADE_TOT"):
                continue
            table = "ENRL_AGE" if item["key"] == "AGE_TOT" else "ENRL_GRADE"
            for y in sub.years:
                excel = ws.cell(item["row"], spec.FIRST_DATA_COL + sub.years.index(y)).value or 0
                py = d[(d.table == table) & (d.level == item["level"]) & (d.sex == "T") & (d.year == y)].value.sum()
                if abs(float(excel) - py) > 0.5:
                    bad.append(f"{item['key']} {item['level']} {y}: Excel {excel} vs Python {py}")
        out.append({"test": "Excel formulas agree with Python (LibreOffice recalculation)",
                    "passed": not bad, "detail": "; ".join(bad[:3])})
    return out
