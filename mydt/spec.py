"""Layout specification for the MYDT-style templates.

Everything that knows *where* a number lives in the workbook is defined here.
The writer (template.py), the reader (reader.py) and the functional tests all
use this one spec, so a change to the template layout is made in one place.

Sheet names and row/column codes are language-neutral (ENRL_AGE, L1, F...).
Only the visible labels are translated, so one reader handles every language.
"""
from __future__ import annotations

from dataclasses import dataclass

from openpyxl.utils import get_column_letter

LEVELS = ["L1", "L2", "L3"]
LEVEL_OFFSET = {"L1": 0, "L2": 6, "L3": 9}          # years after primary entrance age
DURATION = {"L1": 6, "L2": 3, "L3": 3}
GRADES = {
    "L1": [f"G{i}" for i in range(1, 7)],
    "L2": ["G7", "G8", "G9"],
    "L3": ["G10", "G11", "G12"],
}
AGES = ["<5"] + [str(a) for a in range(5, 21)] + ["21+", "UNK"]
POP_AGES = [str(a) for a in range(0, 25)]
SEXES = ["F", "M", "T"]
TEACHER_ITEMS = ["TCH", "TCH_TRAINED"]
FIN_ITEMS = ["XEXP_L1", "XEXP_L2", "XEXP_L3", "XEXP_EDU", "XEXP_GOV", "GDP"]

# UIS-style observation codes accepted in place of a number
MISSING_CODES = {
    "m": "missing",
    "a": "not applicable",
    "x": "included in another category",
    "n": "nil or negligible",
}

COVER_FIELDS = [
    "ISO3", "COUNTRY", "SURVEY_YEAR", "LANG", "CURRENCY", "ENTRANCE_AGE",
    "RESP_NAME", "RESP_EMAIL", "SUBMIT_DATE",
]
METADATA_FIELDS = ["SOURCE", "REF_DATE", "COVERAGE", "NOTES"]

TITLE_ROW = 1
INSTR_ROW = 2
YEAR_ROW = 4
SEX_ROW = 5
FIRST_DATA_ROW = 6
FIRST_DATA_COL = 5          # column E; A-D hold codes and labels


@dataclass(frozen=True)
class SheetSpec:
    name: str                # worksheet name == table code
    dims: tuple[str, ...]    # row dimensions; codes go in columns A and C
    by_sex: bool
    editable: bool           # False = pre-filled reference data (locked)

    def rows(self) -> list[dict]:
        if self.name == "ENRL_AGE":
            return [{"level": lv, "age": a} for lv in LEVELS for a in AGES]
        if self.name in ("ENRL_GRADE", "REPEATERS"):
            return [{"level": lv, "grade": g} for lv in LEVELS for g in GRADES[lv]]
        if self.name == "TEACHERS":
            return [{"level": lv, "item": it} for lv in LEVELS for it in TEACHER_ITEMS]
        if self.name == "POP":
            return [{"age": a} for a in POP_AGES]
        if self.name == "FIN":
            return [{"item": it} for it in FIN_ITEMS]
        raise KeyError(self.name)

    @property
    def sexes(self) -> list[str | None]:
        return SEXES if self.by_sex else [None]

    def row_of(self, **dims) -> int:
        for i, r in enumerate(self.rows()):
            if all(r.get(k) == v for k, v in dims.items()):
                return FIRST_DATA_ROW + i
        raise KeyError((self.name, dims))

    def rows_where(self, **dims) -> list[int]:
        return [FIRST_DATA_ROW + i for i, r in enumerate(self.rows())
                if all(r.get(k) == v for k, v in dims.items())]

    def col_of(self, years: list[int], year: int, sex: str | None) -> int:
        i = years.index(year)
        j = self.sexes.index(sex)
        return FIRST_DATA_COL + i * len(self.sexes) + j

    def col_letter(self, years, year, sex) -> str:
        return get_column_letter(self.col_of(years, year, sex))

    def last_col(self, years) -> int:
        return FIRST_DATA_COL + len(years) * len(self.sexes) - 1

    def last_row(self) -> int:
        return FIRST_DATA_ROW + len(self.rows()) - 1


DATA_SHEETS = [
    SheetSpec("ENRL_AGE", ("level", "age"), True, True),
    SheetSpec("ENRL_GRADE", ("level", "grade"), True, True),
    SheetSpec("REPEATERS", ("level", "grade"), True, True),
    SheetSpec("TEACHERS", ("level", "item"), True, True),
    SheetSpec("FIN", ("item",), False, True),
    SheetSpec("POP", ("age",), True, False),
]
SHEETS = {s.name: s for s in DATA_SHEETS}


def official_ages(entrance_age: int, level: str) -> list[int]:
    start = entrance_age + LEVEL_OFFSET[level]
    return list(range(start, start + DURATION[level]))


def age_to_int(code: str) -> int | None:
    """'7' -> 7; aggregate or unknown age codes -> None."""
    return int(code) if code.isdigit() else None
