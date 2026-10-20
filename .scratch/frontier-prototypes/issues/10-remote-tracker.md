# 10 远程仓库与 GitHub issue tracker

Type: task ｜ Status: resolved ｜ Blocked by: —

## Question

把项目远程仓库设为 `https://github.com/Moke110/frontier`，并把 mattpocock/setup 生成的本地 markdown issue tracker（`docs/agents/issue-tracker.md`）改为使用远程 GitHub Issues：

- map / ticket / 阻塞 / frontier 查询都在 GitHub 上表达；
- 保留现有 `.scratch` 作为历史，不再新增；
- AGENTS.md 与 labels 文档同步。

## Answer

- 已添加 `origin` → `https://github.com/Moke110/frontier.git`，并 `git fetch` 到 `origin/main`。
- 重写 `docs/agents/issue-tracker.md`：GitHub Issues 为唯一 tracker；map = `wayfinder:map` issue；ticket = sub-issue + `wayfinder:<type>` label；claim = assignee；blocking = native blocked-by（gh ≥ 2.94 用 `--add-blocked-by`，旧版用 REST `/issues/<n>/dependencies/blocked_by`）；frontier 查询给了可直接执行的 `gh api` 片段；spec = `spec` label issue。
- 更新 `AGENTS.md` 的 Issue tracker 一节；`.scratch/` 标记为 legacy/read-only。
- 在远程仓库创建了 triage / spec / wayfinder 标签。
