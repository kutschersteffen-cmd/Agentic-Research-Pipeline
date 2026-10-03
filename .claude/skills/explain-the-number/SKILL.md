---
name: explain-the-number
description: Use before you trust, report or act on a number you measured or extracted, such as a speedup, a latency, an eval score, a backtest result or a figure pulled from a disclosure. Find what limits it and rule out that it measured something else.
---

# Explain the number

A measured number is a claim about a system. Before you report it or act on it, find what limits it and rule out that it measured something other than the work you think.

**Why:** a run that went wrong still prints a plausible number. Failed requests, a cache that skipped the work, code that never ran, noise between runs and a side left on default settings all give results that look fine. If you cannot say why the number is not twice as good, you do not know what you measured.

- **Ask "why not double?"** Name what bounds the result (a core, a lock, the disk, the network, the model, the data) from a profile or counters taken during the run. A guess from reading the code is not a limiter.
- **List what else it could be measuring,** and rule out each with evidence: errors, skipped or cached work, noise, a piece too small to matter end to end.
- **Keep the evidence with the number:** run count, spread and the named limiter, in the notes or a linked artifact.

In this repo a number can also be an extracted figure or a score:

- An extracted figure must resolve to its grounded citation (`backend/arp/grounding.py`). If it cannot, it is not yet a number you can report.
- A backtest or index result needs the in-sample and out-of-sample split stated, and what the deflated Sharpe or constraint re-check said, not only the headline figure.

You skipped this when a number has no run count, no spread or no named limiter.

Adapted from pstack (Lauren Tan, MIT). See `../PSTACK-LICENSE.txt`.
