# 知客 · 华为 PC 营销图文智能体

**比比拉布团队｜华为·产业进阶赛道参赛作品**

把顾客的购机需求，转成有来源、可修改、可核验的门店营销图文。

## 项目入口

- 源码与运行步骤：https://github.com/Nothing-cell-bit/zhike-pc-agent
- 作品说明书：https://github.com/Nothing-cell-bit/zhike-pc-agent/blob/main/docs/competition/WORK_DESCRIPTION.md
- 真实旧版结果节选：https://github.com/Nothing-cell-bit/zhike-pc-agent/blob/main/docs/competition/RESULT_EXCERPT.md
- 提示词：https://github.com/Nothing-cell-bit/zhike-pc-agent/blob/main/backend/prompts/marketing-system.txt

## 做什么

面向门店导购和内容运营，输入完整产品型号、目标人群、使用场景、内容目标与发布平台，生成公众号、小红书、朋友圈或海报内容。系统保留资料与图片来源，支持人工编辑、重新核验及 Markdown、HTML、ZIP 和本地海报导出。

## 自研 Agent 如何工作

任务补充 → 型号绑定与证据读取 → 场景和平台策略 → 图文生成 → 同型号选图与编排 → 独立事实核验与合规检查 → 人工改稿 → 四部分导出。

大模型负责理解和表达；自研系统负责业务规则、来源约束、图片匹配、版本状态和导出。型号或关键输入不明时先补充；资料冲突时停止成稿；修改后撤销原核验状态。

## 当前完成度

本地应用已实现客户接待、需求分析、营销创作、资料检索、核验与导出主流程。新版 store-v4-ima 已保存三组真实文本结果：新生小红书和差旅公众号使用 ima；新生朋友圈在 ima 返回错误后整体回退本地。三组最终结果均经过人工修订与独立模型重验，并非一次生成即通过。

**系统优先读取 ima，调用失败时整体回退本地，并显示实际来源。当前有两组新版 ima 通过案例，第三组是本地回退，不能冒充 ima 验收。** 同型号选图基于描述与场景规则，不声称具备图片视觉理解。完整赛题对照和连续真实录屏仍需补齐。

## 运行与资料边界

Python 3.11+、Node.js 22.12+ 或 24+；FastAPI + React + SQLite。完整安装、环境变量和启动方法见 GitHub README。新机器需使用自己的模型凭证与有权访问的知识资料，未配置模型时不会伪造答案。

本空间已部署原 React + FastAPI 工作台，员工功能需要登录。当前文本模型依赖用户电脑与临时认证隧道持续运行；ima 当日限额时按实际情况使用已授权的私有产品缓存，并明确标记本地来源。源码不包含 API Key、Client ID、客户数据、私有知识库原件或原图。比赛知识来源、实时销售政策和最终内容仍需按赛题要求核实。
