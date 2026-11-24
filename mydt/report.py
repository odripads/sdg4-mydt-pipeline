"""Country QC checklists (Excel) and indicator review reports (HTML)."""
from __future__ import annotations

import html
from datetime import date
from pathlib import Path

import pandas as pd
from jinja2 import Template
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .validate import RULE_TITLES

KEY_INDICATORS = [
    ("GER_L1", "Gross enrolment ratio, primary (%)"),
    ("GER_L2", "Gross enrolment ratio, lower secondary (%)"),
    ("GER_L3", "Gross enrolment ratio, upper secondary (%)"),
    ("NERT_L1", "Total net enrolment rate, primary (%)"),
    ("OOSR_L1", "Out-of-school rate, primary age (%)"),
    ("OOSR_L2", "Out-of-school rate, lower secondary age (%)"),
    ("GPI_GER_L1", "Gender parity index, GER primary"),
    ("GPI_GER_L2", "Gender parity index, GER lower secondary"),
    ("REPP_L1", "Repeaters, primary (%)"),
    ("PTR_L1", "Pupil-teacher ratio, primary"),
    ("PTR_L2", "Pupil-teacher ratio, lower secondary"),
    ("TRTP_L1", "Trained teachers, primary (%)"),
    ("XGDP", "Government expenditure on education (% of GDP)"),
    ("XGOVEXP", "Education share of government expenditure (%)"),
]
CHART_INDICATORS = ["GER_L1", "GER_L2", "GER_L3", "OOSR_L1", "PTR_L1", "XGDP"]


def status_of(flags: pd.DataFrame) -> tuple[str, str]:
    if (flags.severity == "ERROR").any():
        return "Return to country", "bad"
    if (flags.severity == "WARNING").any():
        return "Needs explanation", "warn"
    return "Ready for release", "ok"


# ------------------------------------------------------------------ checklists
def write_checklists(res, folder: Path):
    hdr = PatternFill("solid", fgColor="1F4E79")
    fills = {"PASS": PatternFill("solid", fgColor="E2EFDA"),
             "FAIL": PatternFill("solid", fgColor="F8CBAD"),
             "REVIEW": PatternFill("solid", fgColor="FFF2CC")}
    for s in res.submissions:
        flags = res.qc[res.qc.iso3 == s.iso3]
        rows = []
        for rule, title in RULE_TITLES.items():
            f = flags[flags.rule == rule]
            n_err, n_warn, n_info = ((f.severity == k).sum() for k in ("ERROR", "WARNING", "INFO"))
            result = "FAIL" if n_err else ("REVIEW" if n_warn or n_info else "PASS")
            rows.append({"Rule": rule, "Check": title, "Result": result, "Errors": n_err,
                         "Warnings": n_warn, "Info": n_info, "Analyst comment": "", "Country response": ""})
        path = folder / f"{s.iso3}_QC_checklist.xlsx"
        with pd.ExcelWriter(path, engine="openpyxl") as xw:
            pd.DataFrame(rows).to_excel(xw, sheet_name="Checklist", index=False, startrow=3)
            flags.drop(columns="iso3").to_excel(xw, sheet_name="Flags", index=False)
            ws = xw.sheets["Checklist"]
            ws["A1"] = f"QC checklist - {s.cover.get('COUNTRY')} ({s.iso3}) - survey year {s.cover.get('SURVEY_YEAR')}"
            ws["A1"].font = Font(bold=True, size=14, color="1F4E79")
            ws["A2"] = f"Status: {status_of(flags)[0]}. Generated {date.today().isoformat()} from {s.path.name}"
            for c in ws[4]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = hdr
            for r in range(5, 5 + len(rows)):
                cell = ws.cell(r, 3)
                cell.fill = fills[cell.value]
                cell.alignment = Alignment(horizontal="center")
            for col, w in zip("ABCDEFGH", (18, 52, 10, 8, 10, 6, 36, 36)):
                ws.column_dimensions[col].width = w
            wf = xw.sheets["Flags"]
            for c in wf[1]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = hdr
            for i, w in enumerate((18, 10, 20, 6, 5, 7, 36, 12, 12, 80), start=1):
                wf.column_dimensions[get_column_letter(i)].width = w


