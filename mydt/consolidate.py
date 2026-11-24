"""Run the whole cycle: read -> validate -> consolidate -> indicators -> reports.

Outputs (under the output folder)
  consolidated/obs_templates.csv   every cell from country templates, with its cell address
  consolidated/obs_mined.csv       data mined from national publications, same schema
  consolidated/indicators.csv      SDG 4 indicators, both sources
  consolidated/indicators.dta      the same, for Stata users
  consolidated/sdg4.sqlite         all of the above plus the QC log, one table each
  qc/qc_log.csv                    every flag from every country
  qc/{ISO3}_QC_checklist.xlsx      checklist for each country
  reports/{ISO3}_review.html       country indicator review report
  reports/index.html               overview of all countries
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import indicators as ind_mod
from .reader import OBS_COLUMNS, read_folder
from .validate import load_rules, validate_indicators, validate_submission


@dataclass
class Result:
    obs_templates: pd.DataFrame
    obs_mined: pd.DataFrame
    indicators: pd.DataFrame
    qc: pd.DataFrame
    countries: pd.DataFrame
    submissions: list


def read_mined(folder) -> pd.DataFrame:
    """Wide yearbook tables (one row per level x sex, one column per year) -> tidy obs."""
    parts = []
    for p in sorted(Path(folder).glob("*.csv")):
        w = pd.read_csv(p)
        years = [c for c in w.columns if str(c).isdigit()]
        long = w.melt(id_vars=["country_code", "level", "sex", "source"], value_vars=years,
                      var_name="year", value_name="value")
        parts.append(pd.DataFrame({
            "iso3": long.country_code, "survey_year": None, "table": "ENRL_LEVEL",
            "level": long.level, "age": None, "grade": None, "item": None, "sex": long.sex,
            "year": long.year.astype(int), "value": pd.to_numeric(long.value, errors="coerce"),
            "status": "", "raw": None, "cell": p.name, "source": "mined",
        }))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=OBS_COLUMNS)


def run(data_dir, out_dir, survey_year: int | None = None, reports: bool = True) -> Result:
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    ref = data_dir / "reference"
    rules = load_rules()
    pop = pd.read_csv(ref / "population.csv", dtype={"age": str})
    countries = pd.read_csv(ref / "countries.csv")
    prev_path = ref / "previous_release.csv"
    previous = pd.read_csv(prev_path) if prev_path.exists() else None

    subs = read_folder(data_dir / "submissions")
    qc = [validate_submission(s, pop, rules, survey_year) for s in subs]
    obs_t = pd.concat([s.data for s in subs], ignore_index=True) if subs else pd.DataFrame(columns=OBS_COLUMNS)
    obs_m = read_mined(data_dir / "mined") if (data_dir / "mined").exists() else pd.DataFrame(columns=OBS_COLUMNS)

    entrance = dict(zip(countries.iso3, countries.entrance_age))
    for s in subs:                                   # the country's own cover page wins
        try:
            entrance[s.iso3] = int(s.cover.get("ENTRANCE_AGE"))
        except (TypeError, ValueError):
            pass
    ind = ind_mod.compute(pd.concat([obs_t, obs_m], ignore_index=True), pop, entrance)
    qc.append(validate_indicators(ind, rules, previous))
    qc = pd.concat(qc, ignore_index=True)
    sev_order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
    qc = qc.sort_values(["iso3", "severity", "rule", "year"],
                        key=lambda s: s.map(sev_order) if s.name == "severity" else s).reset_index(drop=True)

    cons, qcd = out_dir / "consolidated", out_dir / "qc"
    cons.mkdir(parents=True, exist_ok=True)
    qcd.mkdir(parents=True, exist_ok=True)
    obs_t.to_csv(cons / "obs_templates.csv", index=False)
    obs_m.to_csv(cons / "obs_mined.csv", index=False)
    ind.to_csv(cons / "indicators.csv", index=False)
    ind.assign(level=ind.level.fillna(""), sex=ind.sex.fillna("")).to_stata(
        cons / "indicators.dta", write_index=False, version=118)
    qc.to_csv(qcd / "qc_log.csv", index=False)
    db = cons / "sdg4.sqlite"
    db.unlink(missing_ok=True)
    with sqlite3.connect(db) as con:
        obs_t.to_sql("obs_templates", con, index=False)
        obs_m.to_sql("obs_mined", con, index=False)
        ind.to_sql("indicators", con, index=False)
        qc.to_sql("qc_log", con, index=False)
        countries.to_sql("countries", con, index=False)

    res = Result(obs_t, obs_m, ind, qc, countries, subs)
    if reports:
        from .report import write_checklists, write_reports
        write_checklists(res, qcd)
        write_reports(res, out_dir / "reports", previous)
    return res
