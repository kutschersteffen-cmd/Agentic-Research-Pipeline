# Engineering playbook skill

This package turns the agreed playbook into an explicitly invoked agent workflow
and a local Python function/CLI. It is a first implementation of the skill and
advisory evaluator, not an installed remote orchestrator or enforcement of CI.

## Codex

The repository skill lives in `.agents/skills/engineering-playbook/`. In a Codex
client that supports repository skills, refresh/restart skill discovery after
checking out this branch, then invoke:

```text
$engineering-playbook plan Fix conflicting reviewer corrections
$engineering-playbook start <approved task>
$engineering-playbook status <PR or ledger>
$engineering-playbook verify <PR>
$engineering-playbook release-check <candidate>
```

No mode means plan. Loading/installing the skill does not execute any task. The
current conversation's available tools are not changed by committing a skill.
Hosts without repository-skill discovery can explicitly read its `SKILL.md` and
follow the same instructions. The full playbook and executable helper contract
are bundled in its `references/` directory.

## Existing Claude plugin marketplace

This repository already provides the `arp-mods` marketplace. The optional adapter
is registered there but is **not auto-installed or enabled** by this change:

```sh
claude plugin marketplace add .
claude plugin install engineering-playbook@arp-mods
```

Then use `/engineering-playbook:engineering plan <task>` in a compatible Claude
Code session. The adapter requires this matching repository checkout; it is not
a standalone ChatGPT App Store plugin. No hooks, credentials or auto-deployers
are installed. The adapter reads the canonical Codex skill rather than maintaining
a second process definition. Claude runtime validation was not available in the
development environment; inspect the draft PR's validation record.

## Callable function

Load `scripts/workflow.py` with Python/importlib and call
`evaluate_run(run, evidence, gate="merge" | "release" | "done", now=...)`.
The standard-library CLI supplies persistent accounting, worker registration,
pause/resume and structured JSON. See `references/helper.md` for the schema.

The helper checks recorded evidence; it cannot establish external truth or human
identity. It grants no merge/deployment authority. The coordinator must enforce
remote timeouts and validate authenticated approval/CI evidence independently.
CI and protected environments remain unchanged. Existing factory rules, including
high-risk owner merges, remain in force.

## Validation

```sh
python -m unittest discover -s .agents/skills/engineering-playbook/tests -v
python .agents/skills/engineering-playbook/scripts/workflow.py --help
```

Future adoption work: authenticated GitHub evidence ingestion, a global remote
deadline governor, measured/optimized holdout execution, and deliberate policy
reconciliation. Those remain separate scoped changes requiring their own evidence;
this package does not imply the existing CI pipeline meets 15 minutes.
