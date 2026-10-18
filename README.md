# 知客 · 门店增长工作台

**比比拉布团队｜华为·产业进阶赛道参赛作品**

> **部署状态：魔搭部署还是有点问题。** 当前云端部署与学校模型访问链路仍在联调；现有方案依赖本机认证网关和临时隧道持续在线，尚未完成云端稳定性与完整业务流程验收。请优先按下文在本地运行，具体部署条件见 [魔搭部署说明](docs/competition/DEPLOYMENT.md)。

把顾客的购机需求，转成有来源、可修改、可核验的门店营销图文。知客提供客户接待、场景策略、图文创作、独立核验与导出；当前为本地比赛原型，营销生成已支持 ima 优先、调用失败时本地兜底。

- [作品说明书](docs/competition/WORK_DESCRIPTION.md) · [真实旧版结果节选](docs/competition/RESULT_EXCERPT.md) · [系统提示词](backend/prompts/marketing-system.txt)
- [提交指南与材料对照](docs/competition/SUBMISSION_GUIDE.md) · [提交文案](docs/competition/SUBMISSION_COPY.md)
- 双击根目录 `一键准备提交.cmd`：检查、生成源码包并打开本地提交准备台，支持一键复制字段。尚未填写官方入口或完成真实验收时会显示待补齐。

产品范围以 [spec.md](spec.md) 为准，完成证据与剩余限制见 [ACCEPTANCE.md](ACCEPTANCE.md)。

## ima 优先与本地兜底

营销生成按完整型号读取 ima 资料和原图，保存来源快照，再生成与核验。当前策略为 **ima 优先，读取失败则整项回退本地**，每篇作品显示实际来源与原因。详情见 [ima 接入与验收](docs/competition/IMA_INTEGRATION.md)。

凭证放在私有 `.env.ima`，优先于 `.env`，不进入前端。三个真实案例经明确修订与模型重验后通过：两个使用 ima，一个在真实接口错误后使用本地回退。新版已在 `http://127.0.0.1:8765/staff` 使用原业务库运行，三组作品及版本、来源快照已迁入，原有数据逐条验证保留。8768 已停止，隔离库与迁移前备份仍保留。当前仅本机监听。

## 赛题补齐与本地材料（2026-10-18）

已补购买阶段／主要问题输入、场景判断、同型号场景选图、按正文位置插图、四部分统一复制／导出，以及“查看创作依据”窗口。资料冲突会停止成稿，修改不能直接解除冲突；正式稿、草稿和海报均需遵守拦截。标签、配图说明也参与合规检查；正文不能夹带外部图片绕过图源列表。后端改动需重启本地服务后生效。

- [作品说明书草稿](docs/competition/WORK_DESCRIPTION.md)
- [ima 准备清单](docs/competition/IMA_PREPARATION.md)：账号、共享库权限、同账号凭证、官方 Skill 本地路径。
- [系统提示词与调用设计](docs/competition/PROMPT_DESIGN.md)
- [统一验收任务与录屏提纲](docs/competition/EVALUATION.md)

可用以下命令把已有三组历史记录整理为本地案例册，无网络或模型调用；产物在被忽略的 `output/competition/`，不会改写历史记录。案例册使用旧 store-v2 记录重新排版，不能作为新 store-v3 或 ima 接入的真实验收。

```powershell
.\.venv\Scripts\python.exe scripts/prepare_competition_materials.py
```

此段记录的是此前开发轮次；当前仓库与展示页准备进度以 [提交配置](docs/competition/submission.json) 和提交指南为准。连续真实 Demo 和比赛正式投递未完成；ima 接入的最新进展见上方说明。

## 当前功能

登录后的工作台主页集中展示客户接待、营销内容、产品资料三个入口，下面显示待办跟进与最近作品。跟进可直接打开事项，作品可直接打开编辑页。侧栏保留首页和三个业务入口；跟进计划在客户接待内，创作与作品在营销内容内，通知在右上角，管理员设置与退出在左下角账号菜单。

