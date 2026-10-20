# 13 · 前端载体调研：可免费部署 / 远程访问 / HTML+PDF 渲染 / 非文本交互

> 目标：替掉"微信纯文本卡片"，找一个手机端能**富文本看卡片 + 同界面翻 PDF + 一键三档评分**，且点击能回流到 WSL 上 Hermes cron 的前端载体。
> 结论日期 2026-10-19。所有额度数字均来自官方定价/文档页并附 URL；查不到的进 §9「未核实清单」，不猜。
> 实测环境：WSL，中国大陆家宽（单点单时刻），2026-10-19 15:00 CST。**单网络单次测量，不代表全国**，但足以定性判断"通/不通"。

---

## 1. 结论（先看这个）

| 排名 | 方案 | 一句话 | 定位 |
|---|---|---|---|
| **1** | **飞书自建应用：消息卡片 + 长连接回调 + 文件消息送 PDF** | 唯一同时做到「国内 35ms 直连 + 锁屏真推送 + 原生按钮 + 不需要公网 IP/域名/备案/信用卡」的组合 | **国内直连最优（主推）** |
| **2** | **Cloudflare Pages(自定义域名) + Workers + D1 + ntfy/Bark** | 完全掌控 HTML/PDF，额度白送，但国内首屏 3–8s，且 `*.pages.dev` 被 DNS 污染，必须自带域名 | **可翻墙时最优；国内"能用但慢"** |
| **3** | **自建 FastAPI(WSL) + Cloudflare Tunnel / Tailscale Funnel** | 想怎么渲染就怎么渲染，代价是 WSL 必须常开、隧道单点、国内延迟同样受 CF 边缘拖累 | 掌控力最强、运维最重 |

**一句话取舍**：要"手机一点就着"，选飞书；要"页面长什么样我说了算"，选 Cloudflare；两者可以并存 —— 飞书负责通知与一键评分，Cloudflare 页面负责长文与 PDF 精读（方案 A+，见 §6）。

---

## 2. 实测：国内可达性硬数据（决定排名的关键）

| 目标 | 结果 | 判定 |
|---|---|---|
| `baidu.com`（基线） | 200 / 0.025s | 参照 |
| `open.feishu.cn` | 200 / **0.035s** / TLS 0.010s | 国内直连，极快 |
| `gitee.com` | 200 / 0.34s | 通 |
| `pages.github.com` / `github.io` | 200 / **0.34s** / 0.79s | 本次通（历史有波动） |
| `ntfy.sh` | 200 / 2.1s | 通，偏慢 |
| `supabase.com` / `app.supabase.com` | 200 / 2.4s / 0.54s | 通 |
| `notion.so` | 200 / 1.5–2.8s，解析到 `208.103.161.17` | **可疑**：非 Notion 官方 Cloudflare 段，疑似第三方中转；历史有封锁记录 |
| `www.cloudflare.com` | 200 / 8.6s（TLS 0.9s） | 通，但慢 |
| `pages.dev`（系统 DNS） | **解析到 `127.0.0.1`** | **DNS 污染**（经典投毒值） |
| `pages.dev`（`--resolve` 真实 CF IP 104.18.20.135 + SNI） | 200 / **TLS 3.54s / 总 5.81s** | 可达但极慢；说明是"慢"不是"墙" |
| `workers.dev` | **15s 超时**（连真实 IP 也超时） | **被阻断**（TCP/SNI 层） |
| `api.telegram.org` | **15s 超时** | **被墙** |
| `supabase.co`（AliDNS 返回 `76.76.21.21`） | **0.08s 立即 RST** | 该 A 记录在国内被即时重置 |
| `vercel.app` / `nuxt.vercel.app` | **15s 超时**；`vercel.com` 2.8s 通 | 预览域名被墙，控制台可通 |
| `netlify.app` | 1.1s 失败；`www.netlify.com` 0.62s 通 | 同上 |
| `trycloudflare.com` | 200 / 4.2s | 通，慢（临时隧道域名） |
| `api.day.app`（Bark） / `api2.pushdeer.com` | 1.3s / 0.6s | 通 |
| `gitee.io` | **12s 超时**；`<user>.gitee.io` → **404** | Gitee Pages 事实上已无服务 |

> 方法：`curl -sL -w "%{http_code} %{remote_ip} %{time_total}"`；系统 DNS 与 AliDNS(DoH) 交叉比对，区分"解析被污染"与"IP/SNI 被阻断"。

---

## 3. 逐候选 11 维对照

维度：① 免费额度 ② 部署成本 ③ 国内可达性 ④ HTML 渲染 ⑤ PDF 渲染 ⑥ 非文本交互 ⑦ 入站通路 ⑧ 通知 ⑨ 运维 ⑩ 风险 ⑪ 结论。

### 3.1 Cloudflare Pages + Workers + D1/R2 + Tunnel

