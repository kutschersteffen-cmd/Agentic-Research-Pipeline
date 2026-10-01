"""The TPA pitch at committee density: the same 10 headlines, pre-read fills with eyebrows and takeaway bars.

Every number is the indicator set's structure or a fact from the notes (walk 34 / talk 30, category counts, the
pipeline steps, 105 cells and 86 sources). No company is scored: the profile slide says it shows the output format.
"""
# ruff: noqa: E501

from arp.schemas.reporting import (
    ColumnKind,
    DatasetColumn,
    QuantitativeDataset,
    ReportRequest,
    SlideContent,
    Storyline,
    TableSpec,
)
from tests.fixtures.tpa_pitch import PAPER, TOOL, tpa_pitch

counts = QuantitativeDataset(
    dataset_id="ds_counts", name="Indicator set by category", description="Indicators, walk and talk per category (indicators.json)",
    columns=[DatasetColumn(name="Category", kind=ColumnKind.CATEGORY), DatasetColumn(name="Indicators", kind=ColumnKind.NUMBER),
             DatasetColumn(name="Walk", kind=ColumnKind.NUMBER), DatasetColumn(name="Talk", kind=ColumnKind.NUMBER),
             DatasetColumn(name="Walk share", kind=ColumnKind.CATEGORY)],
    rows=[{"Category": "Target", "Indicators": 12, "Walk": 0, "Talk": 12, "Walk share": "0%"},
          {"Category": "Governance", "Indicators": 9, "Walk": 2, "Talk": 7, "Walk share": "22%"},
          {"Category": "Strategy", "Indicators": 24, "Walk": 17, "Talk": 7, "Walk share": "71%"},
          {"Category": "Tracking", "Indicators": 19, "Walk": 15, "Talk": 4, "Walk share": "79%"},
          {"Category": "All", "Indicators": 64, "Walk": 34, "Talk": 30, "Walk share": "53%"}])


def _s(layout, variant, eyebrow, slots, refs, notes="", **kw):
    return SlideContent(headline="x", eyebrow=eyebrow, layout=layout, variant=variant, slots=slots, source_refs=refs, speaker_notes=notes, **kw)


