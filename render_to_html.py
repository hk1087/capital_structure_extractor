"""
Reads a capital-structure JSON (the extractor's output) and writes an HTML view.

Left: the cap structure table (tranche, maturity, coupon, collateral summary,
gross, intercompany, net), ordered by seniority, grouped by lien class.
Right: an "Open disputes" sidebar listing each contested position with its reason
and verified source quote. Contested rows carry a marker linking to the sidebar.

PRESENTATION only — never touches extraction. Same data feeds the eval / match vector.

"""
import json, sys

CLASS_ORDER = [
    ("abl",        "First-out / ABL",                 {"abl_revolver", "abl"}),
    ("secured",    "Senior secured — pari (Term Loans + PGNs)",
                   {"term_loan", "priority_guarantee_note"}),
    ("unsecured",  "Senior unsecured",                {"senior_unsecured_note", "senior_note"}),
    ("legacy",     "Legacy / structurally junior",    {"legacy_senior_note", "legacy_note"}),
    ("other",      "Other",                           set()),
]

def _class_of(tranche_type):
    for key, _label, types in CLASS_ORDER:
        if tranche_type in types:
            return key
    return "other"

def _num(x):
    if x is None or x == 0:
        return ""
    return f"{x:,.0f}"

def summarize_collateral(sec):
    if not sec:
        return "unsecured"
    s = sec.lower()
    if "unsecured" in s:
        return "unsecured"
    bits = []
    if "first-priority" in s or "first priority" in s or "1st" in s:
        bits.append("1st lien")
    elif "second-priority" in s or "second priority" in s:
        bits.append("2nd lien")
    if "pari" in s:
        bits.append("pari")
    if ("receivable" in s) and ("second" in s or "2nd" in s):
        bits.append("2nd on A/R")
    return " &middot; ".join(dict.fromkeys(bits)) or "secured"

def _total_funded(d):
    t = d.get("total_funded_debt")
    if isinstance(t, (int, float)):
        return t
    if isinstance(t, dict):
        if "value_usd_mm" in t:
            return t["value_usd_mm"]
        obs = t.get("observations")
        if obs:
            return obs[0].get("value_usd_mm")
    return None

def _waterfall(d):
    ps = d.get("priority_structure", {}) or {}
    return ps.get("effective_waterfall_top_to_bottom") or ps.get("effective_waterfall") or []

def order_tranches(d):
    tranches = list(d.get("tranches", []))
    wf = _waterfall(d)
    if wf:
        rank = {name: i for i, name in enumerate(wf)}
        tranches.sort(key=lambda t: rank.get(t.get("name"), 999))
    else:
        class_rank = {key: i for i, (key, _l, _t) in enumerate(CLASS_ORDER)}
        tranches.sort(key=lambda t: (class_rank[_class_of(t.get("type"))],
                                     -(t.get("principal_usd_mm") or 0)))
    return tranches

GRID = "grid-template-columns: 1fr 72px 66px 78px 72px 78px 150px;"

HEADER = (
    "<div class='hdr'>"
    "<div class='c-name'>Tranche</div>"
    "<div class='c-mat'>Maturity</div>"
    "<div class='c-cpn'>Coupon</div>"
    "<div class='c-num'>Gross</div>"
    "<div class='c-num'>Interco.</div>"
    "<div class='c-num'>Net</div>"
    "<div class='c-coll'>Collateral</div>"
    "</div>"
)

