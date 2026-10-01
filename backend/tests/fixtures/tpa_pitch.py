"""The TPA pitch deck (report rpt_539893ef602b, 2026-10-01) as a golden brief, ported verbatim from the session's build script.

Layouts are the ones the deck was built with (bullets etc.), so the art director has real work to do.
"""
# ruff: noqa: E501

from arp.schemas.reporting import (
    AudienceLevel,
    AudienceProfile,
    ChartSpec,
    ChartType,
    ColumnKind,
    DatasetColumn,
    LayoutInstructions,
    OutputFormat,
    QuantitativeDataset,
    ReportRequest,
    SlideContent,
    Storyline,
    StorylineSlide,
    TableSpec,
    Tone,
)

NOTES = """Transition Plan Assessment replicates Colesanti Senni, Schimanski, Bingler, Ni and Leippold (2024),
'Using AI to assess corporate climate transition disclosures', Environmental Research Communications.
The study scored 143 Climate Action 100+ companies and found disclosure skews toward talk (targets) over walk (implementation).
Its guidelines were validated by 28 domain experts across 26 institutions.
The tool scores every company on 64 fixed yes/no indicators in 4 categories: Target 12, Governance 9, Strategy 24, Tracking 19.
34 indicators are walk and 30 are talk. Walk by category: Target 0, Governance 2, Strategy 17, Tracking 15.
For each indicator it retrieves the 8 most relevant passages, an answer model gives YES/NO/NA with up to 200 words and verbatim citations,
a different verifier model re-checks the verdict, and code re-verifies every quote against the source document.
Unverified or disputed verdicts go to a review queue; analysts approve, edit or reject with comments and full history.
Outputs: per-company evidence grid of 64 rows, walk score, talk score, category breakdown, review flags, export to Decision Studio with zero LLM calls,
joinable with extraction, financials and TNFD runs.
Transition Barrier Assessment: 105 cells (35 criteria across 9 hard-to-abate sectors, EU/US/China) backed by 86 verified sources."""

cats = QuantitativeDataset(dataset_id="ds_cats", name="Indicators by category", description="Walk and talk indicators per category (indicators.json)",
    columns=[DatasetColumn(name="Category", kind=ColumnKind.CATEGORY), DatasetColumn(name="Walk", kind=ColumnKind.NUMBER), DatasetColumn(name="Talk", kind=ColumnKind.NUMBER)],
    rows=[{"Category": "Target", "Walk": 0, "Talk": 12}, {"Category": "Governance", "Walk": 2, "Talk": 7},
          {"Category": "Strategy", "Walk": 17, "Talk": 7}, {"Category": "Tracking", "Walk": 15, "Talk": 4}])
outs = QuantitativeDataset(dataset_id="ds_outputs", name="What you receive",
    columns=[DatasetColumn(name="Output", kind=ColumnKind.CATEGORY), DatasetColumn(name="Contents", kind=ColumnKind.CATEGORY)],
    rows=[{"Output": "Evidence grid", "Contents": "64 rows per company: verdict, quote, source, confidence"},
          {"Output": "Walk score", "Contents": "Share of the 34 walk indicators disclosed"},
          {"Output": "Talk score", "Contents": "Share of the 30 talk indicators disclosed"},
          {"Output": "Category view", "Contents": "Disclosure across target, governance, strategy and tracking"},
          {"Output": "Review flags", "Contents": "Indicators an analyst should check"}])

PAPER = "Colesanti Senni et al. (2024), Environmental Research Communications"
TOOL = "ARP Transition Plan Assessment, methodology and indicator set"
H = [
 "Published research finds companies talk about transition far more than they act on it",
 "We test every plan against the same 64 indicators from peer-reviewed research",
 "34 of the 64 indicators test action already under way, not targets",
 "Every verdict quotes the report word for word, and code checks the quote",
 "A second, different model re-checks each verdict before it is accepted",
 "Uncertain verdicts go to an analyst, and every decision is logged",
 "You get a 64-row evidence grid per company and a walk-versus-talk score",
 "Results feed straight into ranking and engagement work, with no retyping",
 "Sector barrier ratings show whether a weak plan reflects ambition or headroom",
 "A pilot on your own holdings is the next step",
]
story = Storyline(title="Transition plans you can check, indicator by indicator", subtitle="Transition Plan Assessment",
                  slides=[StorylineSlide(headline=h, purpose="pitch") for h in H])

