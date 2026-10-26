# frontier

Personal frontier repo — workspace for the mattpocock/skills engineering workflow.

## Agent skills

### Issue tracker

Issues, specs, tickets, and wayfinder maps live only in GitHub Issues of `Moke110/frontier`; do not create local spec/ticket drafts or mirrors. See `docs/agents/issue-tracker.md`. `.scratch/` is legacy/read-only.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout (`CONTEXT.md` + `docs/adr/` at the repo root). See `docs/agents/domain.md`.

### frontier loop

The daily workflow (checkpoints → retrieval → editor/writer agent tasks → Lark push → ratings → knowledge-graph/proposition updates) is documented in `SKILL.md`. Installation is a task for the user's agent: `INSTALL.md`; contracts live in `contracts/`.

### Skill pack

`mattpocock/skills` (38 skills) is installed user-level at `~/.workbuddy/skills/` — each entry is a directory junction to `~/.agents/skills/<name>/`, and `~/.agents/.skill-lock.json` records source and hashes. Update via `~/.agents/skills`, **not** by editing through `~/.workbuddy/skills` (writes land in the shared source).

Driven by the user as `/skill-name` (their `SKILL.md` sets `disable-model-invocation: true`, so the model never auto-starts them): `wayfinder`, `to-spec`, `to-tickets`, `triage`, `implement`, `implement-spec`, `grill-me`, `grill-with-docs`, `improve-codebase-architecture`, `wait-what`, `loop-me`, `retro`, `handoff`, `claude-handoff`, `teach`, `to-questionnaire`, `writing-beats`, `writing-fragments`, `writing-shape`, `ask-matt`, `setup-matt-pocock-skills`, `setup-ts-deep-modules`.

Model-invocable on match: `code-review`, `codebase-design`, `diagnosing-bugs`, `domain-modeling`, `git-guardrails-claude-code`, `grilling`, `migrate-to-shoehorn`, `pr`, `prototype`, `research`, `resolving-merge-conflicts`, `scaffold-exercises`, `setup-pre-commit`, `tdd`, `wizard`, `writing-for-agents`.

The tracker config those skills read is `docs/agents/issue-tracker.md`; `setup-matt-pocock-skills` only needs re-running if the tracker moves.
