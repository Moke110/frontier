# 存量核对与云端恢复验收（#39）

- 日期：2026-10-27
- 结论：**未通过（阻塞）**。核对工具与「可丢弃目录」演练已做完并有真实输出；**真实 Base 的 174 篇核对、云端恢复演练、三个连续自然日的零差异**都还没有证据，因此不标记通过。

历史上下文：[#22 飞书唯一存储](https://github.com/Moke110/frontier/issues/22)、[#28 迁移与切换](https://github.com/Moke110/frontier/issues/28)（均已关闭，剩余验收由本 ticket 承接）。

## 已建成的能力

| 能力 | 位置 | 说明 |
|---|---|---|
| 基线核对 | `python -m hostrun.cli audit run --baseline <manifest>` | 读 `fixtures/pdf-manifest.jsonl` 这类清单，逐条比对「原文」表；`--record` 落盘当天结果 |
| 零差异连续天数 | `python -m hostrun.cli audit streak` | 只有连续自然日都 `zero_diff` 才 `satisfied: true`（要求 ≥3 天） |
| 分片顺序 | 同上 | 按 `part01, part02…` **顺序**比对，顺序颠倒即报 `part_problems`（旧实现只比集合，已修正） |
| 旧测试推送 | 同上 | 单独统计 `legacy_test_refs`（`push_id` 含 `test`），只报告，不自动删除 |
| 配额差异 | 同上 | `registered_bytes` vs Drive 实际字节，差异 <1% 才算通过 |
| 只读、不删 | 同上 | 全程不写 Base；不把「上传失败」改标「无原件」，`pending_upload` 与 `no_source` 分开计数 |

测试：`tests/test_hostrun_runtime.py` 覆盖缺失基线项、完全对齐、分片乱序 + 悬空引用、连续三天、缺基线文件报错。

## 真机实跑输出（空库 + 真实 174 篇基线）

在**可丢弃目录** `/tmp/kl-rehearsal` 初始化离线库后，用仓库里的 174 篇清单核对：

```bash
python -m library.cli --home /tmp/kl-rehearsal --offline setup
python -m hostrun.cli --home /tmp/kl-rehearsal --offline audit run --baseline fixtures/pdf-manifest.jsonl
python -m hostrun.cli --home /tmp/kl-rehearsal audit streak
```

```json
{
  "ok": false,
  "zero_diff": false,
  "counts": {
    "baseline_expected": 174,
    "registered_sources": 0,
    "registered_pushes": 0,
    "missing": 174,
    "unexpected": 0,
    "no_source": 0,
    "pending_upload": 0,
    "part_problems": 0,
    "dangling_push_refs": 0,
    "legacy_test_refs": 0
  },
  "missing": ["pdf_2012_data_ccle", "pdf_2012_data_gdsc", "…"]
}
```

```json
{ "days": 0, "dates": [], "satisfied": false }
```

两点值得记录：

1. 空库对上 174 篇基线时，工具报 **174 缺失、`zero_diff: false`**，没有把「没数据」当成「零差异」——这是验收能成立的前提。
2. `streak` 在没有任何记录时返回 `0`，不会默认满足三天。

同一目录下 `scripts/demo.py` 也跑通了「检索 → 排序 → 写作任务 → 入库 → 发评分卡（dry-run）→ 评分 → 统一队列 → 逐题同意 → 命题多一条证据」，证明本地重建链路可用（该 demo 自身此前已因七段推送格式而失败，本次一并修复）。

## 逐条对照

| 要求 | 结果 | 证据 / 原因 |
|---|---|---|
| 以 174/174 为历史基线核对当前清单，不重复全量上传 | **工具通过，真实库未做** | 工具能读 174 篇清单并逐条比对（上方实测）；本机**没有可用的 `lark-cli` 登录**，无法读取真实 Base |
| 检查报道关联、分片、悬空测试推送引用 | **工具通过，真实库未做** | `dangling_push_refs` / `part_problems` / `legacy_test_refs` 三项独立计数，有测试覆盖 |
| 15 条旧测试推送不回填正式库 | **设计通过，数据未核** | 工具只统计不删除；是否已回填要看真实库结果 |
| 无未解释的待上传/缺失；不把失败改标无原件 | **设计通过，真实库未做** | `pending_upload` 与 `no_source` 分开统计，报告给出 `next`：只补实际缺口 |
| 三个连续自然日零差异 | **未取得** | `streak = 0`；本机无法产生第一天 |
| 独立可丢弃目录证明云端权威读、按需下载、本地重建、一篇推送 | **部分** | 本地重建与一篇推送已在临时目录跑通；「云端权威读 + 按需下载」需要真实租户，未做。原始工作目录与唯一备份全程未触碰 |
| 配额登记与实际占用差异 <1% | **工具通过，真实库未做** | 计算与阈值已实现（`QUOTA_TOLERANCE = 0.01`），真实字节数需真实 Drive |
| 报告区分已验证 / 缺口 / 阻塞 | **通过** | 报告含 `verified` / `gaps` / `blocked` 三段；无基线时明确写「无法核对 174 篇历史回填」 |

## 为什么不能算通过

`audit` 的价值在于「对着真实云端说真话」。在没有真实 Base、没有真实 Drive、也没有连续三天运行的情况下，任何「已通过」都要靠编造。本记录选择留下空库实测的原始输出，而不是把工具就绪当成验收完成。

## 解除阻塞需要什么

1. 装好 `lark-cli` 并完成 user 登录，`hostrun kb attach` 指向真实 Base。
2. `hostrun audit run --baseline fixtures/pdf-manifest.jsonl --record`：拿到第一天的真实差异清单，只补实际缺口。
3. 连续三个自然日各跑一次（`--record`），`hostrun audit streak` 返回 `satisfied: true`。
4. 在一个**独立可丢弃目录**里做一次恢复演练：`feedback rebuild` + 下载一篇原文 + 跑通一篇推送，全程不删原工作目录。
5. 把上述原始输出补进本文件；在此之前，本 ticket 保持未通过。