# ------------------------------------------------------------------ HTML reports
def spark(cur: pd.Series, prev: pd.Series | None, w=260, h=90) -> str:
    """Inline SVG line chart: current submission solid, previous release dashed."""
    series = [s for s in (cur, prev) if s is not None and len(s)]
    if not series:
        return ""
    allv = pd.concat(series)
    years = sorted(set().union(*[set(s.index) for s in series]))
    lo, hi = allv.min(), allv.max()
    pad = (hi - lo) * 0.15 or abs(hi) * 0.05 or 1
    lo, hi = lo - pad, hi + pad
    x = lambda y: 34 + (w - 56) * (years.index(y) / max(len(years) - 1, 1))
    yy = lambda v: 10 + (h - 30) * (1 - (v - lo) / (hi - lo))

    def path(s, cls):
        pts = " ".join(f"{x(k):.1f},{yy(v):.1f}" for k, v in s.items())
        dots = "".join(f'<circle cx="{x(k):.1f}" cy="{yy(v):.1f}" r="2.5" class="{cls}"/>' for k, v in s.items())
        return f'<polyline points="{pts}" class="{cls}" fill="none"/>{dots}'

    out = [f'<svg viewBox="0 0 {w} {h}" class="spark" role="img">']
    out.append(f'<text x="2" y="14" class="ax">{hi - pad:.1f}</text>')
    out.append(f'<text x="2" y="{h - 20}" class="ax">{lo + pad:.1f}</text>')
    for k in years:
        out.append(f'<text x="{x(k):.1f}" y="{h - 4}" class="ax" text-anchor="middle">{k}</text>')
    if prev is not None and len(prev):
        out.append(path(prev, "prev"))
    out.append(path(cur, "cur"))
    out.append("</svg>")
    return "".join(out)


TEMPLATE = Template("""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title><style>
:root{--ink:#1d2733;--muted:#5b6876;--line:#dfe4ea;--brand:#1f4e79;--bg:#f6f8fa;
--ok:#2e7d32;--okbg:#e6f4ea;--warn:#8a5a00;--warnbg:#fff4d6;--bad:#b3261e;--badbg:#fde7e5}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);background:var(--bg)}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:32px 0 10px;color:var(--brand)}
.sub{color:var(--muted)}.badge{display:inline-block;padding:3px 10px;border-radius:999px;font-weight:600;font-size:13px}
.ok{color:var(--ok);background:var(--okbg)}.warn{color:var(--warn);background:var(--warnbg)}.bad{color:var(--bad);background:var(--badbg)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:16px}
.card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.card b{display:block;font-size:22px}.card span{color:var(--muted);font-size:12px}
.tbl{overflow-x:auto;background:#fff;border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:#eef2f6;font-weight:600;white-space:nowrap}td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td code{font-size:12px;background:#f1f3f5;padding:1px 4px;border-radius:4px}
.prevv{display:block;color:var(--muted);font-size:11px}.rev{background:var(--warnbg)}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.spark{width:100%;height:auto}.spark .cur{stroke:var(--brand);stroke-width:2;fill:var(--brand)}
.spark polyline.cur{fill:none}.spark .prev{stroke:#9aa5b1;stroke-width:1.5;stroke-dasharray:4 3;fill:#9aa5b1}
.spark polyline.prev{fill:none}.ax{font-size:9px;fill:var(--muted)}
.legend{color:var(--muted);font-size:12px}footer{margin-top:40px;color:var(--muted);font-size:12px}
a{color:var(--brand)}
</style></head><body><main>
{{ body }}
<footer>Generated {{ today }} by mydt-pipeline. Synthetic demonstration data: all countries and figures are fictional.</footer>
</main></body></html>""")


