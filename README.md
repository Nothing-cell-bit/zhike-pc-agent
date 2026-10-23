# 知客 · 门店增长工作台

比比拉布团队｜华为·产业进阶赛道参赛作品

## 项目介绍

知客面向华为 PC 门店，将客户咨询、AI 辅助接待、人工核实、规则报价与营销图文创作连接起来。客户在聊天中表达需求，客服据此提供选购建议，也能将已确认的需求转为营销创作素材。

| 角色 | 主要功能 |
| --- | --- |
| 客户端 | 浏览产品、发起咨询、补充需求、接收回复与报价 |
| 客服端 | 多轮 AI 回复建议、核实待办、四级规则报价、营销创作与跟进 |
| 管理员端 | 账号管理、会话分配、模型配置、知识库、报价规则与运行维护 |

产品资料优先从 ima 检索，读取失败时按配置回退本地资料并标明来源。AI 回复由客服确认后发送；核实事项单独跟进，已确认的信息可以继续推进。营销作品保留资料来源、内容版本与核验记录，支持配图、AI 海报和导出。

技术栈：React、TypeScript、Ant Design、FastAPI、SQLAlchemy、SQLite。

## 功能演示

[观看／下载演示视频](output/competition-video-tight-20261023/知客-三端演示-连贯配音与营销联动版.mp4)｜约 **2 分 24 秒**，1080p，全屏中文女声解说。

视频展示客户咨询、管理员分配、客服多轮回复、门店核实与报价反馈，再将同一会话的产品、场景和预算带入营销创作，说明公众号、小红书、朋友圈三类文案的差别。视频为剪辑版，价格与销售组合均为演示测试数据；成稿预览使用独立案例。

- [作品说明书](docs/competition/WORK_DESCRIPTION.md) · [PDF 版](output/pdf/比比拉布-知客-作品说明书.pdf)
- [完整问答与录制说明](output/competition-video-full-20261023/完整对话与录制说明.md) · [视频字幕](output/competition-video-tight-20261023/中文字幕.srt)

完成下方依赖安装与前端构建后，也可以运行本地文案样例：

```powershell
.\.venv\Scripts\python.exe scripts/run_demo.py
```

访问 `http://127.0.0.1:8767/staff`，使用终端显示的演示账号登录。此模式使用独立数据目录，无需 API，供查看已有文案和导出草稿。

## 安装运行

运行环境：Python 3.11+、Node.js 22.13+ 或 24+、Git。以下命令适用于 Windows PowerShell。

### 1. 获取代码并安装依赖

```powershell
git clone https://github.com/Nothing-cell-bit/zhike-pc-agent.git
cd zhike-pc-agent
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci --prefix frontend
npm run build --prefix frontend
```

### 2. 初始化配置、管理员和产品资料

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m backend.cli admin --username admin
.\.venv\Scripts\python.exe -m backend.cli import 'C:\path\知识库.zip'
```

管理员初始密码保存在 `data/initial-admin.txt`，首次登录后修改；已有管理员无需重复创建。将示例路径替换为你有权使用的知识库 ZIP，仓库不附带知识库原件和服务凭证。

在 `.env` 配置 `TEXT_API_BASE`、`TEXT_API_KEY`、`TEXT_MODEL`；ima 凭证放入私有 `.env.ima`。需要 AI 配图时配置图片服务。文本模型也可在管理员“网站设置 → AI配置”中设置。具体变量和连接要求见 [API 与 ima 配置手册](docs/competition/API_CONFIGURATION.md)。

### 3. 启动网站

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
```

| 入口 | 地址 |
| --- | --- |
| 客户咨询 | `http://127.0.0.1:8765/` |
| 客服工作台 | `http://127.0.0.1:8765/staff` |
| 管理后台 | `http://127.0.0.1:8765/admin` |

也可在 PowerShell 7 中运行 `.\scripts\start.ps1`；加 `-Build` 重新构建前端，加 `-Lan` 开放可信局域网访问。部署方式见 [部署说明](docs/competition/DEPLOYMENT.md)。

## 使用方法

1. **配置门店**：管理员创建客服账号、分配会话，在网站设置中配置 AI、查看知识库状态并维护报价规则。正式对客报价前需录入门店核准的价格、条件和有效期。
2. **接待客户**：客户从前台发起咨询；负责客服查看需求与 AI 建议，点击“更多”查看候选，采用后确认发送。
3. **核实与报价**：遇到不确定的问题，登记核实事项并填写结论、条件和来源。核实完成后反馈客户；选定配置后采用有效报价卡，确认金额和适用条件再发送。需要后续联系时，可安排 1／3／5 天跟进。
4. **转为营销创作**：在“会话详情 → 跟进与创作”点击“转为营销创作任务”，核对已预填的需求，补充缺失信息，并在“结合的聊天”中选择具体消息。也可从“营销内容”独立创建作品。
5. **编辑、检查与导出**：选择文案类型后生成内容，修改正文与配图，完成内容检查与人工确认，再预览、制作海报或导出。支持文本、Markdown、HTML 与图文 ZIP；修改作品后需重新检查。

| 文案类型 | 适合的表达 |
| --- | --- |
| 公众号深度文章 | 分节讲清选购依据、使用建议和适用边界 |
| 小红书场景笔记 | 从具体使用场景切入，采用短段落、清单与话题配图 |
| 朋友圈自然短文 | 像门店顾问与朋友聊天，保留重点，搭配产品或场景图 |

第三方复用与许可证说明：[OpenDesign](third_party/open-design/NOTICE.md)、[平台内容生成](third_party/platform-content/NOTICE.md)、[图文排版](third_party/doocs-md/NOTICE.md)。