| 维度 | 内容 |
|---|---|
| ① 免费额度 | Pages：500 次构建/月（单次 20 分钟超时）、20,000 文件/站、单文件 25 MiB、100 自定义域/项目、100 项目；Workers：**100,000 请求/天**、10 ms CPU/次、128 MB、50 子请求、5 个 Cron Trigger；D1：10 库、单库 500 MB、账号共 5 GB、5M 行读/天、100k 行写/天；R2：10 GB-month、100 万 Class A、1000 万 Class B、**出网免费**。超限：Workers $5/月起步含 1000 万请求，之后 $0.30/百万；D1 $0.75/GB-month；R2 $0.015/GB-month。<br>来源：<https://developers.cloudflare.com/pages/platform/limits/> · <https://developers.cloudflare.com/workers/platform/pricing/> · <https://developers.cloudflare.com/workers/platform/limits/> · <https://developers.cloudflare.com/d1/platform/limits/> · <https://developers.cloudflare.com/r2/pricing/> · <https://www.cloudflare.com/plans/> |
| ② 部署成本 | $0。免费 `*.pages.dev` 子域 + 自动 TLS；自定义域名需自购（¥50–100/年）。**不需要信用卡、不需要实名、不需要 ICP 备案**（服务器在境外）。 |
| ③ 国内可达性 | `pages.dev` **DNS 被污染到 127.0.0.1**，默认域名在国内基本打不开；换真实 IP 可 200，但 TLS 3.5s / 首屏 5.8s。**必须自带域名**，即便如此仍绕行境外 PoP，延迟 2–8s。`workers.dev` 直接被阻断，API 不能挂在 `*.workers.dev` 上。 |
| ④ HTML 渲染 | 满分：任意 HTML/CSS/JS，KaTeX/MathJax、代码高亮、图片、暗色模式全自由。 |
| ⑤ PDF 渲染 | 自建：`pdf.js` 或 `<iframe src="...pdf">`。注意 arXiv 的 PDF 无 CORS 头且带 `X-Frame-Options`，需 Worker 代理转发（Worker 请求体上限 100 MB，足够单篇论文）。大文件放 R2（单文件 >25 MiB 时 Pages 放不下）。 |
| ⑥ 非文本交互 | 满分：原生 `<button>`，`fetch('/api/score', {method:'POST'})` → Worker。无第三方控件约束。 |
| ⑦ 入站通路 | 按钮 → Worker → 写 D1/KV → WSL cron 每 5 分钟 `GET /api/events?since=<cursor>` 拉增量 → 写本地 state。**不走 webhook 打内网**。 |
| ⑧ 通知 | 无自带推送。需配 ntfy.sh / Bark / PushDeer（见 3.7）或邮件。 |
| ⑨ 运维 | 低：`wrangler deploy` 一条命令；无常驻进程；D1 有 7 天 Time Travel。 |
| ⑩ 风险 | ① 国内可达性随运营商/时段波动（无 SLA，免费版无中国节点，China Network 仅 Enterprise，见 <https://developers.cloudflare.com/china-network/>）；② `*.pages.dev` 已被污染，换域名是硬成本；③ 免费额度政策历史上多次调整（Workers 免费额度、Pages 与 Workers 合并趋势）。 |
| ⑪ 结论 | **可翻墙时最优；国内"能用但慢"**，前提：自有域名 + 接受 3–8s 首屏 + 通知另配。 |

### 3.2 Supabase 免费版 + 静态前端（Pages/Vercel/Netlify）

| 维度 | 内容 |
|---|---|
| ① 免费额度 | 无限 API 请求、**50,000 MAU**、**500 MB 数据库**、共享 CPU/500 MB RAM、**5 GB 出网 + 5 GB 缓存出网**、**1 GB 文件存储**、**2 个活跃项目**、**1 周无活动即暂停**。超限：Pro $25/月（含 8 GB 盘、250 GB 出网、100 GB 存储），出网 $0.09/GB、存储 $0.0213/GB。<br>来源：<https://supabase.com/pricing> |
| ② 部署成本 | $0，无需信用卡；前端另找托管（Pages/Vercel/Netlify）。 |
| ③ 国内可达性 | `supabase.com` / `app.supabase.com` 实测通（2.4s / 0.5s）；但**项目 API 域 `<ref>.supabase.co` 未验证**（`supabase.co` 无泛解析，假 ref 查不到是正常现象，不能据此判定被墙）；`supabase.co` 顶点在 AliDNS 下返回 Vercel IP 且 0.08s RST，**该域名的国内解析质量差**。 |
| ④ HTML 渲染 | 满分（前端自选）。 |
| ⑤ PDF 渲染 | 前端 pdf.js；PDF 可放 Supabase Storage（免费 1 GB，单文件上限未核实）或直连 arXiv。 |
| ⑥ 非文本交互 | 满分（自写 UI），数据层用 supabase-js 直连。 |
| ⑦ 入站通路 | 按钮 → supabase-js `insert` → WSL cron `select ... where id > cursor`。**注意**：anon key 暴露在前端，必须开 RLS 且只允许 insert 到评分表，绝不能给 select/update 权限。 |
| ⑧ 通知 | 无推送能力，需另配 ntfy/Bark。 |
| ⑨ 运维 | 中低；**免费项目 1 周无请求会暂停**，靠 cron 每日心跳维持（正好每日推送可当心跳）。 |
| ⑩ 风险 | 免费项目暂停策略、2 项目上限、1 GB 存储很快被 PDF 吃满；国内对 `*.supabase.co` 的可达性缺长期数据。 |
| ⑪ 结论 | 作为"云 DB + 静态前端"很顺手，但**它只是数据库，不解决推送与 PDF 托管**，且多一层国内可达性未知。 |

### 3.3 GitHub Pages / Gitee Pages + GitHub Issue 作入站

| 维度 | 内容 |
|---|---|
| ① 免费额度 | GitHub Pages：站点 ≤ **1 GB**、仓库建议 ≤ 1 GB、带宽软限 **100 GB/月**、构建 **10 次/小时**（自定义 Actions 不受此限）、部署 10 分钟超时；**免费账号仅支持公开仓库**。GitHub API：认证 **5,000 请求/小时**，匿名 60/小时。<br>来源：<https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits> · <https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api><br>Gitee Pages：**无官方产品页**（`gitee.com/pages` 只是同名用户主页）、`<user>.gitee.io` 返回 **404**、帮助文章 4136 已 302 到帮助中心首页 → **判定服务已下线**；下线公告未找到（见 §9）。 |
| ② 部署成本 | GitHub $0，无需信用卡/备案。Gitee 需实名认证（注册强制），Pages 已不可用。 |
| ③ 国内可达性 | 本次实测 `github.io` **0.34s，很快**；但 GitHub 系域名在国内历史波动大（间歇性污染/限速），不可当 SLA。 |
| ④ HTML 渲染 | 满分（纯静态）。 |
| ⑤ PDF 渲染 | pdf.js 自建；PDF 不能进仓库（1 GB 限制），放外部或 Release 附件。 |
| ⑥ 非文本交互 | 有按钮，但**没有后端**：只能 ① 跳转预填 `issues/new?title=...&body=...`（两步，不是一键）或 ② 前端持细粒度 token 调 API（token 泄露风险，需极窄权限 + 只对单一 repo 的 issues:write）。 |
| ⑦ 入站通路 | cron `gh issue list --label score --state open` 轮询 → 解析标题里的 `paper_id|score` → 写本地 → `gh issue close`。天然无公网，但**延迟取决于 cron 周期**。 |
| ⑧ 通知 | 无推送，另配 ntfy/Bark；GitHub 自身只发邮件。 |
| ⑨ 运维 | 低；但公开仓库 = 你的评分与阅读记录全公开（隐私硬伤）。 |
| ⑩ 风险 | 免费版 Pages 强制公开仓库；GitHub 在国内的可达性不稳；issue 作消息队列语义弱（无幂等、无顺序）。 |
| ⑪ 结论 | **只适合当"零成本兜底 + 入站旁路"**，不适合当主前端。 |

