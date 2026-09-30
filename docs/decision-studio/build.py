"""Builds one page per Decision Studio node. Content comes from
arp/schemas/decision.py, arp/decision/*.py and docs/DECISION_MECHANISM.md;
examples are the sample table run through the engine."""
from pathlib import Path

OUT = Path(__file__).parent

NODES = [
    ("data", "1", "Data", False),
    ("profile", "2", "Profile", True),
    ("rules", "3", "Rules", False),
    ("mechanism", "4", "Mechanism", True),
    ("tree", "5", "Decision tree", True),
    ("results", "6", "Results", True),
    ("movement", "7", "Movement", False),
    ("audit", "8", "Audit", True),
    ("output", "", "Published tiers", False),
]


def table(head, rows):
    h = "".join(f"<th>{c}</th>" for c in head)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'


def block(title, intro, body=""):
    p = f"<p>{intro}</p>" if intro else ""
    return f'<section class="block"><h2>{title}</h2>{p}{body}</section>'


def steps(items):
    return '<ol class="order">' + "".join(f"<li><b>{a}</b><span>{b}</span></li>" for a, b in items) + "</ol>"


def ex(items):
    return "".join(f'<div class="ex-i"><code>{c}</code><p>{r}</p></div>' for c, r in items)


PAGES = {}

# ---------------------------------------------------------------- 1 Data
PAGES["data"] = dict(
    lede="Gets the table the decision rests on: one row per entity, one column per indicator. Every other tab stays locked until a table is selected.",
    blocks=[
        block("Three ways in", "Pick one. All three end in the same kind of saved table.", table(
            ["Route", "What it does", "When to use it"], [
                ["Upload a file", "CSV, TSV, TXT, XLSX or XLS. Parsed on the server.", "A table from outside the system: a vendor export, a spreadsheet."],
                ["Build from a run", "Turns one of this system's runs into a table through a source adapter (below).", "Scoring what the pipeline already produced."],
                ["Apply a template", "Loads a saved framework onto the selected table. The list shows each template's fit: <em>fits</em>, or <em>needs</em> and the missing columns.", "Repeating last quarter's decision on this quarter's data."],
            ])),
        block("Source adapters", "Each adapter names what one row is. Three of them are not companies: the engine scores rows.", table(
            ["Source", "One row per", "Columns it produces"], [
                ["Transition plan run", "company", "Disclosed count, walk/talk split, per-category disclosure %, confidence. Optional: one Yes/No column per indicator (<code>Ind_&lt;id&gt;_Disclosed</code>)."],
                ["Extraction run", "company", "One column per schema field, each cell's confidence carried; zero where the citation did not ground."],
                ["Financials run", "company", "CapEx and R&amp;D totals, segment count, summed segment revenue, as reported (no currency conversion)."],
                ["TNFD run", "company", "One Yes/No per TNFD recommendation, count disclosed, grounded core metrics per category."],
                ["Joined runs", "company", "Two or more of the four above, matched on <code>Company_Id</code> or name. Shared columns get a prefix: <code>TP_</code>, <code>Extraction_</code>, <code>Financials_</code>, <code>TNFD_</code>."],
                ["Thematic universe run", "company", "Activities included, best and mean exposure, adjudicator confidence."],
                ["Portfolio snapshot + climate", "company", "Holdings on one date joined to climate data points. <code>market_value_eur</code> becomes the size column."],
                ["Transition barrier matrix", "sector × region", "Per-pillar feasibility, confidence, staleness. Reference data; needs no run. Filter by region."],
                ["Emerging themes run", "theme", "Velocity, breadth, persistence, novelty, action score, materiality, grounded-source share, status."],
                ["Strategy replication runs", "strategy", "In/out-of-sample Sharpe and return, persistence, max drawdown, deflated Sharpe, verdict."],
            ])),
        block("Parsing logic", "Runs on every upload, so a file reads the same way every time.", table(
            ["Rule", "What it does", "Why"], [
                ["Delimiter", "Picks the delimiter that gives the most <em>consistent</em> column count, not the most frequent character.", "A free-text column full of commas would otherwise beat the semicolons that separate fields."],
                ["Number format", "Detected per column from its values. <code>1.234,5</code> reads as 1234.5.", "Read wrongly, it becomes 1.234: plausible and wrong, with no error."],
                ["Yes/No values", "<code>yes, ja, wahr, x, 1</code> and their negatives are read as booleans.", "Bilingual exports need no cleaning."],
                ["Confidence", "Carried per cell when the source has it (every extraction-based table does).", "Grounded coverage on the Mechanism tab needs it."],
            ])),
    ],
    example=[
        ("example_transition_universe.csv", "Sniffed as comma-delimited: 24 rows × 17 columns."),
        ("Scope12_Intensity;1.234,5", "Illustration: a semicolon export with comma decimals would read as 1234.5."),
        ("Template fit: needs Green_Capex_Share_pct", "Illustration: a template picker line for a table that lacks one column."),
    ],
)

