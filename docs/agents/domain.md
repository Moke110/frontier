# Domain documentation

Single context: root `CONTEXT.md` is the project glossary; `docs/adr/` holds the decision history. These are maintained through Matt Pocock's `domain-modeling` workflow, reached while using `grill-with-docs` or resolving domain decisions.

Before exploring or planning, read `CONTEXT.md` and the ADRs relevant to the work. If a document is absent, proceed; create entries lazily when a term or meaningful decision is resolved.

- Use canonical glossary terms in issues, code and discussion. Clarify conflicting meanings and update the resolved definition immediately.
- Keep the glossary about vocabulary; schemas and implementation rules belong in `contracts/`, plans in GitHub Issues.
- Keep existing ADR history and supersession links. Flag a proposal that conflicts with an accepted ADR instead of silently overriding it.
- Record an ADR only for a decision with a meaningful trade-off, a real cost to reverse and context a future reader would otherwise miss. Use the skill's format and next sequential number.
- Put development instructions in `AGENTS.md`, user instructions in `README.md`, and runtime instructions in `skills/frontier-run/`. Keep each rule authoritative in one place.

Do not introduce a multi-context map unless the project actually grows separate domain contexts and the user agrees to the layout change.
