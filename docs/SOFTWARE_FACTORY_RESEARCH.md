# Software Factory: What the Primary Sources Say

*Researched 2026-10-16. Sources: StrongDM's factory.strongdm.ai and its `strongdm/*` repos; Dan Shapiro's own blog;
Factory's docs.factory.com; docs.github.com and the `github/*` repos; OpenAI's Codex docs and `openai/*` repos;
Anthropic's engineering posts and code.claude.com docs; each surveyed repo's own README and LICENSE. Repository
facts (stars, last push, license) come from the GitHub repository search API and raw README/LICENSE files, all
read on 2026-10-16. No secondary summaries are used. Pages that could not be fetched are listed at the end.
This builds on [AGENTIC_ENGINEERING_PROCESS_RESEARCH.md](AGENTIC_ENGINEERING_PROCESS_RESEARCH.md) (2026-10-11),
which covers verification loops, hooks, CI gates, CLAUDE.md size and Pocock's skills. None of that is repeated here.*

## Summary

A "software factory" in current first-party usage is a pipeline that takes a work item (issue, ticket or spec)
and returns a merged change with as few human touches as the risk allows. The vendors and the one public
practitioner agree on the shape: **complete intent in, isolated run, verification the implementer cannot game,
review by a separate agent, a merge gate, and a loop that feeds failures back**. They disagree on one thing,
which is where the human sits. StrongDM says code "must not be reviewed by humans". GitHub's Copilot agent cannot
approve or merge its own PRs, Anthropic's Code Review "never approves or blocks", and Anthropic's own engineers
still review every change, though they now review its intent rather than every line.

