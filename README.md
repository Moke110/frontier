# frontier

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/Moke110/frontier?include_prereleases&label=release)](https://github.com/Moke110/frontier/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-0078D6)](#what-you-need)
[![Runtime](https://img.shields.io/badge/python-3.13%20bundled-3776AB)](#what-you-need)

**English** | [简体中文](README.zh-CN.md)

**A research knowledge base that reads papers for you and reports back in Feishu.**

frontier turns the themes you care about into knowledge cards, retrieves the papers that
match them, has an agent rank and write a daily report, and delivers it to your Feishu.
You rate the report and confirm knowledge updates; every accepted update makes the cards,
claims and evidence sharper. The result is a research memory that grows from your own
judgement instead of a firehose of links.

## What it does

- **Retrieval grounded in your cards** — each report starts from the knowledge cards you
  confirmed, not from a generic feed, so the searched queries stay on your topic.
- **Agent-written reports** — one bounded run ranks candidates, writes one report and
  renders it with figures, then delivers it as a Feishu file message.
- **Human confirmation, not silent edits** — the agent only proposes knowledge updates.
  You score the report, accept or reject each update, and only accepted proposals are
  written back to the authoritative Feishu Base.
- **Nothing resident on your machine** — frontier registers no Windows service, no
  scheduled task, no registry key and no PATH entry. A single foreground console window
  is the service; close it and everything stops.

## How it works

```text
 your themes ──▶  Feishu Base: cards · claims · evidence
                        │
                        │  retrieve (arXiv, Europe PMC, …)
                        ▼
                  candidate papers
                        │
                        │  agent ranks, writes, renders
                        ▼
                  one report ──▶  Feishu file message
                        │                    │
                        │                    ▼
                        │             you rate and confirm
                        │                    │
                        ▼                    ▼
                 accepted updates ◀──────────┘
                        │
                        └──▶  Feishu Base grows
```

Knowledge itself lives in Feishu: the Base tables hold the cards, claims and evidence, and
Drive folders hold the originals and delivered reports. The copy on your machine is
rebuildable. The archive directory keeps only `originals/` and `pushes/`; configuration,
queues, logs, leases and install records live under the code directory, in
`<code>\.frontier\`.

## Installation

### What you need

- Windows 10/11 on x64.
- A host agent that can run local commands, load skills and start a foreground console
  window. DeepSeek Harness on Windows is the reference host, which is why the install path
  below is agent-driven.
- A Feishu account with admin rights, so frontier can create a Base, two Drive folders and
  a bot app, and can send you direct messages.
- A workspace folder. That is all: the user path needs no git, uv, pip or system Python,
  because the distribution package carries its own runtime.

The install creates this layout in your workspace:

```text
<workspace>\
  frontier\          code directory: package files, bundled runtime, runtime state
  frontier-archive\  archive directory: originals\ and pushes\ only
```

### Step 1 — copy this prompt to your host agent

```text
Install frontier on this machine. Follow these rules exactly:

1. Resolve the release. Read releases/index.json from https://github.com/Moke110/frontier
   (or the v* GitHub Release) and take the newest entry: version (without the leading v),
   channel, artifact name frontier-<version>-<channel>.zip and artifact sha256. The index
   currently lists only the prerelease channel. Take packages from GitHub Releases and the
   release index only, never from a package marketplace.
2. Download the artifact and its digest JSON into a temporary folder inside the workspace.
   Do not extract anything into the code directory yet.
3. Verify before extracting. Compare Get-FileHash -Algorithm SHA256 "<zip>" with the
   artifact.sha256 in the matching .digest.json. On a mismatch, stop before writing to the
   code directory or the install lock.
4. Install the package. Expand-Archive the zip into a temporary bootstrap folder; the zip
   entries are at the archive root, so you get <temp>\bin\frontier.cmd. Then run:
     <temp>\bin\frontier.cmd --code "<code>" --archive "<archive>" install package --from "<zip>" --digest "<digest.json>"
   The code directory must be empty, absent, or a previous package install. The install lock
   is written to <code>\.frontier\dist.lock.json; delete the bootstrap folder afterwards.
5. Write the console launcher:
     <code>\bin\frontier.cmd --code "<code>" --archive "<archive>" console install --dsh "<absolute path to dsh>"
6. Register the skill pointer so this host can find frontier again:
     <code>\bin\frontier.cmd --code "<code>" --archive "<archive>" install skill --root "<code>" --target "<host skills dir>"
7. Start the console and hand me the window; I will run /frontier-init inside it. Check
   write permissions first. If writing Feishu credentials or an archive directory outside
   the workspace is denied, ask me to relaunch <code>\bin\frontier-console.cmd with full
   permissions and keep the initialization progress already made.
8. After I finish /frontier-init, report honestly: what really ran, what is blocked and what
   was not measured. A successful command or a created schedule is not proof that a report
   was delivered.
```

The whole user path runs on the bundled runtime: the package supplies the code directory,
the runtime and the install lock, so git, uv, pip and the system Python are never involved.

### Step 2 — the parts only you can do

Inside the console window, `/frontier-init` walks you through the decisions frontier cannot
make for you:

1. confirm the archive directory;
2. confirm the agent that executes frontier's runs;
3. log in to the Feishu CLI and authorize the admin scopes;
4. click the button in the test message frontier sends you;
5. reply with the display names of the Feishu facilities it creates;
6. choose the daily push time (default 08:00);
7. decide whether to initialize the knowledge base from a folder of PDFs now.

Nothing is pushed to Feishu until these steps are done. If you interrupt, ask your host
agent to continue the installation — progress is kept, and you do not have to recreate the
knowledge base from scratch.

### Maintenance

| Goal | Command |
|---|---|
| Check the install lock against the files on disk | `<code>\bin\frontier.cmd --code "<code>" --archive "<archive>" install verify` |
| Show the install report | `<code>\bin\frontier.cmd --code "<code>" --archive "<archive>" install report` |
| Upgrade | download the newer zip and its `.digest.json`, verify the sha256, then repeat `install package --from "<zip>" --digest "<digest.json>"` |
| Roll back to the retained previous version | `<code>\bin\frontier.cmd --code "<code>" --archive "<archive>" install rollback`, or `install rollback --to "<version>"` |

Upgrading replaces package files only: the archive directory and the `<code>\.frontier\`
runtime state stay untouched, and the previous version is retained for a rollback. Rolling
back does not re-download or rebuild anything — it switches back to the retained tree and
restores the install lock. After any upgrade or rollback, re-run the skill-pointer step so
the recorded version follows the package.

## Using frontier

Three ways to drive it, all equivalent:

- **Console** (always the primary surface): the foreground window shows scheduled runs,
  Feishu messages and card clicks, agent-run summaries and errors; the input line at the
  bottom takes the commands below.
- **Feishu direct message** while the console is open: send one of the six phrases below.
- **Host agent**: write a control-file request, which the console picks up within a second.

| Console command | What it does |
|---|---|
| `/frontier-init` | first-run setup; also resumes an interrupted setup |
| `/frontier-start` | start the service again after a pause |
| `/frontier-stop` | pause pushes and Feishu replies; the console stays open |
| `/frontier-status` | current state, last run, last failure |
| `/frontier-push` | request one more report now |
| `/frontier-update-kb` | incremental knowledge-base initialization with per-item review |
| `/frontier-logs` | recent console and agent-run logs |
| `/frontier-help` | command help |
| `/exit` | stop the console (and with it the whole service) |

| Feishu direct message | Meaning |
|---|---|
| `推一篇` | push one report now |
| `处理反馈` | process submitted feedback |
| `状态` | current status |
| `暂停` | pause the service |
| `恢复` | resume the service |
| `测试飞书消息` | send a test message to yourself |

Only your own direct messages are accepted; groups and other people are ignored. While the
service is paused, only `恢复` gets through and every other message is answered with a pause
notice. Two commands need arguments — changing the push time and changing the archive
directory — so frontier first runs a read-only intent check, and only a confirmation card
you click executes the change.

Each report arrives with a feedback entry point. Rate it first, then confirm each knowledge
update question one by one; an edited answer only takes effect after you explicitly submit
it. Unanswered questions block the next push, but they do not block storage maintenance.

The console keeps time itself: one push per day at your chosen time (default 08:00), with a
single catch-up run if a day was missed. Feedback is polled every five minutes, and every
ten minutes frontier pulls text edits and "under review" flags from the Base back into the
local copy of truth. It stays quiet when nothing changed.

### Initializing or extending the knowledge base

`/frontier-update-kb` pauses the formal service, asks you for a folder, has the agent read
everything in shards, and prints each candidate card and claim for review: press Enter to
accept, Backspace to discard, Tab to keep it marked `Under review`. Cards and claims carrying
that marker are not retrieved or written about until you clear "under review" in the Feishu
Base. Progress is incremental: a second run reads only files the archive has not registered
yet.

## Pausing, moving to another machine and recovering

`/frontier-stop` (or `暂停` in Feishu) pauses scheduled pushes and Feishu replies while the
console stays open; `/frontier-start` (or `恢复`) resumes. Closing the console window stops
the whole service and nothing responds in Feishu until you open it again. When you reopen it,
frontier restores the previous state: paused stays paused, running starts the service again.

To move to another machine or host, stop the console on the old machine first, then run the
installation on the new one and choose to connect to the existing Feishu knowledge base; the
agent takes over and restores from there. Only one executor may use a knowledge base at a
time.

The local copy is rebuildable, but an offline archive can be the only remaining copy of a
paper that was removed from Drive — keep it. Uninstalling the runtime configuration never
deletes Feishu data, and deleting cloud originals always needs a separate confirmation after
a verified offline backup.

## Troubleshooting

- **The console exits right after starting** — usually missing write permissions or a damaged
  runtime. Relaunch the launcher with full permissions, or ask your host agent for the
  conclusions of `install report` and `install verify`.
- **Feishu commands do nothing** — the console must be open. Closing the window stops all
  Feishu responses; queued feedback is processed after the next start.
- **The queue does not move** — check that answers were explicitly submitted and that there
  is no older unanswered question blocking the next push.
- **A push failed** — `/frontier-status` shows the last failure and the number of attempts.
  frontier does not retry automatically: fix the cause, then request a new push.
- **"Running" does not mean delivered** — a scheduled run that produced no delivery evidence
  is reported as such. Trust the delivery result, not the timer.

## Development (source install)

The source install is only for developing frontier itself. Users take the package path
above; the two paths never overwrite each other. It needs git, uv and Python 3.13:

```powershell
git clone https://github.com/Moke110/frontier.git "<workspace>\frontier"
cd "<workspace>\frontier"
python -m hostrun.cli install workspace --root "<workspace>" --repo-url https://github.com/Moke110/frontier.git
python -m hostrun.cli --code "<code>" install toolchain --root "<workspace>"
python -m hostrun.cli --code "<code>" --archive "<archive>" console install --dsh "<absolute path to dsh>"
python -m hostrun.cli install skill --root "<workspace>" --target "<host skills dir>"
```

The source install lock records `distribution: "source"` and the git commit instead of a
package version and artifact digest; `install verify` reports `source_install` for it. The
private environment lives in `<code>/.frontier/.venv`. Development checks, the branch model
and the tag/release conventions are in [AGENTS.md](AGENTS.md); module contracts are in
[contracts/](contracts/README.md).

## Docs and license

- Runtime skill for the host agent: [skills/frontier-run/SKILL.md](skills/frontier-run/SKILL.md)
- Development guide: [AGENTS.md](AGENTS.md) · Glossary: [GLOSSARY.md](GLOSSARY.md)
- Module contracts: [contracts/](contracts/README.md)
- License: [MIT](LICENSE)