- 客户访客咨询、账号注册、登录和个人历史；注册绑定当前访客会话。
- 客服会话列表、原子认领／接管、消息去重、断线重连与历史补读。只有当前负责人能回复。
- 浙大 `qwen3.8-27b` 需求分析，七项需求独立记录，并保留客户原话依据与人工修正。缺少信息时提供一句追问；建议只填入输入框，由人发送。
- 按产品、人群、场景、目标和平台生成营销图文，保存来源、图片和版本；编辑后必须重新核验。
- 公众号、小红书、朋友圈、海报规则；资料冲突、无依据事实和配图不足阻止正式导出。
- 文本、Markdown、独立 HTML、包含实图与引用的 ZIP；Pillow 本地海报 PNG。
- 魔搭异步背景任务：单并发、远端编号持久化、180 秒超时、人工续查、取消保护。未配置时可直接用实图合成。
- 跟进 1／3／7 天、北京时间编辑、完成反馈、拒绝后停止；接管时转交待办。
- 客服任务中心、管理员工、门店设置、导入重建、审计、SQLite 一致性备份和隔离恢复演练。

这是本地比赛原型。营销任务优先读取 ima，本地 ZIP 用于产品选择及调用失败时的回退。旧稿保持原来源。未实现四级报价、公网发布、多店、订单或支付。

## 安装与启动（Windows PowerShell）

需要 Python 3.11+、Node.js 22.12+ 或 24+。所有操作在本项目内完成。

```powershell
cd D:\门店增长智能体
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
```

仅首次配置：复制 `.env.example` 为 `.env`，在本机编辑服务端密钥；**已有 `.env` 时不要覆盖**。

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
# 首次创建管理员，已存在的账号不会被覆盖
.\.venv\Scripts\python.exe -m backend.cli admin --username admin
# 首次导入已有知识包
.\.venv\Scripts\python.exe -m backend.cli import 'D:\资料\知识库.zip'
```

管理员随机初始密码保存于私有 `data/initial-admin.txt`。不要提交、截图或公开分享该文件。登录后在管理设置修改密码；普通客服由管理员创建。请勿把密码作为 shell 参数传入。

```powershell
# 仅本机
.\scripts\start.ps1
# 重新构建并开放可信局域网
.\scripts\start.ps1 -Build -Lan
```

- 客户入口：`http://127.0.0.1:8765/`
- 客服入口：`http://127.0.0.1:8765/staff`
- 手机与电脑连接同一网络后，访问 `http://电脑局域网IP:8765/`。
- 如防火墙拦截，仅为可信专用网络开放该端口；不需要开放公网路由器端口。
- 开发模式：后端运行 `python -m uvicorn backend.main:app --port 8765`，前端目录运行 `npm run dev`，访问 5173。
- 仅启动一个后端 worker，确保文本与图片单并发以及内存 WebSocket 广播一致。

## 模型配置

完整的文件位置、变量填写、优先级、知识源模式与验证步骤见 [模型与 ima API 配置手册](docs/competition/API_CONFIGURATION.md)。真实服务地址和凭证只存本机 `.env` / `.env.ima`，不上传仓库或魔搭展示页。

文本服务使用 `TEXT_API_BASE`（包含 `/v1`）和 `TEXT_API_KEY`；模型固定为 `qwen3.8-27b`，无外部备用文本模型。没有配置时，任务显示失败原因，不生成模拟答案。

魔搭使用 `MODELSCOPE_IMAGE_BASE_URL`、`MODELSCOPE_IMAGE_MODEL`、`MODELSCOPE_IMAGE_API_KEY`。默认模型 `Qwen/Qwen-Image-2.1-Turbo`。`NothingK` 只是待核对的账号标记，不能代替 Token，也不代表已验证归属。

背景仅包含场景，不重绘产品；本地合成保留原产品比例。透明原图保留 alpha，非透明图放在卡片区域。`data/assets` 保存背景、合成图及数据库关系，不能用合成图冒充比赛知识库原图。

## 核验与版本

初次生成与后续核验都使用独立模型调用；JSON／结构最多修复一次，瞬时网络错误最多重试一次。核验从当前正文重新提取事实，不沿用旧稿参数。返回不完整核验结构时不能通过。

