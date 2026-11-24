"""Command line entry point.

  python -m mydt generate                      # synthetic countries -> data/
  python -m mydt run                           # validate, consolidate, report -> output/
  python -m mydt build-templates --survey-year 2027 --langs en fr es pt ru
  python -m mydt test-template output/templates/2027/XAA_MYDT_2027_fr.xlsx
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mydt", description="SDG 4 MYDT template processing")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("generate", help="create synthetic submissions and reference data")
    r = sp.add_parser("run", help="validate, consolidate and report")
    r.add_argument("--data", default=ROOT / "data")
    r.add_argument("--out", default=ROOT / "output")
    r.add_argument("--survey-year", type=int, default=2026)
    b = sp.add_parser("build-templates", help="pre-filled templates for the next cycle")
    b.add_argument("--survey-year", type=int, default=2027)
    b.add_argument("--langs", nargs="+", default=["en", "fr", "es", "pt", "ru"])
    b.add_argument("--countries", nargs="*")
    b.add_argument("--window", type=int, default=5)
    b.add_argument("--db", default=ROOT / "output" / "consolidated" / "sdg4.sqlite")
    b.add_argument("--out", default=ROOT / "output" / "templates")
    t = sp.add_parser("test-template", help="functional test of a template")
    t.add_argument("paths", nargs="+")
    t.add_argument("--no-recalc", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "generate":
        from .synth import generate
        info = generate(ROOT)
        print(f"Wrote submissions to {info['submissions']} ({info['errors']} planted errors in answer key)")

    elif a.cmd == "run":
        from .consolidate import run
        res = run(a.data, a.out, a.survey_year)
        q = res.qc
        print(f"Read {len(res.submissions)} templates, {res.obs_mined.iso3.nunique()} mined sources")
        print(f"{len(res.indicators):,} indicator values; QC: "
              f"{(q.severity == 'ERROR').sum()} errors, {(q.severity == 'WARNING').sum()} warnings, "
              f"{(q.severity == 'INFO').sum()} info")
        print(q.groupby(["iso3", "severity"]).size().unstack(fill_value=0).to_string())
        print(f"Reports: {Path(a.out) / 'reports' / 'index.html'}")

    elif a.cmd == "build-templates":
        from .update import test_template, update_template
        with sqlite3.connect(a.db) as con:
            obs = pd.read_sql("select * from obs_templates", con)
        obs["year"] = obs.year.astype(int)
        pop = pd.read_csv(ROOT / "data" / "reference" / "population.csv", dtype={"age": str})
        from .reader import read_folder
        subs = {s.iso3: s for s in read_folder(ROOT / "data" / "submissions")}
        isos = a.countries or sorted(subs)
        failed = 0
        for iso3 in isos:
            s = subs[iso3]
            meta = {r.table: {k: getattr(r, k) for k in ("SOURCE", "REF_DATE", "COVERAGE", "NOTES")}
                    for r in s.metadata.itertuples()}
            for lang in a.langs:
                p = update_template(obs, pop, s.cover, a.survey_year,
                                    Path(a.out) / str(a.survey_year) / f"{iso3}_MYDT_{a.survey_year}_{lang}.xlsx",
                                    lang, a.window, meta)
                yrs = list(range(a.survey_year - a.window, a.survey_year))
                tr = test_template(p, yrs, recalc=False)
                failed += (~tr.passed).sum()
                print(f"{p.name}: {tr.passed.sum()}/{len(tr)} tests passed")
        sys.exit(1 if failed else 0)

    elif a.cmd == "test-template":
        from .update import test_template
        bad = 0
        for p in a.paths:
            tr = test_template(p, recalc=not a.no_recalc)
            print(f"\n{p}")
            for r in tr.itertuples():
                print(f"  [{'PASS' if r.passed else 'FAIL'}] {r.test} {r.detail if not r.passed else ''}")
            bad += (~tr.passed).sum()
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
