# 验收记录与待补证据

本文件只记录验收证据与缺口，不替代 [GitHub 任务](https://github.com/Moke110/frontier/issues/29)。以下为 2026-10-27 已记录证据的归并；未重新执行飞书或宿主实测。代码通过离线测试不等于产品通过真实验收。

## 宿主与恢复

| 范围 | 已有证据 | 尚缺证据 | 任务 |
|---|---|---|---|
| ChatGPT 本地宿主 | 安装续接、知识库和队列机制有离线测试 | 具体版本与权限、真实新装/恢复、本地定时触发、离线反馈续接 | [ChatGPT 接入与本地定时验收](https://github.com/Moke110/frontier/issues/37) |
| WorkBuddy 本地宿主 | 历史开发会话验证过项目访问、技能加载、本地命令 | 内置调度实际触发、无人值守权限、真实飞书闭环 | [WorkBuddy 接入与本地定时验收](https://github.com/Moke110/frontier/issues/38) |
| 云端存量恢复 | 基线核对、分片顺序、配额计算与故障测试；空库会正确报告缺失 | 真实 174 篇核对、云端恢复演练、配额实测与连续三天零差异 | [存量核对与云端恢复验收](https://github.com/Moke110/frontier/issues/39) |
| 安装说明 | 现行用户入口与运行时技能已统一 | 在目标宿主按最终说明完成新装、恢复并留证 | [统一安装说明并退役旧部署入口](https://github.com/Moke110/frontier/issues/40) |

核对时发现 ChatGPT 任务已被标为关闭，但其最后一条验收评论仍写“未实测”，未附新的通过证据；因此本表保留证据缺口，不以 issue 状态推断验收通过。后续执行者须先核对关闭原因与最新证据；本轮不更改 tracker 状态。

2026-10-27 的原始安装检查只确认 `dependencies: ok`；当时 `lark_cli/identity: blocked`、`host: untested`，其余步骤 pending。它描述当时环境，不能当作当前安装检查；后续必须重新探测。原 WorkBuddy 开发解释器已失效，也不能沿用其 venv 作为有效安装证据。

空库恢复演练的原始结果为 `baseline_expected: 174`、`registered_sources: 0`、`missing: 174`、`zero_diff: false`、`streak: 0`。这证明核对工具没有把空库误报为完整恢复，不证明真实数据已经恢复。

## 下一次真实验收

1. 由宿主按 [用户安装流程](../../README.md) 准备私有依赖并引导用户完成飞书授权，连接实际 Base。仅报告身份状态，不输出凭据。
2. 分别在目标宿主验证版本、工作目录、技能、权限，以及至少一次真实到点触发；保存任务配置、时间、运行输出和反馈续接记录。一款宿主的结果不能替代另一款。
3. 使用 `fixtures/pdf-manifest.jsonl` 复核历史 174 篇原文，只补实际缺口；检查分片、原文关联、测试推送引用和配额差异（小于 1%）。不得将上传失败改成无原件来通过验收。
4. 在真实库上执行 `audit run --baseline <manifest> --record`，取得连续三个实际执行自然日的零差异记录，再用 `audit streak` 验证；不模拟日期或伪造补跑。
5. 在独立可丢弃目录从云端恢复知识、已发问题与决定，按需下载原文并完成一篇推送。不删除原工作目录、唯一离线备份或用户云端资料。
6. 将结果和原始证据追加到对应 GitHub issue；只在满足验收条件后关闭任务。稳定、可复现的结论可精炼到本表，原始长日志留在 issue 或相应工件。

## 历史证据

旧环境的成功记录只证明当时的 WSL/systemd 或迁移阶段，不证明现在的宿主方案通过。完整历史固定在清理前提交，避免工作区重复维护长日志：

- [2026-10-21 首轮端到端](https://github.com/Moke110/frontier/blob/978cbfc/docs/acceptance/2026-10-21-e2e.md)：曾有自动续推与重复论文问题。
- [2026-10-22 端到端复验](https://github.com/Moke110/frontier/blob/978cbfc/docs/acceptance/2026-10-22-e2e-followup.md)：旧服务模式下两项问题修复通过。
- [命题 v3 与 HTML](https://github.com/Moke110/frontier/blob/978cbfc/docs/acceptance/2026-10-22-v3-phase2.md)、[Bitable 镜像](https://github.com/Moke110/frontier/blob/978cbfc/docs/acceptance/2026-10-22-bitable-phase3a.md)：当时的功能与切换边界。
- [宿主原始检查](https://github.com/Moke110/frontier/blob/978cbfc/docs/acceptance/2026-10-27-host-matrix.md)、[云端恢复原始检查](https://github.com/Moke110/frontier/blob/978cbfc/docs/acceptance/2026-10-27-cloud-recovery.md)。
- [v1 到 v2 迁移记录](https://github.com/Moke110/frontier/blob/978cbfc/docs/migrations/2026-10-20-v1-to-v2.md)。旧 Base 回填结果另见 [旧迁移任务](https://github.com/Moke110/frontier/issues/28) 的历史评论，当前工作仍需复核。