# ---------------------------------------------------------------- 2 Profile
PAGES["profile"] = dict(
    lede="Tells you what each column is and proposes a job and a direction for it. This is where you catch a guess before it inverts a ranking.",
    blocks=[
        block("Column type, from the values", "The header is not trusted: it can lie or be in another language.", table(
            ["Type", "Recognised when"], [
                ["numeric", "Values parse as numbers (and are not ordinal)."],
                ["ordinal", "Whole numbers with 7 or fewer distinct values (e.g. 0–3, 0–5)."],
                ["boolean", "95%+ of values are Yes/No vocabulary, at most 3 distinct."],
                ["categorical", "Text with few distinct values: sector, region."],
                ["identifier", "Looks like a code: ISIN, LEI, ids."],
                ["text", "Free text with many distinct values."],
            ])),
        block("What the profile table shows", "Columns: Column, Type, Coverage, Distinct, Job, Direction, Why.", table(
            ["Figure", "Meaning"], [
                ["Coverage", "Share of rows with a value."],
                ["Distinct", "Number of different values."],
                ["Quantiles", "min, p5, Q1, median, Q3, p95, max, mean, sd; for Yes/No, the share of Yes."],
                ["Spread flag", "Set when every present value is the same. Such a column cannot tell entities apart."],
            ])),
        block("The seven jobs", "Proposed for every column. Change any of them.", table(
            ["Job", "What the engine does with it"], [
                ["label", "Names each row. The first high-cardinality text column."],
                ["reference", "Carried through, never scored (ISIN, ids)."],
                ["size", "Position size (<code>weight</code>, <code>bps</code>, <code>aum</code>). Used for leverage only, never as a criterion."],
                ["gate", "A Yes/No flag with exclusion wording. Becomes a gate on the Decision tree tab."],
                ["criterion", "Scored. Numeric, ordinal or Yes/No with spread."],
                ["segment", "A grouping. Can become the peer cohort."],
                ["excluded", "Ignored: no spread, free text, or you turned it off."],
            ])),
        block("Direction", "Higher-is-better or lower-is-better, inferred from the column name against keyword dictionaries.", table(
            ["Case", "Result"], [
                ["Name matches one dictionary", "Direction set, reason shown: <em>name matches intensity, co2</em>."],
                ["Name matches both", "Heavier keyword wins, and the proposal is marked <b>needs check</b>."],
                ["Name matches neither", "Defaults to higher, marked <b>needs check</b>."],
            ]) + '<p class="note">The dictionaries live in <code>arp/decision/data/role_keywords.json</code> as data, so a house that reports in a third language extends them with an edit, not a code change.</p>'),
    ],
    example=[
        ("Portfolio_Weight_bps", "<b>size</b>: name signals position size, not quality."),
        ("Scope12_Intensity_tCO2e_per_mEUR", "<b>criterion, lower is better</b>: name matches intensity, co2."),
        ("Emissions_Data_Coverage_pct", "<b>higher is better, needs check</b>: name also matches the opposite dictionary."),
        ("Severe_Controversy_Flag", "<b>gate</b>: binary flag with exclusion-type wording."),
        ("Region", "<b>segment</b>: 4 levels, proposed as the peer cohort."),
        ("ISIN", "<b>reference</b>: looks like an identifier."),
    ],
)