### 3.4 Telegram Bot（inline keyboard / Mini App / Web App）

| 维度 | 内容 |
|---|---|
| ① 免费额度 | Bot API 完全免费，无配额计费。限流（30 条/秒全局、单聊 1 条/秒、群 20 条/分钟）为公开文档常识，**本机 `core.telegram.org` 不可达，未复核**。 |
| ② 部署成本 | $0；Bot 用 @BotFather 建，无需信用卡；Mini App 需一个公网 HTTPS 页面（又是托管问题）。 |
| ③ 国内可达性 | **`api.telegram.org` 15s 超时（被墙）**，必须全程代理。手机端不翻墙收不到推送。 |
| ④ HTML 渲染 | Bot 消息只支持 Markdown/HTML 子集；**Mini App（Web App）才是完整 HTML**，需另托管页面。 |
| ⑤ PDF 渲染 | 发 document 消息，Telegram 内置 PDF 查看器（体验不错）；Mini App 内需 pdf.js。 |
| ⑥ 非文本交互 | **inline keyboard 是最成熟的原生按钮体系**：`callback_data` 直接回传，无需公网（长轮询 `getUpdates` 即可）。Mini App 还能 `sendData` 回传。 |
| ⑦ 入站通路 | `getUpdates` 长轮询（出站 HTTPS，无需公网 IP）→ 本地写 state。**拓扑上比飞书长连接更简单**。 |
| ⑧ 通知 | 系统级锁屏推送，质量最好。 |
| ⑨ 运维 | 低（单进程长轮询）。 |
| ⑩ 风险 | **国内不可直连**（硬伤）；账号需 +86 可注册但 API 被墙；翻墙链路的稳定性/合规风险。 |
| ⑪ 结论 | **技术上最优雅，地理上不可用**。降级为「可翻墙时备选」；若你长期挂着梯子，它就是第一。 |

### 3.5 飞书（Lark）开放平台：消息卡片 + 云文档 + 多维表格

| 维度 | 内容 |
|---|---|
| ① 免费额度 | 免费版 **¥0、支持 100 用户**，含 IM / 云文档 / 视频会议 / 多维表格 / 免费邮箱（<https://www.feishu.cn/service>）。API：发消息 **1000 次/分钟、50 次/秒**，**单用户 5 QPS**；卡片体 **≤30 KB**（文本消息 150 KB）；卡片 **≤200 组件/元素**；长连接 **每应用 ≤50 连接**，回调 **3 秒内必须响应**。<br>来源：<https://open.feishu.cn/document/server-docs/im-v1/message/create.md> · <https://open.feishu.cn/document/server-docs/event-subscription-guide/event-subscription-configure-/request-url-configuration-case.md> · <https://open.feishu.cn/document/event-subscription-guide/callback-subscription/step-1-choose-a-subscription-mode/configure-callback-request-address.md> |
| ② 部署成本 | $0。**不需要公网 IP、域名、证书、备案、信用卡**；注册一个飞书团队（手机号）即可建「企业自建应用」。是否需要企业认证/营业执照：**官方文档未明写，未核实**（实践上免费团队可创建自建应用）。 |
| ③ 国内可达性 | **`open.feishu.cn` 实测 0.035s**，与百度同量级，全国直连无争议。 |
| ④ HTML 渲染 | 卡片 JSON 2.0 支持 markdown 富文本（标题层级、粗斜体、链接、代码块、公式有限）、图片、分栏、表格、折叠、按钮、输入框、下拉、日期选择器。**不是任意 HTML**，但覆盖"卡片正文"需求；要完整 HTML 就放一个跳转链接（网页应用/云文档）。 |
| ⑤ PDF 渲染 | **两种原生路子**：① 发 `file` 消息，飞书 App 内置 PDF 阅读器直接翻页；② 上传云文档，卡片按钮跳转飞书文档预览。无需自己写 viewer。 |
| ⑥ 非文本交互 | **原生按钮/表单/下拉全套**，点击 → `card.action.trigger` 回调，回传 `action.value`（自定义 JSON）。 |
| ⑦ 入站通路 | **关键能力：长连接（WebSocket）接收回调，官方明说"无需提供公网 IP 或域名、无需使用内网穿透工具"**，SDK 内置加密鉴权，3 秒内处理完即可。→ 点击直接落进 WSL 进程，比轮询延迟更低；同时**保留本地队列文件 + cron 兜底**（长连接断线期间的事件由飞书重推，仍有丢失窗口，见 §5）。 |
| ⑧ 通知 | 系统级锁屏推送（iOS APNs + 国产厂商通道），飞书 App 自带，国内直连。 |
| ⑨ 运维 | 低：一个常驻 Python 进程（`lark-oapi` 长连接）+ 一个 cron。断线自动重连。 |
| ⑩ 风险 | ① 长连接**仅企业自建应用**（商店应用不行）；② 卡片 30 KB / 200 组件，长正文要分页或跳链接；③ 3 秒回调超时会重推，处理必须幂等；④ 免费版政策（用户数、存储）历史多次调整；⑤ 卡片 JSON 版本升级有 breaking change 先例（1.0→2.0）。 |
| ⑪ 结论 | **国内直连最优**。唯一同时满足"无公网 + 真推送 + 原生按钮 + 原生 PDF"的载体。 |

