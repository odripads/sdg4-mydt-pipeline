"""Point-and-click front end for colleagues who don't run Python.

    streamlit run app/streamlit_app.py

Upload country templates (or use the bundled sample), and the app validates
them, shows every flag with its cell address, plots the indicators, and lets
you download the QC log, checklists and review reports.
"""
from __future__ import annotations

import io
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mydt.consolidate import run  # noqa: E402
from mydt.reader import safe_name  # noqa: E402
from mydt.report import KEY_INDICATORS, status_of  # noqa: E402
from mydt.validate import RULE_TITLES  # noqa: E402

st.set_page_config(page_title="SDG 4 template checker", layout="wide")
st.title("SDG 4 template checker")
st.caption("Validates MYDT-style country templates, computes SDG 4 indicators and produces review reports. "
           "Demo build with fictional countries.")

with st.sidebar:
    st.header("Input")
    files = st.file_uploader("Country templates (.xlsx)", type="xlsx", accept_multiple_files=True)
    use_sample = st.toggle("Use bundled sample submissions", value=not files)
    survey_year = st.number_input("Survey year", value=2026, step=1)
    go = st.button("Run checks", type="primary", use_container_width=True)


@st.cache_data(show_spinner="Validating templates...")
def process(payload: tuple[tuple[str, bytes], ...], sample: bool, year: int):
    tmp = Path(tempfile.mkdtemp())
    data = tmp / "data"
    shutil.copytree(ROOT / "data" / "reference", data / "reference")
    if (ROOT / "data" / "mined").exists():
        shutil.copytree(ROOT / "data" / "mined", data / "mined")
    subs = data / "submissions"
    subs.mkdir(parents=True)
    if sample:
        for p in (ROOT / "data" / "submissions").glob("*.xlsx"):
            shutil.copy(p, subs)
    for i, (name, blob) in enumerate(payload):
        stem = safe_name(Path(name).stem)             # never trust an uploaded file name
        (subs / f"upload_{i:03d}_{stem}.xlsx").write_bytes(blob)
    res = run(data, tmp / "output", int(year))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in (tmp / "output").rglob("*"):
            if f.is_file() and f.suffix in (".html", ".xlsx", ".csv"):
                z.write(f, f.relative_to(tmp / "output"))
    return res.qc, res.indicators, res.countries, buf.getvalue()


if go or "result" in st.session_state:
    if go:
        payload = tuple((f.name, f.getvalue()) for f in files or [])
        st.session_state.result = process(payload, use_sample, survey_year)
    qc, ind, countries, zipped = st.session_state.result

    names = dict(zip(countries.iso3, countries.name))
    rows = []
    for iso3 in sorted(ind.iso3.unique()):
        f = qc[qc.iso3 == iso3]
        rows.append({"Country": names.get(iso3, iso3), "Code": iso3,
                     "Errors": int((f.severity == "ERROR").sum()),
                     "Warnings": int((f.severity == "WARNING").sum()),
                     "Info": int((f.severity == "INFO").sum()), "Status": status_of(f)[0]})
    c1, c2, c3 = st.columns(3)
    c1.metric("Countries", len(rows))
    c2.metric("Errors", int((qc.severity == "ERROR").sum()))
    c3.metric("Warnings", int((qc.severity == "WARNING").sum()))
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.download_button("Download QC log, checklists and reports (.zip)", zipped,
                       "sdg4_qc_outputs.zip", "application/zip")

    tab_qc, tab_ind = st.tabs(["Validation flags", "Indicators"])
    with tab_qc:
        iso = st.selectbox("Country", ["All"] + sorted(qc.iso3.unique()), key="qc_c")
        sev = st.multiselect("Severity", ["ERROR", "WARNING", "INFO"], default=["ERROR", "WARNING"])
        view = qc[qc.severity.isin(sev)]
        if iso != "All":
            view = view[view.iso3 == iso]
        view = view.assign(check=view.rule.map(RULE_TITLES))
        st.dataframe(view[["iso3", "severity", "check", "year", "cell", "message"]],
                     hide_index=True, use_container_width=True)
    with tab_ind:
        labels = dict(KEY_INDICATORS)
        code = st.selectbox("Indicator", list(labels), format_func=labels.get)
        sel = st.multiselect("Countries", sorted(ind.iso3.unique()), default=sorted(ind.iso3.unique())[:4])
        d = ind[(ind.indicator == code) & ind.iso3.isin(sel) & (ind.sex.isin(["T"]) | ind.sex.isna())]
        if len(d):
            st.line_chart(d.pivot_table(index="year", columns="iso3", values="value"))
            st.dataframe(d.pivot_table(index="iso3", columns="year", values="value").round(1),
                         use_container_width=True)
else:
    st.info("Upload templates or keep the sample toggle on, then press **Run checks**.")