# ---------------------------------------------------------------- 3 Rules
PAGES["rules"] = dict(
    lede="Adds calculated columns before anything is scored. Drawn on a canvas as a decision model and evaluated once per row.",
    blocks=[
        block("Node types you can use", "Only declarative nodes. The schema refuses anything that runs code or loads another graph.", table(
            ["Node", "What it does", "Example"], [
                ["Input", "The row: every column by name or slug (<code>Scope 1 (t)</code> → <code>scope_1_t</code>).", ""],
                ["Expression", "One output per line. Formulas and AND/OR conditions. Earlier outputs in the same box are <code>$.name</code>.", "<code>capex / revenue * 100</code>"],
                ["Decision table", "Columns combine with AND, rows with OR. First matching row wins.", "sector = Utilities AND coal = Yes → high_risk = true"],
                ["Switch", "Sends the row down one branch by condition.", "region = EU → EU rule set"],
                ["Output", "Every key that is not already a column becomes a calculated column.", ""],
                ["Function, Decision (sub-graph)", "<b>Refused.</b> Function runs JavaScript; Decision loads another graph.", ""],
            ])),
        block("Three rules that keep the source in charge", "", table(
            ["Rule", "What happens"], [
                ["Never overwrite a source column", "An output named like an existing column is dropped and logged."],
                ["A failing row gets blanks", "Null arithmetic or division by zero leaves that row's calculated values empty. The count and the first error are logged as needs check."],
                ["Server values are the record", "The browser runs the same engine for a live preview. Scoring always re-runs the rules on the server."],
            ])),
        block("What a calculated column can become", "It is profiled and proposed a job like any other column.", table(
            ["Output type", "Typical job"], [
                ["Number (ratio, share, difference)", "criterion"],
                ["Yes/No (AND/OR condition)", "gate: a compound gate needs no second gate system"],
                ["Text (category)", "segment or cohort"],
            ])),
    ],
    example=[
        ("coal_expansion_flag and not sbti_validated_target", "New Yes/No column. Yes for Vega Power, Tarn Mining, Kalahari Resources."),
        ("green_capex_share_pct / 100", "Zenith REIT has no Green Capex value, so its result is blank and it is logged, not an error."),
        ("Portfolio_Weight_bps (as output name)", "Dropped and logged: rules never overwrite a source column."),
    ],
)

