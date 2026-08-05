# GitHub Pages 静态选股报告站 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GitHub Actions 每日生成选股/大盘/仪表盘报告,经 `docs/archive` + `index.json` 推送到仓库,由 GitHub Pages 展示成静态报告站。

**Architecture:** 纯静态模式。Actions 分析完成后把 `reports/*.md` 复制到 `docs/archive/YYYY-MM-DD/`,`scripts/build_site_index.py` 扫描生成 `docs/index.json`,workflow 用 GITHUB_TOKEN commit+push 回 main,Pages 从 `/docs` 发布。页面用原生 HTML/CSS/JS + marked.js CDN 渲染,零后端、零密钥暴露。

**Tech Stack:** Python 3(stdlib 仅 json/pathlib)、HTML/CSS/JS、GitHub Actions(YAML)、marked.js(CDN)。

## Global Constraints

- 报告文件名(上游已确认,均为 `reports/` 目录,日期为 `YYYYMMDD` 无连字符):
  - `selection_YYYYMMDD.md`(选股)、`market_review_YYYYMMDD.md`(大盘)、`report_YYYYMMDD.md`(仪表盘)
- 归档目录命名:`docs/archive/YYYY-MM-DD/`(连字符),目录内统一三份:`selection.md` / `market_review.md` / `dashboard.md`
- `docs/index.json` 结构:`{"dates": [{"date", "selection", "market_review", "dashboard"}...], "latest": "YYYY-MM-DD"}`,日期倒序
- `build_site_index.py` 仅用标准库;支持 CLI 可选参数 `[archive_dir] [output_file]`,缺省为仓库 `docs/archive` → `docs/index.json`
- 静态站点只读,无后端/无认证;md 由应用生成,无用户输入
- 工作流发布步骤仅在 schedule / workflow_dispatch 触发时运行(`if: always()` 保证分析部分失败仍发布已有报告)
- 本环境沙箱无法连通 GitHub,完整 Actions+Pages 链路由用户按其一次性设置步骤验证

---

### Task 1: `scripts/build_site_index.py` + 单元测试

**Files:**
- Create: `scripts/__init__.py`(空)
- Create: `scripts/build_site_index.py`
- Test: `tests/test_build_site_index.py`

**Interfaces:**
- Produces:
  - `find_report_dates(archive_dir: Path) -> List[dict]`(倒序,每项含 `date` + 三个布尔标志)
  - `build_index(archive_dir: Path) -> dict`(`{"dates": [...], "latest": str}`)
  - CLI:`python scripts/build_site_index.py [archive_dir] [output_file]`

- [ ] **Step 1: 写失败测试**

Create `tests/test_build_site_index.py`:

```python
# -*- coding: utf-8 -*-
from scripts.build_site_index import build_index, find_report_dates


def _make_archive(tmp_path):
    d1 = tmp_path / '2026-08-05'
    d1.mkdir()
    (d1 / 'selection.md').write_text('sel', encoding='utf-8')
    (d1 / 'market_review.md').write_text('mr', encoding='utf-8')
    # d1 无 dashboard
    d2 = tmp_path / '2026-08-04'
    d2.mkdir()
    (d2 / 'selection.md').write_text('sel', encoding='utf-8')
    (d2 / 'dashboard.md').write_text('dash', encoding='utf-8')
    (tmp_path / 'not-a-date').mkdir()  # 非日期目录应跳过
    return tmp_path


def test_build_index_dates_desc_and_flags(tmp_path):
    idx = build_index(_make_archive(tmp_path))
    assert [d['date'] for d in idx['dates']] == ['2026-08-05', '2026-08-04']
    assert idx['latest'] == '2026-08-05'
    assert idx['dates'][0]['selection'] is True
    assert idx['dates'][0]['market_review'] is True
    assert idx['dates'][0]['dashboard'] is False
    assert idx['dates'][1]['dashboard'] is True


def test_find_report_dates_skips_non_date_dirs(tmp_path):
    dates = find_report_dates(_make_archive(tmp_path))
    assert all(d['date'] != 'not-a-date' for d in dates)


def test_build_index_empty(tmp_path):
    assert build_index(tmp_path) == {'dates': [], 'latest': ''}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_build_site_index.py -v`
