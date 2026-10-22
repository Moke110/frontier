# Bitable 镜像与双读验收（Phase 3a）

- 日期：2026-10-22
- 生产 Base：`https://ncnuh1ao6njt.feishu.cn/base/B39TbRl04asx1fs57eQczWmLnpf`
- 配置：`~/knowledge-loop/knowledge/base.json`
- 定时：`frontier-sync.timer`，每 10 分钟 `pull → sync → compare`

## 已验证

| 项 | 证据 |
|---|---|
| 五表与关联 | 知识卡片 10 / 命题 6 / 证据 5 / 报道 10 / 变更日志 6；命题↔卡片、命题↔证据、证据↔报道、命题↔日志 |
| 全量导入 | 实测 `compare` 返回 `ok:true`、`diffs:[]` |
| 幂等 sync | 连续两次 `sync`：creates/updates 全 0 |
| 手工文本回拉 | `tests/test_bitable.py::test_pull_applies_text_edits_and_flags_invalid_ones`：改 annotation/review 落本地并补 changelog；超 200 字 conclusion 不落本地，写「待修正」 |
| 漂移检测 | `compare` 检出 annotation 差异；`sync` 修复后恢复 `ok:true` |
| 定时器 | 12:04 首次运行 `pull` 建立基线、`sync` 0 变更、`compare` 通过 |

全部 110 个测试通过。

## 尚未切换（Phase 3b）

- 读仍走本地 `archive/`；Bitable 是镜像，不是当前读路径。
- 未实现 WAL；双读期靠幂等 sync 重放。
- 7 天无漂移后再切换读路径并下线本地写入。