# ---------------------------------------------------------------- 4 Mechanism
PAGES["mechanism"] = dict(
    lede="Decides how criteria become a score: the scale, how values are compared, which criteria are grouped, and how much each group weighs.",
    blocks=[
        block("Scoring mode", "The first choice on the tab. Everything below depends on it.", table(
            ["Mode", "How a criterion is scored", "Use it when"], [
                ["Relative to the other companies", "Normalised against the other entities in the table. A score moves when the peers change.", "You want to know who stands where in this field."],
                ["Fixed levels from rules", "Each criterion gets a level on a fixed scale (e.g. 1–7) from rules over the entity's own data.", "A threshold must mean the same for everyone: \"target coverage ≥ 65% is level 4\"."],
            ])),
        block("Normalisation (relative mode)", "", table(
            ["Option", "What it does"], [
                ["Percentile rank <em>(default)</em>", "Rank within the field, 0–100. Unaffected by outliers and units."],
                ["Min–max", "Linear between the lowest and highest value."],
                ["Z-score", "50 + 15 × (standard deviations from the mean), clamped to 0–100."],
                ["Winsorise tails", "0–20%, default 5%. Clips extremes before min–max and z-score."],
                ["Direction", "Lower-is-better criteria are flipped to <code>100 − v</code>."],
                ["Yes/No", "Straight to 0 or 100; no winsorising."],
                ["A lone value", "Maps to 50: with nothing to compare against, neither extreme is defensible."],
            ])),
        block("Peer cohorts", "", table(
            ["Setting", "Default", "What it does"], [
                ["Normalise within", "none (proposed from a segment column)", "Each criterion is normalised inside its sector or region."],
                ["Minimum cohort size", "5", "Smaller cohorts fall back to the whole table: a percentile over three peers is noise."],
            ])),
        block("Dimensions", "Correlated criteria are grouped so one theme measured many ways is not counted many times.", table(
            ["Setting", "What it does"], [
                ["Cluster threshold", "Default 0.72. Two criteria join a dimension only if their Spearman rank correlation clears it."],
                ["Complete linkage", "<em>Every</em> pair in a dimension must clear the threshold, so a chain of moderate links cannot merge unrelated criteria."],
                ["Naming", "From the words members share, else the member most typical of the rest."],
                ["Your edits", "Move a criterion between dimensions, disable it, or set its weight to 0 to park it."],
            ])),
        block("Weighting", "Weights are relative; the engine normalises them to 100%.", table(
            ["Preset", "How weight is shared"], [
                ["Breadth-adjusted <em>(default)</em>", "A dimension weighs √(criteria count), split evenly among its members."],
                ["Equal", "Every criterion the same."],
                ["Discriminating power", "Entropy weights: criteria that spread entities apart more get more."],
                ["Manual", "Your numbers per dimension and criterion."],
            ])),
        block("Missing values", "", table(
            ["Policy", "A blank value…"], [
                ["Re-weight <em>(default)</em>", "Leaves the entity's weight base. Nothing is invented."],
                ["Neutral", "Counts as 50."],
                ["Mean", "Counts as the column mean."],
                ["Penalise", "Counts as 25."],
            ]) + '<p class="note">With <b>require grounded coverage</b> on, sufficiency counts only values whose confidence clears the bar (default 0.8). Needs a table with per-cell confidence.</p>'),
        block("Levels mode", "Replaces normalisation and derived dimensions.", table(
            ["Part", "Logic"], [
                ["Scale", "<code>level_min</code>..<code>level_max</code>, default 1–7."],
                ["Clusters", "Named and weighted by hand."],
                ["Level rules", "Ordered <code>level</code> + <code>when</code> conditions. The first that holds sets the level; <em>otherwise</em> is the fallback."],
                ["Blanks", "A comparison with a blank never holds, so missing data never earns a level."],
                ["Scores", "Cluster = weighted average of its levels; total = weighted average of clusters. Both on the scale."],
                ["Checks on save", "A condition that does not parse, or a level off the scale, is refused."],
            ])),
    ],
    example=[
        ("5 criteria, Spearman 0.86–0.98", "Target ambition, plan disclosure, data coverage, lobbying, say-on-climate become one <b>Climate Lobbying group</b>."),
        ("Green capex + board oversight, 0.89", "Grouped as <b>Green Capex group</b>."),
        ("weight √5 = 2.24", "The 5-criterion group gets <b>33.6%</b> (6.7% each). Scope 1+2 intensity alone keeps <b>15%</b>."),
        ("cohort = Region, min 5", "UK has 4 companies, so UK values rank against the whole table."),
        ("level 4 when target_coverage_pct >= 65", "Levels mode illustration: the same company gets level 4 in any table."),
    ],
)