### 3.6 企业微信：应用消息 / 模板卡片

| 维度 | 内容 |
|---|---|
| ① 免费额度 | 应用消息免费；频率上限：**每应用 ≤ 账号上限数 × 200 人次/天**，**对同一成员 ≤30 次/分钟、1000 次/小时**，超出丢弃。模板卡片 `response_code` **72 小时内有效且只能调用一次**。<br>来源：<https://developer.work.weixin.qq.com/document/path/90236> |
| ② 部署成本 | $0 起，但**注册需企业主体信息**；「企业微信认证」需企业资质与费用（金额/年审**未核实**，官方页面为 SPA 未抓到正文）。自建应用还需配置**可信 IP** 与**公网回调 URL**。 |
| ③ 国内可达性 | 腾讯自有网络，国内直连（未单独实测，量级应与 feishu 同）。 |
| ④ HTML 渲染 | 模板卡片支持 markdown 子集、图片、左右图文、引用区、按钮、下拉（`button_selection`）；`textcard` 支持有限 HTML 片段（`<div class="gray|normal|highlight">`）。 |
| ⑤ PDF 渲染 | 发 `file` 消息，企微内置预览；无网页级 PDF 控件。 |
| ⑥ 非文本交互 | 按钮交互型/投票型/多选型卡片支持回调，但**必须自建公网回调接口**（AES 加解密 + 验签）；**没有飞书那种长连接**（仅"智能机器人"有长连接模式，普通自建应用没有）。 |
| ⑦ 入站通路 | 点击 → 企微服务器 POST 你的公网 URL → 你必须有个公网入口（CF Tunnel/备案域名）→ 再写库 → WSL 轮询。**比飞书多一跳公网暴露面**。 |
| ⑧ 通知 | 系统级推送，国内直连。 |
| ⑨ 运维 | 中高：公网回调服务 + 加解密 + 可信 IP 维护 + 证书。 |
| ⑩ 风险 | 认证门槛（企业资质）、回调必须公网、接口权限按认证状态分级（未认证企业的具体限制**未核实**）。 |
| ⑪ 结论 | 能力接近飞书但**入站成本高一档**；除非你已有认证企业主体，否则不选。 |

### 3.7 ntfy.sh / Bark / PushDeer + 自建静态页

| 维度 | 内容 |
|---|---|
| ① 免费额度 | ntfy.sh：匿名主题免注册免费；付费档 Supporter **$6/月（年付 $5）**=2,500 条/天、3 保留主题；Pro **$12/月（$10）**=20k/天；Business **$25/月（$20）**=50k/天。**免费档的每日条数未在页面标注 → 未核实**。<https://ntfy.sh/>（定价区为 JS 渲染，浏览器实读）<br>Bark：iOS 客户端免费，官方服务器免费；PushDeer：免费/开源自建。 |
| ② 部署成本 | $0，无账号（ntfy 主题名即密钥）。 |
| ③ 国内可达性 | `ntfy.sh` 2.1s 通；`api.day.app` 1.3s 通；`api2.pushdeer.com` 0.6s 通。均可用但非国内节点。 |
| ④ HTML 渲染 | **无**。ntfy 支持 markdown 子集与 action buttons（打开 URL / 发 HTTP 请求 / 复制），但通知本体不是网页。 |
| ⑤ PDF 渲染 | 附件可带 PDF，点击交给系统查看器；无内嵌翻页。 |
| ⑥ 非文本交互 | ntfy **action buttons 可发 HTTP 请求**（`http` action）→ 可做到"点按钮 = 打你的 API"，但**需要那个 API 有公网入口**；Bark 只能点开跳 URL。 |
| ⑦ 入站通路 | 按钮 → 打公网 API（若走 http action）→ 写库 → WSL 轮询；或按钮只打开你的静态页，再在页内点。 |
| ⑧ 通知 | **真锁屏推送**（APNs/FCM），这是它唯一强项。 |
| ⑨ 运维 | 极低（纯 curl 一条）。 |
| ⑩ 风险 | ntfy.sh 公共实例无 SLA、主题名泄露即被读；国内访问依赖境外线路。 |
| ⑪ 结论 | **只当"通知层"用**，不当载体。Bark 对 iOS 最省事，PushDeer 国内服务器最快。 |

### 3.8 自建 FastAPI / Next.js + Tailscale Funnel / Cloudflare Tunnel / frp

| 维度 | 内容 |
|---|---|
| ① 免费额度 | 软件全免费。Tailscale Personal **$0，最多 6 用户、设备不限**，Funnel "available for all plans"（beta）（<https://tailscale.com/pricing> · <https://tailscale.com/kb/1223/funnel>）。Cloudflare Tunnel 属 Cloudflare One 免费档（**≤50 用户**，<https://www.cloudflare.com/plans/>）。frp 需自备公网 VPS（¥30–60/月）。 |
| ② 部署成本 | $0（隧道）～¥50/年（域名）。CF Tunnel 用自有域名无需备案；Tailscale 给你 `*.ts.net` 子域，无需域名。 |
| ③ 国内可达性 | `trycloudflare.com` 4.2s 通；CF 隧道走同一境外边缘，**首屏与 Pages 同级（3–8s）**。`*.ts.net` 走 Tailscale DERP 中继，国内中继质量不稳定（**未实测**）。 |
| ④ HTML 渲染 | 满分（自己的框架）。 |
| ⑤ PDF 渲染 | 满分：服务端可做 Range 请求、pdf.js、甚至预渲染缩略图。 |
| ⑥ 非文本交互 | 满分。 |
| ⑦ 入站通路 | 页面按钮 → 你的 FastAPI（经隧道暴露）→ 直接写本地 SQLite。**最短链路**，但要求 WSL 常开 + 隧道进程常开。 |
| ⑧ 通知 | 无系统推送，需 ntfy/Bark/飞书机器人补。 |
| ⑨ 运维 | **最高**：家庭网络抖动、WSL 重启、隧道掉线、证书续期都要管。 |
| ⑩ 风险 | 单点（你的机器）；家宽上传带宽；隧道服务条款；CF 免费边缘国内慢。 |
| ⑪ 结论 | 想完全自定义时的唯一解，但**不是"免运维"方案**。 |

