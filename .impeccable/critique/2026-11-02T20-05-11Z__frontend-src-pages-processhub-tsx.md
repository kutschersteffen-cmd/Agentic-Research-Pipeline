---
target: start page
total_score: 26
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 1
target_identity: "file:/home/user/Agentic-Research-Pipeline/frontend/src/pages/ProcessHub.tsx"
target_fingerprint: "sha256:82fe408c784610665f767dfb7b06927dc1962652155a64f44bb6eb417587b878"
target_path: /home/user/Agentic-Research-Pipeline/frontend/src/pages/ProcessHub.tsx
timestamp: 2026-11-02T20-05-11Z
slug: frontend-src-pages-processhub-tsx
---
# Start page critique (after PR #311): 26/40 (Acceptable)
Method: dual-agent. Fixtures: busy, calm, backend down.
Heuristics: status 3, real world 3, control 3, consistency 2, prevention 3, recognition 3, flexibility 2, minimalism 3, recovery 3, help 1.
P1 card 'waiting on you' lines (5+7=12) still differ from the headline (14): cards leave out failed runs and blocking data issues. Sidebar badge (7) counts the review queue only, unlabelled.
P2 'Your name' field: empty-required border is amber (--mid), which reads as the signal colour from across a room.
P2 Needs-you rows are links but show no affordance (no arrow, hover only).
P2 cards still tall at >=1400px; NOW and Engagement fall below the fold at 1440x900.
P3 no explanation of what counts as a decision.
False positives: 'Signed in as Steffen ()' is the fixture's missing role; screen-reader dot labels exist (visually-hidden).
Detector: 0 CLI findings; overlay overused-font (Geist, light only), unstable.