# ---------------------------------------------------------------- 5 Decision tree
PAGES["tree"] = dict(
    lede="Turns scores into tiers in a fixed order. The order is what makes a result reproducible.",
    blocks=[
        block("The fixed order", "", steps([
            ("1 · Sufficiency", "Weight covered below the minimum (default 60%) → routed to data collection, not ranked."),
            ("2 · Hard gates", "An <em>exclude</em> gate removes the entity before any averaging."),
            ("3 · Score band", "Cut-points are drawn over the entities still eligible."),
            ("4 · Modifiers", "Demote gates and the dimension floor move an entity down."),
        ])),
        block("Gates", "A gate is a decision, not a deduction. A blank value never triggers one.", table(
            ["Operator", "Meaning", "Works on"], [
                ["is", "equals", "Yes/No, text, numbers"],
                ["is not", "differs", "Yes/No, text, numbers"],
                ["&lt;", "below", "numbers"],
                ["&gt;", "above", "numbers"],
                ["=", "equals the number", "numbers"],
            ]) + table(["Outcome", "Effect"], [
                ["Exclude outright", "Out of scoring and tiers. Does shift peers' cut-points (it is removed first)."],
                ["Demote one tier", "Scored and banded, then moved one tier down. Several demotions stack."],
                ["Flag only", "Tier unchanged; a note is added."],
            ])),
        block("Cut-points", "", table(
            ["Mode", "How the lines are drawn"], [
                ["Quantile <em>(default)</em>", "Evenly between the 20th and 80th percentile. For 4 tiers: 80 / 50 / 20."],
                ["Natural breaks", "At the widest gaps between scores. Each band keeps at least 10% of entities. Too few distinct scores → falls back to quantile, and says so."],
                ["Fixed", "Your numbers. They survive a re-run on new data. Changing the tier count re-spaces them evenly."],
            ])),
        block("Dimension floor", "One strong dimension should not carry an entity that fails elsewhere.", table(
            ["Setting", "Default", "Effect"], [
                ["Enabled", "on", ""],
                ["Minimum dimension score", "30", "Below it → demoted one tier."],
                ["Minimum criteria in the dimension", "2", "A dimension resting on one Yes/No answer cannot demote."],
            ])),
        block("Tiers", "Default four, named Tier 1 to Tier 4, with no actions. Tier 1 is the highest score band. Rename them, add or remove tiers, and give each an action.", ""),
        block("Tier rules (optional)", "A second decision model that <b>replaces steps 2 and 4</b>. Sufficiency and cut-points stay in the engine.", table(
            ["", "Available"], [
                ["Inputs", "<code>band</code>, <code>score</code>, <code>rank</code>, <code>percentile</code> in cohort, <code>coverage</code>, <code>grounded_coverage</code>, <code>dim_&lt;dimension&gt;</code>, <code>cohort</code>, <code>segment</code>, <code>tier_count</code>, every column."],
                ["Outputs", "<code>tier</code> (1..tier count), optional <code>exclude</code>, optional <code>note</code>. Starts as <code>tier = band</code>."],
                ["Red flags", "Tick Yes/No columns; each becomes a first-placed row sending Yes to a chosen tier with the note <em>Red flag: &lt;column&gt;</em>."],
                ["Safety", "Unevaluable row or out-of-range tier → keeps its band, flagged. Moving an entity <em>up</em> is allowed and flagged."],
            ])),
    ],
    example=[
        ("Severe_Controversy_Flag is Yes → exclude", "<b>5 excluded</b>: Sable, Tarn, Sunda, Severn Vale, Kalahari."),
        ("coverage 37% < 60%", "Zenith REIT → <b>data collection</b>."),
        ("quantile cuts 86.5 / 64.6 / 34.8", "Drawn over the 18 still eligible."),
        ("Coal_Expansion_Flag is Yes → demote", "Vega Power: Tier 4."),
        ("floor: Climate Lobbying group < 30", "Kestrel Airlines, Silverline Autoparts, Brera Fashion demoted to Tier 4."),
        ("floor: Green Capex group < 30", "Rheinpfad Logistik demoted to Tier 4."),
    ],
)

