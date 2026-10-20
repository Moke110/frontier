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

Fields: `id`, `title`, `content`, `history`, `related_knowledge`.

- `related_knowledge` is a list of knowledge card ids and **must contain at least two cards**.
- `history` is the proposition's change log and evidence trail: timestamp, source (paper/push), before → after, rationale, and the supporting quote/page where applicable.

## Theme（主题）

Not a stored entity. A theme is only a grouping used to batch-confirm the initial knowledge-base build. Confirmed themes become knowledge cards and propositions; the theme name itself is not persisted as a graph node.

## Push（推送）

One paper's long-form PDF plus its rating question and any knowledge-update questions. One push, one paper.

## Unified question queue（统一问题队列）

A single serial queue of questions produced by a push or by the initial build confirmation flow.

- Item kinds: push rating, knowledge-card update, proposition update.
- One active question at a time; the next is sent only after the current one is submitted.
- Updates to the same card or the same proposition are grouped into one question.
- A rating is answered first; update questions follow.
- An `irrelevant` rating discards that push's update questions.
- Every question must be answered before the next retrieval push may start.

## Pending retrieval request（待推请求）

A retrieval trigger (manual "再推一篇" or the daily 08:00 run) that arrives while the question queue is non-empty. It is recorded, coalesced with other pending requests, and executed automatically once the queue is empty.

## Rating（评分）

`irrelevant` / `ok` / `great`. This phase uses ratings only to gate knowledge updates; ratings do **not** feed back into retrieval weights or ranking.

## Writer

The agent role that reads a paper and proposes knowledge-card / proposition updates. The writer never writes `$KL_HOME/archive/**` directly; approved changes go through the archive CLI.