def S(layout, variant, slots, refs, notes, **kw):
    return SlideContent(headline="x", layout=layout, variant=variant, slots=slots, source_refs=refs, speaker_notes=notes, **kw)

fills = [
 S("big_number", "two", {"number_1": "143", "label_1": "Climate Action 100+ companies scored in the study",
                          "number_2": "28", "label_2": "Domain experts from 26 institutions validated its method"},
   [PAPER], "The study found disclosure leans toward targets and away from implementation. That gap is what clients want measured."),
 S("big_number", "two", {"number_1": "64", "label_1": "Fixed yes-or-no indicators, the same for every company",
                          "number_2": "4", "label_2": "Categories: target, governance, strategy and tracking"},
   [PAPER, TOOL], "Indicators are taken verbatim from the paper's reference code, so results compare across companies and years."),
 S("chart_takeaway", "chart_left", {"takeaway": "Strategy and tracking hold most walk indicators, 17 and 15. Target indicators are all talk, so a plan built on targets scores low on walk."},
   [TOOL], "Walk means a concrete, checkable activity. Talk means a target or general intention.",
   chart=ChartSpec(dataset_id="ds_cats", chart_type=ChartType.BAR, category_column="Category", value_columns=["Walk", "Talk"])),
 S("bullets", "three", {"items": ["Each verdict cites a verbatim passage from the company's own report.",
                                  "Code checks every quote against the source document before the verdict counts.",
                                  "A verdict whose quote cannot be found is flagged for review."]},
   [TOOL], "This is the main difference from the paper's tool, which trusts the model's own list of sources."),
 S("two_column", "text_text", {"left": "First pass. A model reads the eight most relevant passages for each indicator and answers yes, no or not applicable, with an explanation of up to 200 words.",
                               "right": "Second pass. A different model rereads the same passages, checks that the quote supports the verdict and looks for vague claims. If it disagrees, its verdict stands and the indicator is marked for review."},
   [TOOL], "Using two different models means the second check is independent of the first."),
 S("bullets", "three", {"items": ["Indicators without verified evidence, or where the two models disagree, go to a review queue.",
                                  "Analysts approve, edit or reject each flagged verdict and add a comment.",
                                  "Every decision keeps its reviewer, time and history for audit."]},
   [TOOL], "Nothing uncertain is accepted at face value."),
 S("table", "highlight", {"takeaway": "The gap between walk and talk scores is the number to raise in engagement."},
   [TOOL], "Each grid row links back to the passage it rests on.", table=TableSpec(dataset_id="ds_outputs", columns=["Output", "Contents"])),
 S("bullets", "three", {"items": ["Scores export to Decision Studio as ranked, tiered columns with no model calls.",
                                  "They join with emissions, financials and nature data on the same companies.",
                                  "Engagement teams can use the walk score to pick which plans to question first."]},
   [TOOL], "The export is deterministic, so the same run always gives the same ranking."),
 S("big_number", "three", {"number_1": "105", "label_1": "Sector and region cells rated for transition barriers",
                            "number_2": "86", "label_2": "Verified public sources behind those ratings",
                            "number_3": "3", "label_3": "Regions covered: EU, US and China"},
   ["ARP Transition Barrier Assessment, 2026"], "Barrier ratings sit alongside plan scores today; joining them per company is planned, not built."),
 S("summary", "default", {"items": ["We run the assessment on a sample of your holdings and share the evidence grids.",
                                    "Your analysts review the flagged verdicts with us to calibrate confidence.",
                                    "We agree which walk-score gaps to raise in your next engagement cycle."]},
   [], "Close by agreeing the sample and the review session."),
]


def tpa_pitch() -> tuple[ReportRequest, Storyline, list[SlideContent]]:
    req = ReportRequest(title=story.title, qualitative_notes=NOTES, datasets=[cats, outs],
        goal="The client commissions a pilot of Transition Plan Assessment on its holdings",
        audience=AudienceProfile(level=AudienceLevel.EXECUTIVE, tone=Tone.PERSUASIVE, description="Client investment and stewardship leads"),
        layout=LayoutInstructions(output_format=OutputFormat.HOUSE_DECK, theme="light", density="present"))
    return req, story, [f.model_copy(deep=True) for f in fills]