# ---------------------------------------------------------------- 6 Results
PAGES["results"] = dict(
    lede="Shows the outcome with its uncertainty next to it. Every number here comes back from the engine.",
    blocks=[
        block("What is on the tab", "", table(
            ["Element", "Shows"], [
                ["Tier cards", "Count per tier with its action, plus a card for <em>gated / insufficient</em>."],
                ["Score distribution", "Histogram with the cut lines, and which cut-point method actually ran."],
                ["Ranked table", "#, Name, Score, Rank band, Outcome, Coverage, Notes. Order by score or by leverage."],
                ["Explain (per row)", "Each criterion's normalised value, weight and contribution to the score."],
                ["Export CSV", "The ranked outcome as a file."],
            ])),
        block("Rank stability", "Each entity is scored under four specifications. Its best and worst rank form the rank band.", table(
            ["Specification", "Changes"], [
                ["The framework", "as configured"],
                ["Equal weights", "every criterion the same"],
                ["Entropy weights", "discriminating power"],
                ["Contrasting normalisation", "percentile or min–max → z-score; z-score → min–max"],
            ])),
        block("Leverage", "Where engagement moves the most: not who scores worst, but big positions far from perfect.", '<p class="formula">leverage = size × (100 − score) / 100</p>'),
        block("Sensitivity", "On demand, per entity. Each dimension's weight is swept across a range.", table(
            ["Result", "Meaning"], [
                ["Tipping point", "The weight at which the tier flips, the change needed, and the new tier."],
                ["Robust", "No weight in the range changes the tier."],
                ["Smallest change", "The minimum over all dimensions: the figure a committee asks for."],
            ])),
        block("Level overrides (levels mode)", "Set one criterion's level for one entity by hand.", table(
            ["Needs", "Result"], [
                ["Level, reason (3+ characters), your name", "Replaces the rules' level before averaging; the tier moves with it."],
                ["", "The rules' level stays on record; notes say <em>Override: criterion 1 → 5</em>; one audit entry per override."],
                ["", "An override that no longer fits (entity gone, criterion removed, level off scale) is dropped and flagged."],
            ])),
    ],
    example=[
        ("Lumen Semiconductor", "Score 100, rank 1, band 1–1. Tier 1."),
        ("Kanto Heavy Industries", "Tier 3, score 39.8, rank 12, <b>band 11–16</b>."),
        ("Kanto sensitivity", "Scope 3 weight 15% → 19.1% (<b>+4.1</b>) drops it to Tier 4. Climate Lobbying 33.6% → 14.4% does too."),
        ("Nordwind Energie sensitivity", "Tier 2, <b>robust</b> on all five dimensions."),
        ("47 bps × (100 − 25.1) / 100", "Vega Power leverage <b>35.2</b>, the highest in the table."),
        ("Tier cards", "Tier 1: 4 · Tier 2: 5 · Tier 3: 4 · Tier 4: 5 · Gated / insufficient: 5 / 1."),
    ],
)

# ---------------------------------------------------------------- 7 Movement
PAGES["movement"] = dict(
    lede="Applies the same framework version, unchanged, to an earlier table. Holding the framework fixed makes any movement belong to the entities.",
    blocks=[
        block("What it returns", "", table(
            ["Output", "Meaning"], [
                ["Counts", "improved, worsened, unchanged, entered (new in this table), left (gone)."],
                ["Per entity", "tier, score, rank and status before and after, with the deltas. A negative tier change is an improvement."],
                ["Drivers", "The criteria whose contribution moved most, largest first."],
            ])),
        block("Guards", "", table(
            ["Situation", "Result"], [
                ["Different framework or version on each side", "<b>Refused</b> with the reason: the difference would describe the frameworks."],
                ["Percentile scores on both sides", "Returned with a caveat: ranks show movement relative to the field, never absolute improvement."],
                ["A move with no driver", "Empty driver list: the shape of a data problem, not progress."],
            ]) + '<p class="note">For period-on-period work, score with min–max or z-score and fixed cut-points so the scale means the same in both tables.</p>'),
    ],
    example=[
        ("Q2 table + Q3 table, both v1", "Illustration: tier moves with drivers, e.g. a company rising because Scope3_Reported turned Yes."),
        ("Q2 by v1, Q3 by v2", "Refused."),
        ("percentile on both sides", "Result plus the rank-only caveat."),
    ],
)

