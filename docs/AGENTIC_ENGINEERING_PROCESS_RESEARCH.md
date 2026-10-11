# Agentic Engineering Process: What the Primary Sources Say

*Researched 2026-10-11. Sources: Anthropic engineering posts, code.claude.com docs, the `anthropics` GitHub org,
and Matt Pocock's `mattpocock/skills` repo (commit `49dd158`, the same commit copied into `.claude/skills/`) plus his aihero.dev articles.
No secondary summaries are used. Pages that could not be fetched are listed at the end.*

## Summary

Anthropic and Pocock make the same main point. An agent's output is only as good as the **feedback loop** it can
close on its own, so the process should give it checks it can run (tests, types, build, lint, screenshots). Rules
that must always hold should be **mechanical gates** (hooks, pre-commit, CI), not more prose in CLAUDE.md, which
Anthropic calls "advisory" and "context, not enforced configuration". Both say to keep the always-loaded
instruction file small, work in small verified slices, plan or interview before non-trivial work, and have a fresh
context review the diff. Pocock goes further on **code design**: he treats deep modules and a shared domain language
as the biggest lever on agent output. Anthropic's material covers harness and context engineering more than
architecture, but it owns the frontend-aesthetics guidance. In this repo the cheapest
gaps to close are: run the frontend's existing `npm test` in CI, add a fast deterministic Stop hook, and put the
test commands (not plugin setup prose) in CLAUDE.md.

---

## (a) Avoiding unnecessary complexity

- **Start simple and add only what has been shown to help.** "we recommend finding the simplest solution possible, and only
  increasing complexity when needed" and "consider adding complexity only when it demonstrably improves outcomes"
  ([Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)). The same post warns
  about frameworks: "Incorrect assumptions about what's under the hood are a common source of customer error."
- **Reviewers can push code toward over-engineering.** Anthropic's best-practices page warns that a reviewer asked for gaps will
  find some, and "Chasing every finding leads to over-engineering: extra abstraction layers, defensive code, and
  tests for cases that can't happen. Tell the reviewer to flag only gaps that affect correctness or the stated
  requirements" ([Best practices](https://code.claude.com/docs/en/best-practices#add-an-adversarial-review-step)).
