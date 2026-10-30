# How Anthropic tests the code it ships (incl. code written with Claude Code)

Research date: 2026-10-30. Primary Anthropic sources only. Quotes are verbatim from the linked page as fetched on that date; paraphrases are marked as such. Several older anthropic.com URLs now 308-redirect to code.claude.com or claude.com; the redirect targets are cited.

## TL;DR

- **Verification is the core rule.** Anthropic's own guidance says the agent must have something to run that tells it the work is done (tests, typecheck, Stop hook, CI); otherwise "you [are] the test suite". Test-first ("write a failing test that reproduces it, then fix it") is the recommended prompt shape ([best practices](https://code.claude.com/docs/en/best-practices)).
- **Review by something that did not write the code.** `/code-review` runs in "a fresh subagent that never saw your conversation"; the hosted Code Review product uses several parallel agents plus a verification step that filters false positives, and never approves or blocks a PR ([Code Review docs](https://code.claude.com/docs/en/code-review)).
- **Published internal numbers (Anthropic-reported, not independently verified):** PRs with substantive review comments went from 16% to 54%; 84% of >1,000-line PRs get findings (avg 7.5); under 1% of findings marked incorrect ([Code Review launch, 2026-03-09](https://claude.com/resources/articles/code-review)). Claude authors "about 80% of the code merged" ([secure SDLC](https://claude.com/blog/how-anthropic-secures-its-ai-native-software-development-lifecycle)).
- **Layered gates, humans on the risky slice.** Agentic plus deterministic (SAST) reviews, invariant-focused tests, a logged and risk-sampled approval trail, and human review focused on "regulated or truly critical code" ([secure SDLC](https://claude.com/blog/how-anthropic-secures-its-ai-native-software-development-lifecycle)).
- **Evals are tests for agents, and they still miss things.** Prefer deterministic, outcome-based graders (do the tests pass?), read transcripts, isolate trials. The April 2026 postmortem admits a bug passed "multiple human and automated code reviews, as well as unit tests" and commits to broader per-model evals on every Claude Code system-prompt change ([evals post](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents), [postmortem](https://www.anthropic.com/engineering/april-23-postmortem)).

## 1. Testing practices: test-first with agents

- The best-practices page frames it bluntly: "Claude stops when the work looks done. If it has nothing to run that tells it whether the work actually *is* done, 'looks done' is all it has to go on. In practice that makes you the test suite" ([best practices](https://code.claude.com/docs/en/best-practices)).
- Recommended prompt for a bug: "write a failing test that reproduces it, then fix it" ([best practices](https://code.claude.com/docs/en/best-practices)).
- Ways to give a check: in the prompt ("run the auth tests after, and keep going until they pass"), or as `/goal all tests in tests/auth pass and lint is clean`, which "sets a condition that a separate model checks against the conversation after every turn" ([best practices](https://code.claude.com/docs/en/best-practices)).
- Ask for evidence: "'All tests pass' on its own tells you very little" — request the command and its output, or a screenshot. `/verify` has Claude "build and run the app and look at the result", catching "the kind of problem that tests and typechecks miss" ([best practices](https://code.claude.com/docs/en/best-practices)).
- Spec-first: write `SPEC.md`, then "start a fresh session to build from it, so the build begins with a clean context and a written definition of done" ([best practices](https://code.claude.com/docs/en/best-practices)).
- Internal teams: Security Engineering moved from "design doc → janky code → refactor → give up on tests" to "guiding it through test-driven development, and checking in periodically"; Product Design uses Claude Code "to write comprehensive tests for new features" ([How Anthropic teams use Claude Code](https://claude.com/blog/how-anthropic-teams-use-claude-code)).
- Coding agents suit autonomy because "Code solutions are verifiable through automated tests" and "Agents can iterate on solutions using test results as feedback" ([Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)).

## 2. CI and automated checks

- `claude -p` "is how Claude Code ends up in CI jobs, git hooks, and shell loops"; example loop: `/loop 15m check CI on this branch, and if it's red pull the failing job's log, fix it and push` ([best practices](https://code.claude.com/docs/en/best-practices)).
- Where "done" lives: "Tests, typecheck, a `Stop` hook, CI" ([best practices](https://code.claude.com/docs/en/best-practices)).
- Anthropic's own pipeline: "the team could only move as quickly as humans could review code" (CI as bottleneck); "Another round of testing focuses on invariants like 'user A can never read user B's data,' and triggers additional manual reviews"; "We combine our agentic scans with SAST tools as well, which post directly on PRs"; "Dynamic testing should match deployment cadence" ([secure SDLC](https://claude.com/blog/how-anthropic-secures-its-ai-native-software-development-lifecycle)).
- `anthropics/claude-code-action` runs Claude on your own GitHub runner, triggered by `@claude` mentions, issue assignment or explicit automation prompts; it "Analyzes PR changes and suggests improvements" and "Can implement simple fixes, refactoring, and even new features" ([claude-code-action](https://github.com/anthropics/claude-code-action)). The README does not mention running tests.

## 3. Code review (human and Claude)

- **Hosted Code Review:** four stages — Find (several agents in parallel), Verify ("filters out false positives"), Rank, Post. "A review never approves or blocks the pull request, so the decision to merge stays with your team." It focuses on "bugs that would break production, not formatting preferences or missing test coverage", reads code "without building or running your code", and reads `REVIEW.md` from the base branch, "never from the pull request's own changes" ([Code Review docs](https://code.claude.com/docs/en/code-review)).
- **Local review:** `/code-review` reviews the diff "in a fresh subagent that never saw your conversation. It isn't swayed by the reasoning that produced the code." A read-only reviewer subagent (`tools: Read, Grep, Glob`) makes the no-edit limit "enforced by Claude Code rather than requested in a prompt." Warning: "A reviewer that's asked to find problems will always find *something*" — add "skip style" ([best practices](https://code.claude.com/docs/en/best-practices)).
- **Anthropic internally:** narrow, separate review agents ("They do not share biases and blindspots"); `/security-review` as a final self-check; "Every approval is logged with the signals and reasoning behind it, and a risk-weighted sample is reviewed by humans"; new AI reviewers start in "Shadow mode"; humans focus on "regulated or truly critical code" (paraphrase of surrounding sentence). Requiring agents to "write a proof that their finding is valid" is credited for the 16%→54% rise ([secure SDLC](https://claude.com/blog/how-anthropic-secures-its-ai-native-software-development-lifecycle)).
- Human review still matters: "human review remains crucial for ensuring solutions align with broader system requirements" ([Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)).

## 4. Evals for models and agents

- Grader types: code-based (fast, objective, "Brittle to valid variations"), model-based (flexible, needs calibration against humans), human (gold standard, use sparingly). Grade outcomes, not step order ([Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)).
- Coding agents: deterministic graders fit because the question is "does the code run and do the tests pass?"; unit tests often paired with an LLM rubric for quality ([Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)).
- pass@k vs pass^k: 75% per-trial success gives ~42% for three in a row ([Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)).
- Practice: start with 20–50 tasks from real failures; regression evals near 100%, capability evals start low; a 0% pass rate usually means a broken task; read transcripts; eliminate shared state (Claude exploited git history from earlier trials); Opus 4.5 went from 42% to 95% on CORE-Bench after grading bugs were fixed. Claude Code started with narrow evals (concision, file edits) and added ones for over-engineering ([Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)).
- SWE-bench Verified: "a 500 problem subset of SWE-bench that has been reviewed by humans to make sure they are solvable"; graded with "the real unit tests from the pull request that closed the original GitHub issue". The agent prompt tells it to write a reproduce script, "Rerun your reproduce script and confirm that the error is fixed!" Claude 3.5 Sonnet (new) scored 49% ([SWE-bench Sonnet](https://www.anthropic.com/research/swe-bench-sonnet)).

## 5. When it fails: the April 2026 postmortem

- "neither our internal usage nor evals initially reproduced the issues"; a caching bug "made it past multiple human and automated code reviews, as well as unit tests"; a verbosity prompt change shipped after "multiple weeks of internal testing and no regressions", and only a broader ablation showed "a 3% drop for both Opus 4.6 and 4.7" ([postmortem](https://www.anthropic.com/engineering/april-23-postmortem)).
- Committed fixes: more staff on "the exact public build of Claude Code"; "a broad suite of per-model evals for every system prompt change"; Code Review gets "support for additional repositories as context"; "soak periods, a broader eval suite, and gradual rollouts" ([postmortem](https://www.anthropic.com/engineering/april-23-postmortem)).

## 6. Published numbers

| Claim | Source |
|---|---|
| PRs with substantive review comments: 16% → 54% | [Code Review launch](https://claude.com/resources/articles/code-review), [secure SDLC](https://claude.com/blog/how-anthropic-secures-its-ai-native-software-development-lifecycle) |
| >1,000-line PRs: 84% get findings, avg 7.5; <50 lines: 31%, avg 0.5 | [Code Review launch](https://claude.com/resources/articles/code-review) |
| <1% of findings marked incorrect | [Code Review launch](https://claude.com/resources/articles/code-review) |
| Review ~20 min, ~$15–25 each | [Code Review launch](https://claude.com/resources/articles/code-review) |
| Claude authors ~80% of merged code; "8x as much code per quarter" | [secure SDLC](https://claude.com/blog/how-anthropic-secures-its-ai-native-software-development-lifecycle) |
| ~1/3 of bugs behind past claude.ai incidents would be caught by current automation | [secure SDLC](https://claude.com/blog/how-anthropic-secures-its-ai-native-software-development-lifecycle) |
| SWE-bench Verified ~40% → >80% in one year (industry) | [Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) |

All are Anthropic self-reported; no independent verification found.

## 7. What this repo could adopt

Compared against `.claude/CLAUDE.md` (holdout tests, mutation check, golden set, steward, evaluator, Stop hook).

| Anthropic practice | This repo today | Gap / suggestion |
|---|---|---|
| Reviewer that never saw the writing session | `/code-review` + `/ponytail:ponytail-review`; holdout tests written in a separate session | Already strong; holdout goes further than anything Anthropic publishes. Consider a read-only reviewer subagent (`tools: Read, Grep, Glob`) checking the diff against the spec's Acceptance table. |
| Findings must carry a proof (16%→54%) | Not required | Require each review finding to cite a failing test, a command output or a line-level trace before it blocks; drop unproven ones. |
| Verification step filters false positives; reviews never block | Review findings feed steward fix rounds | Add a verify pass before counting a finding toward the three-round limit, so false positives don't burn rounds. |
| Ask for evidence, not "tests pass" | Stop hook runs checks; evaluator records evidence | Fits. Make PR descriptions paste the actual check output. |
| Invariant tests triggering manual review | `risk:high` → owner merge + mutation check | Name a few invariants (e.g. no cross-tenant data, golden-set grounding) and auto-label PRs touching them `risk:high`. |
| Logged approvals, risk-weighted human sampling, shadow mode for new reviewers | Merge button per PR/SHA | Sample some auto-merged `risk:low` PRs in the weekly retro; run any new review agent in shadow mode first. |
| Evals: real-failure tasks, regression near 100%, read transcripts, isolate trials | Golden set + transition-barrier golden in CI | Feed retro failures into the golden set; ensure golden runs share no state (Anthropic saw git-history leakage). |
| Broad evals on every prompt/model change; soak + gradual rollout | Golden set triggers on `arp/llm`, `arp/extraction`, config | Extend triggers to prompt files if they live elsewhere; Main guard revert already covers rollback. |
| `/verify` runs the app | evaluator skill + E2E job | Already covered. |

Not adopted by Anthropic as far as published: mutation testing and hidden holdout acceptance tests do not appear in these sources; this repo is ahead there.

## Not verified

- No first-party Anthropic statement found on mutation testing or hidden/holdout acceptance tests.
- The claude-code-action README does not say it runs tests; whether it does depends on configured tools (unverified).
- Exact full sentence around "regulated or truly critical code" was not captured; the summary is a paraphrase.
- The "How Anthropic teams use Claude Code" PDF (www-cdn.anthropic.com) was not read separately; the blog version was used.

## Sources (accessed 2026-10-30)

- Best practices for Claude Code — https://code.claude.com/docs/en/best-practices (redirect from anthropic.com/engineering/claude-code-best-practices)
- Code Review docs — https://code.claude.com/docs/en/code-review
- Code Review for Claude Code (launch, 2026-03-09) — https://claude.com/resources/articles/code-review
- How Anthropic secures its AI-native software development lifecycle — https://claude.com/blog/how-anthropic-secures-its-ai-native-software-development-lifecycle
- How Anthropic teams use Claude Code — https://claude.com/blog/how-anthropic-teams-use-claude-code
- Demystifying evals for AI agents — https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- An update on Claude Code quality reports (April 23 postmortem) — https://www.anthropic.com/engineering/april-23-postmortem
- Building effective agents — https://www.anthropic.com/engineering/building-effective-agents
- Raising the bar on SWE-bench Verified with Claude 3.5 Sonnet — https://www.anthropic.com/research/swe-bench-sonnet
- anthropics/claude-code-action — https://github.com/anthropics/claude-code-action
