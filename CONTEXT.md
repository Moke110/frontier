# frontier — domain glossary

This file is vocabulary, not a spec. Implementation lives in `contracts/` and the code.

## Knowledge card（知识卡片）

The canonical frontier item. A knowledge card **replaces** the old checkpoint.

Fields: `id`, `label`, `ontology`, `annotation`.

- `ontology` drives recall (synonyms / surface forms).
- `annotation` drives precision (definition, exclusions, confusions).
- A card stores **no** knowledge-to-knowledge links and **no** knowledge-to-proposition links.

## checkpoint

Retired as an independent entity. Where the old vocabulary says "checkpoint", read "knowledge card id". Retrieval plans over knowledge cards.

## Proposition（命题）

A cross-paper synthesized claim, not a per-paper summary.

Fields: `id`, `title`, `review`, `related_knowledge`, `evidence`, `changelog`,
`evidence_updates_since_review`.

- `related_knowledge` is a list of knowledge card ids and **must contain at least two cards**.
- A new proposition must carry **at least two evidence entries**.
- `review` is the current synthesis (≤2000 characters, four fixed sections).
- `changelog` records non-evidence changes (title / review / related_knowledge): timestamp, source, before → after, rationale.

## Evidence（证据）

One entry in a proposition's `evidence` list: `id`, `stance` (`supports` /
`contradicts`), `conclusion` (≤200 characters), `papers[]` (paper_id, push_id,
page, quote, added_at), `created_at`, `updated_at`.

- An entry contains only reports whose conclusions point in the same direction.
- Different entries under the same proposition may contradict each other.
- A new report merges into an existing entry when the stance and direction agree; otherwise it becomes a new entry.

## Review（综述）

A proposition's `review` is synthesized from its evidence, never from outside
facts. It is rewritten automatically after every ten accepted evidence updates.
Rejecting a new review keeps the counter; the next accepted evidence update
retries.

## Evidence update（证据更新）

One accepted `add_proposition_evidence` or `merge_proposition_evidence` proposal.
Each accepted proposal counts as one update, regardless of how many reports it
adds.

## Review update（综述更新）

The queued question that asks the user to adopt a newly written review. It is
independent of the per-push update budget and gates the next retrieval push
until answered.

## Theme（主题）

Not a stored entity. A theme is only a grouping used to batch-confirm the initial knowledge-base build. Confirmed themes become knowledge cards and propositions; the theme name itself is not persisted as a graph node.

## Push（推送）

One paper's long-form push (HTML from Phase 3) plus its rating question and any knowledge-update questions. One push, one paper.

## Unified question queue（统一问题队列）

A single serial queue of questions produced by a push or by the initial build confirmation flow.

- Item kinds: push rating, knowledge-card update, proposition evidence update, proposition review update.
- One active question at a time; the next is sent only after the current one is submitted.
- Updates to the same card or the same proposition are grouped into one question.
- One push has at most **two entity targets** in total (cards + propositions, creates included).
- A rating is answered first; update questions follow.
- An `irrelevant` rating discards that push's update questions.
- Every question must be answered before the next retrieval push may start.

## Pending retrieval request（待推请求）

A retrieval trigger (manual "再推一篇" or the daily 08:00 run) that arrives while the question queue is non-empty. It is recorded, coalesced with other pending requests, and executed automatically once the queue is empty.

## Rating（评分）

`irrelevant` / `ok` / `great`. This phase uses ratings only to gate knowledge updates; ratings do **not** feed back into retrieval weights or ranking.

## Writer

The agent role that reads a paper and proposes knowledge-card / proposition updates. The writer never writes `$KL_HOME/archive/**` directly; approved changes go through the archive CLI.
