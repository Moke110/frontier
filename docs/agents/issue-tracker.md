# Issue tracker: GitHub Issues

Issues, specs, and wayfinder maps live in the **GitHub repository** `Moke110/frontier` (remote `origin`), not in `.scratch/`.

`.scratch/` is a **legacy archive** of the pre-migration local tracker. It is read-only: never create new issues there.

## Conventions

- Repository: `Moke110/frontier` (public). Use `gh`; it must be authenticated (`gh auth status`).
- **Issue** = one GitHub issue in that repo.
- **Spec / PRD**: an issue labeled `spec`. The issue body is canonical; long-form material may also live under `docs/specs/<slug>.md` and be linked from the spec issue.
- **Comments / history**: GitHub issue comments and timeline. Do not append a `## Comments` section to issue bodies.
- **State**: open/closed via GitHub. No `Status:` line in the body.
- **Triage labels**: see `docs/agents/triage-labels.md`; create them once with the bootstrap command below.

Bootstrap labels (safe to re-run; skip ones that already exist):

```bash
for spec in \
  "needs-triage|Maintainer needs to evaluate this issue|fbca04" \
  "needs-info|Waiting on reporter for more information|d876e3" \
  "ready-for-agent|Fully specified, ready for an AFK agent|0e8a16" \
  "ready-for-human|Requires human implementation|1d76db" \
  "spec|Specification / PRD|5319e7" \
  "wayfinder:map|Wayfinder map|0052cc" \
  "wayfinder:research|Wayfinder research ticket|1d76db" \
  "wayfinder:prototype|Wayfinder prototype ticket|bfd4f2" \
  "wayfinder:grilling|Wayfinder grilling ticket|d4c5f9" \
  "wayfinder:task|Wayfinder task ticket|fef2c0"; do
  IFS='|' read -r name desc color <<< "$spec"
  gh label create "$name" --repo Moke110/frontier --description "$desc" --color "$color" 2>/dev/null || true
done
```

## Wayfinding operations

The **map** is an issue labeled `wayfinder:map`. Its **tickets** are native **sub-issues** of the map, each labeled `wayfinder:<type>`.

### Create the map

```bash
gh issue create --repo Moke110/frontier \
  --title "<effort name>" \
  --label wayfinder:map \
  --body-file map.md
```

The map body keeps the usual sections: Destination / Notes / Decisions so far / Not yet specified / Out of scope.

### Create a ticket

```bash
gh issue create --repo Moke110/frontier \
  --title "<ticket title>" \
  --label wayfinder:prototype \
  --body-file ticket.md
```

Attach it as a sub-issue of the map:

```bash
# gh >= 2.94
gh issue edit <ticket> --repo Moke110/frontier --set-parent <map>

# older gh: use the REST API with the issue's internal id (not its number)
CHILD_ID=$(gh api repos/Moke110/frontier/issues/<ticket> --jq .id)
gh api --method POST repos/Moke110/frontier/issues/<map>/sub_issues -F sub_issue_id="$CHILD_ID"
```

Ticket body is only the question / brief. The answer is posted later as a resolution comment.

### Claim a ticket

Before any work, assign it to yourself (an open, unassigned ticket is unclaimed):

```bash
gh issue edit <ticket> --repo Moke110/frontier --add-assignee @me
```

### Blocking (native dependencies)

Use GitHub's **blocked by** relationship, not a body convention:

```bash
# gh >= 2.94
gh issue edit <ticket> --repo Moke110/frontier --add-blocked-by <blocker>

# older gh
BLOCKER_ID=$(gh api repos/Moke110/frontier/issues/<blocker> --jq .id)
gh api --method POST \
  repos/Moke110/frontier/issues/<ticket>/dependencies/blocked_by \
  -F issue_id="$BLOCKER_ID"
```

List blockers:

```bash
gh api repos/Moke110/frontier/issues/<ticket>/dependencies/blocked_by
```

### Frontier

Open, unassigned, unblocked sub-issues of the map, lowest number first:

```bash
MAP=<map-number>
gh api repos/Moke110/frontier/issues/$MAP/sub_issues --paginate \
  --jq '.[] | select(.state=="open" and (.assignees|length)==0) | .number' |
while read -r n; do
  open_blockers=$(gh api \
    repos/Moke110/frontier/issues/$n/dependencies/blocked_by \
    --jq '[.[] | select(.state=="open")] | length')
  [ "$open_blockers" = "0" ] && echo "$n"
done | sort -n
```

### Resolve

```bash
gh issue comment <ticket> --repo Moke110/frontier --body-file answer.md
gh issue close <ticket> --repo Moke110/frontier

# then append one line to the map's "Decisions so far" and update it:
gh issue view <map> --repo Moke110/frontier --json body --jq .body > map.md
# edit map.md, then:
gh issue edit <map> --repo Moke110/frontier --body-file map.md
```

### Refer by name

Every map and ticket is an issue with a title. In narration and in the map's Decisions-so-far, refer to it by **title**, linked to the issue URL — never by a bare number or slug.

## Legacy notes

- Existing `.scratch/knowledge-loop/` and `.scratch/frontier-prototypes/` content predates this migration and is kept for history. New efforts must use GitHub Issues.
- `docs/agents/triage-labels.md` still lists the canonical label strings; they now map to GitHub labels of the same name.
