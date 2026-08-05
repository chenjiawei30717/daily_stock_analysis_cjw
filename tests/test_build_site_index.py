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
