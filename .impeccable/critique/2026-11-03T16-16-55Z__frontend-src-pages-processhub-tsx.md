---
target: start page
total_score: 26
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 1
target_identity: "file:/home/user/Agentic-Research-Pipeline/frontend/src/pages/ProcessHub.tsx"
target_fingerprint: "sha256:5513824568637c494c7c1af5e018ca58def8a2aa43674f905c9ac00592954448"
target_path: /home/user/Agentic-Research-Pipeline/frontend/src/pages/ProcessHub.tsx
timestamp: 2026-11-03T16-16-55Z
slug: frontend-src-pages-processhub-tsx
---
# Start page critique (after #320): 26/40 (Acceptable)
Method: dual-agent. Fixtures: busy, calm, backend down.
Heuristics: status 4, real world 3, control 2, consistency 2, prevention 3, recognition 3, flexibility 2, minimalism 2, recovery 3, help 2.
P1 Light theme: card "waiting on you" (--hi-ink rgb 184,64,15) and "failed" (--low ~rgb 191,56,41) measure 1.01:1 apart, so the #320 split is invisible. Fix: failed text in ink with the red diamond marker.
P2 Cards repeat Needs you ("N waiting on you" for rows already listed); the signal colour appears ~15 times on a busy screen (icon accents are DESIGN.md's Icon Accent Rule, so only the repeated text is in scope).
P2 Failed row: whole row links to #/history while Resume is the action; link should go to the run.
P2 Sidebar badge "7 items" vs headline "14 decisions": mixed nouns.
P3 Phone rows lose the "Open" affordance.
Dropped: card icons in signal colour (DESIGN.md Icon Accent Rule); skip-link order (headless could not test).
Detector: 0 CLI findings; overused-font (Geist, light only). Contrast, targets, overflow clean. Card aria-labels verified complete.
