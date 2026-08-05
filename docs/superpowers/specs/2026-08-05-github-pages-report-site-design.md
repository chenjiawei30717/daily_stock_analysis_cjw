# GitHub Pages 静态选股报告站 — 设计文档

日期:2026-08-05
状态:已确认(用户批准)

## 1. 背景与目标

已有选股模块(每日生成选股报告)与大盘复盘/自选股仪表盘,均通过通知渠道推送。用户希望用 GitHub Pages(`*.github.io`)公网查看报告。

**关键约束**:GitHub Pages 只能托管静态文件,不能运行 Python/调用 akshare/Gemini。因此采用「静态报告站点」模式:GitHub Actions 每日定时跑分析 → 生成报告 → commit 到仓库 → Pages 发布展示。

### 已确认的决策
| 决策点 | 选择 |
|---|---|
| 展示内容 | 选股报告 + 大盘复盘 + 自选股仪表盘 + 历史归档(四者都要) |
| 部署方式 | GitHub Pages,从 `main` 分支的 `/docs` 目录发布 |
| 触发 | GitHub Actions `daily_analysis.yml` 每日定时(周一~五 18:00 北京)+ 手动 workflow_dispatch |
| 页面交互 | 只读展示;历史按日期翻看;不提供网页内触发分析 |
| 安全 | 只发布已生成 md,不暴露任何密钥/API Key;无认证面、无公网端口 |

## 2. 架构与数据流

```
GitHub Actions 每日 18:00(daily_analysis.yml)
   → python main.py 生成三类报告到 reports/
       reports/selection_YYYYMMDD.md        (选股报告)
       reports/market_review_YYYYMMDD.md    (大盘复盘)
       reports/report_YYYYMMDD.md           (自选股仪表盘)
   → 新步骤:复制 reports/*.md → docs/archive/YYYY-MM-DD/
   → 运行 scripts/build_site_index.py 生成 docs/index.json
   → 用 GITHUB_TOKEN commit + push 回 main
   → GitHub Pages(设置:main 分支 /docs 目录)自动发布
```

静态资源(一次性提交):`docs/index.html` + `docs/style.css` + `docs/app.js`。
页面只读已生成报告;API Key 永远留在 Actions Secrets 中。

## 3. 报告文件命名约定(上游已确认)

| 报告 | 文件名 | 生成处 |
|---|---|---|
| 选股报告 | `selection_YYYYMMDD.md` | `main.py` run_full_analysis 选股块 |
| 大盘复盘 | `market_review_YYYYMMDD.md` | `market_review.py` |
| 自选股仪表盘 | `report_YYYYMMDD.md` | `notification.py save_report_to_file` 默认名 |

均落盘到项目根 `reports/` 目录。

## 4. 新增/修改文件

### 4.1 `scripts/build_site_index.py`(新增)
扫描 `docs/archive/` 下所有 `YYYY-MM-DD` 目录,生成 `docs/index.json`:
```json
{
  "dates": [
    {"date": "2026-08-05", "selection": true, "market_review": true, "dashboard": true},
    ...
  ],
  "latest": "2026-08-05"
}
```
- 日期倒序;`latest` 为最新有任一报告的日期
- 目录内存在对应 md 则对应布尔为 true
- 纯标准库,无第三方依赖;CLI 可独立运行

### 4.2 `docs/index.html` + `docs/style.css` + `docs/app.js`(新增)
单页报告查看器(纯 HTML/CSS/JS,无构建工具):
- `index.html`:三 Tab 布局(今日选股 / 今日大盘 / 今日仪表盘)+ 历史日期下拉;CDN 加载 marked.js 渲染 md
- `app.js`:`fetch('index.json')` 取日期列表;默认显示 `latest` 三份报告;切换日期重新加载三份 md
- 历史归档:日期下拉 → 回看当天三份报告
- 无后端、无密钥;异常时显示「今日无此报告」占位

### 4.3 `.github/workflows/daily_analysis.yml`(修改)
分析步骤之后新增「生成并发布报告站点」步骤:
```yaml
permissions:
  contents: write
```
步骤逻辑:
1. `mkdir -p docs/archive/$(date +%F)`
2. 复制三个 `reports/*.md` → `docs/archive/$(date +%F)/` 对应命名(缺失则跳过,`|| true`)
3. `python scripts/build_site_index.py`
4. `git config user.name/user.email` + `git add docs/` + commit + push(用 `GITHUB_TOKEN`,Push 到 main 触发 Pages 重新发布)
- 仅在 `github.event_name == 'schedule' || 'workflow_dispatch'` 时执行(避免非分析触发污染)

## 5. 页面交互与展示

- 顶部:站点标题 + 当前日期(默认最新)
- Tab 切换:选股 / 大盘 / 仪表盘
- 历史:日期下拉选择,切换后三 Tab 显示所选日期内容
- 无数据日期:各 Tab 显示占位提示
- 样式:移动端友好,深色主题可选(简单自适应)

## 6. 安全与边界

- 只发布已生成 md;不发布 `.env`、日志、reports/ 原始目录
- Actions 仅需 `contents: write`(写自己仓库),无需其他权限
- 报告为只读产物,无用户输入/无认证面,无注入风险(md 由应用生成,非用户提交)
- 若某报告当日生成失败:index.json 对应布尔为 false,页面显示占位

## 7. 验证与部署

### 7.1 本地验证
- `build_site_index.py` 单测(构造 archive 目录,断言 index.json 内容)
- 本地 `python -m http.server 8000 -d docs` 起站,浏览器目测三 Tab + 历史切换
- 沙箱限制说明:本环境无法连通 GitHub,完整 Actions+Pages 链路需用户在 GitHub 建库后验证(一次性设置步骤见 spec 附录)

### 7.2 用户一次性设置步骤(交付时提供)
1. 新建 GitHub 空仓库,推送本仓库代码(参考 #2 指引)
2. 仓库 Settings → Pages → Build and deployment → Source: Deploy from a branch → main + /docs
3. Settings → Secrets and variables → Actions:配置 GEMINI_API_KEY、通知渠道、`SELECTION_ENABLED=true`
4. 启用 Actions,首次手动 Run 一次触发,验证报告生成与 Pages 更新

## 8. 明确不做(YAGNI)
- 不在网页内提供"触发分析"按钮(依赖 Actions 定时/workflow_dispatch)
- 不做登录/鉴权(站点为只读报告,无需)
- 不做多仓库/独立 gh-pages 分支(统一用 main /docs)
- 不做移动端 App