### 3.9 Notion 免费版（页面 + PDF 嵌入 + 评论作入站）

| 维度 | 内容 |
|---|---|
| ① 免费额度 | Free **$0/成员/月**：个人不限页面/块、基础表单、可发布到 Web、数据库；**单文件上传有大小限制（具体数值未在定价页标注 → 未核实）**；协作访客数与历史版本限制未在页面标注。<https://www.notion.so/pricing> |
| ② 部署成本 | $0，无信用卡。 |
| ③ 国内可达性 | 本次 `notion.so` 返回 200（1.5–2.8s），但解析到 `208.103.161.17`，非 Notion 官方 Cloudflare 段；Notion 在国内有长期不稳定/被墙记录。**不可依赖**。 |
| ④ HTML 渲染 | 页面排版好，但**不是 HTML**：无自定义 CSS/JS、无 KaTeX 之外的控制、无按钮回调。 |
| ⑤ PDF 渲染 | 可上传 PDF 作附件/嵌入块，Notion 内预览；受单文件大小限制，论文 PDF 常 5–20 MB。 |
| ⑥ 非文本交互 | **无按钮**。只能靠"评论"或改属性；无回调机制。 |
| ⑦ 入站通路 | cron 轮询 Notion API 读评论/属性变更（可行，但延迟 + API 限流 3 请求/秒量级，未核实）。 |
| ⑧ 通知 | Notion App 推送（若可达）。 |
| ⑨ 运维 | 低。 |
| ⑩ 风险 | 国内可达性差 + 无交互控件 + 文件限额，三条都不满足需求。 |
| ⑪ 结论 | **不适用**（除当"论文笔记归档"外）。 |

### 3.10 PWA + Web Push（iOS 16.4+）

| 维度 | 内容 |
|---|---|
| ① 免费额度 | 无服务费；需自建托管 + VAPID 密钥。 |
| ② 部署成本 | 需 HTTPS 公网域名（Pages/CF/隧道）+ 域名年费。 |
| ③ 国内可达性 | 取决于托管。**关键坑：Android 国内浏览器/Chrome 的 Web Push 走 FCM，FCM 在国内不通 → Android 上 PWA 推送实际不可用**；iOS 走 APNs，可用。 |
| ④ HTML 渲染 | 满分。 |
| ⑤ PDF 渲染 | 满分（pdf.js + Service Worker 离线缓存）。 |
| ⑥ 非文本交互 | 满分（原生 UI）。 |
| ⑦ 入站通路 | 页面 POST 到后端 → 本地库；或 IndexedDB 暂存 + 后台同步（iOS 支持差）。 |
| ⑧ 通知 | **iOS 16.4+ 仅当"添加到主屏幕"后才有 Web Push**（<https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/>）；Android 国内基本无解。 |
| ⑨ 运维 | 中：SW 缓存版本、VAPID、订阅过期清理。 |
| ⑩ 风险 | iOS 需手动加主屏（引导成本）；Android 推送不可用；国内 HTTPS 域名成本。 |
| ⑪ 结论 | 当"网页形态"很好，当"推送通道"在国行 Android 上不成立。 |

### 3.11 Zotero / Readwise 类现成阅读器

| 维度 | 内容 |
|---|---|
| ① 免费额度 | Zotero：**300 MB 免费**；2 GB **$20/年**、6 GB $60/年、无限 $120/年（<https://www.zotero.org/storage>）。Readwise：**无免费档，仅 30 天试用**；Lite **$5.59/月**（年付）、Full **$9.99/月**（<https://readwise.io/pricing>）。 |
| ② 部署成本 | Zotero $0 起；Readwise 必付费。 |
| ③ 国内可达性 | zotero.org 可用（同步偶慢）；Readwise 未测。 |
| ④ HTML 渲染 | Zotero 阅读器渲染 PDF 强，但**没有卡片正文的 HTML 版式**；Readwise Reader 有排版但不可自定义。 |
| ⑤ PDF 渲染 | Zotero 最强项（标注、笔记、同步）。 |
| ⑥ 非文本交互 | **无评分按钮回调**。Zotero 标签算半个；Readwise 有高亮/笔记但无自定义三级评分闭环。 |
| ⑦ 入站通路 | 只能轮询 Zotero Web API（改标签/笔记）→ 可做，但要走"改标签"这种别扭映射。 |
| ⑧ 通知 | 基本无（Zotero 无推送）。 |
| ⑨ 运维 | 最低（现成 App）。 |
| ⑩ 风险 | 免费 300 MB 装不下多少 PDF；Readwise 付费；都要为"评分"做 hack。 |
| ⑪ 结论 | **当 PDF 阅读/标注后端很合适，当推送+交互前端不合格**。可作为方案 A/B 的"深读"外挂。 |

---

## 4. 「不翻墙」方案的可达性风险（专节）

### 4.1 四种失败模式（在本机全部实测到）

| 失败模式 | 表现 | 本次实测样本 | 后果 |
|---|---|---|---|
| **DNS 污染** | 域名解析到 `127.0.0.1` / 保留地址 / 错误 IP | `pages.dev → 127.0.0.1` | 浏览器直接连不上；换 DNS（DoH）可绕，但手机默认 DNS 不改就废 |
| **TCP/SNI 阻断** | 连真实 IP 也 15s 超时，TLS 握手起不来 | `workers.dev`、`api.telegram.org` | 无法通过"换 IP/换域名解析"解决，只能换域名或走代理 |
| **IP 级 RST** | 0.08s 立即重置 | `supabase.co` 解析到 `76.76.21.21` | 首包即断，重试无用 |
| **无中国节点 → 纯延迟** | 能连上但 TLS 3.5s、首屏 5.8s | `pages.dev`（真实 CF IP）、`cloudflare.com` 8.6s | 可用但体验差；弱网/移动网络下易超时 |

