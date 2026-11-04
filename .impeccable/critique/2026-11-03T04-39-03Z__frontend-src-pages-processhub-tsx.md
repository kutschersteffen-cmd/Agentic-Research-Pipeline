---
target: start page
total_score: 27
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
target_identity: "file:/home/user/Agentic-Research-Pipeline/frontend/src/pages/ProcessHub.tsx"
target_fingerprint: "sha256:98f3bae907bc4324d2be54bf29692f0681c6890e976cb34400fb92575c3ee6d3"
target_path: /home/user/Agentic-Research-Pipeline/frontend/src/pages/ProcessHub.tsx
timestamp: 2026-11-03T04-39-03Z
slug: frontend-src-pages-processhub-tsx
---
# Start page critique (after #314, #318): 27/40 (Acceptable)
Method: dual-agent. Fixtures: busy, calm, backend down.
Heuristics: status 3, real world 3, control 3, consistency 2, prevention 3, recognition 2, flexibility 2, minimalism 3, recovery 3, help 3.
P1 Card status fuses signal and status: "1 waiting on you · 1 failed" all in signal orange (.hub-card-state.await).
P1 Data Hub card says "No runs yet" and "1 waiting on you" together (now-line ignores counted items).
P2 Card aria-label replaces inner text, so per-process dot states are never announced.
P2 Sidebar badge "7" vs headline 14: label exists only as tooltip/aria; visually unexplained.
P2 Count stated twice (h1 and orange stat).
P3 Clamped card purposes: full text only in a title tooltip, which phones never show.
P3 Sidebar label "Transition Intelligence Platf..." clipped at 1280/1440.
Dropped: legend dots ~8px (they are 12px); "Signed in as ()" (stub).
Detector: 0 CLI findings; overused-font (Geist, light only). Contrast, targets, overflow, tab order clean.
