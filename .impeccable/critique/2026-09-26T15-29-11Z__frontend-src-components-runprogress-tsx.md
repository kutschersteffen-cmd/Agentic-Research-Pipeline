---
target: run-stage stepper in RunProgress
total_score: 18
max_score: 40
na_heuristics: 
p0_count: 1
p1_count: 2
target_identity: "file:/home/user/Agentic-Research-Pipeline/frontend/src/components/RunProgress.tsx"
target_fingerprint: "sha256:27809bc84059554883c8fa1890749aef71a5b958d3aade1901378963f52e44a4"
target_path: /home/user/Agentic-Research-Pipeline/frontend/src/components/RunProgress.tsx
timestamp: 2026-09-26T15-29-11Z
slug: frontend-src-components-runprogress-tsx
---
Method: dual-agent (A: design review · B: detector + browser)

Heuristics: 1 Status 2 | 2 Real world 2 | 3 Control 2 | 4 Consistency 1 | 5 Error prevention 2 | 6 Recognition 3 | 7 Efficiency 1 | 8 Minimalist 2 | 9 Error recovery 1 | 10 Help 2 | Total 18/40 (Poor)

Specificity: generic four-dot stepper; only "Human review" is product-specific, and it never resolves. Queued/Finished duplicate the status pill.
Detector: RunProgress.tsx 0 findings. Browser: 7 anti-patterns, none on the stepper (layout-transition on pre-existing .progress-bar-fill index.css:409; cream-palette on body = deliberate theme). Browser caught the pending mark/connector contrast at 1.39:1 (needs 3:1).

Priority issues:
- [P0] Failed/cancelled runs show Human review ✓ "Nothing flagged" over unprocessed companies. Fix: ✓ only when completed and 0 flagged; else "Not reached · N not processed". (harden)
- [P1] Numerator mismatch (215 processed vs 212 companies) and green ✓ on partial runs next to amber pill. Fix: "390 done · 10 failed of 400"; amber warning state for partial. (clarify)
- [P1] Human review permanently current and pulsing on historic runs. Fix: pulse only while pending/running; static "awaiting sign-off" state linked to the review queue; ideally backend reviewed count. (harden)
- [P2] Failure marked twice (Processing ! + Finished ! failed). Fix: mark Processing only with "Stopped at 41/400" + inline error; later steps "not reached". (distill)
- [P2] Pending marks/connectors 1.39:1; 12px details carry the numbers. Fix: --neutral pending border, --text-sm details, filled accent current disc. (polish)

Personas: Alex – count mismatch, no link to queue, wants one-line compact form. Sam – raw enum state words, no live region. Stewardship analyst – stepper pushes Resume down on phone; green vs amber prompts "finished or not?" in committee.

Minor: status.replace only first underscore, pill raw enum; start time for Queued; "Human review · 9 flagged" during run reads as review underway; label/state text concatenated in DOM.
