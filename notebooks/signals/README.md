# Signal notebooks

Percent-format Python scripts (`# %%` cells) that use the Signal Lab through `arp.signal_lab.lab.Lab`.
They are plain `.py` files so they diff and test cleanly.

## Example

`narrative_momentum.py` ingests transcripts, previews a `narrative_attention` signal, checks it for look-ahead,
registers it and a z-scored variant, and compares the two. It reads three settings:

- `ARP_NB_PRICES`: month-end price CSV (`date` column, one column per issuer).
- `ARP_NB_TRANSCRIPTS`: transcript CSV with `issuer_key`, `event_time`, `title`, `text`.
- `ARP_POSTGRES_DSN` (and optionally `ARP_RUNS_DIR`, `ARP_TRAINING_CUTOFFS_PATH`): the text store and run registry.

Run it as a script (`python notebooks/signals/narrative_momentum.py`) or as a notebook. Re-running is safe: the
same transcripts add nothing and the same recipes are not registered twice.

## Opening as a notebook

```
pip install 'arp[notebooks]'
jupytext --to ipynb notebooks/signals/narrative_momentum.py   # writes narrative_momentum.ipynb
jupyter lab
```

Or open the `.py` directly in JupyterLab: right-click it, then "Open With" and "Notebook" (needs jupytext installed).

## Previews are not evidence

`lab.preview(...)` prints `[unregistered, not evidence]`. It has no experiment id, and `compare` and `decide`
refuse it. Only `lab.run(...)` registers an experiment, and only registered experiments can be compared or graduated.
`insufficient_data` from `compare` is a valid answer, not an error.