### 4.2 备案与"国内节点"的真实门槛

- **ICP 备案**只对"服务器在中国大陆"的站点强制。用 Cloudflare 海外节点 / Vercel / Supabase，**不需要备案**，但也拿不到中国节点。
- **Cloudflare 中国网络（JD Cloud 合作）明确只对 Enterprise 销售**：「available as a separate subscription for customers on an Enterprise plan」（<https://developers.cloudflare.com/china-network/>）。免费版永远走境外 PoP —— 这是"CF 在国内慢"的根本原因，不是配置问题。
- 想在境内拿到低延迟，只有三条路：
  1. **国内云 + ICP 备案**（阿里云/腾讯云轻量 ¥60–100/年 + 域名 ¥50/年；备案需域名实名 + 国内接入商，个人可办，通常 7–20 天，需承诺内容合规）；
  2. **香港/新加坡轻量服务器**（**无需备案**，到大陆 40–80ms，¥24–40/月）——这是"要快又不想备案"的现实折中；
  3. **对象存储 + CDN（国内）** 同样要备案，静态站可走 OSS 静态托管。

### 4.3 各候选的"绕行成本"

| 候选 | 默认形态在国内 | 绕行手段 | 绕行成本 |
|---|---|---|---|
| Cloudflare Pages | `*.pages.dev` 污染 | 自有域名 + CF（仍境外边缘） | 域名 ¥50–100/年；延迟不改善 |
| Cloudflare Workers API | `*.workers.dev` 阻断 | 自有域名绑 Worker Route | 同上，**必须有域名** |
| Supabase | 控制台可通，项目域未验证 | 自有域名反代 / 换 Neon/Turso | 多一跳，收益不明 |
| Vercel / Netlify | `*.vercel.app`、`*.netlify.app` 阻断 | 自有域名 | 域名费 + 仍慢 |
| GitHub Pages | 本次 0.34s 通 | 无 | 波动风险自担 |
| Telegram | 全阻 | 全程代理 | 手机必须常开梯子 |
| Notion | 可疑中转 | 代理 | 同上 |
| 飞书 / 企微 | 原生直连 | 无 | 0 |
| 自建 + 隧道 | 隧道域走境外 | 香港 VPS + 自有域名 | ¥24–40/月 |

---

## 5. 入站通路：为什么"cron 轮询云端/本地队列"优于"webhook 打进内网"

WSL 的现实约束：没有公网 IP、没有固定 IP（家宽 NAT）、休眠/重启会换地址、Windows 防火墙 + WSL NAT 双栈穿透麻烦。任何"让别人 POST 到我家"的设计都要额外买隧道或做端口映射。

| 维度 | Webhook 打进内网 | cron 轮询 | 长连接（飞书/Telegram） |
|---|---|---|---|
| 需要公网 IP/域名 | **要** | 不要 | 不要（出站 WS） |
| WSL 重启后 | 回调全丢（对端重试窗口有限） | 下个周期自动补 | 断线重连后对端重推（窗口内） |
| 幂等/去重 | 要在入口做 | 天然可做（`since` 游标 + 唯一键） | 必须做（3s 超时会重推） |
| 延迟 | 秒级 | 取决于周期（5 分钟） | 亚秒 |
| 攻击面 | 公网暴露一个写接口 | **零暴露** | 零入站端口 |
| 失败可见性 | 对端报错你看不到 | 本地日志 + 游标可查 | SDK 日志 |
| 运维 | 隧道/证书/防火墙 | 一个 cron | 一个常驻进程 |

**推荐拓扑（本地队列 + 双写）**：

```
手机点击
  ├─(主) 飞书长连接 ──► WSL 常驻进程 ──► inbox/*.jsonl (append-only, 幂等键=event_id)
  └─(兜底) 每 5 min cron ──► 读 inbox + 校验 state 游标 ──► 合并 → state/checkpoints.yaml
```
- 若选 Cloudflare 方案：`按钮 → Worker → D1(events 表, id 自增) → cron GET /api/events?since=last_id → 本地`。
- **幂等键统一用 `event_id`/`id`**，本地写 `processed_ids` 集合，重放安全。
- 理由一句话：**WSL 是不可靠端点（会睡、会换 IP），把"可靠性"放在云端队列 + 本地游标上，比维持一条常驻入站通道便宜得多。**

---

## 6. 三个组合方案（前端 + 入站 + 通知 的完整闭环）

### 方案 A（★ 国内直连最优）：飞书卡片 + 长连接 + 飞书文件 PDF

| 角色 | 选型 |
|---|---|
| 前端 | 飞书消息卡片 JSON 2.0（标题/正文 markdown/图/链接/代码块 + 三个按钮：不相关 / 相关但一般 / 质量高 + 「追问」输入框） |
| PDF | 同一条会话补发 `file` 消息（arXiv PDF），飞书 App 原生阅读器翻页 |
| 入站 | `lark-oapi` 长连接（WebSocket，无需公网），`card.action.trigger` → 本地 `inbox.jsonl`；cron 每 5 分钟合并 + 兜底 |
| 通知 | 飞书 App 系统级锁屏推送 |
| 存储 | 本地 `state/checkpoints.yaml` + `archive/papers.jsonl`（不上云） |