- **Skip planning when the task is small.** "If you could describe the diff in one sentence, skip the plan"
  ([Best practices](https://code.claude.com/docs/en/best-practices#explore-first-then-plan-then-code)).
- **Fewer, better tools.** "More tools don't always lead to better outcomes" and "We recommend building a few
  thoughtful tools targeting specific high-impact workflows"
  ([Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)).
- **Pocock: speculative generality is a review finding.** His `code-review` smell baseline includes "Speculative
  Generality: abstraction, parameters, or hooks added for needs the spec doesn't have. → delete it" and "Middle Man
  … cut it" ([skills/engineering/code-review/SKILL.md](https://github.com/mattpocock/skills/blob/main/skills/engineering/code-review/SKILL.md)).
- **Pocock: only add a seam when something varies across it.** "One adapter means a hypothetical seam. Two adapters means a real one." "The deletion test.
  Imagine deleting the module. If complexity vanishes, it was a pass-through"
  ([codebase-design/SKILL.md](https://github.com/mattpocock/skills/blob/main/skills/engineering/codebase-design/SKILL.md);
  local copy `.claude/skills/codebase-design/SKILL.md`).
- **Pocock: TDD without speculation.** "Write the failing test first, then only enough code to pass it. Don't
  anticipate future tests or add speculative features"
  ([tdd/SKILL.md](https://github.com/mattpocock/skills/blob/main/skills/engineering/tdd/SKILL.md)).
- **Pocock: against frameworks that own the process.** "These skills are designed to be small, easy to adapt, and
  composable." Approaches that try "owning the process … take away your control and make bugs in the process hard to
  resolve" ([README](https://github.com/mattpocock/skills#readme)).

## (b) Maintainability

- **Pocock: code design is the lever.** "Your codebase, way more than your prompt or your `AGENTS.md` file, is the
  biggest influence on AI's output." Deep modules are "lots of implementation controlled by a simple interface" and
  "You own the interface. AI owns the implementation. Tests keep it honest"
  ([How To Make Codebases AI Agents Love](https://aihero.dev/how-to-make-codebases-ai-agents-love)).
- **Agents speed up entropy.** "Because agents can radically speed up coding, they also accelerate software entropy";
  the fix is "caring about the design of the code", e.g. running `/improve-codebase-architecture` "once every few
  days". He says that skill "is a survey, not a rescue" ([README](https://github.com/mattpocock/skills#readme)).
- **Agents copy existing patterns.** "The patterns you establish will be copied." "Agents amplify what they see." When
  instructions conflict with the code, "it will follow the codebase, not your instructions"
  ([11 Tips For AI Coding With Ralph Wiggum](https://www.aihero.dev/tips-for-ai-coding-with-ralph-wiggum)).
  Anthropic says the same from the prompt side: "Reference existing patterns … follow the pattern"
  ([Best practices](https://code.claude.com/docs/en/best-practices#provide-specific-context-in-your-prompts)).
- **Use a shared domain language.** A glossary "helps agents decode the jargon used in the project". Benefits: consistent naming, a
  codebase that is "easier to navigate", fewer thinking tokens ([README](https://github.com/mattpocock/skills#readme)).
  Local skill: `.claude/skills/domain-modeling/SKILL.md`. It says to offer an ADR only when the decision is "Hard to reverse",
  "Surprising without context", and "the result of a real trade-off".
- **Tests should sit at the interface.** "Tests should survive internal refactors … If a test has to change when the
  implementation changes, it's testing past the interface". "Replace, don't layer": delete old shallow-module tests
  once interface tests exist (`.claude/skills/codebase-design/DEEPENING.md`).
- **Anthropic: treat CLAUDE.md like code.** "review it when things go wrong, prune it regularly, and test changes by
  observing whether Claude's behavior actually shifts"; include "Architectural decisions specific to your project",
  exclude "File-by-file descriptions of the codebase" ([Best practices](https://code.claude.com/docs/en/best-practices#write-an-effective-claude-md)).
- **Persist state outside the context window.** For long work, use a progress file, a JSON feature list ("the model is less likely
  to inappropriately change or overwrite JSON files"), and git commits that leave "the kind of code that would be
  appropriate for merging to a main branch"
  ([Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)).
  Pocock: "A progress file short-circuits that exploration" ([Ralph tips](https://www.aihero.dev/tips-for-ai-coding-with-ralph-wiggum));
  `/handoff` does the same job between sessions (`.claude/skills/handoff/SKILL.md`).

## (c) Frontend UX quality

- **Check UI changes visually.** Anthropic's example: "[paste screenshot] implement this design. take a screenshot of
  the result and compare it to the original. list differences and fix them"
  ([Best practices](https://code.claude.com/docs/en/best-practices#give-claude-a-way-to-verify-its-work)).
  Claude in Chrome adds "Live debugging: read console errors and DOM state", "Design verification", and "Web app
  testing: test form validation, check for visual regressions, or verify user flows"
  ([Chrome docs](https://code.claude.com/docs/en/chrome)). It warns that enabling Chrome by default "increases context usage".
- **Agents verify UIs well only when prompted to use a browser.** "Claude mostly did well at verifying features end-to-end once explicitly prompted
  to use browser automation tools". Known blind spot: "Claude can't see browser-native alert modals through the
  Puppeteer MCP" ([Effective harnesses](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)).
- **Ask for specific design choices, or the output is generic.** The cookbook says Claude "tends toward generic, conservative designs" and
  "defaults to simplistic designs with white and purple backgrounds". It names three strategies: "Guide specific design
  dimensions", "Reference design inspirations", "Call out common defaults"
  ([prompting_for_frontend_aesthetics.ipynb](https://github.com/anthropics/claude-cookbooks/blob/main/coding/prompting_for_frontend_aesthetics.ipynb)).
- **Anthropic `frontend-design` skill.** "make deliberate, opinionated choices about palette, typography, and layout
  that are specific to this brief". "Spend your boldness in one place … cut any decoration that does not serve the
  brief". "fade-and-slide-up entrances on each section and hover transitions on every card are the generic default
  and read as AI-generated". If a brief exists, "follow it exactly"
  ([anthropics/skills frontend-design](https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md)).
- **Interview before building, including UI/UX.** Ask Claude to interview you "about technical implementation, UI/UX, edge cases …"
  then write SPEC.md; good specs "end with an end-to-end verification step"
  ([Best practices](https://code.claude.com/docs/en/best-practices#let-claude-interview-you)).
- **Pocock's material on UX quality is mostly about feedback.** He lists "browser access" as a core feedback loop ([README](https://github.com/mattpocock/skills#readme)),
  and `diagnosing-bugs` ranks a "Headless browser script (Playwright / Puppeteer) that drives the UI and asserts on
  DOM/console/network" fourth among loop types. I found no Pocock primary source on visual design quality.

## (d) Self-detection of bugs: tests, verification loops, hooks, CI

- **Anthropic's top recommendation.** "Give Claude a check it can run: tests, a build, a screenshot to compare. It's the
  difference between a session you watch and one you walk away from." "Without a check it can run, 'looks done' is
  the only signal available, and you become the verification loop"
  ([Best practices](https://code.claude.com/docs/en/best-practices#give-claude-a-way-to-verify-its-work)).
- **Four ways to gate on a check, from cheapest to strongest** (same page): ask in the prompt; a `/goal` condition; "a Stop
  hook runs your check as a script and blocks the turn from ending until it passes"; "a verification subagent … so the
  agent doing the work isn't the one grading it". "The `/goal` and Stop hook versions are what let an unattended run
  finish correctly without you." Also: "Have Claude show evidence rather than asserting success."
- **Ground the agent in its environment.** Agents should "gain 'ground truth' from the environment at each step"; "Code solutions are
  verifiable through automated tests" ([Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)).
- **Known failure mode: claiming done without testing.** Anthropic lists "Claude's tendency to mark a feature as complete without proper
  testing". Their fix is to start each session by running "a basic end-to-end test before implementing a new feature",
  plus the rule "It is unacceptable to remove or edit tests because this could lead to missing or buggy
  functionality" ([Effective harnesses](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)).
- **Hook mechanics** ([Hooks guide](https://code.claude.com/docs/en/hooks-guide)): hooks give "deterministic control:
  certain actions always happen rather than relying on the LLM to choose to run them". Exit 2 blocks the action, and on
  some events the stderr "feed[s] it to Claude as feedback so it can adjust". A Stop hook is overridden "after it
  blocks eight times in a row", so scripts must check `stop_hook_active`. The guide's example is an agent-type Stop
  hook: "Verify that all unit tests pass. Run the test suite and check the results". Agent hooks are "experimental …
  For production workflows, prefer command hooks".
- **Write tests first, as vertical slices.** Anthropic: "write a failing test that reproduces the issue, then fix it"; "have one Claude
  write tests, then another write code to pass them" ([Best practices](https://code.claude.com/docs/en/best-practices)).
  Pocock: "For automated tests, a red-green-refactor loop is critical"; avoid "Horizontal slicing: writing all tests
  first, then all implementation"; tests verify "behavior through public interfaces"; avoid "Tautological" assertions;
  "Test only at pre-agreed seams … confirm them with the user"
  ([tdd/SKILL.md](https://github.com/mattpocock/skills/blob/main/skills/engineering/tdd/SKILL.md)).
- **Pocock: for hard bugs, build the feedback loop first.** "If you have a tight pass/fail signal for the bug … you will find the cause". The
  Phase 1 exit criterion is one command that is "Red-capable", "Deterministic", "Fast", "Agent-runnable". "No
  red-capable command, no Phase 2"
  ([diagnosing-bugs/SKILL.md](https://github.com/mattpocock/skills/blob/main/skills/engineering/diagnosing-bugs/SKILL.md)).
- **Pocock: pre-commit as the agent's gate.** "you need feedback loops so the AI can verify its own work"; "TypeScript is
  essentially free feedback for your AI"; with Husky, "If any step fails, the commit is blocked and the AI gets an
  error message" ([Essential AI Coding Feedback Loops For TypeScript Projects](https://www.aihero.dev/essential-ai-coding-feedback-loops-for-type-script-projects)).
  His `setup-pre-commit` skill runs lint-staged, typecheck and tests on every commit
  ([setup-pre-commit/SKILL.md](https://github.com/mattpocock/skills/blob/main/skills/misc/setup-pre-commit/SKILL.md)).
  `implement`: "Run typechecking regularly, single test files regularly, and the full test suite once at the end"
  ([implement/SKILL.md](https://github.com/mattpocock/skills/blob/main/skills/engineering/implement/SKILL.md)).
- **CI.** Claude Code GitHub Actions can run `/code-review:code-review --comment` on every PR, and `actions: read`
  "lets Claude read CI results on PRs". It also notes "GitHub doesn't trigger workflows on commits made with the default
  `GITHUB_TOKEN`" ([GitHub Actions docs](https://code.claude.com/docs/en/github-actions)).

## (e) Harness engineering and agent loops

- **Context is the main budget.** "Claude's context window fills up fast, and performance degrades as it fills"
  ([Best practices](https://code.claude.com/docs/en/best-practices)). Aim for "the smallest set of high-signal tokens that
  maximize the likelihood of your desired outcome"; sub-agents return "a condensed, distilled summary"; use structured
  notes "persisted to memory outside of the context window"
  ([Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)).
- **Written rules are advisory; hooks enforce.** "Unlike CLAUDE.md instructions which are advisory, hooks are deterministic and
  guarantee the action happens"; "Use hooks for actions that must happen every time with zero exceptions"
  ([Best practices](https://code.claude.com/docs/en/best-practices#set-up-hooks)). "Claude treats them as context, not
  enforced configuration. To block an action regardless of what Claude decides, use a PreToolUse hook"
  ([Memory docs](https://code.claude.com/docs/en/memory)). On over-specified CLAUDE.md: "Ruthlessly prune. If Claude
  already does something correctly without the instruction, delete it or convert it to a hook."
- **CLAUDE.md size and wording.** "target under 200 lines per CLAUDE.md file. Longer files consume more context and reduce
  adherence"; write instructions "concrete enough to verify", e.g. "Run `npm test` before committing" instead of "Test
  your changes"; contradictions mean "Claude may pick one arbitrarily"; `/doctor prompt-audit` finds stale or
  conflicting instructions ([Memory docs](https://code.claude.com/docs/en/memory)). "Bloated CLAUDE.md files cause Claude
  to ignore your actual instructions!"; per line, ask "Would removing this cause Claude to make mistakes?"
  ([Best practices](https://code.claude.com/docs/en/best-practices#write-an-effective-claude-md)).
- **Pocock agrees, more strongly.** CLAUDE.md/AGENTS.md "should be used incredibly sparingly, usually only for
  navigation pointers". A "mechanical" violation "gets a deterministic check, full stop … Default to building the check
  over writing the rule"; "A repo with no guardrail (no pre-commit hook and no CI job running its lint/typecheck/test
  command) is itself a finding"; "a check that already exists but sits unwired or silently broken is the finding"
  ([retro/SKILL.md](https://github.com/mattpocock/skills/blob/main/skills/engineering/retro/SKILL.md)).
- **The reviewer, not the implementer, should enforce standards.** "the review agent should be responsible for imposing coding standards,
  not the implementation agent", because the implementer carries the most "context pressure" (retro). His
  `code-review` runs Standards and Spec as "parallel sub-agents so they don't pollute each other's context". Anthropic:
  "A fresh context improves code review since Claude won't be biased toward code it just wrote"
  ([Best practices](https://code.claude.com/docs/en/best-practices#run-multiple-claude-sessions)).
- **Loop shape.** Anthropic: explore → plan → implement → commit; "If you've corrected Claude more than twice … `/clear`
  and start fresh". For long runs: an initializer writes `init.sh`, the feature list and a progress file, and each later
  session takes "only one feature at a time" ([Effective harnesses](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)).
  The evaluator-optimizer pattern: "one LLM call generates a response while another provides evaluation and feedback in
  a loop" ([Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)).
  Pocock: "The rate at which you can get feedback is your speed limit"; "Fail fast on risky work"; for unattended runs
  "always cap your iterations"; "define what 'done' looks like"
  ([Ralph tips](https://www.aihero.dev/tips-for-ai-coding-with-ralph-wiggum)).
- **Guardrails for unattended runs.** Use allowlists, sandboxing, `--permission-mode dontAsk` with `--allowedTools`, and
  `--max-turns` with workflow timeouts in CI ([Best practices](https://code.claude.com/docs/en/best-practices#fan-out-across-files);
  [GitHub Actions docs](https://code.claude.com/docs/en/github-actions#manage-costs)). "extensive testing in sandboxed
  environments, along with the appropriate guardrails" ([Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)).
- **Tool and error design.** "prompt-engineer your error responses to clearly communicate specific and actionable
  improvements" ([Writing effective tools](https://www.anthropic.com/engineering/writing-tools-for-agents)). The same
  applies to hook stderr, which is what the agent reads when a gate fails.

---

## Where Anthropic and Pocock agree and differ

**Agree**
1. Verification loops come first. Anthropic: "If you can't verify it, don't ship it." Pocock: without feedback "the agent will be
   flying blind".
2. Use deterministic checks for anything mechanical. Keep always-loaded prose short (under 200 lines, or "pointers only").
3. Work in small steps: one feature per session (Anthropic) or one vertical slice per TDD cycle (Pocock).
4. Align before coding: Anthropic's AskUserQuestion interview and Pocock's grilling.
5. Review the diff in a fresh context, separate from the implementer.
6. Keep progress and handoff state in files, not in the conversation.

**Differ (in emphasis)**
1. **Main lever.** Pocock says the codebase's design (deep modules, glossary) shapes output more than any prompt.
   Anthropic's docs say little about code architecture and put the main lever on context and harness.
2. **Who picks the test seams.** Pocock: confirm seams with the user before writing any test. Anthropic: specify tests in the
   prompt, or split the work so one Claude writes tests and another writes code.
3. **Review scope.** Pocock's reviewer applies a 12-smell baseline (always "a judgement call"). Anthropic warns that
   reviewers asked for gaps cause over-engineering and should flag only correctness or requirements gaps.
4. **Process frameworks.** Pocock rejects frameworks that "own the process". Anthropic offers heavier built-in gates
   (`/goal`, agent hooks, workflows) but still advises "the simplest solution possible".
5. **Frontend.** Only Anthropic gives primary-source guidance on aesthetics (cookbook, `frontend-design`). Pocock covers
   browser access only as a feedback loop.

---

## Implications for this repo (ranked: smallest change that holds first)

Current state checked on 2026-10-11:
- `.claude/settings.json` has a single hook, SessionStart (`install-plugins.sh`).
- CI frontend job runs `npm run lint` and `npm run build` (`tsc -b && vite build`), but not `npm test`, although
  `frontend/package.json` defines `test` and `frontend/tests/` holds 18 `*.test.ts` files.
- `.pre-commit-config.yaml` runs only gitleaks.
- `.claude/CLAUDE.md` is 135 lines and mostly plugin-installation prose, with no build or test commands.

1. **Run `npm test` in the CI frontend job** (one step after "Lint"). Pocock's retro says a check that "already exists but
   sits unwired" is itself the finding. This needs no new tooling and turns CI into a complete gate for the frontend.
2. **Add the test commands to CLAUDE.md** (about 4 lines): `cd backend && ruff check . && pytest -q`;
   `cd frontend && npm run lint && npm test && npm run build`. Anthropic lists "Testing instructions and preferred
   test runners" as must-include content, and its example rule is literally "Run `npm test` before committing".
   This is cheap, but it remains advisory, which is why item 3 follows.
3. **Add one command-type Stop hook** that runs only the fast checks for the parts of the tree that changed: `ruff check`
   plus targeted `pytest` for `backend/`, and `npm run lint && npm test` for `frontend/`. It should exit 2 with the failing output
   on stderr, and exit 0 early when `stop_hook_active` is true (block cap is 8). This is Anthropic's "deterministic gate",
   and it closes the in-session gap. Keep it fast: skip the Postgres and OpenSearch suites, which already skip when their
   env vars are unset, and skip `vite build`, which CI covers. Use a command hook, not the experimental agent hook.
4. **Extend pre-commit with local hooks** for `ruff check` and the frontend lint and test (Pocock's "commit is blocked and the AI
   gets an error message"). Note that pre-commit only fires after `pre-commit install`, and fresh cloud containers
   don't have it. Either have the existing SessionStart hook run `pre-commit install`, or rely on items 1 and 3.
5. **Move the plugin-install prose out of CLAUDE.md** into a doc such as `docs/INSTALLATION.md` (it already exists) and leave a
   one-line pointer. Keep the PR-base rule, the phase table and the coding rules. Then run `/doctor prompt-audit`.
   Both sources say the always-loaded file should hold only what prevents mistakes. Seven enabled plugins also
   load skill descriptions and SessionStart hooks into every session, so an audit should check that each one still
   earns its place ("More tools don't always lead to better outcomes").
6. **Verify UI changes visually**: use a screenshot-compare prompt, or Playwright, which is already installed in backend dev extras for
   deck checks, against the dev server for UI tasks. Pair this with the impeccable or ui-ux-pro-max critique the repo already
   uses. This needs no new dependency. Add a `.claude/rules/frontend.md` scoped with `paths: frontend/**` only if
   a UI rule keeps being missed.
7. **Optional, add when PR volume justifies it:** the `claude-code-action` review workflow
   (`/code-review:code-review --comment`) with `--max-turns`. The repo's CLAUDE.md already prescribes `/code-review`
   in-session, and Anthropic advises telling reviewers to flag only correctness or requirements gaps, which matches
   ponytail's review split.

Skipped: agent-type Stop hooks (experimental), `/goal`-driven runs, and long-running initializer harnesses. Add them when
unattended multi-session runs become the norm.

---

## Sources

Anthropic, first-party:
- https://www.anthropic.com/engineering/building-effective-agents
- https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- https://www.anthropic.com/engineering/writing-tools-for-agents
- https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents (published Nov 26, 2025)
- https://code.claude.com/docs/en/best-practices (target of the 308 redirect from anthropic.com/engineering/claude-code-best-practices)
- https://code.claude.com/docs/en/hooks-guide
- https://code.claude.com/docs/en/memory
- https://code.claude.com/docs/en/github-actions
- https://code.claude.com/docs/en/chrome
- https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md
- https://github.com/anthropics/claude-cookbooks/blob/main/coding/prompting_for_frontend_aesthetics.ipynb

Matt Pocock, first-party:
- https://github.com/mattpocock/skills (README, commit `49dd158`), plus `skills/engineering/{tdd,diagnosing-bugs,code-review,retro,implement,codebase-design}/SKILL.md` and `skills/misc/setup-pre-commit/SKILL.md`
- Local copies: `.claude/skills/{codebase-design,domain-modeling,grilling,handoff,improve-codebase-architecture,research}/`
- https://aihero.dev/how-to-make-codebases-ai-agents-love
- https://www.aihero.dev/essential-ai-coding-feedback-loops-for-type-script-projects
- https://www.aihero.dev/tips-for-ai-coding-with-ralph-wiggum

Could not fetch or not used:
- https://www.aihero.dev/workshops/day-4-feedback-loops-fcqu2 returned 404.
- Pocock's conference talks (ai.engineer) were found only through third-party summaries, so they are excluded.
- The skills, subagents and headless doc pages were not fetched separately. Their guidance is cited through the best-practices page that links them.
