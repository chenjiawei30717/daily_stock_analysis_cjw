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
from typing import List

REPORTS = ['selection', 'market_review', 'dashboard']
EXT = '.md'


def _is_date_dir(name: str) -> bool:
    parts = name.split('-')
    return len(parts) == 3 and all(p.isdigit() for p in parts)


def find_report_dates(archive_dir: Path) -> List[dict]:
    """扫描 archive 下日期目录,返回倒序 [{date, selection, market_review, dashboard}]。"""
    if not archive_dir.exists():
        return []
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
