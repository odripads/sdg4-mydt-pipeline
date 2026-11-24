"""SDG 4 indicator calculations, following UIS definitions.

Population denominators come from the reference population file (UN
estimates), not from the copy shown in the template, as in UIS practice.

Indicators
  GER_Lk      Gross enrolment ratio, level k (%)
  GPI_GER_Lk  Gender parity index of the GER (F / M)
  NERT_L1/L2  Total net enrolment rate: official-age children enrolled at that
              level or higher (%)
  OOSR_L1/L2  Out-of-school rate = 100 - NERT (%)              [SDG 4.1.4]
  REPP_Lk     Percentage of repeaters (%)
  PTR_Lk      Pupil-teacher ratio (head counts)
  TRTP_Lk     Proportion of teachers with minimum required training (%) [SDG 4.c.1]
  XGDP        Government expenditure on education as % of GDP      [SDG 1.a.2 / 4 framework]
  XGOVEXP     Government expenditure on education as % of total government expenditure
"""
from __future__ import annotations

import pandas as pd

from . import spec

IND_COLUMNS = ["iso3", "indicator", "level", "sex", "year", "value", "source"]


def official_pop(pop: pd.DataFrame, entrance: dict[str, int]) -> pd.DataFrame:
    rows = []
    p = pop.copy()
    p["age_i"] = p["age"].astype(int)
    for iso3, g in p.groupby("iso3"):
        e = entrance.get(iso3)
        if e is None:
            continue
        for lv in spec.LEVELS:
            ages = spec.official_ages(e, lv)
            s = g[g.age_i.isin(ages)].groupby(["sex", "year"]).value.sum().reset_index()
            s["iso3"], s["level"] = iso3, lv
            rows.append(s)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
        columns=["sex", "year", "value", "iso3", "level"])


def level_totals(obs: pd.DataFrame) -> pd.DataFrame:
    """Total enrolment by level from age tables (templates) or level series (mined)."""
    o = obs[obs.value.notna()]
    parts = []
    t = o[o.table == "ENRL_AGE"]
    if len(t):
        parts.append(t.groupby(["iso3", "level", "sex", "year", "source"]).value.sum().reset_index())
    m = o[o.table == "ENRL_LEVEL"]
    if len(m):
        parts.append(m[["iso3", "level", "sex", "year", "source", "value"]])
    if not parts:
        return pd.DataFrame(columns=["iso3", "level", "sex", "year", "source", "value"])
    return pd.concat(parts, ignore_index=True)


def _ind(df, name, level=None, sex_col=True):
    d = df.copy()
    d["indicator"] = name
    if level is not None:
        d["level"] = level
    if not sex_col:
        d["sex"] = None
    return d[IND_COLUMNS]


def compute(obs: pd.DataFrame, pop: pd.DataFrame, entrance: dict[str, int]) -> pd.DataFrame:
    out = []
    popoff = official_pop(pop, entrance)
    lev = level_totals(obs)

    # GER and GPI
    ger = lev.merge(popoff, on=["iso3", "level", "sex", "year"], suffixes=("_e", "_p"))
    ger["value"] = ger.value_e / ger.value_p * 100
    for lv in spec.LEVELS:
        g = ger[ger.level == lv]
        out.append(_ind(g, f"GER_{lv}"))
        piv = g.pivot_table(index=["iso3", "year", "source"], columns="sex", values="value").reset_index()
        if {"F", "M"} <= set(piv.columns):
            piv["value"] = piv["F"] / piv["M"]
            piv["level"] = lv
            out.append(_ind(piv, f"GPI_GER_{lv}", sex_col=False))

    o = obs[obs.value.notna()]
    src = lambda d: d.assign(source="country_template")

    # NERT / OOSR (needs single-age data -> templates only)
    age = o[o.table == "ENRL_AGE"].copy()
    age = age[age.age.str.isdigit()]
    age["age_i"] = age.age.astype(int)
    for lv, higher in (("L1", ["L1", "L2", "L3"]), ("L2", ["L2", "L3"])):
        rows = []
        for iso3, g in age.groupby("iso3"):
            e = entrance.get(iso3)
            if e is None:
                continue
            sel = g[g.age_i.isin(spec.official_ages(e, lv)) & g.level.isin(higher)]
            s = sel.groupby(["sex", "year"]).value.sum().reset_index()
            s["iso3"] = iso3
            rows.append(s)
        if not rows:
            continue
        num = pd.concat(rows)
        d = num.merge(popoff[popoff.level == lv], on=["iso3", "sex", "year"], suffixes=("_e", "_p"))
        d["value"] = d.value_e / d.value_p * 100
        out.append(_ind(src(d), f"NERT_{lv}", level=lv))
        d2 = d.copy()
        d2["value"] = 100 - d2["value"]
        out.append(_ind(src(d2), f"OOSR_{lv}", level=lv))

    # Repeaters
    gr = o[o.table == "ENRL_GRADE"].groupby(["iso3", "level", "sex", "year"]).value.sum()
    rp = o[o.table == "REPEATERS"].groupby(["iso3", "level", "sex", "year"]).value.sum()
    d = pd.concat([rp.rename("r"), gr.rename("e")], axis=1).dropna().reset_index()
    d["value"] = d.r / d.e * 100
    for lv in spec.LEVELS:
        out.append(_ind(src(d[d.level == lv]), f"REPP_{lv}"))

    # Teachers
    t = o[o.table == "TEACHERS"].pivot_table(index=["iso3", "level", "sex", "year"],
                                              columns="item", values="value").reset_index()
    if len(t):
        tt = t[t.sex == "T"].merge(lev[lev.sex == "T"], on=["iso3", "level", "sex", "year"])
        tt["value"] = tt.value / tt.TCH
        for lv in spec.LEVELS:
            out.append(_ind(tt[tt.level == lv], f"PTR_{lv}"))
        t["value"] = t.TCH_TRAINED / t.TCH * 100
        for lv in spec.LEVELS:
            out.append(_ind(src(t[t.level == lv]), f"TRTP_{lv}"))

    # Finance
    f = o[o.table == "FIN"].pivot_table(index=["iso3", "year"], columns="item", values="value").reset_index()
    if len(f):
        if {"XEXP_EDU", "GDP"} <= set(f.columns):
            out.append(_ind(src(f.assign(value=f.XEXP_EDU / f.GDP * 100, level=None)), "XGDP", sex_col=False))
        if {"XEXP_EDU", "XEXP_GOV"} <= set(f.columns):
            out.append(_ind(src(f.assign(value=f.XEXP_EDU / f.XEXP_GOV * 100, level=None)), "XGOVEXP", sex_col=False))

    res = pd.concat([x for x in out if len(x)], ignore_index=True)
    res = res[res.value.notna() & (res.value != float("inf"))]
    res["year"] = res.year.astype(int)
    return res.sort_values(["iso3", "indicator", "sex", "year"], na_position="first").reset_index(drop=True)
