"""Synthetic countries for demonstrating and testing the pipeline.

All countries, names and numbers are fictional (ISO 3166 user-assigned codes
XAA-XAJ). The data are internally consistent by construction: population
follows cohorts, and enrolment is built cell by cell in a grade x age matrix,
so age and grade tables agree. Known errors are then injected into some
countries, and the answer key records which check should catch each one.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import spec
from .reader import OBS_COLUMNS
from .template import values_from_frame, write_template

COUNTRIES = [
    # iso3, name, template language, entrance age, currency
    ("XAA", "Arcadia", "en", 6, "ARD"),
    ("XAB", "Borealia", "fr", 6, "BRF"),
    ("XAC", "Corvina", "es", 7, "CVP"),
    ("XAD", "Dunmore", "en", 5, "DND"),
    ("XAE", "Esterra", "pt", 6, "ESR"),
    ("XAF", "Falkovia", "ru", 7, "FKR"),
    ("XAG", "Galdera", "fr", 6, "GDF"),
    ("XAH", "Halvania", "es", 6, "HVP"),
]
MINED = [("XAI", "Kestrel Islands", 6), ("XAJ", "Lumeria", 5)]
SURVEY_YEAR = 2026
YEARS = list(range(2021, 2026))
POP_YEARS = list(range(2019, 2028))


def _age_code(a: int) -> str:
    return "<5" if a < 5 else ("21+" if a >= 21 else str(a))


def make_population(iso3, rng):
    births = rng.uniform(60_000, 400_000)
    growth = rng.uniform(0.99, 1.025)
    fshare = rng.uniform(0.485, 0.495)
    rows = []
    for y in POP_YEARS:
        for a in range(0, 25):
            t = births * growth ** (y - a - 2000) * 0.997 ** a
            t = round(t * rng.normal(1, 0.003))
            f = round(t * fshare)
            for sx, v in (("F", f), ("M", t - f), ("T", t)):
                rows.append({"iso3": iso3, "age": str(a), "sex": sx, "year": y, "value": float(v)})
    return pd.DataFrame(rows)


def _rates(e, rng):
    """Participation rate by (level, single age) at year 2021, before trend."""
    r1, r2, r3 = rng.uniform(0.80, 0.97), rng.uniform(0.60, 0.92), rng.uniform(0.40, 0.82)
    rates = {}
    for a in range(0, 25):
        k = a - e
        rates[("L1", a)] = (r1 if 0 <= k < 6 else
                            {-1: 0.03, 6: 0.08, 7: 0.04, 8: 0.02}.get(k, 0.0))
        rates[("L2", a)] = (r2 if 6 <= k < 9 else
                            {5: 0.02, 9: 0.10, 10: 0.05, 11: 0.02}.get(k, 0.0))
        rates[("L3", a)] = (r3 if 9 <= k < 12 else
                            {8: 0.02, 12: 0.12, 13: 0.06, 14: 0.03, 15: 0.01}.get(k, 0.0))
    return rates


def _grade_split(level, a, e):
    """Share of children of single age a in each grade of a level."""
    grades = spec.GRADES[level]
    gi = a - (e + spec.LEVEL_OFFSET[level])
    n = len(grades)
    if gi < 0:
        return {grades[0]: 1.0}
    if gi >= n:
        return {grades[-1]: 0.7, grades[-2]: 0.3}
    split = {grades[gi]: 0.85}
    split[grades[max(gi - 1, 0)]] = split.get(grades[max(gi - 1, 0)], 0) + 0.10
    split[grades[max(gi - 2, 0)]] = split.get(grades[max(gi - 2, 0)], 0) + 0.05
    return split


def make_country(iso3, name, lang, e, currency, seed):
    rng = np.random.default_rng(seed)
    pop = make_population(iso3, rng)
    P = pop.set_index(["age", "sex", "year"]).value
    rates = _rates(e, rng)
    f_adj = {lv: rng.uniform(0.93, 1.04) for lv in spec.LEVELS}
    rep_rate = {lv: rng.uniform(0.02, 0.08) for lv in spec.LEVELS}
    ptr = {"L1": rng.uniform(20, 42), "L2": rng.uniform(15, 28), "L3": rng.uniform(12, 24)}
    tfem = {"L1": 0.65, "L2": 0.52, "L3": 0.45}
    trained = {lv: rng.uniform(0.70, 0.97) for lv in spec.LEVELS}

    def _rate(lv, a, sx, trend):
        """Participation by level; total across levels capped below 100% of the age group."""
        r = {l: (rates[(l, a)] + trend if rates[(l, a)] else 0) * (f_adj[l] if sx == "F" else 1.0)
             for l in spec.LEVELS}
        tot = sum(r.values())
        return r[lv] * (min(1.0, 0.96 / tot) if tot else 0)

    recs = []

    def add(table, sex, year, value, **dims):
        recs.append({"iso3": iso3, "survey_year": SURVEY_YEAR, "table": table,
                     "level": dims.get("level"), "age": dims.get("age"),
                     "grade": dims.get("grade"), "item": dims.get("item"),
                     "sex": sex, "year": year, "value": float(value), "status": "",
                     "raw": None, "cell": None, "source": "country_template"})

    for y in YEARS:
        trend = 0.005 * (y - YEARS[0])
        for lv in spec.LEVELS:
            cells = {}   # (sex, grade, age_code) -> count
            for sx in ("F", "M"):
                for a in range(0, 25):
                    rate = _rate(lv, a, sx, trend)
                    if rate == 0:
                        continue
                    n = P[(str(a), sx, y)] * rate * rng.normal(1, 0.01)
                    for g, share in _grade_split(lv, a, e).items():
                        k = (sx, g, _age_code(a))
                        cells[k] = cells.get(k, 0) + n * share
                tot = sum(v for (s, _, _), v in cells.items() if s == sx)
                mid = spec.GRADES[lv][len(spec.GRADES[lv]) // 2]
                cells[(sx, mid, "UNK")] = tot * 0.003
            cells = {k: round(v) for k, v in cells.items()}

            for sx in ("F", "M", "T"):
                pick = (lambda s: s in ("F", "M")) if sx == "T" else (lambda s, sx=sx: s == sx)
                for ac in spec.AGES:
                    add("ENRL_AGE", sx, y, sum(v for (s, g, a), v in cells.items() if pick(s) and a == ac),
                        level=lv, age=ac)
                for g in spec.GRADES[lv]:
                    add("ENRL_GRADE", sx, y, sum(v for (s, gg, a), v in cells.items() if pick(s) and gg == g),
                        level=lv, grade=g)
            # repeaters
            for g in spec.GRADES[lv]:
                fm = {}
                for sx in ("F", "M"):
                    enr = sum(v for (s, gg, a), v in cells.items() if s == sx and gg == g)
                    fm[sx] = round(enr * rep_rate[lv] * rng.uniform(0.8, 1.2))
                for sx, v in (("F", fm["F"]), ("M", fm["M"]), ("T", fm["F"] + fm["M"])):
                    add("REPEATERS", sx, y, v, level=lv, grade=g)
            # teachers
            enr_t = sum(cells.values())
            t_tot = round(enr_t / ptr[lv] * (1 + 0.01 * (y - YEARS[0])))
            t_f = round(t_tot * tfem[lv])
            tr = min(0.99, trained[lv] + trend)
            for item, mult in (("TCH", 1.0), ("TCH_TRAINED", tr)):
                f = round(t_f * mult)
                m = round((t_tot - t_f) * mult)
                for sx, v in (("F", f), ("M", m), ("T", f + m)):
                    add("TEACHERS", sx, y, v, level=lv, item=item)
        # finance (millions of national currency)
        gdp = 40_000 * (seed % 7 + 1) * 1.04 ** (y - YEARS[0])
        gov = gdp * 0.25
        edu = gov * (0.13 + 0.002 * (seed % 5))
        fin = {"GDP": gdp, "XEXP_GOV": gov, "XEXP_EDU": edu,
               "XEXP_L1": edu * 0.40, "XEXP_L2": edu * 0.25, "XEXP_L3": edu * 0.18}
        for it, v in fin.items():
            add("FIN", None, y, round(v, 1), item=it)

    for r in pop[pop.year.isin(YEARS)].itertuples():
        add("POP", r.sex, r.year, r.value, age=r.age)

    obs = pd.DataFrame(recs, columns=OBS_COLUMNS)
    cover = {"ISO3": iso3, "COUNTRY": name, "SURVEY_YEAR": SURVEY_YEAR, "LANG": lang,
             "CURRENCY": currency, "ENTRANCE_AGE": e,
             "RESP_NAME": "Statistics Unit, Ministry of Education (fictional)",
             "RESP_EMAIL": f"stats@moe.{iso3.lower()}.example", "SUBMIT_DATE": "2026-04-15"}
    metadata = {t: {"SOURCE": "Annual school census (EMIS)", "REF_DATE": "Start of school year",
                    "COVERAGE": "Public and private", "NOTES": None}
                for t in ("ENRL_AGE", "ENRL_GRADE", "REPEATERS", "TEACHERS")}
    metadata["FIN"] = {"SOURCE": "Ministry of Finance, executed budget", "REF_DATE": "Fiscal year",
                       "COVERAGE": "Central and local government", "NOTES": None}
    return obs, pop, cover, metadata


# ---------------------------------------------------------------- error injection
def inject_errors(iso3, values, metadata, cover):
    """Plant realistic data-entry problems. Returns answer-key rows."""
    key = []

    def bump(k, delta):
        values[k] = values[k] + delta

    if iso3 == "XAB":   # grade table does not add up to age table
        bump(("ENRL_GRADE", "L2", "G8", "F", 2024), 1500)
        bump(("ENRL_GRADE", "L2", "G8", "T", 2024), 1500)
        key.append((iso3, "R05_AGE_GRADE", "L2 2024: grade table 1,500 higher than age table"))
    if iso3 == "XAC":   # F + M != T
        bump(("ENRL_AGE", "L1", "8", "T", 2025), 230)
        key.append((iso3, "R04_SEX_SUM", "ENRL_AGE L1 age 8, 2025: T is not F + M"))
        key.append((iso3, "R05_AGE_GRADE", "same cell makes age table total disagree with grade table"))
    if iso3 == "XAD":   # negative number and free text in numeric cells
        values[("ENRL_GRADE", "L3", "G11", "M", 2023)] = -412
        values[("TEACHERS", "L1", "TCH", "F", 2025)] = "approx. 5 200"
        key.append((iso3, "R02_NEGATIVE", "ENRL_GRADE L3 G11 M 2023 is negative"))
        key.append((iso3, "R01_INVALID", "TEACHERS L1 TCH F 2025 contains text"))
        key.append((iso3, "R04_SEX_SUM", "consequence of the negative value: F + M != T"))
        key.append((iso3, "R05_AGE_GRADE", "consequence of the negative value: grade total too low"))
        key.append((iso3, "R09_REPEATERS", "consequence of the negative value: repeaters above (negative) pupils"))
    if iso3 == "XAE":   # one age row typed with a missing digit: cohort break
        for sx in ("F", "M", "T"):
            k = ("ENRL_AGE", "L1", "9", sx, 2024)
            values[k] = round(values[k] / 10)
        key.append((iso3, "R06_COHORT", "ENRL_AGE L1 age 9, 2024 is a tenth of the cohort"))
        key.append((iso3, "R05_AGE_GRADE", "consequence: age table no longer matches grade table"))
        key.append((iso3, "R15_REVISION", "consequence: 2024 primary indicators fall sharply vs last release"))
    if iso3 == "XAF":   # enrolment exceeds population (double counting)
        for sx in ("F", "M", "T"):
            k = ("ENRL_AGE", "L1", "8", sx, 2025)
            values[k] = values[k] * 2
            kg = ("ENRL_GRADE", "L1", "G2", sx, 2025)
            values[kg] = values[kg] + values[k] / 2
        key.append((iso3, "R07_POP_EXCEEDED", "L1 age 8, 2025 doubled: enrolment above population"))
        key.append((iso3, "R06_COHORT", "consequence: age 7 -> 8 cohort doubles"))
        key.append((iso3, "R14_IND_RANGE", "consequence: primary net enrolment rate above 100%"))
        key.append((iso3, "R08_YOY", "consequence: primary enrolment jumps over 20% in 2025"))
    if iso3 == "XAG":   # missing metadata, expenditure by level above total
        metadata.pop("ENRL_GRADE", None)
        values[("FIN", "XEXP_L1", None, None, 2025)] = values[("FIN", "XEXP_EDU", None, None, 2025)] * 0.9
        key.append((iso3, "R11_METADATA", "No source given for ENRL_GRADE"))
        key.append((iso3, "R10_FIN", "2025 expenditure by level exceeds total education expenditure"))
    if iso3 == "XAH":   # repeaters above enrolment, sudden jump, missing codes
        values[("REPEATERS", "L1", "G3", "T", 2025)] = values[("ENRL_GRADE", "L1", "G3", "T", 2025)] + 10
        values[("REPEATERS", "L1", "G3", "F", 2025)] = values[("ENRL_GRADE", "L1", "G3", "F", 2025)] + 10
        values[("REPEATERS", "L1", "G3", "M", 2025)] = values[("ENRL_GRADE", "L1", "G3", "M", 2025)]
        for k in list(values):
            if k[0] in ("ENRL_AGE", "ENRL_GRADE") and k[1] == "L3" and k[4] == 2025 and k[3] in ("F", "M"):
                values[k] = round(values[k] * 1.45)
        for k in list(values):
            if k[0] in ("ENRL_AGE", "ENRL_GRADE") and k[1] == "L3" and k[4] == 2025 and k[3] == "T":
                values[k] = values[(k[0], k[1], k[2], "F", k[4])] + values[(k[0], k[1], k[2], "M", k[4])]
        for sx in ("F", "M", "T"):
            values[("TEACHERS", "L3", "TCH_TRAINED", sx, 2021)] = "m"
        key.append((iso3, "R09_REPEATERS", "L1 G3 2025: more repeaters than pupils"))
        key.append((iso3, "R08_YOY", "L3 enrolment up 45% in 2025"))
        key.append((iso3, "R05_AGE_GRADE", "consequence: rounding the inflated rows leaves totals 1-2 pupils apart"))
    return key


def to_mined_csv(obs, iso3, name, path):
    """Mimic data mined from a national statistical yearbook: wide by year, level totals only."""
    t = obs[obs.table == "ENRL_AGE"].groupby(["level", "sex", "year"]).value.sum().reset_index()
    w = t.pivot_table(index=["level", "sex"], columns="year", values="value").reset_index()
    w.insert(0, "series", "Enrolment")
    w.insert(0, "country_name", name)
    w.insert(0, "country_code", iso3)
    w["source"] = f"{name} National Statistical Yearbook 2025, table 4.2"
    w.columns = [str(c) for c in w.columns]
    w.to_csv(path, index=False)


def generate(root: Path) -> dict:
    """Write submissions, mined files and reference data under root/data."""
    from .indicators import compute

    data = Path(root) / "data"
    subs, mined, ref = data / "submissions", data / "mined", data / "reference"
    for d in (subs, mined, ref):
        d.mkdir(parents=True, exist_ok=True)
    pops, key, clean, countries = [], [], [], []
    for i, (iso3, name, lang, e, cur) in enumerate(COUNTRIES):
        obs, pop, cover, meta = make_country(iso3, name, lang, e, cur, seed=100 + i)
        clean.append(obs)
        pops.append(pop)
        countries.append({"iso3": iso3, "name": name, "entrance_age": e, "channel": "template", "lang": lang})
        values = values_from_frame(obs)
        key += inject_errors(iso3, values, meta, cover)
        write_template(subs / f"{iso3}_MYDT_{SURVEY_YEAR}.xlsx", cover, YEARS, values, lang, meta,
                       new_years=[YEARS[-1]])
    for j, (iso3, name, e) in enumerate(MINED):
        obs, pop, *_ = make_country(iso3, name, "en", e, "XXX", seed=200 + j)
        clean.append(obs)
        pops.append(pop)
        countries.append({"iso3": iso3, "name": name, "entrance_age": e, "channel": "mined", "lang": "en"})
        to_mined_csv(obs, iso3, name, mined / f"{iso3}_yearbook.csv")

    pop_all = pd.concat(pops, ignore_index=True)
    pop_all.to_csv(ref / "population.csv", index=False)
    cdf = pd.DataFrame(countries)
    cdf.to_csv(ref / "countries.csv", index=False)

    # previous data release: indicators up to 2024, with small revisions
    ent = dict(zip(cdf.iso3, cdf.entrance_age))
    prev = compute(pd.concat(clean), pop_all, ent)
    prev = prev[prev.year <= 2024].copy()
    rng = np.random.default_rng(7)
    prev["value"] = prev.value * rng.uniform(0.995, 1.005, len(prev))
    m = (prev.iso3 == "XAA") & (prev.indicator == "GER_L2") & (prev.year == 2023)
    prev.loc[m, "value"] = prev.loc[m, "value"] - 6.0   # a large revision to explain
    key.append(("XAA", "R15_REVISION", "previous release GER_L2 2023 was 6 points lower"))
    prev.drop(columns="source").to_csv(ref / "previous_release.csv", index=False)
    pd.DataFrame(key, columns=["iso3", "expected_rule", "description"]).to_csv(
        ref / "answer_key.csv", index=False)
    return {"submissions": subs, "mined": mined, "reference": ref, "errors": len(key)}
