# -*- coding: utf-8 -*-
"""选股模块单元测试。纯函数测试不联网,编排测试用 mock。"""

import pandas as pd
from src.stock_selector import SelectionParams, is_main_board_code, coarse_filter


def _snapshot_rows():
    return [
        {'代码': '600519', '名称': '贵州茅台', '最新价': 45.0, '涨跌幅': 1.2, '换手率': 3.0, '量比': 1.5, '总市值': 2000e8},     # 通过
        {'代码': '300750', '名称': '宁德时代', '最新价': 200.0, '涨跌幅': 2.0, '换手率': 5.0, '量比': 2.0, '总市值': 8000e8},    # 创业板:排除
        {'代码': '688981', '名称': '中芯国际', '最新价': 60.0, '涨跌幅': 1.0, '换手率': 4.0, '量比': 1.2, '总市值': 3000e8},    # 科创:排除
        {'代码': '002415', '名称': '海康威视', '最新价': 30.0, '涨跌幅': 0.5, '换手率': 2.0, '量比': 1.1, '总市值': 1000e8},    # 深主板002:通过
        {'代码': '600001', '名称': '*ST测试', '最新价': 5.0, '涨跌幅': 1.0, '换手率': 3.0, '量比': 1.2, '总市值': 100e8},        # ST:排除
        {'代码': '000002', '名称': '万科A', '最新价': 9.9, '涨跌幅': 10.0, '换手率': 4.0, '量比': 1.5, '总市值': 500e8},        # 涨停:排除
        {'代码': '000004', '名称': '国农科技', '最新价': 0.0, '涨跌幅': -1.0, '换手率': 2.0, '量比': 1.1, '总市值': 100e8},      # 停牌(价<=0):排除
        {'代码': '601818', '名称': '光大银行', '最新价': 2.5, '涨跌幅': 0.3, '换手率': 2.0, '量比': 1.1, '总市值': 400e8},       # 现价<3:排除
        {'代码': '603686', '名称': '龙马环卫', '最新价': 8.0, '涨跌幅': 0.5, '换手率': 20.0, '量比': 1.1, '总市值': 200e8},      # 换手>15:排除
        {'代码': '605099', '名称': '共创草坪', '最新价': 10.0, '涨跌幅': 0.5, '换手率': 3.0, '量比': 9.0, '总市值': 100e8},      # 量比>8:排除
        {'代码': '601857', '名称': '中国石油', '最新价': 8.0, '涨跌幅': 0.2, '换手率': 1.0, '量比': 1.1, '总市值': 15000e8},     # 市值>2000亿:排除
        {'代码': '000030', '名称': '富奥股份', '最新价': 20.0, '涨跌幅': -7.0, '换手率': 3.0, '量比': 1.2, '总市值': 300e8},     # 跌<-5:排除
    ]


# ---------- 粗筛 ----------

def test_coarse_filter_main_board_and_thresholds():
    df = pd.DataFrame(_snapshot_rows())
    out = coarse_filter(df, SelectionParams())
    codes = [c['code'] for c in out]
    assert codes == ['600519', '002415']


def test_coarse_filter_keeps_expected_fields():
    df = pd.DataFrame(_snapshot_rows()[:1])
    out = coarse_filter(df, SelectionParams())
    assert out and out[0]['code'] == '600519'
    assert out[0]['name'] == '贵州茅台'
    assert out[0]['price'] == 45.0
    assert out[0]['volume_ratio'] == 1.5


def test_is_main_board_code():
    assert is_main_board_code('600519')
    assert is_main_board_code('601818')
    assert is_main_board_code('603686')
    assert is_main_board_code('000001')
    assert is_main_board_code('002415')
    assert not is_main_board_code('300750')
    assert not is_main_board_code('301012')
    assert not is_main_board_code('688981')
    assert not is_main_board_code('830799')
    assert not is_main_board_code('430047')


def test_coarse_filter_empty_pool():
    df = pd.DataFrame([row for row in _snapshot_rows() if row['代码'] == '688981'])
    assert coarse_filter(df, SelectionParams()) == []


def test_coarse_filter_missing_columns():
    df = pd.DataFrame({'代码': ['600519']})
    assert coarse_filter(df, SelectionParams()) == []