**单人运维成本**：约 10 分钟/月（看一次长连接是否掉线、清一次 inbox）。
**最小上线步骤（8 步）**：
1. 手机号注册飞书团队（免费版，100 人）。
2. `open.feishu.cn/app` 创建「企业自建应用」，拿 `app_id` / `app_secret`。
3. 开权限：`im:message`、`im:message:send_as_bot`（发消息）；按需 `contact:user.employee_id:readonly`。
4. 开发者后台 → 事件与回调 → 订阅方式选「**使用长连接接收**」→ 添加回调 `card.action.trigger`。
5. WSL：`pip install lark-oapi`，跑一个 40 行的 `ws_client.py`（`larkws.NewClient` / `lark.ws.Client`），把 `action.value` 追加进 `inbox.jsonl` 并 `return` 一个 toast。
6. 推送脚本：拼卡片 JSON（≤30 KB），`POST /open-apis/im/v1/messages?receive_id_type=open_id` 发卡片；随后 `POST /open-apis/im/v1/files` 上传 PDF + 发 `file` 消息。
7. systemd/`nohup` 常驻 `ws_client.py`；Hermes cron 每日推送 + 每 5 分钟合并 inbox。
8. 自测：手机点三个按钮 → 看 `inbox.jsonl` 是否出现三条带 `event_id` 的记录 → 跑一次合并，确认 `state` 权重变化。

**已知天花板**：卡片 30 KB（长正文必须分页/跳链接）、3 秒回调、200 组件、5 QPS/用户。

---

### 方案 B（可翻墙时最优，国内"能忍"）：Cloudflare Pages + Workers + D1 + ntfy/Bark

| 角色 | 选型 |
|---|---|
| 前端 | 自有域名 → Cloudflare Pages（静态 SPA：卡片列表 + KaTeX + 代码高亮 + `pdf.js` 内嵌翻页） |
| PDF | `pdf.js`；arXiv PDF 经 Worker 代理（剥 `X-Frame-Options`，加 CORS），>25 MiB 的放 R2 |
| 入站 | 按钮 `POST /api/score` → Worker 写 D1 `events` 表 → WSL cron 每 5 分钟 `GET /api/events?since=<id>` |
| 通知 | ntfy.sh（iOS/Android 都行）或 Bark（iOS 最省事） |
| 鉴权 | Cloudflare Access（免费 ≤50 用户）保护页面，或 URL 里带一次性 token |

**单人运维成本**：约 20 分钟/月（`wrangler` 部署、看 D1 用量）。
**最小上线步骤（9 步）**：
1. 买域名（¥50–100/年），NS 指到 Cloudflare（免费档）。
2. `npm create cloudflare@latest` 建 Pages/Worker 项目。
3. 写 `schema.sql`：`events(id INTEGER PRIMARY KEY, paper_id, action, ts, consumed)`；`wrangler d1 execute --remote`。
4. 写 `/api/score`（校验 HMAC 或 Access JWT，写 D1）。
5. 写 `/api/events?since=`（只读，需 token）。
6. 前端：卡片渲染 + `pdf.js` + 三个按钮。
7. Worker 加 `/api/pdf?u=arxiv_id` 代理（限制域名白名单，防 SSRF）。
8. `wrangler deploy`，绑自定义域名（**不要用 `*.pages.dev`，已被污染**）。
9. WSL cron：拉 events → 写本地 state → 推送用 ntfy `curl -d`（或 Bark）。

**已知天花板**：国内首屏 3–8s；Workers 10 ms CPU（不能做 PDF 解析）；D1 单库 500 MB；免费版无中国节点。

---

### 方案 C（掌控最强 / 兜底）：自建 FastAPI + 隧道 + PWA

| 角色 | 选型 |
|---|---|
| 前端 | FastAPI + Jinja/HTMX 或 Next.js；`pdf.js`；PWA manifest |
| PDF | 服务端 Range 代理 + pdf.js，可做缩略图/预取 |
| 入站 | 页内按钮 → 同源 `POST /score` → 直接写本地 SQLite（**零跨网**） |
| 通知 | ntfy/Bark；iOS 可加 Web Push（需"添加到主屏幕"） |
| 暴露 | Cloudflare Tunnel（自有域名，无需备案）或 Tailscale Funnel（`*.ts.net`，免费） |

**单人运维成本**：约 60 分钟/月（隧道掉线、WSL 重启、证书、备份）。
**最小上线步骤（7 步）**：装 `cloudflared` → `cloudflared tunnel login` → `create` → 配 `config.yml` 指向 `localhost:8000` → `route dns` → 跑 FastAPI（systemd）→ 手机加书签/主屏。
**已知天花板**：WSL 必须常开；家宽上行带宽；国内访问仍是"境外边缘"延迟。

---

### 6.4 推荐落地：A 为主，B 为"深读页"

- **推送 + 一键评分 + 锁屏提醒**：全部走飞书（0.035s、无公网、原生按钮）。
- **卡片里"读全文/看 PDF"按钮**：跳到 Cloudflare Pages 的精读页（pdf.js 翻页、公式、代码、图）。
- 这样"每天 5 秒点三下"在国内直连完成；"想细读"时才付 3–8s 的页面加载代价。
- 若嫌 B 重：精读页直接用飞书的 `file` 消息（PDF 阅读器）+ 云文档，先不上 CF。

---

## 7. 明确写死：免费额度下**做不到**的事

