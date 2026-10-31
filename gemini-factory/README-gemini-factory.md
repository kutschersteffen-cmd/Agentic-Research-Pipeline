# Gemini factory kit

Runs features through spec → hidden tests → implement → review → evaluate → merge with Gemini Code Assist
agent mode (VS Code or IntelliJ) or Gemini CLI. Each stage is a fresh chat. The fresh chat keeps the reviewer
separate from the builder.

## Install (about 10 minutes)

1. Copy everything in this folder into the root of your repo: `GEMINI.md`, `.gemini/`, `docs/factory/`.
2. Create a GitHub fine-grained token with Contents, Pull requests, Issues and Actions (read/write) on the repo,
   and export it as `GITHUB_PAT` before starting the IDE. `.gemini/settings.json` uses it for the GitHub MCP server.
3. Create labels: `risk:low`, `risk:normal`, `risk:high`, `factory:blocked`.
4. Protect `main`: require PRs and green CI.
5. Hidden tests: create a private `holdout` repo, plus a CI job in the main repo that, on PRs with a `Spec: <slug>`
   line, checks out holdout with a secret token, runs `specs/<slug>/` and `regression/`, and prints only `AC-n pass|fail`.
   Until that exists, write those rows as `unit`.
6. Open the repo in your IDE, switch the Gemini chat to **Agent** mode, and type `/factory`.

## Daily use

| You type in a NEW chat | Where | What happens |
|---|---|---|
| `/factory <feature idea>` | main repo | Tells you which command to start with |
| `/factory:spec <feature idea>` | main repo | Q&A, spec, you approve, spec PR. You merge it. |
| `/factory:tests <slug>` | **holdout repo window** | Hidden tests PR. You merge it. |
| `/factory:implement <slug>` | main repo | Code PR, fixes CI |
| `/factory:review <pr>` | main repo | `Code review (factory)` comment |
| `/factory:evaluate <pr>` | main repo | `Acceptance matrix (evaluator)` comment |
| You merge on GitHub | | Then `/factory:tests <slug> --regression` in the holdout window |
| `/factory` | main repo | Status of every feature + next command |

Never open the holdout repo in the same window or chat as implementation work.

## If slash commands don't show up

Custom commands come from Gemini CLI's `.gemini/commands/*.toml`. If your Code Assist version doesn't list them,
open the matching `.toml`, copy its `prompt` text into the chat and replace `{{args}}` by hand. The rules in
`GEMINI.md` load as context either way.
