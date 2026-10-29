# frontier

面向研究者的知识库与论文报道推送系统：知识卡片驱动论文检索，报道推送到飞书，评分与采纳的更新持续积累为命题与证据。

## Language

### Knowledge

**Knowledge card（知识卡片）**:
The canonical unit of research interest, defined by a label, recall terms and a precision annotation. It replaces the retired checkpoint.
_Avoid_: checkpoint, topic, keyword

**checkpoint**:
Retired name for a knowledge-card id; it is not an independent entity.
_Avoid_: entity, node

**Proposition（命题）**:
A cross-paper claim synthesized from evidence and related knowledge cards.
_Avoid_: finding, summary, note

**Evidence（证据）**:
One directional entry under a proposition, supported by one or more reports.
_Avoid_: citation, quote, source

**Report（报道）**:
A specific citation of one source paper in one push, identified by the paper, push, page and quote.
_Avoid_: paper, papers table, excerpt

**Review（综述）**:
A proposition's current synthesis, rewritten only from its evidence after accepted updates.
_Avoid_: article, summary, write-up

**Theme（主题）**:
A temporary grouping used only to confirm the first batch of knowledge cards; the theme itself is not stored.
_Avoid_: category, tag, folder

### Delivery

**Push（推送）**:
One paper's long-form report plus its rating and knowledge-update questions.
_Avoid_: article, PDF, post

**Push artifact（推送件）**:
The self-contained HTML rendered for one push; it records what the researcher saw and is not a regenerable view.
_Avoid_: push, PDF, report file

**Rating（评分）**:
The researcher's `irrelevant` / `ok` / `great` verdict on a push; it gates knowledge updates, not retrieval ranking.
_Avoid_: score, vote, feedback score

**Unified question queue（统一问题队列）**:
One serial queue of rating and update questions, with one active question and at most two entity targets per push.
_Avoid_: approval queue, inbox, pending list

**Pending retrieval request（待推请求）**:
A retrieval trigger recorded while the question queue is non-empty; requests coalesce and run after the queue empties.
_Avoid_: backlog, retry queue, scheduled job

**Writer**:
The agent role that proposes knowledge-card and proposition updates; it never writes the archive directly.
_Avoid_: author, editor, generator

### Installation and storage

**Installation workspace（安装工作区）**:
The host project folder that contains the code directory and the data root as separate children.
_Avoid_: repo root, project root, workspace root

**Host（运行宿主）**:
The agent application that installs and runs frontier on the user's machine: it executes local commands, loads the runtime skill, and wakes itself when a planned run is due.
_Avoid_: machine, runtime, bot

**Host schedule（宿主定时任务）**:
A schedule owned by the host rather than the operating system that starts one frontier run at the planned time; creating it is not evidence that it fired.
_Avoid_: cron job, service, daemon

**Listener（监听进程）**:
The single foreground process on the host machine that consumes Feishu events from the owner and runs bounded frontier actions, so the system answers without an open agent session. It is started and stopped by the user, not by the operating system.
_Avoid_: service, daemon, bot, background job

**Heartbeat（心跳）**:
The listener's periodic liveness record, rewritten while the listener runs; the evidence used to tell "listening" from "process exists".
_Avoid_: pid file, ping

**Listener health check（监听巡检）**:
The host agent's bounded daily run that reads the heartbeat, restarts the listener at most once, and reports what it found.
_Avoid_: watchdog, monitor, uptime check

**Derived host run（派生运行）**:
A bounded host-agent run the listener starts for work that needs judgement, such as sorting and writing one push; it holds the same single-executor lease and is not a second executor.
_Avoid_: headless agent, child session, bot run

**Code directory（代码目录）**:
The frontier repository checkout, kept separate from research data.
_Avoid_: workspace, install directory, app folder

**Data root（数据根）**:
The local location for configuration, run state, cache and offline backups for one installation.
_Avoid_: cache, backup, home

**Data-root private environment（数据根私有环境）**:
The uv-managed Python environment and interpreter kept inside the data root (`<home>/.venv`), created by a uv resolved from outside the workspace first; the code directory holds no environment, and later runs use the recorded absolute interpreter.
_Avoid_: repo venv, workspace virtualenv, system Python

**Source document（原文）**:
A paper's PDF original, keyed by `paper_id`; a paper has at most one source file.
_Avoid_: literature, reference, attachment

**Library（库）**:
A Drive root directory plus its Base registration table; source and push libraries share one quota.
_Avoid_: folder, bucket, archive

**In library（在库）**:
A file is in Drive and registered in the Base; only this state counts toward the quota.
_Avoid_: uploaded, synced, stored

**No source file（无原件）**:
A source record exists but Drive has no file, usually because of a paywall.
_Avoid_: missing paper, broken record, empty

**Archived offline（已离线归档）**:
The file was downloaded, md5-verified and removed from Drive; its Base row remains permanently.
_Avoid_: deleted, purged, removed

**Pending upload（待上传）**:
A Base row exists without a Drive file and is waiting for the file.
_Avoid_: missing, orphan, queued

**Quota（配额）**:
The combined Drive bytes allowed for the source and push libraries, defaulting to 5 GB.
_Avoid_: limit, capacity, storage cap

**Cache（缓存）**:
Locally downloaded or derived copies that can be deleted and rebuilt, validated by md5.
_Avoid_: mirror, backup, local library

**Offline backup（离线备份）**:
A verified local copy made before removing a file from Drive; it may be the only remaining copy.
_Avoid_: export, archive, snapshot

**Reconcile（对账）**:
Comparing Drive files with Base registrations to find orphan files, broken links, duplicates and state mismatches.
_Avoid_: sync, audit, verify

**Decision（决定）**:
The researcher's accepted or rejected outcome for one update proposal, recorded per proposal.
_Avoid_: approval, answer, vote

**Part（分片）**:
An ordered fragment of a source file that exceeds the Drive per-file limit.
_Avoid_: chunk, segment, piece
