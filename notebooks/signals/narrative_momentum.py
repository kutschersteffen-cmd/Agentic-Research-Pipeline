# %% [markdown]
# # Narrative momentum
# How much do earnings calls talk about a theme, and does a rise in that talk predict returns?
# Set `ARP_NB_PRICES` (month-end price CSV) and `ARP_NB_TRANSCRIPTS` (issuer_key, event_time, title, text CSV),
# plus `ARP_POSTGRES_DSN` for the text store and run registry.

# %%
import csv
import os
from pathlib import Path

from arp.signal_lab.adapters.transcripts import CsvTranscriptSource
from arp.signal_lab.lab import Lab
from arp.signal_lab.registry import Recipe

prices = Path(os.environ["ARP_NB_PRICES"])
transcripts = Path(os.environ["ARP_NB_TRANSCRIPTS"])
lab = Lab.from_settings()

# %% [markdown]
# ## Ingest
# Same path as `arp signals ingest-transcripts`. Items are keyed by content, so re-running adds nothing.

# %%
records = CsvTranscriptSource(transcripts).records()
new = sum(lab.text_store.add(r) for r in records)
print(f"{len(records)} records, {new} new")

# %% [markdown]
# ## Define the signal
# The window starts a year into the price file; the earlier months are history the method may read.

# %%
with prices.open(newline="") as f:
    dates = [row[0] for row in list(csv.reader(f))[1:]]
spec = {"method": "narrative_attention", "params": {"terms": ["AI", "artificial intelligence"], "lookback_months": 3}}
recipe = Recipe(
    category="sentiment_narrative", method=spec["method"], text_source=None, params=spec["params"],
    universe="notebook", window_start=dates[12], window_end=dates[-1],
)
inp, data_version = lab.inputs(recipe, prices, texts=lab.texts(), history_from=dates[0])

# %% [markdown]
# ## Preview
# A preview is quick feedback, not evidence: it has no experiment id and cannot be compared or graduated.

# %%
preview = lab.preview(spec, inp)
print(preview)

# %% [markdown]
# ## Look-ahead check
# Lists (issuer, month index) wherever a score changes when later data is cut off. Empty is what you want.

# %%
violations = lab.check(spec, inp)
print(f"look-ahead violations: {violations}")

# %% [markdown]
# ## Run as a registered experiment
# Registration is what makes a result count. Running the same recipe on the same data again returns the same record.

# %%
base = lab.run(recipe, inp, data_version)
print(f"experiment_id: {base.experiment_id}")

# %% [markdown]
# ## A variant: cross-sectional z-score of the same signal
# Same universe, window and cost, so the two can be compared.

# %%
variant_recipe = recipe.model_copy(update={"method": "transform", "params": {"base": spec, "steps": [{"op": "zscore"}]}})
variant = lab.run(variant_recipe, inp, data_version)
print(f"experiment_id: {variant.experiment_id}")

# %% [markdown]
# ## Compare
# Only post-cutoff months count, and the verdict is corrected for how many experiments share this scope.
# `insufficient_data` is a valid answer when there are too few months to separate them.

# %%
result = lab.compare(base.experiment_id, variant.experiment_id)
print(f"{result.verdict} ({result.months} common post-cutoff months, corrected for {result.n_comparisons} comparisons)")
if result.reason:
    print(result.reason)
