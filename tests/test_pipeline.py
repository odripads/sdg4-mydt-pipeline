"""End-to-end and unit tests. Run with: pytest -q"""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest
import yaml

from mydt import spec
from mydt.consolidate import run
from mydt.indicators import compute
from mydt.reader import parse_value, read_template
from mydt.synth import COUNTRIES, YEARS, generate, make_country
from mydt.template import LABELS_PATH, LANGS, values_from_frame, write_template
from mydt.update import test_template as functional_test
from mydt.update import update_template


@pytest.fixture(scope="session")
def workspace(tmp_path_factory):
    root = tmp_path_factory.mktemp("ws")
    shutil.copytree(Path(__file__).resolve().parent.parent / "config", root / "config")
    generate(root)
    res = run(root / "data", root / "output", survey_year=2026)
    return root, res


def test_every_planted_error_is_caught(workspace):
    root, res = workspace
    key = pd.read_csv(root / "data" / "reference" / "answer_key.csv")
    caught = set(zip(res.qc.iso3, res.qc.rule))
    missed = set(zip(key.iso3, key.expected_rule)) - caught
    assert not missed, f"planted errors not detected: {missed}"


def test_no_false_alarms(workspace):
    """Every flag raised must be explained by the answer key."""
    root, res = workspace
    key = pd.read_csv(root / "data" / "reference" / "answer_key.csv")
    extra = set(zip(res.qc.iso3, res.qc.rule)) - set(zip(key.iso3, key.expected_rule))
    assert not extra, f"unexpected flags: {extra}"


def test_clean_country_has_no_errors_or_warnings(workspace):
    _, res = workspace
    q = res.qc[res.qc.iso3 == "XAA"]
    assert not q.severity.isin(["ERROR", "WARNING"]).any()


def test_roundtrip_every_language(tmp_path):
    obs, pop, cover, meta = make_country("XAA", "Arcadia", "en", 6, "ARD", seed=1)
    values = values_from_frame(obs)
    for lang in LANGS:
        p = write_template(tmp_path / f"t_{lang}.xlsx", cover, YEARS, values, lang, meta)
        sub = read_template(p)
        assert sub.years == YEARS
        got = values_from_frame(sub.data[sub.data.value.notna()])
        assert got == values, lang


def test_translations_complete():
    with open(LABELS_PATH, encoding="utf-8") as f:
        L = yaml.safe_load(f)

    def keys(d, prefix=""):
        out = set()
        for k, v in d.items():
            out |= keys(v, f"{prefix}{k}.") if isinstance(v, dict) else {f"{prefix}{k}"}
        return out

    ref = keys(L["en"])
    for lang in LANGS:
        assert keys(L[lang]) == ref, lang


def test_parse_value_codes():
    assert parse_value(12)[1] == ""
    assert parse_value("m") == (pytest.approx(float("nan"), nan_ok=True), "m")
    assert parse_value(" X ")[1] == "x"
    assert parse_value("1 234")[1] == "invalid"
    assert parse_value(None)[1] == "blank"


def test_ger_hand_calculation():
    obs = pd.DataFrame([{"iso3": "ZZZ", "table": "ENRL_AGE", "level": "L1", "age": "6", "grade": None,
                         "item": None, "sex": "T", "year": 2025, "value": 900.0, "status": "",
                         "source": "country_template"}])
    pop = pd.DataFrame([{"iso3": "ZZZ", "age": str(a), "sex": "T", "year": 2025, "value": 200.0}
                        for a in range(0, 25)])
    ind = compute(obs, pop, {"ZZZ": 6})
    ger = ind[(ind.indicator == "GER_L1")].value.iloc[0]
    nert = ind[(ind.indicator == "NERT_L1")].value.iloc[0]
    assert ger == pytest.approx(900 / (6 * 200) * 100)        # 6 official primary ages
    assert nert == pytest.approx(900 / 1200 * 100)
    assert ind[ind.indicator == "OOSR_L1"].value.iloc[0] == pytest.approx(25.0)


def test_template_update_adds_year_and_prefills(workspace, tmp_path):
    root, res = workspace
    pop = pd.read_csv(root / "data" / "reference" / "population.csv", dtype={"age": str})
    sub = next(s for s in res.submissions if s.iso3 == "XAA")
    p = update_template(res.obs_templates, pop, sub.cover, 2027, tmp_path / "XAA_2027_fr.xlsx", "fr")
    tr = functional_test(p, expected_years=list(range(2022, 2027)), recalc=False)
    assert tr.passed.all(), tr[~tr.passed]
    new = read_template(p)
    assert new.cover["SURVEY_YEAR"] == 2027
    d = new.data
    assert d[(d.year == 2026) & (d.table == "ENRL_AGE")].status.eq("blank").all()   # new year empty
    assert d[(d.year == 2026) & (d.table == "POP")].value.notna().all()             # population pre-filled
    kept = d[(d.table == "ENRL_AGE") & (d.year == 2025)]
    assert kept.value.sum() == sub.data[(sub.data.table == "ENRL_AGE") & (sub.data.year == 2025)].value.sum()


def test_outputs_written(workspace):
    root, _ = workspace
    out = root / "output"
    for f in ["consolidated/indicators.csv", "consolidated/indicators.dta", "consolidated/sdg4.sqlite",
              "qc/qc_log.csv", "qc/XAB_QC_checklist.xlsx", "reports/index.html", "reports/XAI_review.html"]:
        assert (out / f).exists(), f


def test_hostile_submission_is_contained(workspace, tmp_path):
    """A bad ISO3 code cannot steer output paths, and formulas typed into cells are not run."""
    root, _ = workspace
    data = tmp_path / "data"
    shutil.copytree(root / "data" / "reference", data / "reference")
    obs, pop, cover, meta = make_country("XAA", "Arcadia", "en", 6, "ARD", seed=1)
    values = values_from_frame(obs)
    values[("TEACHERS", "L1", "TCH", "F", 2025)] = '=HYPERLINK("http://example.invalid","x")'
    write_template(data / "submissions" / "evil.xlsx", {**cover, "ISO3": "../../pwn"}, YEARS, values, "en", meta)
    res = run(data, tmp_path / "out", survey_year=2026)
    assert "R00_STRUCTURE" in set(res.qc.rule)
    assert not list(tmp_path.glob("pwn*")) and not list((tmp_path / "out").rglob("*..*"))
    sheet = tmp_path / "out" / "qc" / "INVALID_evil_QC_checklist.xlsx"
    flags = pd.read_excel(sheet, sheet_name="Flags")
    assert {"R00_STRUCTURE", "R01_INVALID"} <= set(flags.rule)
    bad = flags[flags.rule == "R01_INVALID"]
    assert len(bad)
    assert bad.value.astype(str).str.startswith("'=").all()
