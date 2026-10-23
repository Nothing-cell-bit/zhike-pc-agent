# Platform content adaptations

- `backend/platform_content.py`: platform-specific writing instructions and writing principles adapted from [qiuxchao/content-agent](https://github.com/qiuxchao/content-agent), revision `c256e3c13339963fe9c1e8fff92ec93a47ec87cf`, `agent/prompts/templates.py`. Copyright (c) 2025 qiuxchao. MIT license retained in `content-agent.LICENSE`.
- The evidence-bound Article Plan is adapted from [liyown/ai-trend-publish](https://github.com/liyown/ai-trend-publish), revision `5366f02b5d5f83c620a6c7ff9a23740fad69c2a6`, `src/prompts/article-plan.prompt.ts`. Copyright 2025 Yaowen Liu. MIT license retained in `trendpublish.LICENSE`.

Modifications: use the existing server-side gateway and product knowledge instead of news search, omit LangGraph/Chroma dependencies, add a separate WeChat Moments contract, validate source IDs and platform structures, bound rewrites to one, and retain the existing independent factual verification. No upstream account publishing or telemetry is used.