def render(d):
    tranches = order_tranches(d)
    total = _total_funded(d)
    class_labels = {k: l for k, l, _t in CLASS_ORDER}

    rows, cur_class, class_sum = [], None, 0
    disputes = []          # (name, reason, quote, loc) for the sidebar

    def flush_subtotal():
        if cur_class is not None:
            rows.append(
                "<div class='row grid subtot'>"
                f"<div class='c-name'>Subtotal &mdash; {class_labels[cur_class]}</div>"
                "<div class='c-mat'></div><div class='c-cpn'></div>"
                f"<div class='c-num'>{_num(class_sum)}</div><div class='c-num'></div><div class='c-num'></div>"
                "<div class='c-coll'></div></div>"
            )

    for t in tranches:
        cls = _class_of(t.get("type"))
        if cls != cur_class:
            flush_subtotal()
            cur_class, class_sum = cls, 0
            rows.append(f"<div class='grp'>{class_labels[cls]}</div>")
        class_sum += (t.get("principal_usd_mm") or 0)

        name = t.get("name", "?")
        principal = t.get("principal_usd_mm") or 0
        ic = t.get("intercompany_held_usd_mm")
        net = principal - (ic or 0)
        maturity = t.get("maturity") or "&mdash;"
        coupon = (f"{t.get('coupon')}%" if t.get("coupon") is not None else "&mdash;")
        security = t.get("security", "") or ""
        summary = summarize_collateral(security)
        collateral_cell = (
            ("<details class='coll'><summary>" + summary + "</summary>"
             "<div class='coll-full'>" + security + "</div></details>")
            if security else f"<span class='coll-plain'>{summary}</span>"
        )

        contested = bool(t.get("contested"))
        marker = " <span class='dot'>&#9679;</span>" if contested else ""
        if contested:
            disputes.append((
                name,
                t.get("contested_reason", "") or "Standing in dispute.",
                t.get("quote", ""),
                t.get("source_locator", ""),
            ))

        rows.append(
            f"<div class='row grid{' ct' if contested else ''}'>"
            f"<div class='c-name'><span class='nm'>{name}</span>{marker}</div>"
            f"<div class='c-mat'>{maturity}</div>"
            f"<div class='c-cpn'>{coupon}</div>"
            f"<div class='c-num'>{_num(principal)}</div>"
            f"<div class='c-num ic'>{('('+_num(ic)+')') if ic else ''}</div>"
            f"<div class='c-num'>{_num(net) if net else _num(principal)}</div>"
            f"<div class='c-coll'>{collateral_cell}</div>"
            "</div>"
        )

    flush_subtotal()

    if total:
        rows.append(
            "<div class='row grid total'>"
            "<div class='c-name'>Total funded debt (Debtor)</div>"
            "<div class='c-mat'></div><div class='c-cpn'></div>"
            f"<div class='c-num'>{_num(total)}</div><div class='c-num'></div><div class='c-num'></div>"
            "<div class='c-coll'></div>"
            "</div>"
        )

    # sidebar
    if disputes:
        notes = []
        for i, (name, reason, quote, loc) in enumerate(disputes):
            q = (f"<div class='note-q'>&ldquo;{quote}&rdquo;"
                 + (f" <span class='note-loc'>&mdash; {loc}</span>" if loc else "")
                 + "</div>") if quote else ""
            notes.append(
                f"<div class='note{' first' if i == 0 else ''}'>"
                f"<div class='note-h'><span class='dot'>&#9679;</span> {name}</div>"
                f"<div class='note-b'>{reason}</div>{q}</div>"
            )
        sidebar = (
            "<div class='side'>"
            f"<div class='side-h'>Open disputes ({len(disputes)})</div>"
            + "".join(notes) +
            "</div>"
        )
    else:
        sidebar = ("<div class='side'><div class='side-h'>Open disputes (0)</div>"
                   "<div class='side-none'>No positions in dispute.</div></div>")

    return f"""<!doctype html><meta charset="utf-8">
<title>Capital Structure</title>
<style>
  :root {{ --ink:#1a1a1a; --mut:#6a6a6a; --faint:#9a9a9a; --line:#e6e4df;
           --danger:#c0392b; --danger-bg:#fdf4f3; --surface:#fafafa; --link:#3a6ea5; }}
  body {{ font:12.5px/1.35 -apple-system, system-ui, "Segoe UI", sans-serif; color:var(--ink);
          max-width:1320px; margin:16px auto; padding:0 18px; }}
  h1 {{ font-size:16px; font-weight:600; margin:0 0 2px; }}
  .lede {{ color:var(--mut); font-size:11.5px; margin-bottom:10px; }}

  .wrap {{ display:flex; gap:18px; align-items:flex-start; }}
  .stack {{ flex:1; min-width:0; border:1px solid var(--line); border-radius:10px; overflow:hidden; }}

  .grid {{ display:grid; {GRID} align-items:baseline; column-gap:10px; }}
  .c-mat, .c-cpn {{ font-size:12px; color:var(--mut); text-align:right;
                    font-family:ui-monospace,"SF Mono",Menlo,monospace; white-space:nowrap; }}
  .c-num {{ font-family:ui-monospace,"SF Mono",Menlo,monospace; font-size:12.5px;
            text-align:right; color:var(--mut); white-space:nowrap; }}
  .c-num.ic {{ color:#b26a00; }}
  .c-coll {{ font-size:11.5px; text-align:right; }}
  .dot {{ color:var(--danger); font-size:9px; vertical-align:1px; }}

  .coll {{ text-align:right; }}
  .coll summary {{ cursor:pointer; color:var(--link); list-style:none; white-space:nowrap; }}
  .coll summary::-webkit-details-marker {{ display:none; }}
  .coll summary::after {{ content:' +'; color:var(--faint); }}
  .coll[open] summary::after {{ content:' −'; }}
  .coll-full {{ margin-top:5px; color:var(--mut); font-size:11px; line-height:1.45; text-align:right; }}
  .coll-plain {{ color:var(--faint); }}

  .hdr {{ display:grid; {GRID} column-gap:10px; padding:5px 14px; background:#fff;
          border-bottom:1.5px solid var(--ink); }}
  .hdr > div {{ font-size:10px; text-transform:uppercase; letter-spacing:.04em;
                color:var(--faint); font-weight:600; }}
  .hdr .c-name {{ text-align:left; }}
  .hdr .c-mat, .hdr .c-cpn, .hdr .c-num, .hdr .c-coll {{ text-align:right; font-family:inherit; }}

  .grp {{ font-size:9.5px; text-transform:uppercase; letter-spacing:.05em;
          color:var(--faint); padding:6px 14px 2px; background:#fff; }}
  .row {{ padding:6px 14px; border-top:1px solid var(--line); background:#fff; }}
  .grp + .row {{ border-top:none; }}
  .c-name .nm {{ font-size:12.5px; color:var(--mut); }}
  .row.ct {{ background:var(--danger-bg); border-left:3px solid var(--danger); padding-left:11px; }}
  .row.ct .nm {{ color:var(--ink); font-weight:600; }}

  .subtot {{ border-top:1px solid #ccc; background:#fcfcfb; }}
  .subtot .c-name {{ font-weight:600; color:var(--mut); font-size:11.5px; }}
  .subtot .c-num {{ font-weight:600; color:var(--mut); }}
  .total {{ border-top:2px solid var(--ink); }}
  .total .c-name {{ font-weight:700; font-size:14px; color:var(--ink); }}
  .total .c-num {{ font-weight:700; color:var(--ink); font-size:13px; }}

  .side {{ width:400px; flex-shrink:0; align-self:stretch; border:1px solid var(--line); border-radius:10px;
           padding:10px 14px; background:var(--surface); }}
  .side-h {{ font-size:10px; text-transform:uppercase; letter-spacing:.05em;
             color:var(--danger); font-weight:700; margin-bottom:9px; }}
  .side-none {{ font-size:12px; color:var(--faint); }}
  .note {{ padding-top:10px; border-top:1px solid var(--line); }}
  .note.first {{ padding-top:0; border-top:none; }}
  .note-h {{ font-size:12px; font-weight:600; color:var(--ink); margin-bottom:5px; }}
  .note-b {{ font-size:11.5px; color:var(--mut); line-height:1.4; }}
  .note-q {{ margin-top:6px; font-family:ui-monospace,Menlo,monospace; font-size:10px;
             color:var(--mut); background:#fff; border:1px solid var(--line);
             border-radius:6px; padding:7px 9px; line-height:1.45; }}
  .note-loc {{ color:var(--faint); }}

  .foot {{ margin-top:8px; color:var(--faint); font-size:10px; line-height:1.4; }}
  @media (max-width:820px) {{ .wrap {{ flex-direction:column; }} .side {{ width:auto; }} }}
</style>
<h1>iHeartMedia &mdash; capital structure at petition</h1>
<div class="lede">Ordered by seniority. Contested positions are marked &#9679; and detailed in the
  disputes panel, with the open dispute and its source. Collateral summarised — click to expand. Figures in $mm.</div>
<div class="wrap">
  <div class="stack">
    {HEADER}
    {''.join(rows)}
  </div>
  {sidebar}
</div>
<div class="foot">Gross = principal outstanding. Interco. = held by affiliates (eliminated in consolidation).
  Net = gross less intercompany. A position is &ldquo;contested&rdquo; only where a specific, active dispute
  over that instrument is identifiable.</div>
"""

if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "iheart_auto.json"
    d = json.load(open(src))
    out = src.rsplit(".", 1)[0].replace("_auto", "") + "_cap_stack.html"
    open(out, "w", encoding="utf-8").write(render(d))
    print(f"wrote {out}")