FILLS = [
    _s("split", "list", "The evidence base", {
        "statement": "Colesanti Senni, Schimanski, Bingler, Ni and Leippold (2024) used AI to assess the transition disclosures of Climate Action 100+ companies. Disclosure skews toward talk, meaning targets and intentions, and away from walk, meaning implementation under way.",
        "items": ["143 Climate Action 100+ companies scored in the study",
                  "Guidelines validated by 28 domain experts from 26 institutions",
                  "Published in Environmental Research Communications",
                  "Clients want the gap between talk and walk measured, company by company"]},
       [PAPER], "The study is the method's source; the tool replicates it."),
    _s("table", "heat", "Method · indicator set", {
        "commentary": "Every company is scored on the same 64 yes-or-no indicators, taken verbatim from the paper's reference code. Strategy and tracking hold most of the walk indicators; all 12 target indicators are talk. Shading shows each category's walk share.",
        "takeaway_bar": "Why it matters: the indicator set is fixed, so results compare across companies and across years."},
       [PAPER, TOOL], "Shading: below 30% · 30–59% · 60% and above.",
       table=TableSpec(dataset_id="ds_counts", heat={"Walk share": [30, 60]})),
    _s("profile", "default", "Illustration · profile format", {
        "meters": ["Target :: 0%", "Governance :: 22%", "Strategy :: 71%", "Tracking :: 79%"],
        "total": "34 / 64",
        "left": ["Walk: action under way", "A concrete, checkable activity", "34 of the 64 indicators", "17 in strategy and 15 in tracking"],
        "right": ["Talk: targets and intent", "A target or a general intention", "30 of the 64 indicators", "All 12 target indicators are talk"],
        "takeaway_bar": "Illustration of the output format: the meters show each category's walk share, not a company score."},
       [TOOL], "A company's profile shows the shares it actually discloses, per category."),
    _s("flow", "default", "Method · assessment pipeline", {
        "items": ["Retrieve :: the 8 most relevant passages per indicator",
                  "Answer :: YES, NO or NA :: up to 200 words, verbatim quotes",
                  "Verify :: *a different model rechecks each verdict",
                  "Ground :: code matches every quote to the source",
                  "Review :: unverified or disputed verdicts go to analysts"],
        "takeaway_bar": "The difference from the paper: its tool trusts the model's sources; here code checks every quote."},
       [TOOL], "A verdict whose quote cannot be found is flagged for review."),
    _s("tree", "default", "Method · verification", {
        "items": ["quote :: Quote found in the source? :: agree :: unverified",
                  "agree :: Verifier agrees with the verdict? :: accepted :: disputed",
                  "accepted :: =Verdict accepted :: high",
                  "disputed :: =Verifier's verdict stands, flagged :: low",
                  "unverified :: =Unverified, to the review queue :: mid"],
        "takeaway_bar": "Why two models: the second check is independent, so agreement means more than a re-run."},
       [TOOL], "If the verifier disagrees, its verdict stands and the indicator is marked for review."),
    _s("cards", "three", "Governance · review", {
        "items": ["Review queue: indicators with no grounded citation, no valid answer, or where the two models disagree",
                  "Analyst decision: approve, edit or reject each flagged verdict, with a comment",
                  "Audit trail: every decision keeps its reviewer, time and full history"]},
       [TOOL], "Nothing uncertain is accepted at face value."),
    _s("split", "table", "Outputs", {
        "statement": "Each company gets a 64-row evidence grid: verdict, verbatim quote, source and confidence for every indicator. The walk and talk scores are the shares of the 34 walk and 30 talk indicators disclosed. The gap between them is the number to raise in engagement."},
       [TOOL], "Each grid row links back to the passage it rests on.",
       table=TableSpec(dataset_id="ds_outputs", columns=["Output", "Contents"])),
    _s("steps", "four", "Workflow", {
        "items": ["Export: walk and talk counts, walk share, confidence and a review flag per company",
                  "Join: with extraction, financials and TNFD runs on the same companies",
                  "Rank: no model calls, so the same run gives the same ranking",
                  "Engage: use the walk score to pick which plans to question first"]},
       [TOOL], "The export is deterministic."),
    _s("matrix2x2", "default", "Context · transition barriers", {
        "x_axis": "Walk score: low → high",
        "y_axis": "Barriers: many → few",
        "quadrants": ["Weak by choice :: Low walk, few barriers :: Levers exist but go unused: engage here first. :: low",
                      "Delivering :: High walk, few barriers :: Use as the sector reference. :: high",
                      "Constrained :: Low walk, many barriers :: Ask for contingency plans and policy engagement. :: mid",
                      "Ahead in a hard sector :: High walk, many barriers :: Support, and record the barriers it faces. :: neutral"],
        "items": ["Barrier ratings", "105 cells: 35 criteria, 9 hard-to-abate sectors", "Regions: EU, US and China", "Backed by 86 verified sources"],
        "takeaway_bar": "Status: barrier ratings sit alongside plan scores today; joining them per company is planned, not built."},
       ["ARP Transition Barrier Assessment, 2026"], "The 2x2 is the framing; no company is placed on it here."),
    _s("decisions", "default", "Decisions requested", {
        "items": ["Agree the pilot sample :: We run the assessment on a sample of your holdings and share the grids",
                  "Calibrate with your analysts :: Review the flagged verdicts together to calibrate confidence",
                  "Pick the engagement gaps :: Agree which walk-score gaps to raise in your next cycle"]},
       [], "Close by agreeing the sample and the review session."),
]


def tpa_pitch_committee() -> tuple[ReportRequest, Storyline, list[SlideContent]]:
    req, story, _ = tpa_pitch()
    notes = req.qualitative_notes + "\nWalk share by category (walk / indicators): Target 0%, Governance 22%, Strategy 71%, Tracking 79%, all 53%."
    req = req.model_copy(update={"qualitative_notes": notes, "datasets": [*req.datasets, counts], "layout": req.layout.model_copy(update={"density": "committee"})})
    return req, story, [f.model_copy(deep=True) for f in FILLS]