The open-source landscape splits into five roles: spec toolkits, agent runners, factory orchestrators that read
a work queue, parallel-session managers, and multi-agent "company" simulators. The most useful new artefacts are
small and spec-shaped: OpenAI's [Symphony](https://github.com/openai/symphony) and StrongDM's
[Attractor](https://github.com/strongdm/attractor) are both natural-language specifications that you have your
own agent implement. The company simulators (MetaGPT, ChatDev, ruflo) are the weakest fit, because none of the
primary sources credit role-play for good outcomes. They credit verification. "pstack" exists: it is Lauren
Tan's Cursor skill stack, and Garry Tan's gstack is the Claude Code equivalent. Both are skill stacks at the same
layer as the superpowers and ponytail setup already installed here, so there is nothing to add. For
dashboards, claude.ai/code plus GitHub's PR and Actions views already cover agent state and CI state for this
repo.

This repo already has most of the in-session half of a factory: superpowers specs and plans, a Stop-hook gate,
full CI, cloud sessions, and PR auto-fix. The missing pieces are all at the edges. `main` is not a protected
branch, nothing starts a run without a human opening a session, PRs get no review in a fresh context, and no
check exists that the implementing agent cannot see. Close those in that order.

---

## 1. What "software factory" means now

### StrongDM: the "Software Factory" (the strongest form)

- **Definition and rules.** Justin McCarthy (CTO), February 6, 2026: a non-interactive setup in which specs and
  scenarios drive agents that write code and run harnesses until the software is built to "converge without human
  review". The two
  rules are "Code **must not be** written by humans" and "Code **must not be** reviewed by humans". It also sets a
  spending bar: "If you haven't spent at least **$1,000 on tokens today** per human engineer, your software
  factory has room for improvement" ([factory.strongdm.ai](https://factory.strongdm.ai/)).
- **Loop shape.** "Seed → Validation harness → Feedback loop. Tokens are the fuel." "Your validation harness
  must be end-to-end, as close to the real environment as possible." Feedback is "A sample of the output, fed
  back into the inputs." The stopping rule is "The loop runs until the holdout scenarios pass (and stay passing)"
  ([principles](https://factory.strongdm.ai/principles)).
- **Why tests are not enough.** "A test, stored in the codebase, can be lazily rewritten to match the code", and
  "return true" passes narrow tests. Their answer is to repurpose "the word scenario to represent an end-to-end
  'user story', often stored outside the codebase", which works like a model-training holdout set. They measure
  **satisfaction**: "of all the observed trajectories through all the scenarios, what fraction of them likely
  satisfy the user?" ([factory.strongdm.ai](https://factory.strongdm.ai/)).
- **Digital Twin Universe.** These are "behavioral clones of the third-party services our software depends on",
  built "from API contracts and observed edge cases", then validated "against the live dependency until we stop
  finding behavioral differences". This enables "Thousands of scenarios per hour without rate limits or API
  costs" ([DTU](https://factory.strongdm.ai/techniques/dtu)).
- **When non-interactive works.** "Spec + Test Suite = Complete Intent". Interactive work ("generate, clarify,
  generate, approve, correct") stays with tools like Claude Code. Non-interactive work is "Tasks that are already
  fully specified" ([Shift Work](https://factory.strongdm.ai/techniques/shift-work)).
- **Published artefacts.** [strongdm/attractor](https://github.com/strongdm/attractor) "contains NLSpecs to build
  your own version of Attractor to create your own software factory". It is three spec files and no code, and you
  build it by telling an agent "Implement Attractor as described by …". [strongdm/cxdb](https://github.com/strongdm/cxdb)
  is "an AI Context Store for agents", a turn DAG with content-addressed blobs that can capture `claude` and
  `codex` sessions ([products](https://factory.strongdm.ai/products)).

### "Dark factory" and the five levels

Dan Shapiro, January 23, 2026, on [his blog](https://www.danshapiro.com/blog/2026/01/the-five-levels-from-spicy-autocomplete-to-the-software-factory/)
(StrongDM links to it). At Level 3 you manage agents and spend your days reviewing their code. At Level 4 you
write specs and plans, let the agent run, and check whether the tests pass. At Level 5 the process becomes a black box that turns
specs into software. He takes "dark factory" from Fanuc's robot-run plant: "dark, because it's a place where
humans are neither needed nor welcome."

### Factory (factory.com): a product named "Software Factory"

Factory's [Software Factory](https://docs.factory.com/software-factory/overview.md) is "a 24/7 autonomous system
that connects AI agents across the software development lifecycle", in **Private Preview**. Its stages are Triage,
Code-gen, Validate ("Run code review, security review, and QA before merge"), Release, Document and Monitor. It
measures itself with Tickets Triaged, PR Validations ("Merge gate"), PRs Merged ("Ship rate") and Incidents
Processed. Work comes in through [Delegations](https://docs.factory.com/delegations/index.md) from Slack, Linear
and Jira, and [Droid Exec](https://docs.factory.com/droid-exec/overview.md) is the headless mode for CI. The
product is closed source.

### GitHub: Copilot coding agent and Agentic Workflows

- **Copilot cloud agent.** You start it "from the agents panel, a conversation, or an issue or pull request". It
  works in "an ephemeral cloud development environment". "Copilot can only work on one branch at a time and can
  open one pull request per task". Sessions have a 59-minute cap that "cannot be extended or bypassed"
  ([about](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent)). Its guardrails
  are the useful part. Only users with write access can trigger it. It pushes only to a `copilot/` branch. It
  cannot mark its PRs ready, approve them or merge them, and the requesting user cannot approve them either.
  Workflows do not run on its code until a person with write access approves them. The firewall restricts
  internet access ([risks and mitigations](https://docs.github.com/en/copilot/concepts/agents/coding-agent/risks-and-mitigations)).
- **GitHub Agentic Workflows (`gh-aw`).** These are workflows written in Markdown that `gh aw compile` turns into
  "a hardened, pinned Actions workflow", with Copilot, Claude Code, Codex and others as the engine. "The agent runs
  read-only by default". Writes go through **safe outputs**: "Only the writes you declared are applied, by a
  separate job with its own permissions." GitHub calls it a "technical preview" and pitches "Continuous AI" as "A
  third pillar beside CI and CD" ([gh-aw site](https://github.github.com/gh-aw/)). The README says to use normal
  Actions "for deterministic builds, tests, linting" and to add an agentic workflow "when a task needs reasoning".
  It also warns that the tool requires "careful human supervision, and even then things can still go wrong", and
  that releases `>= 0.83.3, < 0.85.4` were retired over a security advisory
  ([github/gh-aw](https://github.com/github/gh-aw)).

### OpenAI: Codex cloud, codex-action, Symphony

- **Codex cloud** runs tasks in the cloud. "Each task has its own workspace". Environments are saved and reused,
  and you "commit or open a pull request when you're ready" ([Codex cloud](https://learn.chatgpt.com/docs/cloud)).
  [openai/codex-action](https://github.com/openai/codex-action) runs Codex in Actions "while keeping tight control
  over the privileges available to Codex", and its example is a PR review bot.
- **Symphony** ([openai/symphony](https://github.com/openai/symphony)) "turns project work into isolated,
  autonomous implementation runs, allowing teams to manage work instead of supervising coding agents". It is "a
  low-key engineering preview for testing in trusted environments". Like Attractor, you are told to have your
  agent "Implement Symphony according to the following spec". An Elixir reference implementation also exists. Its
  [SPEC.md](https://github.com/openai/symphony/blob/main/SPEC.md) is the clearest public design of a factory
  orchestrator. It "continuously reads work from a configured issue tracker, creates an isolated workspace for each
  issue, and runs a coding agent session for that issue". It keeps "the workflow policy in-repo (`WORKFLOW.md`)",
  uses bounded concurrency and exponential backoff, and stops runs "when issue state changes make them
  ineligible". "A successful run can end at a workflow-defined handoff state (for example `Human Review`), not
  necessarily `Done`." The README says Symphony "works best in codebases that have adopted harness engineering",
  which links to OpenAI's harness-engineering post. That post could not be fetched, so none of its claims are
  used here.

### Anthropic: the building blocks, and what Anthropic does internally

- **Turning issues into PRs.** The [Claude Code GitHub Action](https://code.claude.com/docs/en/github-actions)
  lets you "turn issues into pull requests". Interactive mode answers `@claude` in a comment or "in the body or
  title of a newly opened issue". Automation mode runs a fixed `prompt` on any event. The triggering user must
  have write access.
- **Managed review.** [Code Review](https://code.claude.com/docs/en/code-review) sends each PR to "Several agents"
  and adds "A verification step [that] checks findings against the code before they're reported". "A review never
  approves or blocks the pull request, so the decision to merge stays with your team." It is available on Team
  and Enterprise plans.
- **PR babysitting.** [Auto-fix](https://code.claude.com/docs/en/claude-code-on-the-web#auto-fix-pull-requests)
  subscribes to a PR. When a check fails or a reviewer comments, Claude "investigates and pushes a fix if one is
  clear". For ambiguous or architectural comments it "asks you before acting". It cannot react to merge conflicts,
  because "GitHub does not emit a webhook when the base branch advances".
- **Unattended triggers.** [Routines](https://code.claude.com/docs/en/routines) (research preview) are saved
  cloud sessions that fire on a schedule, an API POST, or a GitHub event. They run with "no permission-mode
  picker" and create `claude/`-prefixed branches. The GitHub trigger supports only **Pull request** and
  **Release** events, so issue intake needs a schedule, an API call or the GitHub Action.
- **Completion conditions.** [`/goal`](https://code.claude.com/docs/en/goal) has "a separate evaluator" check the
  condition after every turn, "so completion is decided by a fresh model rather than the one doing the work".
- **Parallelism.** [Run agents in parallel](https://code.claude.com/docs/en/agents) lists subagents, agent view,
  agent teams ("Experimental and disabled by default"), projects, and dynamic workflows, plus worktrees and
  `/batch` ("split one large change into 5 to 30 worktree-isolated subagents").
- **Programmatic harness.** The [Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview) offers "the same
  tools, agent loop, and context management that power Claude Code". Managed Agents is the hosted equivalent.
- **Harness evidence.** The [Harness design](https://www.anthropic.com/engineering/harness-design-long-running-apps)
  post (March 24, 2026) used a planner, a generator and an evaluator. "tuning a standalone evaluator to be
  skeptical turns out to be far more tractable" than making the generator self-critical. Generator and evaluator
  agreed in advance "on what 'done' looked like for that chunk of work before any code was written". A solo run
  cost $9 and its core feature did not work. The full harness cost $200 over 6 hours and produced a working app.
  Components were removed as models improved, because each one encodes an assumption about what the model cannot do alone.
  The [C compiler](https://www.anthropic.com/engineering/building-c-compiler) post (February 5, 2026) ran 16
  parallel agents over nearly 2,000 sessions for "just under $20,000". The setup was a plain loop with git lock
  files and no orchestrator agent. The rule was that "the task verifier is nearly perfect, otherwise Claude will
  solve the wrong problem". Test output stays short, a `--fast` mode samples 1% or 10% of tests, GCC served as a
  "known-good compiler oracle", and CI ensures "new commits can't break existing code". The author warns that "it
  is easy to see tests pass and assume the job is done".
- **Anthropic internally, at scale.** [Redesigning source control](https://www.anthropic.com/engineering/redesigning-source-control)
  (October 13, 2026): "as of September, we merged over 30,000 per day". The bottleneck moved to "source control,
  builds, and CI". Humans still review every change, but "examine the intent of the change as opposed to reading
  every line of code". Adversarial AI review works but over-defends, so "the role of the engineers was to tell
  Claude 'no.'" They dropped a global merge-queue lock in favour of post-merge and pre-deploy testing. That is a
  choice for a monorepo with tens of thousands of merges a day, and it does not carry over to a small repo.
- **Containment.** "network is denied by default". Allowlisted domains are attack surface, and credentials that
  never enter the sandbox cannot be stolen ([How we contain Claude](https://www.anthropic.com/engineering/how-we-contain-claude),
  May 25, 2026).

**Working definition used below.** A software factory is a queue-driven loop: a work item with complete intent
goes in, an agent runs in an isolated workspace, an independent verifier and reviewer judge the result, a merge
gate decides, and failures go back in as new input. "Dark" is a setting on that loop (how much human review sits
at the gate), not a different architecture.

---

## 2. Repositories by role

Stars are rounded. All were read 2026-10-16. The date is the repository's `pushed_at`, except for openai/symphony,
bmad-code-org/bmad-loop, gastownhall/gastown, gastownhall/beads, nimbalyst/nimbalyst and
michael-denyer/pstack-claude. The search tool returned only `updated_at` for those, and that field also moves on
stars or metadata changes.

| Repo | Role | License | Stars / last push | Verdict for this repo |
| :- | :- | :- | :- | :- |
| [anthropics/claude-code-action](https://github.com/anthropics/claude-code-action) | Runner in CI (issue→PR, PR review) | MIT | 9.5k / 2026-10-15 | **Adopt** for the PR review gate and issue intake |
| [openai/symphony](https://github.com/openai/symphony) | Factory orchestrator (tracker → isolated runs) | Apache-2.0 | 27.7k / 2026-10-16 | **Read the spec, borrow `WORKFLOW.md` and the handoff state**. Build a daemon only if a routine can't do the job |
| [github/gh-aw](https://github.com/github/gh-aw) | Agentic Actions with safe outputs | MIT | 5.4k / 2026-10-16 | **Later, for read-only jobs** (CI Doctor-style). Technical preview with a recent advisory |
| [strongdm/attractor](https://github.com/strongdm/attractor) | Factory agent as NLSpec | Apache-2.0 | 1.3k / 2026-03-17 | **Read for the holdout-scenario idea**. Don't build it, Claude Code already is the agent |
| [obra/superpowers](https://github.com/obra/superpowers) | Spec → plan → TDD → review method | MIT | 300k / 2026-10-10 | **Already installed**. It is this repo's spec layer |
| [garrytan/gstack](https://github.com/garrytan/gstack) | Skill stack: "Think → Plan → Build → Review → Test → Ship → Reflect" as role skills | MIT | 137k / 2026-10-16 | **Skip the install, borrow two ideas**: `/qa` against the running app, and a review that names "every weakened test". It overlaps superpowers, ponytail and impeccable |
| [pstack](https://github.com/cursor/plugins/tree/main/pstack) in [cursor/plugins](https://github.com/cursor/plugins) (Lauren Tan) | Cursor skill stack: `/poteto-mode` routes to 23 playbooks | MIT (`pstack/LICENSE`) | repo 11.8k / 2026-10-16 | **Skip, borrow the playbooks to read**: `babysit`, `shipping`, `autonomous-run` and a blinded `eval`. Cursor-native, and it overlaps ponytail and superpowers |
| [michael-denyer/pstack-claude](https://github.com/michael-denyer/pstack-claude) | Third-party port of pstack to Claude Code, Codex, Copilot and others | MIT | 2.6k / 2026-10-16 | Skip. Unofficial port, and the most-starred of many `pstack-claude` forks |
| [anthropics/claude-agent-sdk-python](https://github.com/anthropics/claude-agent-sdk-python) | Programmatic harness | MIT | 8.3k / 2026-10-15 | Adopt only if you write your own dispatcher |
| [anthropics/claude-agent-sdk-typescript](https://github.com/anthropics/claude-agent-sdk-typescript) | Programmatic harness | Proprietary (Anthropic Commercial Terms) | 1.8k / 2026-10-15 | Skip. The backend is Python |
| [github/spec-kit](https://github.com/github/spec-kit) | Spec toolkit (`/speckit-specify → plan → tasks → implement`) | MIT | 141k / 2026-10-15 | Skip. Duplicates superpowers |
| [Fission-AI/OpenSpec](https://github.com/Fission-AI/OpenSpec) | Spec toolkit (proposal/specs/design/tasks per change) | MIT | 72k / 2026-10-15 | Skip. Duplicates superpowers |
| [bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) | Agile multi-role method | MIT + trademark notice | 54k / 2026-10-16 | Skip. v7 is "preview alpha", and the method is heavier than superpowers |
| [eyaltoledano/claude-task-master](https://github.com/eyaltoledano/claude-task-master) | Task graph via MCP | MIT + Commons Clause | 28k / 2026-04-28 | Skip. Not OSI open source, quiet since April, overlaps plans |
| [kirodotdev/Kiro](https://github.com/kirodotdev/Kiro) | IDE product; specs = requirements/design/tasks | No license file | 4.4k / 2026-09-15 | Skip. Closed product. Its [spec format](https://kiro.dev/docs/specs/) matches superpowers' |
| [openai/codex](https://github.com/openai/codex) | Agent CLI | Apache-2.0 | 129k / 2026-10-16 | Skip. The repo is on Claude Code |
| [openai/codex-action](https://github.com/openai/codex-action) | Codex in Actions | Apache-2.0 | 1.3k / 2026-10-14 | Skip, same reason |
| [OpenHands/OpenHands](https://github.com/OpenHands/OpenHands) | Self-hosted agent server + "Agent Canvas" | MIT | 91k / 2026-10-16 | Skip. Duplicates cloud sessions and routines, and adds hosting |
| [SWE-agent/mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) | Minimal bash-only agent, eval baseline | MIT | 8.6k / 2026-10-12 | Skip for production. Useful for evals |
| [SWE-agent/SWE-agent](https://github.com/SWE-agent/SWE-agent) | Research agent | MIT | 20.6k / 2026-10-12 | Skip. Its README says mini "has superseded SWE-agent" |
| [Aider-AI/aider](https://github.com/Aider-AI/aider) | Pair-programming CLI | Apache-2.0 | 50k / 2026-05-22 | Skip. Interactive, no queue or gate, quiet since May |
| [coleam00/Archon](https://github.com/coleam00/Archon) | YAML workflow engine (plan→implement loop→bash validate→review→PR) | MIT | 23.7k / 2026-10-16 | Skip for now. Worth a look if more repos need one shared workflow |
| [bmad-code-org/bmad-loop](https://github.com/bmad-code-org/bmad-loop) | Unattended BMad epic loop | not checked | 159 / 2026-10-15 | Skip. Tied to BMad, young |
| [BloopAI/vibe-kanban](https://github.com/BloopAI/vibe-kanban) | Local kanban + agent workspaces + diff review | Apache-2.0 | 28k / 2026-09-19 | Skip. A local UI, while this repo works in cloud sessions |
| [smtg-ai/claude-squad](https://github.com/smtg-ai/claude-squad) | Terminal manager for parallel agents in worktrees | AGPL-3.0 | 8.6k / 2026-08-20 | Skip. Local tmux, AGPL, cloud sessions already isolate |
| [stravu/crystal](https://github.com/stravu/crystal) → [nimbalyst/nimbalyst](https://github.com/nimbalyst/nimbalyst) | Desktop app for parallel sessions in worktrees | MIT | 3.1k (Crystal, moved) / 1.9k | Skip. Crystal now points to Nimbalyst |
| [gastownhall/gastown](https://github.com/gastownhall/gastown) | Multi-agent workspace manager ("Scale comfortably to 20-30 agents") | MIT | 18.4k / 2026-10-16 | Skip. Built for 20+ concurrent agents |
| [gastownhall/beads](https://github.com/gastownhall/beads) | Git/Dolt-backed dependency graph of work for agents | MIT | 28k / 2026-10-16 | Skip. GitHub issues plus plan files cover this at current scale |
| [strongdm/cxdb](https://github.com/strongdm/cxdb) | Context store for agent transcripts | Apache-2.0 | 520 / 2026-08-28 | Skip. Nothing here needs transcript branching |
| [FoundationAgents/MetaGPT](https://github.com/FoundationAgents/MetaGPT) | "Software Company as Multi-Agent System", `Code = SOP(Team)` | MIT | 71k / 2026-01-21 | Skip. Greenfield generator, quiet since January |
| [OpenBMB/ChatDev](https://github.com/OpenBMB/ChatDev) | Was a "Virtual Software Company". 2.0 is a "Zero-Code Multi-Agent Platform" | Apache-2.0 | 34.5k / 2026-10-16 | Skip. Changed its purpose |
| [ruvnet/ruflo](https://github.com/ruvnet/ruflo) (formerly claude-flow; README still links `ruvnet/claude-flow`) | "Agent meta-harness" with "100+ specialized agents" | MIT | 75k / 2026-10-16 | Skip. Adds a large layer of agents and mods, with no evidence it verifies better |
| [SWE-bench/SWE-bench](https://github.com/SWE-bench/SWE-bench) | Benchmark: issue + codebase → patch, Docker-graded | MIT | 6k / 2026-09-18 | Skip as a factory metric. It measures models and harnesses, not your pipeline |

Notes by role:

- **Spec toolkits all converge on the same artefacts.** Spec-kit's per-feature flow is "specify → plan → tasks →
  implement → converge". OpenSpec writes `proposal.md`, `specs/`, `design.md` and `tasks.md`. Kiro uses
  `requirements.md`, `design.md` and `tasks.md` and runs independent tasks in dependency "waves". BMAD promises
  "Right-sized process". Superpowers already writes a design doc, then a plan whose tasks each have "exact file
  paths, complete code, verification steps" ([README](https://github.com/obra/superpowers)). Swapping toolkits
  changes file names, not outcomes.
- **Runners matter less than their gates.** Every runner can open a PR. They differ in what stops a bad PR:
  Copilot's no-self-approval and `copilot/` branch rule, gh-aw's safe outputs, codex-action's privilege proxy,
  and claude-code-action's write-access check.
- **Orchestrators are where "factory" actually lives.** Symphony (tracker → per-issue workspace → handoff state),
  Attractor (spec → graph of phases, non-interactive) and Archon ("Mix deterministic nodes … with AI nodes") are
  three takes on one idea. Symphony is the most complete public spec. Archon's example
  (`loop … until: ALL_TASKS_COMPLETE`, `fresh_context: true`, then a `bash` validate node) is the clearest
  statement of the pattern in config form.
- **Company simulators model an org chart, not a verifier.** MetaGPT's roles are "product managers / architects /
  project managers / engineers". ChatDev 1.0 used CEO, CTO and Programmer agents. Neither README describes holdout
  checks, merge gates or work on an existing codebase as the main path. ChatDev added "incremental development"
  as an option in 2023. Anthropic's evidence points the other way: the C compiler used no orchestrator agent, and
  the harness post kept only the planner and evaluator, the parts that still paid for themselves.
- **"pstack" and gstack are skill stacks, not factories in the pipeline sense.**
  - **pstack** is real. It is Lauren Tan's ("poteto", Cursor and React core team) plugin in the official
    [cursor/plugins](https://github.com/cursor/plugins) repo, listed as "rigorous agent workflows you can
    parallelize with confidence". Its README says "pstack helps you write less, but higher quality code".
    `/poteto-mode` "matches your task to a playbook" out of 23, including `babysit` ("drive a pr or a stack to
    merge-ready: conflicts, review threads, ci"), `shipping` ("independently verify a green stack, then land
    …"), `autopilot-full` and a blinded `eval`. It splits work across models, with code delegated to one model
    and "the hardest changes, prose, and judgment" to another ([pstack README](https://github.com/cursor/plugins/tree/main/pstack)).
    It installs with Cursor's `/add-plugin pstack`. Claude Code ports are third-party, the largest being
    [michael-denyer/pstack-claude](https://github.com/michael-denyer/pstack-claude) (2.6k stars), then
    [backnotprop/pstack](https://github.com/backnotprop/pstack) (2.0k) and
    [ericlitman/open-pstack](https://github.com/ericlitman/open-pstack) (421, "tracking Cursor pstack upstream"),
    all seen 2026-10-16. Two name clashes to ignore: [peadar/pstack](https://github.com/peadar/pstack) is the Unix
    stack-trace tool, and [no-session/pstack](https://github.com/no-session/pstack) is an unrelated gstack fork.
  - **gstack** is Garry Tan's (YC) Claude Code setup, and he calls it "my open source software factory". It is
    23 role skills (`/office-hours`, `/plan-ceo-review`, `/plan-eng-review`, `/review`, `/qa`, `/ship` …) run "in
    the order a sprint runs". It installs into `~/.claude/skills/gstack`, and its "team mode" commits a
    requirement into the repo's `.claude/` and CLAUDE.md. It also ships an opt-in verification Stop hook,
    `gstack-verify-gate` ([gstack README](https://github.com/garrytan/gstack)).
  - Both sit at the same layer as superpowers plus ponytail plus impeccable, which this repo already runs.
    Installing either would add a third opinion on the same phases. pstack's write-less stance matches ponytail.
    gstack's role sprint is closer to superpowers, plus a QA lead "who opens a real browser".

### How factories measure themselves

- **Scenario satisfaction** (StrongDM): the fraction of trajectories that likely satisfy the user, measured on
  holdout scenarios ([factory.strongdm.ai](https://factory.strongdm.ai/)).
- **Throughput and gate counts** (Factory): tickets triaged, PR validations, PRs merged, incidents processed
  ([docs](https://docs.factory.com/software-factory/overview.md)).
- **Evals of your own agent** (Anthropic): "20-50 simple tasks drawn from real failures is a great start".
  Regression evals "should have a nearly 100% pass rate", while capability evals "should start at a low pass
  rate". Use pass^k ("the probability that all k trials succeed") when reliability matters, which it does for an
  unattended factory. "it's often better to grade what the agent produced, not the path it took." You must "read
  the transcripts" ([Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)).
- **Noise.** Changing only resource limits moved Terminal-Bench scores by 6 points. "leaderboard differences under
  3 percentage points warrant skepticism" ([Infrastructure noise](https://www.anthropic.com/engineering/infrastructure-noise)).
- **SWE-bench**: "Given a *codebase* and an *issue*, a language model is tasked with generating a *patch*"
  ([README](https://github.com/SWE-bench/SWE-bench); [paper](https://arxiv.org/abs/2310.06770)). It is useful for
  picking a model or harness. It says nothing about whether *your* specs, tests and gates are good.

### Dashboards: runs, tasks, PRs and CI at a glance

A factory needs one place that shows three things: which runs are working or blocked, which are waiting on a
human, and the PR and CI state of what they produced. The options below were checked against their own docs or
READMEs.

| Dashboard | Shows | Where it runs | Agents covered | Fit for this repo |
| :- | :- | :- | :- | :- |
| **claude.ai/code session list + Projects Overview** ([cloud](https://code.claude.com/docs/en/claude-code-on-the-web), [projects](https://code.claude.com/docs/en/claude-projects)) | Sessions in the sidebar. Per session, a CI status bar with the Auto-fix toggle. The Projects **Overview** shows "which threads finished, which pull requests are ready for review, and which thread is waiting for your answer" | Cloud, web and mobile | Claude Code | **Best fit, already in use.** Projects is public beta on Pro and Max, and not on Team or Enterprise yet |
| **Claude Code agent view** (`claude agents`, [docs](https://code.claude.com/docs/en/agent-view)) | "what's running, what needs your input, and what's done" | Local terminal, research preview | Claude Code | Good for local runs. Cloud work is better seen in the web list |
| **Claude Code Desktop** ([docs](https://code.claude.com/docs/en/desktop#monitor-pull-request-status)) | Parallel sessions with Git isolation. After a PR, "a CI status bar appears in the session" | Local app (needs `gh`) | Claude Code | Good when working locally |
| **GitHub Agents tab / agents panel** ([changelog](https://github.blog/changelog/2026-01-26-introducing-the-agents-tab-in-your-repository/)) | "all sessions for the repository in one place", with links to the PR | github.com | Copilot coding agent only (per that changelog) | Skip. It doesn't show Claude sessions |
| **GitHub PR list + Actions tab** (built-in) | Open PRs with check status, and every workflow run, gh-aw runs included | github.com | Any agent that opens PRs | **Keep as the source of truth** for PR and CI state, especially once `main` requires checks |
| **Symphony status surface** ([elixir/README](https://github.com/openai/symphony/blob/main/elixir/README.md)) | Optional "Phoenix LiveView dashboard and JSON API" where a run needing input "exposes it as blocked in the runtime state, JSON API, and dashboard". The spec makes the dashboard optional ([SPEC §13.4](https://github.com/openai/symphony/blob/main/SPEC.md)) | Self-hosted | Codex (reference impl) | Borrow the idea (blocked as a first-class state). Don't run it |
| **vibe-kanban** ([README](https://github.com/BloopAI/vibe-kanban)) | Kanban issues → workspaces (branch, terminal, dev server), inline diff comments, PR creation and merge | Local web app (`npx`) | 10+ agents | Skip. Local only, and it duplicates GitHub issues plus cloud sessions |
| **Conductor** ([docs](https://www.conductor.build/docs/)) | "Each task gets its own workspace, branch, files, terminal, diff, and review path" | Mac app | Claude Code, Codex, Cursor, OpenCode | Skip. Local Mac app, and the docs state no license |
| **claude-squad** ([README](https://github.com/smtg-ai/claude-squad)) | TUI list of agent instances, each in "its own isolated git workspace" | Local terminal (tmux) | Claude Code, Codex, Gemini … | Skip. Local, and AGPL-3.0 |
| **Gas Town `gt feed`** ([README](https://github.com/gastownhall/gastown)) | "a three-panel TUI" combining beads activity, agent events and merge queue, with a `--problems` view for "stuck agent detection" | Local terminal plus an optional web dashboard | Claude Code, Copilot, Codex … | Skip. Built for 20-30 agents |
| **OpenHands Agent Canvas** ([README](https://github.com/OpenHands/OpenHands)) | Conversations and automations across local, Docker, VM or cloud backends | Self-hosted web app | OpenHands, Claude Code, Codex … via ACP | Skip. A second platform to host |
| **Factory Software Factory dashboard** ([docs](https://docs.factory.com/software-factory/overview.md)) | Stage health and Tickets Triaged / PR Validations / PRs Merged | Factory App (Private Preview) | Droid | Skip. Closed, different agent |
| **gh-aw** ([github/gh-aw](https://github.com/github/gh-aw)) | No separate dashboard. Agentic workflows run as normal Actions runs | github.com | Copilot, Claude Code, Codex … | Same view as the Actions tab |

**What fits this repo.** The work already runs as cloud sessions that end in PRs, so the dashboard already
exists in two halves. **claude.ai/code** (session list, per-session CI bar, Projects Overview) shows agent
state. **GitHub's PR list and Actions tab** show merge and CI state. Don't build a third.

Two notes on what is in the repo now:

- The `runs-pane` mod is not a factory dashboard. It shows the *product's* pipeline runs (`python3 -m arp.cli
  runs list`: status, type, progress and cost), not coding-agent sessions or PRs
  (`.claude/mods/runs-pane/hooks/register.tsx`).
- The React frontend (`frontend/`) is the investment research product. It already has `BackgroundAgents` and
  `RunHistory` pages for the product's own agents and runs. Adding developer-workflow status there would mix two
  audiences in one app.

If a glance view inside Claude Code turns out to be missed, the smallest addition is a second mod next to
`runs-pane` that lists open PRs and their check state from `gh pr list --json`. It would follow the same
15-second refresh pattern. Hold this until items 1-4 below are in place and the web views have proved
insufficient.

---

## 3. The best approach

### What the primary sources agree on

1. **Start from complete intent, or don't run unattended.** StrongDM: "Spec + Test Suite = Complete Intent".
   Shapiro's Level 4 is writing specs and plans. Symphony reads only eligible tracker states. Anthropic's planner
   writes the spec and leaves out "granular technical detail". If a task needs "generate, clarify, generate", keep
   it interactive.
2. **Agree on "done" before code exists.** Anthropic's sprint contracts settle "what 'done' looked like … before
   any code was written". `/goal` encodes the same idea as a completion condition that a fresh model checks.
3. **Run each item in an isolated, low-privilege workspace.** Examples: Symphony's per-issue workspaces, Codex's
   "Each task has its own workspace", Copilot's `copilot/` branch and firewall, routines' `claude/` branches, and
   gh-aw's read-only agent with safe outputs. Anthropic: "network is denied by default", and secrets stay out of
   the sandbox.
4. **Verification is the product, and it has three layers.**
   (a) Deterministic checks (tests, lint, types, CI) that the agent runs itself. The 2026-10-11 doc covers this.
   (b) A **verifier the implementer cannot edit or see**: StrongDM's holdout scenarios, the C compiler's GCC
   oracle, and the "nearly perfect" task verifier.
   (c) A **separate evaluator agent** that uses the running software ("the way a user would", via Playwright), not
   just the diff, because self-evaluation "confidently praise[s] the work".
5. **Review in a fresh context, with verified findings, and keep it narrow.** Code Review runs several agents,
   then "a verification step". Anthropic's own engineers review intent and "tell Claude 'no'" to over-engineering.
6. **A merge gate the agent cannot open by itself.** Copilot can't approve or merge its own PR. Code Review
   "never approves or blocks". Symphony ends at a `Human Review` state. Only StrongDM removes the human, and only
   behind holdout scenarios plus digital twins.
7. **Close the loop.** CI failures and review comments go back to the agent (auto-fix). StrongDM feeds "A sample
   of the output" back in. Evals grow out of real failures.
8. **Delete harness as models improve.** The harness post dropped sprints and context resets once models no longer
   needed them, and the C compiler used a bash loop rather than an orchestrator. Add a component only when
   something fails without it.

### Ranked options (opinionated)

1. **Vendor-native glue around the tools you already use** (best for this repo). Use cloud sessions plus a
   trigger (routine or GitHub Action), Stop hook plus CI as the deterministic gate, a fresh-context review on
   every PR, auto-fix, and a protected `main`. There is no new framework, and every piece is documented by the
   vendor that runs it.
2. **A thin queue daemon built from the Symphony spec** on the Agent SDK. Reach for this only when routines and
   Actions can't express the intake you need, for example concurrency limits across many issues, retries with
   backoff, or reconciling against tracker state.
3. **A workflow engine** (Archon, or gh-aw for Actions-native teams) when several repos must share one fixed
   plan→implement→validate→review→PR graph.
4. **Another spec toolkit** (spec-kit, OpenSpec, BMAD) only if you are not already on superpowers. They are
   interchangeable at the artefact level.
5. **Company simulators** (MetaGPT, ChatDev, ruflo): don't. They add roles and tokens, while the evidence above
   says outcomes come from verifiers and gates.

**On going "dark".** Holdout scenarios and digital twins are what make StrongDM's no-review rule defensible. Without
them, removing human review just removes the last check. For this repo, which handles investment research data and
has a [Corporate Readiness Plan](CORPORATE_READINESS_PLAN.md), the right target is Shapiro's Level 4. Humans approve
the spec and merge the PR, and they review the intent of the change rather than every line, as Anthropic does.
Agents do everything in between.

---

## Implications for this repo (ranked: smallest change that holds first)

Current state, checked 2026-10-16:

- **Spec and plan:** superpowers brainstorming and writing-plans. `docs/superpowers/` holds 19 specs and 30 plans.
- **Implementation:** cloud sessions. The local history is shallow (it starts 2026-10-03) and holds 40 merged
  PRs, #93 to #146. 39 came from `ccr-*` or `claude/*` session branches.
- **Deterministic gate:** a Stop hook (`.claude/hooks/check.sh`) lints and tests changed code and exits 2 on
  failure. CI (`.github/workflows/ci.yml`) runs backend ruff and pytest against Postgres and OpenSearch, frontend
  lint, build and `npm test`, gitleaks, and a supply-chain audit. The `test-guard` mod flags removed tests.
- **Review:** `/ponytail:ponytail-review` plus `/code-review`, in-session, per CLAUDE.md.
- **Feedback:** PR auto-fix is available in cloud sessions.
- **Gaps:** nothing starts a session except a person. No review runs in a fresh context on the PR. No check is
  hidden from the implementer. The GitHub branches API reports `"protected": false` for `main`.

1. **Make `main` require the CI jobs before merge** (repository settings, no code). Today the gate is advisory:
   CI runs on PRs, but nothing stops a merge on red. This is the cheapest change that turns the existing CI into
   a real merge gate, and every vendor gate above assumes one. Check Settings → Rules first, because rulesets may
   not show in the branches API's `protected` flag. While there, the repo has about 90 leftover session branches,
   so consider auto-deleting head branches after merge.
2. **Add a fresh-context PR review with `claude-code-action`.** The 2026-10-11 doc listed this as optional "when PR
   volume justifies it". Forty PRs in under two weeks justifies it. Use the documented review workflow
   (`/code-review:code-review --comment`) with `--max-turns`, and tell it to flag only correctness and spec gaps,
   which both Anthropic sources ask for. If the account is on Team or Enterprise, managed
   [Code Review](https://code.claude.com/docs/en/code-review) does the same with no workflow file. Leave it
   non-blocking at first, as Code Review itself is.
3. **Give every spec an acceptance block that the reviewer checks.** Superpowers specs already state decisions.
   Add a short "Acceptance" section of runnable commands or user-visible scenarios, and have the review step in
   item 2 check the diff against it ("agreeing on what 'done' looked like … before any code was written"). This is
   a template line plus one sentence in the review prompt, not a new tool.
4. **Add one intake trigger.** Routines' GitHub trigger can't fire on issues, so pick one of these:
   (a) `claude-code-action` on `issues: [labeled]` for a label such as `agent-ready`, which runs on GitHub runners
   with the same CI dependencies; or
   (b) a scheduled routine that picks up `agent-ready` issues through the GitHub connector and opens PRs.
   Either way the run ends at a PR, never a merge, matching Symphony's `Human Review` state. For (a), PRs created
   with the default `GITHUB_TOKEN` do not trigger CI (noted in the earlier doc), so use the Claude GitHub App token.
5. **Add a small holdout scenario suite for one high-stakes flow** once items 1-4 run smoothly, for example an
   end-to-end `arp` CLI or API run on fixed fixtures. Keep it outside what the implementer reads: a private
   companion repo or a CI-only checkout, run as a required check. This is StrongDM's defence against "a test …
   lazily rewritten to match the code", and it is what would make less human review safe later. The repo's
   existing rule "never delete or weaken an existing test" and the `test-guard` mod cover the in-repo side.
6. **Dashboard: use what exists.** Use the claude.ai/code session list and Projects Overview for agent state,
   and GitHub's PR list for checks. Only if that proves insufficient, add a small `gh pr list` mod beside
   `runs-pane` (see Dashboards above). Don't put factory status into the product frontend.
7. **Measure before scaling.** Use a weekly scheduled routine that reports PRs merged, the share needing more than
   one auto-fix round, CI red rate on agent PRs, and reverts. Anthropic's advice is to grow an eval set from real
   failures (20-50 tasks). Don't use SWE-bench for this.

**Adopt:** `anthropics/claude-code-action` (items 2 and 4). Read and borrow from `openai/symphony` (`WORKFLOW.md`
in-repo policy, handoff states, eligibility reconciliation) and `strongdm/attractor` and factory.strongdm.ai
(holdout scenarios, satisfaction). Keep `obra/superpowers` as the spec layer.

**Revisit later:** `github/gh-aw` for read-only "continuous AI" jobs once it leaves technical preview.
`claude-agent-sdk-python` only if item 4 outgrows routines and Actions. Archon if a second repo needs the same
workflow.

**Skip:** the other spec toolkits (they duplicate superpowers), Taskmaster (Commons Clause, quiet since April),
the alternative runners (OpenHands, SWE-agent, aider, Codex), local parallel-session managers (claude-squad,
vibe-kanban, Crystal/Nimbalyst, Gas Town, beads), the company simulators (MetaGPT, ChatDev, ruflo), and cxdb.

Skipped in this research: Codex code-review internals, Factory Missions, Anthropic's dynamic-workflows blog post,
and auto mode. None of them changes the ranking above.

---

## Sources

Definitions and vendor docs:
- https://factory.strongdm.ai/ (Feb 6, 2026), https://factory.strongdm.ai/principles, https://factory.strongdm.ai/techniques, https://factory.strongdm.ai/techniques/dtu, https://factory.strongdm.ai/techniques/shift-work, https://factory.strongdm.ai/products
- https://www.danshapiro.com/blog/2026/01/the-five-levels-from-spicy-autocomplete-to-the-software-factory/ (Jan 23, 2026)
- https://docs.factory.com/software-factory/overview.md, https://docs.factory.com/llms.txt (index of Delegations, Droid Exec, Missions)
- https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent
- https://docs.github.com/en/copilot/concepts/agents/coding-agent/risks-and-mitigations
- https://github.github.com/gh-aw/
- https://learn.chatgpt.com/docs/cloud (redirect target of developers.openai.com/codex/cloud)
- https://kiro.dev/docs/specs/
- https://code.claude.com/docs/en/github-actions, /code-review, /claude-code-on-the-web (auto-fix), /routines, /goal, /agents, /agent-sdk/overview (fetched as `.md`)

Anthropic engineering:
- https://www.anthropic.com/engineering/harness-design-long-running-apps (Mar 24, 2026)
- https://www.anthropic.com/engineering/building-c-compiler (Feb 5, 2026)
- https://www.anthropic.com/engineering/redesigning-source-control (Oct 13, 2026)
- https://www.anthropic.com/engineering/how-we-contain-claude (May 25, 2026)
- https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents (Jan 9, 2026)
- https://www.anthropic.com/engineering/infrastructure-noise (Feb 5, 2026)

Skill stacks and dashboards:
- https://github.com/cursor/plugins (README and `pstack/README.md`, `pstack/LICENSE`), https://github.com/michael-denyer/pstack-claude, https://github.com/garrytan/gstack
- https://code.claude.com/docs/en/agent-view, /desktop, /claude-projects (fetched as `.md`)
- https://github.blog/changelog/2026-01-26-introducing-the-agents-tab-in-your-repository/
- https://www.conductor.build/docs/
- https://github.com/openai/symphony/blob/main/elixir/README.md
- This repo: `.claude/mods/runs-pane/hooks/register.tsx`, `frontend/src/pages/`

Repositories (README, plus LICENSE where the API reported NOASSERTION or none; metadata from the GitHub search API, 2026-10-16):
- strongdm/attractor, strongdm/cxdb, openai/symphony (README and SPEC.md), openai/codex, openai/codex-action, github/spec-kit, github/gh-aw, Fission-AI/OpenSpec, bmad-code-org/BMAD-METHOD, bmad-code-org/bmad-loop (metadata only), eyaltoledano/claude-task-master, kirodotdev/Kiro (metadata only), anthropics/claude-code-action, anthropics/claude-agent-sdk-python (metadata only), anthropics/claude-agent-sdk-typescript, OpenHands/OpenHands, SWE-agent/SWE-agent, SWE-agent/mini-swe-agent, Aider-AI/aider, coleam00/Archon, BloopAI/vibe-kanban, smtg-ai/claude-squad, stravu/crystal, nimbalyst/nimbalyst (metadata only), gastownhall/gastown, gastownhall/beads, FoundationAgents/MetaGPT, OpenBMB/ChatDev, ruvnet/ruflo, SWE-bench/SWE-bench, obra/superpowers
- https://arxiv.org/abs/2310.06770 (SWE-bench paper, cited from its README)

This repo: `.claude/CLAUDE.md`, `.claude/settings.json`, `.claude/hooks/check.sh`, `.github/workflows/ci.yml`,
`docs/superpowers/`, `git log` (shallow, from 2026-10-03), GitHub branches API for `main`.

## Pages not fetched

- https://openai.com/index/harness-engineering/ returned HTTP 403, and the web.archive.org copy was unreachable
  through the proxy. Only its existence and title are used, via Symphony's README link. None of its contents are
  cited.
- https://docs.factory.ai/welcome redirected to docs.factory.com/welcome, which returned 404. The llms.txt index
  and the Software Factory page were used instead.
- https://learn.chatgpt.com/docs/cloud/code-review returned 404, so Codex code review is not described.
- `gh api` was refused for all external repos in this session, so repo metadata came from the GitHub MCP search
  tool and raw.githubusercontent.com.
- https://github.com/ruvnet/claude-flow returned 403 via curl. The rename to ruflo is inferred from ruflo's
  README, which still links the old name and `@claude-flow/*` packages.
- No docs.github.com page for the agents panel or Agent HQ mission control turned up. Only GitHub's changelog
  was used, so whether the Agents tab lists third-party agents may have changed since 2026-01-26.
- Conductor's docs state no license or pricing, and its Checks page was not fetched.
- Branch rulesets for `main` could not be read. Only the branches API `protected` flag was checked.
