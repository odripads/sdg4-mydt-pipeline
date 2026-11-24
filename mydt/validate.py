"""Validation rules for country submissions.

Each rule returns flags in one shape, so the QC log, the country checklist,
the review report and the app all read the same table. Thresholds live in
config/rules.yaml.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from . import spec
from .reader import Submission

RULES_PATH = Path(__file__).resolve().parent.parent / "config" / "rules.yaml"
FLAG_COLUMNS = ["iso3", "rule", "severity", "table", "level", "sex", "year",
                "cell", "value", "expected", "message"]

RULE_TITLES = {
    "R00_STRUCTURE": "Cover page and sheets complete",
    "R01_INVALID": "Only numbers or m/a/x/n codes in data cells",
    "R02_NEGATIVE": "No negative values",
    "R03_BLANK": "No blank cells (use a code if a value is missing)",
    "R04_SEX_SUM": "Female + Male = Total",
    "R05_AGE_GRADE": "Age table and grade table give the same totals",
    "R06_COHORT": "Age cohorts move consistently from year to year",
    "R07_POP_EXCEEDED": "Enrolment at each age does not exceed population",
    "R08_YOY": "No implausible year-on-year change in enrolment",
    "R09_REPEATERS": "Repeaters do not exceed enrolment",
    "R10_FIN": "Expenditure components consistent with totals",
    "R11_METADATA": "Source given for every table with data",
    "R12_TEACHERS": "Trained teachers do not exceed total teachers",
    "R13_POP_CHANGED": "Pre-filled population not modified",
    "R14_IND_RANGE": "Indicators within plausible ranges",
    "R15_REVISION": "Large revisions to previously published indicators",
}


def load_rules(path=RULES_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _flag(iso3, rule, severity, message, table=None, level=None, sex=None, year=None,
          cell=None, value=None, expected=None):
    return {"iso3": iso3, "rule": rule, "severity": severity, "table": table, "level": level,
            "sex": sex, "year": year, "cell": cell, "value": value, "expected": expected,
            "message": message}


def _range(cells: pd.Series) -> str:
    """Sheet!E6:E24 style reference covering a group of cells."""
    cells = [c for c in cells if isinstance(c, str)]
    if not cells:
        return ""
    sheet = cells[0].split("!")[0]
    return f"{sheet}!{cells[0].split('!')[1]}:{cells[-1].split('!')[1]}" if len(cells) > 1 else cells[0]


def validate_submission(sub: Submission, ref_pop: pd.DataFrame | None = None,
                        rules: dict | None = None, expected_survey_year: int | None = None) -> pd.DataFrame:
    rules = rules or load_rules()
    iso3 = sub.key
    d = sub.data
    F = []

    # R00 structure
    if not sub.iso3:
        F.append(_flag(iso3, "R00_STRUCTURE", "ERROR", "Country code (ISO3) missing or not three letters on COVER", cell="COVER!C6"))
    sy = sub.cover.get("SURVEY_YEAR")
    if expected_survey_year and str(sy) != str(expected_survey_year):
        F.append(_flag(iso3, "R00_STRUCTURE", "ERROR",
                       f"Survey year on COVER is {sy}, expected {expected_survey_year}", cell="COVER!C8"))
    for s in sub.missing_sheets:
        F.append(_flag(iso3, "R00_STRUCTURE", "ERROR", f"Sheet {s} missing from workbook", table=s))
    try:
        entrance = int(sub.cover.get("ENTRANCE_AGE"))
    except (TypeError, ValueError):
        entrance = None
        F.append(_flag(iso3, "R00_STRUCTURE", "ERROR", "Official primary entrance age missing", cell="COVER!C11"))

    editable = d[d.table != "POP"]

    # R01 invalid, R02 negative
    for r in editable[editable.status == "invalid"].itertuples():
        F.append(_flag(iso3, "R01_INVALID", "ERROR", f"Text '{r.raw}' where a number or code is expected",
                       r.table, r.level, r.sex, r.year, r.cell, r.raw))
    for r in editable[editable.value < 0].itertuples():
        F.append(_flag(iso3, "R02_NEGATIVE", "ERROR", "Negative value",
                       r.table, r.level, r.sex, r.year, r.cell, r.value))

    # R03 blanks, summarised by table and year
    bl = editable[editable.status == "blank"]
    for (t, y), g in bl.groupby(["table", "year"]):
        F.append(_flag(iso3, "R03_BLANK", "WARNING",
                       f"{len(g)} blank cell(s); enter a value or m/a/x/n (first: {g.cell.iloc[0]})",
                       t, year=y, cell=g.cell.iloc[0], value=len(g)))

    num = d[d.value.notna()]

    # R04 F + M = T
    tol = rules["sex_sum_tolerance"]
    for sh in spec.DATA_SHEETS:
        if not sh.by_sex or not sh.editable:
            continue
        t = num[num.table == sh.name]
        keys = list(sh.dims) + ["year"]
        piv = t.pivot_table(index=keys, columns="sex", values="value", aggfunc="first")
        cells = t[t.sex == "T"].set_index(keys).cell
        if not {"F", "M", "T"} <= set(piv.columns):
            continue
        piv = piv.dropna(subset=["F", "M", "T"])
        bad = piv[(piv["F"] + piv["M"] - piv["T"]).abs() > tol]
        for idx, r in bad.iterrows():
            ix = dict(zip(keys, idx))
            F.append(_flag(iso3, "R04_SEX_SUM", "ERROR",
                           f"Female ({r['F']:,.0f}) + Male ({r['M']:,.0f}) = {r['F'] + r['M']:,.0f}, but Total is {r['T']:,.0f}",
                           sh.name, ix.get("level"), "T", ix["year"], cells.get(idx), r["T"], r["F"] + r["M"]))

    # R05 age vs grade totals
    a = num[num.table == "ENRL_AGE"].groupby(["level", "sex", "year"]).agg(v=("value", "sum"), c=("cell", _range))
    g = num[num.table == "ENRL_GRADE"].groupby(["level", "sex", "year"]).agg(v=("value", "sum"), c=("cell", _range))
    ag = a.add_suffix("_a").join(g.add_suffix("_g"), how="inner")
    for (lv, sx, y), r in ag[(ag.v_a - ag.v_g).abs() > rules["age_grade_tolerance"]].iterrows():
        F.append(_flag(iso3, "R05_AGE_GRADE", "ERROR",
                       f"{lv}, sex {sx}: total by age {r.v_a:,.0f} vs total by grade {r.v_g:,.0f} (difference {r.v_a - r.v_g:+,.0f})",
                       "ENRL_AGE/ENRL_GRADE", lv, sx, y, f"{r.c_a} vs {r.c_g}", r.v_a, r.v_g))

    # single-age totals across levels (T)
    age_t = num[(num.table == "ENRL_AGE") & (num.sex == "T") & num.age.str.isdigit()]
    by_age = age_t.groupby(["age", "year"]).value.sum()
    cell_of = age_t.groupby(["age", "year"]).cell.apply(lambda s: ", ".join(s))

    # R06 cohort
    c = rules["cohort"]
    years = sorted(num.year.unique())
    if entrance is not None:
        for age in range(entrance + c["ages_from_entrance"][0], entrance + c["ages_from_entrance"][1]):
            for y in years[:-1]:
                k0, k1 = (str(age), y), (str(age + 1), y + 1)
                if k0 in by_age and k1 in by_age and by_age[k0] >= c["min_base"]:
                    ratio = by_age[k1] / by_age[k0]
                    if not c["min_ratio"] <= ratio <= c["max_ratio"]:
                        F.append(_flag(iso3, "R06_COHORT", "WARNING",
                                       f"Age {age} in {y} ({by_age[k0]:,.0f}) -> age {age + 1} in {y + 1} "
                                       f"({by_age[k1]:,.0f}): cohort ratio {ratio:.2f}",
                                       "ENRL_AGE", None, "T", y + 1, cell_of.get(k1), round(ratio, 3),
                                       f"{c['min_ratio']}-{c['max_ratio']}"))

    # R07 enrolment above population
    if ref_pop is not None and len(ref_pop):
        rp = ref_pop[(ref_pop.iso3 == sub.iso3) & (ref_pop.sex == "T")].set_index(["age", "year"]).value
        for k, v in by_age.items():
            p = rp.get((k[0], k[1]))
            if p is not None and v > p:
                F.append(_flag(iso3, "R07_POP_EXCEEDED", "WARNING",
                               f"{v:,.0f} enrolled at age {k[0]} but population is {p:,.0f} "
                               f"({v / p:.0%})", "ENRL_AGE", None, "T", k[1], cell_of.get(k), v, p))

    # R08 year-on-year change in level totals
    lt = num[(num.table == "ENRL_AGE") & (num.sex == "T")].groupby(["level", "year"]).value.sum()
    for lv in spec.LEVELS:
        s = lt.get(lv)
        if s is None:
            continue
        ch = s.pct_change()
        for y, v in ch.items():
            if pd.notna(v) and abs(v) > rules["yoy_max_change"]:
                F.append(_flag(iso3, "R08_YOY", "WARNING",
                               f"{lv} enrolment changed {v:+.0%} from {y - 1} ({s[y - 1]:,.0f}) to {y} ({s[y]:,.0f})",
                               "ENRL_AGE", lv, "T", y, None, round(v, 3), f"±{rules['yoy_max_change']:.0%}"))

    # R09 repeaters > enrolment
    rep = num[num.table == "REPEATERS"].set_index(["level", "grade", "sex", "year"])
    enr = num[num.table == "ENRL_GRADE"].set_index(["level", "grade", "sex", "year"]).value
    for idx, r in rep.iterrows():
        e = enr.get(idx)
        if e is not None and r.value > e:
            F.append(_flag(iso3, "R09_REPEATERS", "ERROR",
                           f"{r.value:,.0f} repeaters but {e:,.0f} pupils in {idx[1]}",
                           "REPEATERS", idx[0], idx[2], idx[3], r.cell, r.value, e))

    # R10 finance
    fin = num[num.table == "FIN"].pivot_table(index="year", columns="item", values="value")
    fcell = d[d.table == "FIN"].set_index(["item", "year"]).cell
    for y, r in fin.iterrows():
        parts = sum(r.get(k, 0) for k in ("XEXP_L1", "XEXP_L2", "XEXP_L3") if pd.notna(r.get(k)))
        if pd.notna(r.get("XEXP_EDU")) and parts > r.XEXP_EDU:
            F.append(_flag(iso3, "R10_FIN", "ERROR",
                           f"Primary + secondary expenditure ({parts:,.1f}) exceeds total education "
                           f"expenditure ({r.XEXP_EDU:,.1f})", "FIN", None, None, y,
                           fcell.get(("XEXP_EDU", y)), parts, r.XEXP_EDU))
        for lo, hi in (("XEXP_EDU", "XEXP_GOV"), ("XEXP_GOV", "GDP")):
            if pd.notna(r.get(lo)) and pd.notna(r.get(hi)) and r[lo] > r[hi]:
                F.append(_flag(iso3, "R10_FIN", "ERROR", f"{lo} ({r[lo]:,.1f}) exceeds {hi} ({r[hi]:,.1f})",
                               "FIN", None, None, y, fcell.get((lo, y)), r[lo], r[hi]))

    # R11 metadata
    meta = sub.metadata.set_index("table") if len(sub.metadata) else pd.DataFrame()
    for t in num[num.table != "POP"].table.unique():
        src = meta.SOURCE.get(t) if len(meta) and "SOURCE" in meta else None
        if src is None or (isinstance(src, float) and pd.isna(src)) or not str(src).strip():
            F.append(_flag(iso3, "R11_METADATA", "WARNING", f"No data source given for table {t}",
                           "METADATA", cell="METADATA"))

    # R12 trained teachers <= teachers
    tch = num[num.table == "TEACHERS"].pivot_table(index=["level", "sex", "year"], columns="item",
                                                   values="value")
    if {"TCH", "TCH_TRAINED"} <= set(tch.columns):
        tcell = d[(d.table == "TEACHERS") & (d.item == "TCH_TRAINED")].set_index(["level", "sex", "year"]).cell
        for idx, r in tch[tch.TCH_TRAINED > tch.TCH].iterrows():
            F.append(_flag(iso3, "R12_TEACHERS", "ERROR",
                           f"{r.TCH_TRAINED:,.0f} trained teachers but {r.TCH:,.0f} teachers in total",
                           "TEACHERS", idx[0], idx[1], idx[2], tcell.get(idx), r.TCH_TRAINED, r.TCH))

    # R13 population sheet changed
    if ref_pop is not None and len(ref_pop):
        tp = num[num.table == "POP"].merge(ref_pop[ref_pop.iso3 == sub.iso3], on=["age", "sex", "year"],
                                            suffixes=("", "_ref"))
        tp = tp[(tp.value - tp.value_ref).abs() > rules["pop_tolerance"] * tp.value_ref]
        for r in tp.itertuples():
            F.append(_flag(iso3, "R13_POP_CHANGED", "WARNING", "Pre-filled population differs from UIS reference",
                           "POP", None, r.sex, r.year, r.cell, r.value, r.value_ref))

    out = pd.DataFrame(F, columns=FLAG_COLUMNS)
    out["iso3"] = iso3
    return out


def validate_indicators(ind: pd.DataFrame, rules: dict | None = None,
                        previous: pd.DataFrame | None = None) -> pd.DataFrame:
    rules = rules or load_rules()
    F = []
    sexlab = lambda sx: "" if not isinstance(sx, str) else f" ({sx})"
    for r in ind.dropna(subset=["value"]).itertuples():
        fam = r.indicator.split("_")[0]
        lo_hi = rules["indicator_ranges"].get(fam)
        if lo_hi and not lo_hi[0] <= r.value <= lo_hi[1]:
            F.append(_flag(r.iso3, "R14_IND_RANGE", "WARNING",
                           f"{r.indicator}{sexlab(r.sex)} = {r.value:.1f}, outside plausible range {lo_hi[0]}-{lo_hi[1]}",
                           "INDICATORS", r.level, r.sex, r.year, None, round(r.value, 2), f"{lo_hi[0]}-{lo_hi[1]}"))
    if previous is not None and len(previous):
        norm = lambda df: df.assign(level=df.level.fillna(""), sex=df.sex.fillna(""))
        pct = norm(ind[ind.indicator.str.match(r"^(GER|NERT|OOSR|REPP|TRTP)_") & (ind.sex == "T")])
        m = pct.merge(norm(previous), on=["iso3", "indicator", "level", "sex", "year"], suffixes=("", "_prev"))
        m = m[(m.value - m.value_prev).abs() > rules["revision_pp"]]
        for r in m.itertuples():
            F.append(_flag(r.iso3, "R15_REVISION", "INFO",
                           f"{r.indicator} {r.year} revised from {r.value_prev:.1f} to {r.value:.1f} "
                           f"({r.value - r.value_prev:+.1f} points); ask the country to explain",
                           "INDICATORS", r.level, r.sex, r.year, None, round(r.value, 2), round(r.value_prev, 2)))
    return pd.DataFrame(F, columns=FLAG_COLUMNS)