1. **飞书卡片里嵌 PDF 翻页器** —— 卡片不支持 iframe/PDF 组件；只能"发文件消息"或"跳链接"。要"卡片内翻页"必须自建网页。
2. **飞书卡片塞长正文** —— 30 KB 上限（约 1.5 万汉字无格式，含 JSON 转义更少），超过必须分页或跳转。
3. **飞书 3 秒内做完重活** —— 回调超时会重推；不能在里面跑检索/LLM，只能"落盘 + 返回 toast"。
4. **Cloudflare 免费版拿到中国节点** —— China Network 只卖 Enterprise；免费档国内首屏 3–8s 是物理距离，不是调优问题。
5. **Cloudflare 上用 `*.pages.dev` / `*.workers.dev` 裸域** —— 前者 DNS 污染、后者直接被阻断；**必须自有域名**（年费不可避免）。
6. **Workers 免费版做 PDF 解析/OCR/大模型调用** —— 10 ms CPU/次、128 MB 内存，只能做转发与轻逻辑。
7. **D1 免费库存大量 PDF** —— 单库 500 MB、账号 5 GB；PDF 必须进 R2（10 GB）或对象存储。
8. **Supabase 免费版当"长期在线"后端** —— 1 周无活动即暂停；靠 cron 心跳续命，且只有 2 个活跃项目、1 GB 文件存储。
9. **GitHub Pages 免费版做私密站** —— 免费只支持公开仓库，你的评分/阅读记录会公开。
10. **国内 Android 上的 PWA 推送** —— Web Push 走 FCM，国内不通；iOS 也要"添加到主屏幕"才有（16.4+）。
11. **Telegram 当国内主通道** —— `api.telegram.org` 直连 15s 超时，必须全程代理。
12. **Notion 做交互式卡片** —— 没有按钮回调，只能评论/改属性，且国内可达性可疑。
13. **企业微信"零公网"接回调** —— 模板卡片回调必须公网 URL + 可信 IP，普通自建应用没有长连接。
14. **Zotero 免费 300 MB 存论文库** —— 几十篇 PDF 就满，2 GB 要 $20/年；Readwise 无免费档。

---

## 8. 数值速查（全部来自官方页）

| 项 | 数字 | 来源 |
|---|---|---|
| Workers 免费 | 100,000 请求/天；10 ms CPU；128 MB；50 子请求；5 Cron/账号 | developers.cloudflare.com/workers/platform/{pricing,limits}/ |
| Pages 免费 | 500 构建/月；20,000 文件；25 MiB/文件；100 域/项目；100 项目 | developers.cloudflare.com/pages/platform/limits/ |
| D1 免费 | 10 库；500 MB/库；5 GB/账号；5M 行读/天；100k 行写/天 | developers.cloudflare.com/d1/platform/limits/ |
| R2 免费 | 10 GB-month；1M Class A；10M Class B；出网免费 | developers.cloudflare.com/r2/pricing/ |
| Cloudflare One 免费 | ≤50 用户（Tunnel 所属档） | cloudflare.com/plans/ |
| Supabase 免费 | 500 MB DB；1 GB 存储；5 GB 出网；50k MAU；2 项目；7 天无活动暂停 | supabase.com/pricing |
| GitHub Pages 免费 | 1 GB 站点；100 GB/月软限；10 构建/小时 | docs.github.com/…/github-pages-limits |
| GitHub API | 5,000 请求/小时（认证）；60/小时（匿名） | docs.github.com/…/rate-limits-for-the-rest-api |
| 飞书 免费版 | ¥0；100 用户 | feishu.cn/service |
| 飞书 发消息 | 1,000 次/分钟；50 次/秒；单用户 5 QPS；卡片 30 KB；200 组件 | open.feishu.cn/document/server-docs/im-v1/message/create.md |
| 飞书 长连接 | 每应用 ≤50 连接；回调 3 秒内响应；仅企业自建应用 | open.feishu.cn/document/…/request-url-configuration-case.md |
| 企微 应用消息 | ≤账号上限×200 人次/天；单成员 30 次/分、1,000 次/时；`response_code` 72h 且一次 | developer.work.weixin.qq.com/document/path/90236 |
| ntfy 付费档 | $6/$12/$25 月（年付 $5/$10/$20）；2.5k/20k/50k 条/天 | ntfy.sh（定价区） |
| Tailscale 免费 | $0；≤6 用户；设备不限；Funnel 所有档可用（beta） | tailscale.com/pricing · /kb/1223/funnel |
| Zotero | 300 MB 免费；2 GB $20/年；6 GB $60/年；无限 $120/年 | zotero.org/storage |
| Readwise | 无免费档（30 天试用）；Lite $5.59/月；Full $9.99/月（年付） | readwise.io/pricing |
| Notion 免费 | $0；个人页面/块不限；单文件上限未标注 | notion.so/pricing |

---

## 9. 未核实清单（不编数字）

1. **飞书：注册免费团队是否需营业执照/企业认证**——官方文档只写"企业自建应用"，未写主体门槛；实践上手机号可建团队（未逐字核实）。
2. **飞书免费版云文档/存储容量**（版本对比表为动态加载，未取到数值）。
3. **企业微信认证费用与年审金额**（官方帮助页为 SPA，1.1 MB 无正文）。
4. **企业微信"未认证企业"的具体接口限制**（同上）。
5. **Gitee Pages 官方下线公告**（`gitee.com/pages` 非产品页、`*.gitee.io` 404、帮助文章 4136 已 302，但公告原文未找到）。
6. **Telegram Bot API 限流数字**（`core.telegram.org` 本机不可达，"30 条/秒"未复核）。
7. **Supabase 项目域 `<ref>.supabase.co` 的国内可达性**（`supabase.co` 无泛解析，假 ref 无法测；需真实项目验证）。
8. **Tailscale Funnel `*.ts.net` 的国内可达性/延迟**（需真实 tailnet 才能测）。
9. **Notion 单文件上传上限、访客数、历史版本窗口**（定价页未标注）。
10. **ntfy.sh 免费匿名档的每日消息条数**（页面只列付费档）。
11. **Cloudflare Pages 免费版"中国大陆"的实际 SLA**（无官方承诺，只有 Enterprise 的 China Network 说明）。
12. **企微"智能机器人长连接"是否可用于普通自建应用**（目录里存在该条目，正文未读）。

---

## 10. 一句话给决策

**先上飞书（方案 A）**：它把"推送、按钮、PDF、无公网入站"四件事一次性解决，成本 0，国内 35ms。
**等你嫌卡片 30 KB 不够写、PDF 想内嵌翻页时，再加 Cloudflare Pages 当精读页（方案 B）**——那时你只需要为一个自有域名付钱，且接受 3–8s 首屏。
**Telegram 只在"你确定会长期挂代理"时才考虑**，它的交互模型其实比飞书更顺手，但地理上不在服务区。