# ---------------------------------------------------------------- 8 Audit
PAGES["audit"] = dict(
    lede="The record of every choice, and the actions that fix a framework as a citable version.",
    blocks=[
        block("One log, two halves", "", table(
            ["Origin", "Written when"], [
                ["derived", "The data proposed it: a role, a direction, a grouping, a gate."],
                ["human", "A person changed it. Saving diffs the framework against the version it came from; every difference becomes one entry. Dragging a node is not an edit."],
            ]) + '<p class="note">Each entry: stage, item, decision, why, needs check, origin, who, when.</p>'),
        block("Stages in the log", "Roles · Direction · Peer cohorts · Gates · Dimensions · Weighting · Normalisation · Missing data · Sufficiency · Cut-points · Comparability · Rules · Tier rules · Levels · Overrides · Edit · Import", ""),
        block("Actions", "", table(
            ["Action", "What it does"], [
                ["Save as new version", "Writes v<i>N</i>+1 with its own audit file. Saving over a ratified version is refused."],
                ["Ratify version <i>N</i>…", "Asks for your name. The version becomes fixed; decisions citing it read it as it is now."],
                ["Export as template", "Downloads one version with its audit trail as <code>arp.decision_template</code> JSON."],
                ["Publish to stewardship and index…", "Only for a ratified version. Freezes its result on this table (see Published tiers)."],
            ])),
        block("Where it is stored", "", table(
            ["File", "Holds"], [
                ["<code>frameworks/&lt;id&gt;/v<i>N</i>.json</code>", "The framework version."],
                ["<code>v<i>N</i>.audit.json</code>", "Derivation and edit trail for that exact version."],
                ["<code>latest.json</code>", "Pointer to the newest version."],
            ]) + '<p class="note">A real example, derived from the sample table, edited and ratified: '
            '<a href="example-framework/v1.json">v1.json</a> · <a href="example-framework/v1.audit.json">v1.audit.json</a> · '
            '<a href="example-framework/v2.json">v2.json</a> (ratified) · <a href="example-framework/v2.audit.json">v2.audit.json</a> · '
            '<a href="example-framework/latest.json">latest.json</a>. The last four entries of v2.audit.json are the human edits.</p>'),
    ],
    example=[
        ("derived · Direction · Scope12_Intensity…", "lower is better, because the name matches intensity, co2."),
        ("derived · Dimensions · Climate Lobbying group", "5 criteria grouped, rank correlation 0.86–0.98."),
        ("derived · Gates · Severe_Controversy_Flag", "hard exclusion: a knockout belongs in the tree, not the average."),
        ("human · Direction", "Illustration: you flip Emissions_Data_Coverage_pct. Logged with your name."),
        ("human · Edit · Cut-points", "85, 65, 35, pinned by hand by A. Reviewer (from <a href=\"example-framework/v2.audit.json\">v2.audit.json</a>)."),
        ("Ratify v2", "v2 fixed. Saving over it is refused: <em>v2 is ratified and cannot be overwritten</em>."),
    ],
)