编辑标题、正文、标签、图片或待确认事项都会生成新版本并清除通过状态。待确认事项只有在核实事实或删除对应不确定表述后才应移除；移除后仍需点击“重新核验”。无法确认时可导出带标记的草稿。界面不会把 AI 建议自动发送给客户。

创作输入默认隐藏常见手机、邮箱、证件号及带标签的姓名／地址。自动规则不能识别所有自然语言个人信息；从会话转入创作时只带需求摘要，不带完整聊天，提交前可进一步编辑摘要。

## 数据与备份

业务库 `data/store.db` 使用 SQLite WAL；知识索引独立存放于 `data/knowledge/index.db`。知识原件按哈希版本保存，历次索引留存以支持旧作品引用。

```powershell
.\.venv\Scripts\python.exe -m backend.cli backup
.\.venv\Scripts\python.exe -m backend.cli restore-drill
# 实际恢复前停止网站，并选择有效备份
.\.venv\Scripts\python.exe -m backend.cli restore 'D:\门店增长智能体\data\backups\备份文件.db'
```

应用运行时每小时检查一次，距最近备份超过 24 小时则备份；保留最近 7 天。恢复演练复制到独立临时数据库，执行完整性检查和表统计，不覆盖正在使用的数据。实际恢复会先备份当前业务库。

数据库备份只恢复业务记录。跨机器迁移／整盘故障恢复需要另外保存 `data/knowledge`、`data/assets` 和私有配置；这些文件不能只靠 `.db` 重建。源知识 ZIP 与凭证不得放到公开仓库。恢复时必须停服，避免并发写入。

## 测试

注意：完整后端集成测试和浏览器夹具依赖团队本地的特定知识库快照，公开仓库不分发这份受限资料。新克隆可直接运行 `python -m unittest scripts.test_submission` 和前端测试；完整后端结果的前置条件见 [提交指南](docs/competition/SUBMISSION_GUIDE.md)。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q --cov=backend
npm test --prefix frontend
npm run build --prefix frontend
npm audit --prefix frontend --registry=https://registry.npmjs.org
```

后端测试使用独立临时数据目录并强制清空模型密钥。浏览器验收使用 `tests/e2e_server.py` 的显式测试夹具，**不是实际模型结果**：

```powershell
# 终端一：仅监听本机 8766，重建 tmp/e2e-data 下的测试库
.\.venv\Scripts\python.exe -m tests.e2e_server
# 终端二：设置已安装 Playwright 包的位置；或在 frontend 安装 Playwright
$env:PLAYWRIGHT_MODULES='已安装的node_modules绝对路径'
# 如使用现有 Chromium，可设置 PLAYWRIGHT_EXECUTABLE
node scripts/browser_acceptance.cjs
```

真实接口验收独立运行，可能消耗额度，必须事先授权：

```powershell
.\.venv\Scripts\python.exe scripts/real_acceptance.py --text
# 仅在明确允许生图后才加 --image
```

脚本使用已有私有管理员初始化凭证，不重置账号；已改初始密码后，请从网站手动运行相同场景。每个 run-id 保存任务编号，重跑时读取原任务，避免自动重复提交。结果和图文导出位于 `data/acceptance/`，不提交公开仓库。`scripts/live_acceptance.py` 现在是同一显式开关流程的兼容入口，无参数不会调用外部服务。

## 演示顺序

1. 手机以访客身份咨询预算、任务和顾虑；客服认领并回复。
2. 查看客户需求，人工修正一项；采用建议到输入框，再手动发送。
3. 新建营销任务，选择完整型号与具体受众；缺信息时展示补充提示。
4. 预览作品并查看具体检查问题、待确认信息；选择“自动调整并检查”保存修订版，或核实后填写说明并“人工确认通过”。人工通过可正式导出和制作海报，记录确认人、时间与原始检查结果；再次修改会恢复“待检查”。自动调整失败保留原稿，版本变化时不覆盖新内容；资料冲突及不受管理的图片须先处理。
5. 展示同产品小红书与朋友圈的结构、配图和 CTA 差异，以及差旅公众号案例。
6. 使用实图生成海报，查看版本；安排跟进并展示恢复演练。

真实 ima 接入与魔搭账号权限是外部事项，不用本地测试或原型替代其验收。公开部署和比赛链接提交需另行授权。
