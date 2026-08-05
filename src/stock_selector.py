# -*- coding: utf-8 -*-
"""
===================================
A股趋势突破选股模块
===================================

两级漏斗:
1. 粗筛:全市场快照(东财)按快照字段过滤到少量候选
2. 精筛:对候选逐只拉历史K线,算真实 MA5/10/20 多头排列+乖离率+量能,打分取 Top N

纯量化,不调用 LLM。只读数据、只输出报告,不并入自选股分析管线。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class SelectionParams:
    """选股粗筛阈值与输出数量。测试可直接构造,生产用 from_config。"""
    price_min: float = 3.0
    price_max: float = 50.0
    turnover_min: float = 1.0
    turnover_max: float = 15.0
    volume_ratio_min: float = 1.0
    volume_ratio_max: float = 8.0
    mv_min: float = 50e8
    mv_max: float = 2000e8
    change_pct_min: float = -5.0
    change_pct_max: float = 8.0
    top_n: int = 7

    @classmethod
    def from_config(cls, config) -> "SelectionParams":
        return cls(
            price_min=config.selection_price_min,
            price_max=config.selection_price_max,
            turnover_min=config.selection_turnover_min,
            turnover_max=config.selection_turnover_max,
            volume_ratio_min=config.selection_volume_ratio_min,
            volume_ratio_max=config.selection_volume_ratio_max,
            mv_min=config.selection_mv_min,
            mv_max=config.selection_mv_max,
            change_pct_min=config.selection_change_pct_min,
            change_pct_max=config.selection_change_pct_max,
            top_n=config.selection_top_n,
        )


# 沪深主板代码前缀
_MAIN_BOARD_PREFIXES = ('600', '601', '603', '605', '000', '001', '002', '003')


def is_main_board_code(stock_code: str) -> bool:
    """判断 6 位代码是否为沪深主板(排除创业板300/301、科创688、北交所4xx/8xx)。"""
    return stock_code.startswith(_MAIN_BOARD_PREFIXES)


def _is_st_or_delisting(name: str) -> bool:
    up = (name or '').upper()
    return 'ST' in up or '退' in up


def _to_float(val) -> Optional[float]:
    try:
        f = float(val)
        return f if pd.notna(f) else None
    except (TypeError, ValueError):
        return None


def coarse_filter(df: pd.DataFrame, params: SelectionParams) -> List[dict]:
    """
    粗筛:按快照字段过滤全市场,返回候选列表。

    快照列(东财 stock_zh_a_spot_em):代码/名称/最新价/涨跌幅/换手率/量比/总市值
    任一必需列缺失则跳过该行;整表缺关键列则返回空。
    """
    required = {'代码', '名称', '最新价', '涨跌幅', '换手率', '量比', '总市值'}
    if df is None or df.empty or not required.issubset(df.columns):
        return []

    out: List[dict] = []
    for _, row in df.iterrows():
        code = str(row.get('代码', '')).strip()
        name = str(row.get('名称', '')).strip()
        price = _to_float(row.get('最新价'))
        change_pct = _to_float(row.get('涨跌幅'))
        turnover = _to_float(row.get('换手率'))
        volume_ratio = _to_float(row.get('量比'))
        total_mv = _to_float(row.get('总市值'))

        if not code or not is_main_board_code(code):
            continue
        if _is_st_or_delisting(name):
            continue
        if price is None or price <= 0:            # 停牌
            continue
        if not (params.change_pct_min <= change_pct <= params.change_pct_max):
            continue
        if not (params.turnover_min <= turnover <= params.turnover_max):
            continue
        if not (params.volume_ratio_min <= volume_ratio <= params.volume_ratio_max):
            continue
        if not (params.mv_min <= total_mv <= params.mv_max):
            continue
        if not (params.price_min <= price <= params.price_max):
            continue

        out.append({
            'code': code,
            'name': name,
            'price': price,
            'change_pct': change_pct,
            'turnover_rate': turnover,
            'volume_ratio': volume_ratio,
            'total_mv': total_mv,
        })
    return out
