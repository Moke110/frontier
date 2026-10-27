# frontier

Personal frontier repo — workspace for the mattpocock/skills engineering workflow.

## Development responsibilities

- **Planning:** Codex handles complex work (architecture, cross-module changes, unclear requirements, or risky migrations); DeepSeek Harness handles simple, bounded work. Use the Matt Pocock workflow: `wayfinder` to map uncertain work, `grill-with-docs` to resolve decisions and record domain docs, `to-spec` to publish the agreed spec, then `to-tickets` to publish approved vertical slices and native blocking links. The skill is named `to-tickets` (plural).
- **Implementation:** DeepSeek Harness uses `implement` to execute the approved GitHub spec and tickets. Read the issue body, comments and blockers before starting; work only on unblocked tickets, and follow the skill's testing, review and commit requirements. Record results and remaining blockers in GitHub; close a ticket only when its acceptance criteria are met. Offline tests do not replace required live acceptance.
- **Handoff:** Planning ends with linked GitHub issues and clear acceptance criteria/dependencies. Implementation starts when the user requests it; a planning request alone does not authorize implementation. Return changes to scope or unresolved product decisions to the planner rather than silently changing the spec.
- **WorkBuddy:** no longer used to develop this repository. Keep project-specific WorkBuddy configuration and memory out of the workspace. This development-role change does not remove WorkBuddy as a frontier runtime host or waive its product acceptance requirements.

## Git workflow

All repository work, including planning documents, implementation and fixes, is done on **`dev`**. **`main`** is the integration branch; keep the remote default branch as `main`.

1. Before editing, inspect the working tree and fetch `origin`. Switch to `dev`; create it from the current agreed baseline if absent. Preserve existing commits and user changes. If switching would overwrite work, resolve that state without discarding it.
2. Synchronize `dev` with `origin/dev` and `main` before starting. Prefer fast-forward updates; resolve any divergence on `dev` without rewriting published history. Use explicit branch names when pulling or merging.
3. Commit completed changes on `dev` using explicit file paths. Run checks appropriate to the change and review the diff. An implementation's required live acceptance must remain visibly pending if unavailable.
4. Once the intended change is complete and verified, fetch again, fast-forward local `main` to `origin/main`, and incorporate any new `main` changes into `dev`. Resolve and verify integration on `dev`; keep `main` free of direct development commits.
5. Merge `dev` into `main` with `git merge --no-ff dev`. Push **after** the local merge: `git push --atomic origin dev main`. If atomic push is unsupported, push `dev`, then `main`, checking each result. On rejection, fetch and reconcile without force-pushing.
6. Return to `dev` and fast-forward it to the merged `main`; push `dev` so the next task starts from the same integrated baseline. Verify a clean working tree and matching local/remote tips before reporting completion.

Do not force-push, reset away commits, or delete historical branches as routine cleanup. Explicit user instructions such as “documents only” or “do not push” constrain this workflow.

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

Read the relevant `SKILL.md` before applying a skill. Shared Matt Pocock skills are installed under `~/.agents/skills/<name>/`; source metadata lives in `~/.agents/.skill-lock.json`. Codex and DeepSeek Harness should use their supported skill-loading mechanism against this shared source, without relying on WorkBuddy junctions. If a required skill is unavailable, report the missing integration rather than inventing its behavior.

The planning/implementation skills above are user-invoked workflows. Follow each skill's approval gates and delegated skills (including testing and code review); do not automatically start implementation merely because its skill is installed.

The tracker config those skills read is `docs/agents/issue-tracker.md`; `setup-matt-pocock-skills` only needs re-running if the tracker moves.