Expected: FAIL(`ModuleNotFoundError: No module named 'scripts.build_site_index'`)

- [ ] **Step 3: 实现 `scripts/build_site_index.py`**

Create `scripts/__init__.py`(空文件)与 `scripts/build_site_index.py`:

```python
# -*- coding: utf-8 -*-
"""
===================================
报告站点索引生成器
===================================

扫描 docs/archive/YYYY-MM-DD/ 下的报告 md,生成 docs/index.json
供 GitHub Pages 静态站点读取。仅用标准库。

CLI:
    python scripts/build_site_index.py [archive_dir] [output_file]
    缺省: 仓库根/docs/archive -> 仓库根/docs/index.json
"""

import json
import sys
from pathlib import Path
from typing import List, Dict

REPORTS = ['selection', 'market_review', 'dashboard']
EXT = '.md'


def _is_date_dir(name: str) -> bool:
    parts = name.split('-')
    return len(parts) == 3 and all(p.isdigit() for p in parts)


def find_report_dates(archive_dir: Path) -> List[dict]:
    """扫描 archive 下日期目录,返回倒序 [{date, selection, market_review, dashboard}]。"""
    entries = []
    for child in sorted(archive_dir.iterdir(), reverse=True):
        if not child.is_dir() or not _is_date_dir(child.name):
            continue
        flags = {rep: (child / f'{rep}{EXT}').is_file() for rep in REPORTS}
        entries.append({'date': child.name, **flags})
    return entries


def build_index(archive_dir: Path) -> dict:
    """构建 index.json 内容。"""
    dates = find_report_dates(archive_dir)
    latest = dates[0]['date'] if dates else ''
    return {'dates': dates, 'latest': latest}


def main(argv: List[str]) -> int:
    root = Path(__file__).resolve().parent.parent
    archive_dir = Path(argv[0]) if len(argv) > 0 else root / 'docs' / 'archive'
    out_file = Path(argv[1]) if len(argv) > 1 else root / 'docs' / 'index.json'

    index = build_index(archive_dir)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'index.json 已生成: {len(index["dates"])} 天, latest={index["latest"] or "无"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_build_site_index.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交推送**

```bash
git add scripts/__init__.py scripts/build_site_index.py tests/test_build_site_index.py
git commit -m "feat(site): 报告站点索引生成器 build_site_index