# ---------------------------------------------------------------- Output
PAGES["output"] = dict(
    lede="A ratified framework's result, frozen and signed so other functions can read it. Nothing downstream ever reads a live, re-scorable result.",
    blocks=[
        block("Published snapshot", "", table(
            ["Field", "Content"], [
                ["Framework", "id, version, name"],
                ["Table", "dataset id and name, as-of date"],
                ["Matching", "the id column used to match issuers"],
                ["Sign-off", "published by, published at, note"],
                ["Rows", "entity id, name, score, tier, tier name, rank, rank min/max, status (scored, excluded, insufficient)"],
            ])),
        block("Who reads it", "", table(
            ["Reader", "How"], [
                ["Steward Workflow", "Coverage rules read <code>decision.&lt;framework_id&gt;.tier</code> and score as company fields. Nothing changes there until a person confirms tiers."],
                ["Index Construction", "Joins the scores in an index; nothing changes until a person runs an index review."],
            ])),
        block("Other ways out", "", table(
            ["Route", "What it does"], [
                ["CSV export", "The ranked outcome from the Results tab."],
                ["Template on a run", "Attach a framework to an Extraction, Financials, TNFD or Transition Plan run. It is copied into the run folder and scores the run when every company is done (<code>decision.json</code>). A failure there is recorded, never fails the run."],
                ["Publish from a run", "Stricter than the studio: the version must be ratified, the run finished, and no scored column missing."],
                ["Template import", "A template file becomes a new framework at v1, as a draft. Ratification does not travel with a file."],
            ])),
    ],
    example=[
        ("18 tiered", "Tier 1: 4 (260 bps) · Tier 2: 5 (395 bps) · Tier 3: 4 (151 bps) · Tier 4: 5 (130 bps)."),
        ("6 not tiered", "5 excluded by gate (status excluded), 1 sent to data collection (status insufficient)."),
        ("decision.fw_…​.tier", "Field a coverage rule would read for each published company."),
    ],
)


CSS_LINK = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700&amp;family=IBM+Plex+Mono:wght@400;500;600&amp;family=Newsreader:opsz,wght@6..72,400;6..72,500&amp;display=swap">'


def strip(current):
    out = ['<nav class="strip" aria-label="Decision Studio steps"><a class="home" href="index.html">Flow</a>']
    for slug, n, name, you in NODES:
        cls = "st" + (" you" if you else "") + (" out" if slug == "output" else "") + (" cur" if slug == current else "")
        aria = ' aria-current="page"' if slug == current else ""
        num = f"<span>{n}</span>" if n else ""
        out.append(f'<a class="{cls}" href="{slug}.html"{aria}>{num}{name}</a>')
    return "".join(out) + "</nav>"


for i, (slug, n, name, you) in enumerate(NODES):
    page = PAGES[slug]
    prev = NODES[i - 1] if i > 0 else None
    nxt = NODES[i + 1] if i + 1 < len(NODES) else None
    pager = '<div class="pager">'
    pager += f'<a href="{prev[0]}.html">← {prev[2]}</a>' if prev else '<a href="index.html">← Flow</a>'
    pager += f'<a href="{nxt[0]}.html">{nxt[2]} →</a>' if nxt else '<a href="index.html">Back to the flow →</a>'
    pager += "</div>"
    who = '<span class="pill you">You decide</span>' if you else ('<span class="pill">Output</span>' if slug == "output" else '<span class="pill">The engine computes</span>')
    num = f'<span class="num">{n}</span>' if n else ""
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{name} · Decision Studio</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
{CSS_LINK}
<link rel="stylesheet" href="style.css">
</head><body>
{strip(slug)}
<main class="page">
  <header class="ph">
    <div class="ph-t">{num}<h1>{name}</h1>{who}</div>
    <p class="lede">{page['lede']}</p>
  </header>
  <div class="cols">
    <div class="logic">{''.join(page['blocks'])}</div>
    <aside class="ex"><h2>From the sample table</h2><p class="src">24 companies in <code>example_transition_universe.csv</code>, run through the engine. Lines marked illustration are not from the sample.</p>{ex(page['example'])}</aside>
  </div>
  {pager}
</main>
</body></html>
"""
    (OUT / f"{slug}.html").write_text(html)
print("ok")
