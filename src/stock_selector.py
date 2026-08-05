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
from typing import List, Dict, Optional

import pandas as pd

from data_provider.akshare_fetcher import AkshareFetcher

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


# 精筛硬性门
_MIN_HIST_ROWS = 60       # 排除新股
_BIAS_LIMIT = 5.0         # 乖离率上限(%)
_MIN_VOL_RATIO = 1.1      # 量能配合下限
_MA20_LOOKBACK = 6        # 对比 ma20.iloc[-1] 与 ma20.iloc[-6]


def evaluate_trend(df: pd.DataFrame) -> Optional[dict]:
    """
    精筛:对单只幸存者历史数据做趋势判定与打分。

    门槛(任一不达返回 None):
    - 历史行数 >= 60(排除新股)
    - MA5 > MA10 > MA20(多头排列)
    - 乖离率(close-ma5)/ma5*100 在 0% ~ 5%
    - 当日 volume_ratio >= 1.1(量能配合)
    - MA20 近 5 日抬升(ma20[-1] > ma20[-6])
    """
    if df is None or len(df) < _MIN_HIST_ROWS:
        return None
    for col in ('close', 'ma5', 'ma10', 'ma20', 'volume_ratio'):
        if col not in df.columns:
            return None

    last = df.iloc[-1]
    ma5, ma10, ma20 = last['ma5'], last['ma10'], last['ma20']
    if not (ma5 > ma10 > ma20):
        return None

    # MA20 近5日抬升
    if len(df) < _MA20_LOOKBACK or not (df['ma20'].iloc[-1] > df['ma20'].iloc[-_MA20_LOOKBACK]):
        return None

    close = float(last['close'])
    if ma5 <= 0:
        return None
    bias_ma5 = (close - float(ma5)) / float(ma5) * 100.0
    if not (0.0 <= bias_ma5 <= _BIAS_LIMIT):
        return None

    volume_ratio = float(last['volume_ratio'])
    if volume_ratio < _MIN_VOL_RATIO:
        return None

    # 趋势强度:间距较前一日扩大 -> 强势多头
    prev_spread = float(df['ma5'].iloc[-2] - df['ma20'].iloc[-2])
    cur_spread = float(ma5 - ma20)
    trend_level = '强势多头' if cur_spread > prev_spread else '多头排列'

    score = 0
    score += 3 if trend_level == '强势多头' else 2
    score += 2 if bias_ma5 < 2.0 else 1
    score += 2 if volume_ratio >= 2.0 else 1

    return {
        'trend_level': trend_level,
        'bias_ma5': bias_ma5,
        'volume_ratio': volume_ratio,
        'score': score,
    }


@dataclass
class SelectionResult:
    """单只达标股票的选股结果。"""
    code: str
    name: str
    price: float
    trend_level: str
    bias_ma5: float
    volume_ratio: float
    score: int


@dataclass
class SelectionOutcome:
    """一次选股编排的汇总结果。"""
    scanned: int = 0
    qualified: int = 0
    results: List[SelectionResult] = field(default_factory=list)


def run_selection(fetcher_manager, params: Optional[SelectionParams] = None) -> Optional[SelectionOutcome]:
    """
    执行两级漏斗选股。

    1. 粗筛:全 A 股快照 -> 候选池(~150)
    2. 精筛:逐只拉历史 K 线评估趋势,打分
    3. 排序取 Top N

    Args:
        fetcher_manager: 具备 get_daily_data() 的数据源管理器(DataFetcherManager)
        params: 选股参数,缺省用 Config

    Returns:
        SelectionOutcome;快照获取失败返回 None。
    """
    from src.config import get_config

    p = params or SelectionParams.from_config(get_config())

    snapshot = AkshareFetcher().get_all_a_share_snapshot()
    if snapshot is None:
        logger.error("[选股] 全A股快照获取失败,本次选股中止")
        return None

    candidates = coarse_filter(snapshot, p)
    logger.info(f"[选股] 粗筛完成: {len(snapshot)} 只快照 -> {len(candidates)} 只候选,开始精筛")

    results: List[SelectionResult] = []
    for cand in candidates:
        try:
            df_hist, _ = fetcher_manager.get_daily_data(cand['code'], days=90)
            ev = evaluate_trend(df_hist)
            if ev:
                results.append(SelectionResult(
                    code=cand['code'],
                    name=cand['name'],
                    price=float(cand['price']),
                    trend_level=ev['trend_level'],
                    bias_ma5=ev['bias_ma5'],
                    volume_ratio=ev['volume_ratio'],
                    score=ev['score'],
                ))
        except Exception as e:
            logger.warning(f"[选股] {cand['code']} 精筛失败,跳过: {e}")
            continue

    results.sort(key=lambda r: r.score, reverse=True)
    top = results[:p.top_n]

    logger.info(f"[选股] 精筛完成: {len(results)} 只达标,取 Top {len(top)}")
    return SelectionOutcome(scanned=len(snapshot), qualified=len(results), results=top)