扫描 docs/archive/YYYY-MM-DD -> docs/index.json(dates 倒序 + latest)
仅标准库,CLI 支持可选参数;3 个单元测试全绿"
git push origin main
```

---

### Task 2: 静态报告站点页面

**Files:**
- Create: `docs/index.html`
- Create: `docs/style.css`
- Create: `docs/app.js`

**Interfaces:**
- Consumes: `docs/index.json`(Task 1 产出)与 `docs/archive/YYYY-MM-DD/{selection,market_review,dashboard}.md`
- Produces: 单页报告查看器(index.html/style.css/app.js)

- [ ] **Step 1: 写 `docs/index.html`**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>股票分析报告站</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<header>
  <h1>📈 股票分析报告站</h1>
  <div class="controls">
    <label for="dateSelect">日期</label>
    <select id="dateSelect" aria-label="选择报告日期"></select>
  </div>
</header>
<main>
  <nav class="tabs" id="tabs">
    <button class="tab active" data-tab="selection">选股报告</button>
    <button class="tab" data-tab="market_review">大盘复盘</button>
    <button class="tab" data-tab="dashboard">自选股仪表盘</button>
  </nav>
  <div id="content" class="report"><p class="placeholder">加载中…</p></div>
</main>
<footer>仅供学习参考,不构成投资建议 · 由 GitHub Actions 自动生成</footer>
<script src="https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"></script>
<script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: 写 `docs/style.css`**

```css
:root {
  --bg: #f5f6fa; --card: #ffffff; --text: #1f2328; --muted: #6b7280;
  --accent: #2f6fed; --border: #e5e7eb;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1117; --card: #161b22; --text: #e6edf3; --muted: #8b949e;
    --accent: #58a6ff; --border: #30363d;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
  line-height: 1.6;
}
header {
  background: var(--card); border-bottom: 1px solid var(--border);
  padding: 16px 20px; display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 12px; position: sticky; top: 0;
}
header h1 { margin: 0; font-size: 1.25rem; }
.controls { display: flex; align-items: center; gap: 8px; color: var(--muted); }
select {
  padding: 6px 10px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--card); color: var(--text); font-size: 0.95rem;
}
main { max-width: 860px; margin: 0 auto; padding: 20px; }
.tabs { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
.tab {
  padding: 8px 16px; border-radius: 999px; border: 1px solid var(--border);
  background: var(--card); color: var(--text); cursor: pointer; font-size: 0.95rem;
}
.tab.active { background: var(--accent); color: #fff; border-color: var(--accent); }
.report {
  background: var(--card); border: 1px solid var(--border); border-radius: 12px;
  padding: 20px 24px;
}
.report h1, .report h2, .report h3 { border-bottom: 1px solid var(--border); padding-bottom: 6px; }
.report code { background: var(--bg); padding: 2px 6px; border-radius: 4px; }
.report pre { background: var(--bg); padding: 12px; border-radius: 8px; overflow-x: auto; }
.placeholder { color: var(--muted); text-align: center; padding: 40px 0; }
footer {
  max-width: 860px; margin: 24px auto; text-align: center;
  color: var(--muted); font-size: 0.85rem; padding: 0 20px;
}
```

- [ ] **Step 3: 写 `docs/app.js`**

```js
const TABS = ['selection', 'market_review', 'dashboard'];
const LABELS = { selection: '选股报告', market_review: '大盘复盘', dashboard: '自选股仪表盘' };

const state = { date: '', activeTab: 'selection' };

async function fetchJson(url) {
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error('加载失败: ' + url);
  return res.json();
}

function showContent(html) {
  document.getElementById('content').innerHTML = html;
}

function renderDateOptions(index) {
  const sel = document.getElementById('dateSelect');
  sel.innerHTML = '';
  for (const d of index.dates) {
    const opt = document.createElement('option');
    opt.value = d.date;
    opt.textContent = d.date + (d.date === index.latest ? '（最新）' : '');
    sel.appendChild(opt);
  }
  sel.value = state.date;
}

async function loadReport() {
  showContent('<p class="placeholder">加载中…</p>');
  const url = 'archive/' + state.date + '/' + state.activeTab + '.md';
  try {
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error('no report');
    const md = await res.text();
    const html = window.marked
      ? window.marked.parse(md)
      : '<pre>' + md.replace(/</g, '&lt;') + '</pre>';
    showContent(html);
  } catch (e) {
    showContent('<p class="placeholder">📭 ' + state.date + ' 无' + LABELS[state.activeTab] + '报告</p>');
  }
}

async function init() {
  let index;
  try {
    index = await fetchJson('index.json');
  } catch (e) {
    showContent('<p class="placeholder">站点数据未就绪,请等待首次 Actions 运行生成报告</p>');
    return;
  }
  if (!index.dates || index.dates.length === 0) {
    showContent('<p class="placeholder">暂无报告,请等待首次 Actions 运行</p>');
    return;
  }
  state.date = index.latest;
  renderDateOptions(index);

  document.getElementById('tabs').addEventListener('click', (e) => {
    const btn = e.target.closest('.tab');
    if (!btn) return;
    state.activeTab = btn.dataset.tab;
    document.querySelectorAll('.tab').forEach(b =>
      b.classList.toggle('active', b.dataset.tab === state.activeTab));
    loadReport();
  });

  document.getElementById('dateSelect').addEventListener('change', (e) => {
    state.date = e.target.value;
    loadReport();
  });

  loadReport();
}

init();
```

- [ ] **Step 4: 验证静态文件**

Run: `python -m py_compile docs/index.html` 不适用(HTML);改为:
Run: `node --check docs/app.js`(若 node 存在;否则手动核对语法)
Run: `python -c "print(open('docs/index.html',encoding='utf-8').read().count('marked.min.js'))"` 期望输出 `1`
Expected: app.js 语法正确;marked.min.js 引用存在

- [ ] **Step 5: 提交推送**

```bash
git add docs/index.html docs/style.css docs/app.js
git commit -m "feat(site): 报告站点页面 index.html/style.css/app.js

三 Tab(选股/大盘/仪表盘)+ 历史日期切换,marked.js 渲染 md
只读展示,深色适配,mobile-friendly"
git push origin main
```

---

### Task 3: `daily_analysis.yml` 增加发布步骤

**Files:**
- Modify: `.github/workflows/daily_analysis.yml`(加 `permissions` + 分析后新增步骤)

**Interfaces:**
- Consumes: Task 1 的 `scripts/build_site_index.py`;分析阶段生成的 `reports/*.md`
- Produces: 推送回 main 的 `docs/archive/YYYY-MM-DD/*.md` + `docs/index.json`(触发 Pages 重新发布)

- [ ] **Step 1: 为 analyze job 增加 `permissions`**

在 `.github/workflows/daily_analysis.yml` 的 `jobs.analyze` 下(`runs-on` 之前)插入:

```yaml
    permissions:
      contents: write   # 允许推送 docs/ 报告回仓库,触发 Pages 重建
```

- [ ] **Step 2: 在「执行股票分析」步骤之后插入发布步骤**

在 `执行股票分析` 步骤的 `run:` 块之后、`上传分析报告` 步骤之前插入:

```yaml
      - name: 生成并发布报告站点
        if: always()
        env:
          TODAY: ${{ github.event.repository.updated_at }}
        run: |
          set -e
          D=$(date +%Y%m%d)          # 20260805,对应报告文件名
          TD=$(date +%F)             # 2026-08-05,对应归档目录
          mkdir -p "docs/archive/$TD"
          cp -f "reports/selection_${D}.md"     "docs/archive/$TD/selection.md" 2>/dev/null || true
          cp -f "reports/market_review_${D}.md" "docs/archive/$TD/market_review.md" 2>/dev/null || true
          cp -f "reports/report_${D}.md"        "docs/archive/$TD/dashboard.md" 2>/dev/null || true
          python scripts/build_site_index.py
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add docs/
          git diff --cached --quiet || git commit -m "docs: 更新报告站点 $(date -u '+%Y-%m-%d %H:%M UTC')"
          git push origin main
```

> 说明:`TD` 是 `date +%F`(如 2026-08-05),报告源文件名用 `D=date +%Y%m%d`(如 20260805),避免连字符不匹配。`|| true` 让缺失报告不失败;`git diff --cached --quiet` 避免空提交;push 回 main 触发 Pages 发布,该 workflow 只被 schedule/workflow_dispatch 触发,不会自触发死循环。

- [ ] **Step 3: 校验 YAML 与脚本引用**

Run: `python -c "import yaml; d=yaml.safe_load(open('.github/workflows/daily_analysis.yml',encoding='utf-8')); print('steps:', len(d['jobs']['analyze']['steps']), '| perms:', d['jobs']['analyze'].get('permissions'))"`
Expected: steps 数量比之前多 1;perms 含 `contents: write`
Run: `python scripts/build_site_index.py`(无 archive 时也能安全退出)
Expected: 输出 `index.json 已生成: 0 天, latest=无` 且生成 `docs/index.json`

- [ ] **Step 4: 提交推送**

```bash
git add .github/workflows/daily_analysis.yml
git commit -m "ci: daily_analysis 增加报告站点发布步骤

分析后复制 reports/*.md 到 docs/archive,生成 index.json,
GITHUB_TOKEN 提交回 main 触发 Pages 重建;contents: write 权限"
git push origin main
```

---

### Task 4: 本地冒烟验证 + 部署文档 + 收尾

**Files:**
- Create: `docs/REPORT_SITE.md`(用户一次性设置步骤)
- Test: 复用 Task 1 测试 + 本地 HTTP 冒烟

**Interfaces:**
- Consumes: 全部前期产物
- Produces: 可交付的站点 + 部署文档

- [ ] **Step 1: 本地冒烟(构造样例 archive + HTTP 服务检查)**

```bash
# 构造临时样例(不入库)
python - <<'PY'
from pathlib import Path
import sys
root = Path('.').resolve()
a = root/'docs'/'archive'
(d for d in [a]) # no-op
PY
mkdir -p docs/archive/2026-08-05
printf '# 测试选股\n- 600519 强势多头\n' > docs/archive/2026-08-05/selection.md
printf '# 测试大盘\n上涨 3000 家\n' > docs/archive/2026-08-05/market_review.md
python scripts/build_site_index.py
```

Run: `python -m pytest tests/test_build_site_index.py -q`(期望 3 passed)
Run: 起本地服务并检查 `python -m http.server 8000 -d docs &` 后:
  - `curl -s http://127.0.0.1:8000/index.json` 应含 `2026-08-05`
  - `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/` 应为 `200`
  - `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/archive/2026-08-05/selection.md` 应为 `200`
  - 停掉服务,清理样例:`rm -rf docs/archive docs/index.json`

> 说明:样例 archive 仅本地验证用,不入库;`docs/archive/` 正式内容由 Actions 每日生成。

- [ ] **Step 2: 写部署文档 `docs/REPORT_SITE.md`**

```markdown
# GitHub Pages 报告站点部署

每日选股/大盘/仪表盘报告自动发布到 GitHub Pages 静态站点,零成本、零服务器。

## 一次性设置
1. 新建 GitHub 空仓库,将本项目推上去(本仓库默认分支 main)
2. 仓库 Settings → Pages → Build and deployment → Source 选「Deploy from a branch」
   → Branch 选 `main` + 目录 `/docs` → Save
3. 仓库 Settings → Secrets and variables → Actions,配置:
   - `GEMINI_API_KEY`(或 `OPENAI_API_KEY`)
   - 至少一个通知渠道(如 `WECHAT_WEBHOOK_URL` / `FEISHU_WEBHOOK_URL` / `TELEGRAM_BOT_TOKEN`+`TELEGRAM_CHAT_ID`)
   - 可选 `SELECTION_ENABLED=true` 开启选股
4. 启用 Actions,手动 Run workflow 一次触发首次生成

## 自动运行
- 周一~五 18:00(北京时间)自动跑并发布
- 访问地址:`https://<你的用户名>.github.io/<仓库名>/`

## 原理
Actions 分析后复制报告到 `docs/archive/YYYY-MM-DD/`,生成 `docs/index.json`,
提交回 main,GitHub Pages 从 /docs 自动重建发布。页面只读,密钥仅存于 Secrets。
```

- [ ] **Step 3: 全量回归 + 提交推送**

Run: `python -m pytest tests/ -q`(期望 15 + 3 = 18 passed)
```bash
git add docs/REPORT_SITE.md
git commit -m "docs: GitHub Pages 报告站点部署说明"
git push origin main
```

- [ ] **Step 4: 最终核对**

Run: `git status --porcelain --branch`(期望干净,与 origin/main 同步)
Run: `git log --oneline -4`

---

## Self-Review

- **规范覆盖**:架构/数据流 → Task 3;`build_site_index` → Task 1;静态页面 → Task 2;部署文档与验证 → Task 4。全部覆盖。
- **文件名一致性**:报告源 `selection/market_review/report_YYYYMMDD.md` ↔ 归档 `selection/market_review/dashboard.md`,索引标志字段 `selection/market_review/dashboard` 三处一一对应(已在 Task 3 用 `D=date +%Y%m%d`/`TD=date +%F` 消除连字符差异)。
- **类型/签名一致**:`build_index(archive_dir: Path) -> dict` 在 Task 1 定义、Task 3 CLI 调用、Task 1 测试使用,签名一致。
- **占位符**:无 TODO/TBD;每步含完整代码或命令。
- **安全**:站点仅 md 产物;workflow 权限仅 `contents: write`;无认证面、无密钥入仓(`docs/` 无 .env)。