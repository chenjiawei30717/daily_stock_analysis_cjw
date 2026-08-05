# GitHub Pages 报告站点部署

每日选股/大盘/仪表盘报告自动发布到 GitHub Pages 静态站点,零成本、零服务器。

## 一次性设置

1. 新建 GitHub 空仓库,将本项目推上去(默认分支 `main`)
2. 仓库 **Settings → Pages → Build and deployment** → Source 选「Deploy from a branch」→ Branch 选 `main` + 目录 `/docs` → **Save**
3. 仓库 **Settings → Secrets and variables → Actions**,配置:
   - `GEMINI_API_KEY`(或 `OPENAI_API_KEY`)
   - 至少一个通知渠道(如 `WECHAT_WEBHOOK_URL` / `FEISHU_WEBHOOK_URL` / `TELEGRAM_BOT_TOKEN`+`TELEGRAM_CHAT_ID`)
   - 可选 `SELECTION_ENABLED=true` 开启选股
4. 启用 Actions,手动 **Run workflow** 一次触发首次生成

## 自动运行

- 周一~五 18:00(北京时间)自动跑并发布
- 访问地址:`https://<你的用户名>.github.io/<仓库名>/`

## 原理

Actions 分析后把报告复制到 `docs/archive/YYYY-MM-DD/`,运行 `scripts/build_site_index.py`
生成 `docs/index.json`,用 `GITHUB_TOKEN` 提交回 `main`,GitHub Pages 从 `/docs` 自动重建发布。

- 页面为纯静态只读:三 Tab(选股 / 大盘 / 仪表盘)+ 历史日期切换
- 密钥仅存于 Actions Secrets,站点不暴露任何凭据