def _country_body(iso3, name, channel, flags, ind, prev, survey_year):
    st, cls = status_of(flags)
    counts = {k: int((flags.severity == k).sum()) for k in ("ERROR", "WARNING", "INFO")}
    e = html.escape
    parts = [f'<p class="sub"><a href="index.html">All countries</a></p>',
             f"<h1>{e(name)} ({iso3})</h1>",
             f'<p class="sub">Country indicator review &middot; survey year {survey_year} &middot; '
             f'source: {"country template" if channel == "template" else "mined from national publications"}</p>',
             f'<span class="badge {cls}">{st}</span>',
             '<div class="cards">' + "".join(
                 f'<div class="card"><b>{counts[k]}</b><span>{lab}</span></div>'
                 for k, lab in (("ERROR", "errors to fix"), ("WARNING", "warnings to explain"),
                                ("INFO", "notes for the analyst"))) +
             f'<div class="card"><b>{ind.year.min() if len(ind) else "-"}&ndash;{ind.year.max() if len(ind) else "-"}</b>'
             f'<span>years covered</span></div></div>']

    parts.append("<h2>Validation results</h2>")
    if len(flags):
        rows = "".join(
            f'<tr><td><span class="badge {"bad" if r.severity == "ERROR" else "warn" if r.severity == "WARNING" else "ok"}">'
            f'{r.severity}</span></td><td>{e(RULE_TITLES.get(r.rule, r.rule))}</td>'
            f'<td>{"" if pd.isna(r.year) else int(r.year)}</td>'
            f'<td><code>{e(str(r.cell)) if isinstance(r.cell, str) and r.cell else "&ndash;"}</code></td>'
            f"<td>{e(r.message)}</td></tr>" for r in flags.itertuples())
        parts.append(f'<div class="tbl"><table><tr><th>Severity</th><th>Check</th><th>Year</th>'
                     f"<th>Where</th><th>Detail</th></tr>{rows}</table></div>")
    else:
        parts.append("<p>All checks passed.</p>")

    parts.append("<h2>Indicators</h2>")
    parts.append('<p class="legend">Totals (both sexes). Grey figures underneath are the previous data release; '
                 "shaded cells changed by more than the revision threshold.</p>")
    years = sorted(ind.year.unique())
    tot = ind[ind.sex.isin(["T"]) | ind.sex.isna()]
    pv = prev[prev.iso3 == iso3] if prev is not None else pd.DataFrame(columns=ind.columns)
    pv = pv[pv.sex.isin(["T"]) | pv.sex.isna()]
    head = "".join(f'<th class="n">{y}</th>' for y in years)
    rows = []
    for code, label in KEY_INDICATORS:
        s = tot[tot.indicator == code].set_index("year").value
        if s.empty:
            continue
        p = pv[pv.indicator == code].set_index("year").value
        cells = []
        for y in years:
            v = s.get(y)
            pvv = p.get(y)
            fmt = (lambda z: f"{z:.2f}") if code.startswith("GPI") else (lambda z: f"{z:.1f}")
            rev = pvv is not None and v is not None and abs(v - pvv) > 3 and not code.startswith(("GPI", "PTR", "X"))
            txt = "&ndash;" if v is None else fmt(v)
            if pvv is not None:
                txt += f'<span class="prevv">{fmt(pvv)}</span>'
            cells.append(f'<td class="n{" rev" if rev else ""}">{txt}</td>')
        rows.append(f"<tr><td>{e(label)}</td>{''.join(cells)}</tr>")
    parts.append(f'<div class="tbl"><table><tr><th>Indicator</th>{head}</tr>{"".join(rows)}</table></div>')

    parts.append("<h2>Trends</h2>")
    parts.append('<p class="legend">Solid: this submission. Dashed: previous release.</p><div class="charts">')
    for code in CHART_INDICATORS:
        s = tot[tot.indicator == code].set_index("year").value.sort_index()
        if s.empty:
            continue
        p = pv[pv.indicator == code].set_index("year").value.sort_index()
        label = dict(KEY_INDICATORS)[code]
        parts.append(f'<div class="card"><span>{e(label)}</span>{spark(s, p if len(p) else None)}</div>')
    parts.append("</div>")
    return "".join(parts)


def write_reports(res, folder: Path, previous: pd.DataFrame | None):
    folder.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    index_rows = []
    names = dict(zip(res.countries.iso3, res.countries.name))
    channels = dict(zip(res.countries.iso3, res.countries.channel))
    sub_by = {s.iso3: s for s in res.submissions}
    for iso3 in sorted(set(res.indicators.iso3)):
        flags = res.qc[res.qc.iso3 == iso3]
        ind = res.indicators[res.indicators.iso3 == iso3]
        name = names.get(iso3, iso3)
        sy = sub_by[iso3].cover.get("SURVEY_YEAR") if iso3 in sub_by else "-"
        body = _country_body(iso3, name, channels.get(iso3, "template"), flags, ind, previous, sy)
        (folder / f"{iso3}_review.html").write_text(
            TEMPLATE.render(title=f"{name} review", body=body, today=today), encoding="utf-8")
        st, cls = status_of(flags)
        index_rows.append(
            f'<tr><td><a href="{iso3}_review.html">{html.escape(name)}</a></td><td>{iso3}</td>'
            f'<td>{"Template" if channels.get(iso3) == "template" else "Mined"}</td>'
            f'<td class="n">{(flags.severity == "ERROR").sum()}</td><td class="n">{(flags.severity == "WARNING").sum()}</td>'
            f'<td class="n">{(flags.severity == "INFO").sum()}</td><td><span class="badge {cls}">{st}</span></td></tr>')
    q = res.qc
    body = ("<h1>SDG 4 data processing: survey overview</h1>"
            f'<p class="sub">{len(res.submissions)} country templates and '
            f'{res.obs_mined.iso3.nunique() if len(res.obs_mined) else 0} mined sources processed.</p>'
            '<div class="cards">'
            f'<div class="card"><b>{(q.severity == "ERROR").sum()}</b><span>errors</span></div>'
            f'<div class="card"><b>{(q.severity == "WARNING").sum()}</b><span>warnings</span></div>'
            f'<div class="card"><b>{len(res.indicators):,}</b><span>indicator values</span></div>'
            f'<div class="card"><b>{len(res.obs_templates):,}</b><span>template cells read</span></div></div>'
            '<h2>Countries</h2><div class="tbl"><table><tr><th>Country</th><th>Code</th><th>Channel</th>'
            '<th class="n">Errors</th><th class="n">Warnings</th><th class="n">Info</th><th>Status</th></tr>'
            + "".join(index_rows) + "</table></div>")
    (folder / "index.html").write_text(TEMPLATE.render(title="SDG 4 survey overview", body=body, today=today),
                                       encoding="utf-8")
