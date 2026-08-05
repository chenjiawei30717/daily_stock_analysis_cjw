# A股趋势突破选股模块 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每日从全 A 股(仅沪深主板)自动筛出趋势突破型股票,输出独立量化选股报告,不并入现有自选股分析管线。

**Architecture:** 两级漏斗。粗筛一次调用 `stock_zh_a_spot_em()` 全市场快照,用快照字段(涨跌幅/换手率/量比/市值/现价/代码)过滤到 ~150 只;精筛仅对幸存者逐只拉历史 K 线(经 `DataFetcherManager` 故障切换),算真实 MA5/10/20 多头排列+乖离率+量能,打分取 Top N。纯量化,不调用 LLM。报告经现有多渠道推送。

**Tech Stack:** Python 3.10+, pandas, akshare, 复用现有 `AkshareFetcher`/`DataFetcherManager`/`NotificationService`/`Config`。

## Global Constraints

- 项目非 git 仓库 → 计划中所有「Commit」步骤替换为「Verify」(运行测试/语法检查确认)。
- 仅 A 股;仅沪深主板:沪 `600/601/603/605`,深 `000/001/002/003`;排除创业板 `300/301`、科创 `688`、北交所 `4xx/8xx`。
- 精筛硬性门:历史行数 ≥ 60、`MA5>MA10>MA20`、乖离率 `0%~5%`、当日量比 ≥ 1.1、MA20 近 5 日抬升。
- 打分(仅对通过精筛者):趋势「强势多头(间距扩大)+3 / 多头排列+2」+ 乖离率`<2% +2 / 2~5% +1` + 量比`1.1~2 +1 / ≥2 +2`。**注:精筛已强制多头排列,故无「弱多头」档,打分不设 +1 档趋势分**(修复规范中 3.2/3.3 的不一致)。
- 默认阈值:现价 3~50、换手率 1~15%、量比 1~8、总市值 50亿~2000亿、涨跌幅 -5%~8%、`SELECTION_TOP_N=7`。粗筛阈值全部 `.env` 可配;精筛规则与打分权重硬编码。
- 不调用任何 LLM/搜索服务;失败不阻断当天其余任务。

---

### Task 1: 选股配置项

**Files:**
- Modify: `src/config.py:29-39`(dataclass 字段区)、`src/config.py:225-402`(`_load_from_env`)

**Interfaces:**
- Produces: `Config.selection_enabled: bool`、`Config.selection_top_n: int`、`Config.selection_price_min/max: float`、`Config.selection_turnover_min/max: float`、`Config.selection_volume_ratio_min/max: float`、`Config.selection_mv_min/max: float`、`Config.selection_change_pct_min/max: float`

- [ ] **Step 1: 在 dataclass 字段区添加配置属性**

在 `src/config.py` 的「=== 系统配置 ===」块之后新增「=== 选股配置 ===」块(约第 135 行附近):

```python
    # === 选股配置 ===
    selection_enabled: bool = False            # 是否启用每日选股报告
    selection_top_n: int = 7                    # 选股报告取 Top N
    # 粗筛阈值
    selection_price_min: float = 3.0            # 现价下限（元）
    selection_price_max: float = 50.0           # 现价上限（元）
    selection_turnover_min: float = 1.0         # 换手率下限（%）
    selection_turnover_max: float = 15.0        # 换手率上限（%）
    selection_volume_ratio_min: float = 1.0     # 量比下限
    selection_volume_ratio_max: float = 8.0     # 量比上限
    selection_mv_min: float = 50e8              # 总市值下限（元）
    selection_mv_max: float = 2000e8            # 总市值上限（元）
    selection_change_pct_min: float = -5.0      # 涨跌幅下限（%）
    selection_change_pct_max: float = 8.0       # 涨跌幅上限（%）
```

- [ ] **Step 2: 在 `_load_from_env` 中加载**

在 `Config._load_from_env` 的 `return cls(...)` 中添加(放在 `circuit_breaker_cooldown` 之后、闭合括号之前):

```python
            selection_enabled=os.getenv('SELECTION_ENABLED', 'false').lower() == 'true',
            selection_top_n=int(os.getenv('SELECTION_TOP_N', '7')),
            selection_price_min=float(os.getenv('SELECTION_PRICE_MIN', '3')),
            selection_price_max=float(os.getenv('SELECTION_PRICE_MAX', '50')),
            selection_turnover_min=float(os.getenv('SELECTION_TURNOVER_MIN', '1')),
            selection_turnover_max=float(os.getenv('SELECTION_TURNOVER_MAX', '15')),
            selection_volume_ratio_min=float(os.getenv('SELECTION_VOLUME_RATIO_MIN', '1')),
            selection_volume_ratio_max=float(os.getenv('SELECTION_VOLUME_RATIO_MAX', '8')),
            selection_mv_min=float(os.getenv('SELECTION_MV_MIN', '5000000000')),
            selection_mv_max=float(os.getenv('SELECTION_MV_MAX', '200000000000')),
            selection_change_pct_min=float(os.getenv('SELECTION_CHANGE_PCT_MIN', '-5')),
            selection_change_pct_max=float(os.getenv('SELECTION_CHANGE_PCT_MAX', '8')),
```

- [ ] **Step 3: Verify**

Run: `python -c "from src.config import get_config; c=get_config(); print(c.selection_enabled, c.selection_top_n, c.selection_price_max)"`
Expected: `False 7 50.0`(无 .env 配置时默认值)

---

### Task 2: 粗筛纯函数

**Files:**
- Create: `src/stock_selector.py`(仅含 `SelectionParams` + `is_main_board_code` + `coarse_filter`,后续任务追加)
- Test: `tests/test_stock_selector.py`(本任务仅测粗筛部分)

**Interfaces:**
- Consumes: pandas `DataFrame`(列: `代码/名称/最新价/涨跌幅/换手率/量比/总市值`)
- Produces:
  - `class SelectionParams`(dataclass,含全部粗筛阈值字段 + `top_n` + `from_config(config)` 类方法)
  - `is_main_board_code(code: str) -> bool`
  - `coarse_filter(df: pd.DataFrame, params: SelectionParams) -> List[dict]`,每元素 `{code,name,price,change_pct,turnover_rate,volume_ratio,total_mv}`

- [ ] **Step 1: 写失败测试**

Create `tests/test_stock_selector.py`(同时建 `tests/__init__.py` 空文件):

```python
# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np
from src.stock_selector import SelectionParams, is_main_board_code, coarse_filter


def _snapshot_rows():
    return [
        {'代码': '600519', '名称': '贵州茅台', '最新价': 1800.0, '涨跌幅': 1.2, '换手率': 3.0, '量比': 1.5, '总市值': 2000e8},     # 通过
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
    assert out[0]['price'] == 1800.0
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
    # 全被排除 -> 空列表
    df = pd.DataFrame(_snapshot_rows())  # 含大量违规行,但至少有两行通过;改用只含违规行
    df_restrict = df[df['代码'] == '688981']  # 科创,全排除
    assert coarse_filter(df_restrict, SelectionParams()) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_stock_selector.py -v`
Expected: FAIL(`ModuleNotFoundError: No module named 'src.stock_selector'`)

- [ ] **Step 3: 实现 `src/stock_selector.py`**

```python
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
from typing import List, Dict, Optional, Tuple

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


def _to_float(val) -> Optional[float]:
    try:
        f = float(val)
        return f if pd.notna(f) else None
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_stock_selector.py -v`
Expected: 4 passed

- [ ] **Step 5: Verify 语法与导入**

Run: `python -c "from src.stock_selector import SelectionParams, is_main_board_code, coarse_filter; p=SelectionParams.from_config(__import__('src.config',fromlist=['get_config']).get_config()); print(p.top_n, is_main_board_code('600519'))"`
Expected: `7 True`

---

### Task 3: 精筛与打分纯函数

**Files:**
- Modify: `src/stock_selector.py`(追加 `evaluate_trend`)
- Test: `tests/test_stock_selector.py`(追加精筛测试)

**Interfaces:**
- Consumes: 标准历史 DataFrame(列含 `close/ma5/ma10/ma20/volume_ratio`,由 `BaseFetcher._calculate_indicators` 产出)
- Produces: `evaluate_trend(df: pd.DataFrame) -> Optional[dict]`,返回 `{trend_level: str, bias_ma5: float, volume_ratio: float, score: int}` 或 `None`(任一精筛门不达标)。`trend_level` ∈ `{"强势多头","多头排列"}`。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_stock_selector.py`:

```python
from src.stock_selector import evaluate_trend


def _make_hist(n=70, rising=True):
    """构造 n 行历史,close 单调升/降,含 ma5/ma10/ma20/volume_ratio 列。"""
    if rising:
        close = np.arange(10.0, 10.0 + n, 1.0)
    else:
        close = np.arange(10.0 + n, 10.0, -1.0)
    df = pd.DataFrame({'close': close})
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma20'] = df['close'].rolling(20).mean()
    df['volume_ratio'] = 1.5
    return df


def test_evaluate_trend_passes_bull():
    r = evaluate_trend(_make_hist())
    assert r is not None
    assert r['trend_level'] in ('强势多头', '多头排列')
    assert r['bias_ma5'] >= 0
    assert r['score'] >= 4        # 趋势2~3 + 乖离2 + 量能1


def test_evaluate_trend_trend_score_reflects_strength():
    # 扩散的多头(强势)至少与普通多头同分或更高
    rising = _make_hist(70)
    r = evaluate_trend(rising)
    assert r['score'] <= 7         # 上限: 3(强势)+2(乖离)+2(量能)=7


def test_evaluate_trend_rejects_bear():
    assert evaluate_trend(_make_hist(70, rising=False)) is None


def test_evaluate_trend_rejects_new_stock():
    assert evaluate_trend(_make_hist(30)) is None   # 行数<60


def test_evaluate_trend_rejects_high_bias():
    df = _make_hist()
    # 将最后一根收盘价抬到高于 MA5 10%,乖离率>5% 应被拒
    df.loc[df.index[-1], 'close'] = df['ma5'].iloc[-1] * 1.10
    assert evaluate_trend(df) is None


def test_evaluate_trend_rejects_shrinking_volume():
    df = _make_hist()
    df['volume_ratio'] = 0.6      # 量能不足
    assert evaluate_trend(df) is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_stock_selector.py -k evaluate -v`
Expected: FAIL(`AttributeError ... evaluate_trend`)

- [ ] **Step 3: 实现 `evaluate_trend`**

追加到 `src/stock_selector.py`:

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_stock_selector.py -k evaluate -v`
Expected: 6 passed

---

### Task 4: AkshareFetcher 全市场快照接口

**Files:**
- Modify: `data_provider/akshare_fetcher.py`(在 `get_market_stats` 附近新增方法)

**Interfaces:**
- Consumes: 模块级 `_realtime_cache`、`get_realtime_circuit_breaker`(均已存在)
- Produces: `AkshareFetcher.get_all_a_share_snapshot(self) -> Optional[pd.DataFrame]`,返回东财全 A 股实时快照(列含 `代码/名称/最新价/涨跌幅/换手率/量比/总市值`),命中 20 分钟缓存则直接返回;失败返回 `None`。

- [ ] **Step 1: 在 `get_market_stats` 之前插入方法**

在 `data_provider/akshare_fetcher.py` 的 `get_market_stats` 方法定义之前(约第 1368 行前)新增:

```python
    def get_all_a_share_snapshot(self) -> Optional[pd.DataFrame]:
        """
        获取全 A 股实时行情快照(东方财富)。

        与 _get_stock_realtime_quote_em 共用同一个模块级缓存与熔断器:
        若当日个股分析已触发过全量拉取,这里直接命中缓存;否则触发一次刷新。

        Returns:
            全 A 股快照 DataFrame(含 代码/名称/最新价/涨跌幅/换手率/量比/总市值 等列),
            失败或空返回 None。
        """
        import akshare as ak
        circuit_breaker = get_realtime_circuit_breaker()
        source_key = "akshare_em"
        try:
            current_time = time.time()
            cached = _realtime_cache['data']
            if (cached is not None and not cached.empty and
                    current_time - _realtime_cache['timestamp'] < _realtime_cache['ttl']):
                logger.debug(f"[选股快照] 命中缓存,年龄 {int(current_time - _realtime_cache['timestamp'])}s")
                return cached

            self._set_random_user_agent()
            self._enforce_rate_limit()
            logger.info("[API调用] ak.stock_zh_a_spot_em() 获取全A股快照(选股)...")
            df = ak.stock_zh_a_spot_em()
            circuit_breaker.record_success(source_key)
            _realtime_cache['data'] = df
            _realtime_cache['timestamp'] = current_time
            logger.info(f"[API返回] 选股快照成功: {len(df) if df is not None else 0} 只,缓存已更新")
            return df if df is not None and not df.empty else None
        except Exception as e:
            logger.error(f"[API错误] 获取全A股快照失败: {e}")
            circuit_breaker.record_failure(source_key, str(e))
            return None
```

- [ ] **Step 2: Verify 导入与缓存复用**

Run: `python -c "from data_provider.akshare_fetcher import AkshareFetcher, _realtime_cache; f=AkshareFetcher(); print(hasattr(f,'get_all_a_share_snapshot'), type(_realtime_cache))"`
Expected: `True <class 'dict'>`

> 注:本方法联网,不做单元测试(依赖网络数据源);正确性由 Task 5 端到端 + 本机手动验证覆盖。

---

### Task 5: 选股编排 `run_selection`

**Files:**
- Modify: `src/stock_selector.py`(追加 `SelectionResult`、`SelectionOutcome`、`run_selection`)
- Test: `tests/test_stock_selector.py`(用 mock 验证编排)

**Interfaces:**
- Consumes: `SelectionParams`、`coarse_filter`、`evaluate_trend`(Task 2/3);`AkshareFetcher.get_all_a_share_snapshot`(Task 4);鸭子类型 `fetcher_manager.get_daily_data(code, days=90) -> (DataFrame, source_name)`
- Produces:
  - `@dataclass SelectionResult`:`code/name/price/trend_level/bias_ma5/volume_ratio/score`
  - `@dataclass SelectionOutcome`:`scanned: int`、`qualified: int`、`results: List[SelectionResult]`
  - `run_selection(fetcher_manager, params: Optional[SelectionParams] = None) -> Optional[SelectionOutcome]`;快照失败返回 `None`;无达标返回空 `SelectionOutcome`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_stock_selector.py`:

```python
from unittest.mock import MagicMock
from src.stock_selector import run_selection, SelectionResult


def test_run_selection_end_to_end(mocker):
    df_snapshot = pd.DataFrame([
        {'代码': '600519', '名称': '贵州茅台', '最新价': 1800.0, '涨跌幅': 1.2, '换手率': 3.0, '量比': 1.5, '总市值': 2000e8},
        {'代码': '002415', '名称': '海康威视', '最新价': 30.0, '涨跌幅': 0.5, '换手率': 2.0, '量比': 1.1, '总市值': 1000e8},
    ])
    fetcher_mock = MagicMock()
    # 首只涨幅1.2、换手3、量比1.5、市值2000亿:仅当平台允许时过粗筛;此处用默认阈值市值上限2000亿 -> 通过
    # 构造不同的历史返回:600519 达标,002415 走空头被拒
    hist_bull = _make_hist(70)
    hist_bear = _make_hist(70, rising=False)

    def fake_get_daily_data(code, days=30):
        return (hist_bull if code == '600519' else hist_bear), 'AkshareFetcher'
    fetcher_mock.get_daily_data.side_effect = fake_get_daily_data

    # 打桩快照获取
    import src.stock_selector as ss
    mocker.patch.object(ss.AkshareFetcher, 'get_all_a_share_snapshot', return_value=df_snapshot)

    outcome = run_selection(fetcher_mock, params=SelectionParams())
    assert outcome is not None
    assert outcome.scanned == 2
    assert [r.code for r in outcome.results] == ['600519']
    assert outcome.qualified == 1
    assert isinstance(outcome.results[0], SelectionResult)


def test_run_selection_snapshot_failure_returns_none(mocker):
    import src.stock_selector as ss
    mocker.patch.object(ss.AkshareFetcher, 'get_all_a_share_snapshot', return_value=None)
    assert run_selection(MagicMock()) is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_stock_selector.py -k run_selection -v`
Expected: FAIL(`ImportError` / 缺 `run_selection`)

- [ ] **Step 3: 实现 `run_selection`**

追加到 `src/stock_selector.py`:

```python
import concurrent.futures
from dataclasses import dataclass, field


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
    from data_provider.akshare_fetcher import AkshareFetcher

    p = params or SelectionParams.from_config(__import__('src.config', fromlist=['get_config']).get_config())

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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_stock_selector.py -k run_selection -v`
Expected: 2 passed

> 注:`concurrent` 导入未使用,若保留会触发 lint;本任务未用线程池(逐只串行沿用限流),删除该 `import concurrent.futures` 行。

---

### Task 6: 选股报告格式化

**Files:**
- Modify: `src/stock_selector.py`(追加 `_describe_bias`/`_describe_volume`/`format_selection_report`)
- Test: `tests/test_stock_selector.py`(追加格式化测试)

**Interfaces:**
- Consumes: `SelectionOutcome`(Task 5)
- Produces: `format_selection_report(outcome: SelectionOutcome, date_str: Optional[str] = None, schedule_time: str = "18:00") -> str`,返回完整 markdown 报告

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_stock_selector.py`:

```python
from src.stock_selector import format_selection_report, SelectionOutcome, SelectionResult


def test_format_selection_report():
    outcome = SelectionOutcome(
        scanned=5123, qualified=18,
        results=[
            SelectionResult(code='002165', name='红宝丽', price=18.52,
                            trend_level='强势多头', bias_ma5=1.2, volume_ratio=1.8, score=6),
            SelectionResult(code='002064', name='华峰化学', price=7.85,
                            trend_level='多头排列', bias_ma5=3.5, volume_ratio=1.4, score=4),
        ],
    )
    s = format_selection_report(outcome, date_str='2026-08-05', schedule_time='18:00')
    assert '2026-08-05' in s
    assert '从 5123 只中筛出达标 18 只,取 Top 2' in s
    assert '🔥 强势多头 | 红宝丽(002165)' in s
    assert '✅ 多头排列 | 华峰化学(002064)' in s
    assert '乖离率 1.2% | 回踩MA5最佳买点' in s
    assert '量比 1.4 | 温和放量' in s
    assert '生成时间: 18:00 | 仅供学习参考,不构成投资建议' in s
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_stock_selector.py -k format -v`
Expected: FAIL(`ImportError: cannot import name 'format_selection_report'`)

- [ ] **Step 3: 实现格式化函数**

追加到 `src/stock_selector.py`:

```python
from datetime import datetime


def _describe_bias(bias: float) -> str:
    return '回踩MA5最佳买点' if bias < 2.0 else '偏离略大,等回踩'


def _describe_volume(volume_ratio: float) -> str:
    if volume_ratio < 1.2:
        return '量能平稳'
    if volume_ratio < 2.0:
        return '温和放量'
    return '明显放量'


def format_selection_report(outcome: SelectionOutcome, date_str: Optional[str] = None,
                            schedule_time: str = "18:00") -> str:
    """生成选股报告 markdown。"""
    date_str = date_str or datetime.now().strftime('%Y-%m-%d')
    lines = [f"🎯 {date_str} 今日选股 · A股趋势突破"]
    lines.append(f"从 {outcome.scanned} 只中筛出达标 {outcome.qualified} 只,取 Top {len(outcome.results)}")
    lines.append("候选池: 沪深主板 | 排除ST/新股/涨停")
    lines.append("")
    for r in outcome.results:
        icon = "🔥" if r.trend_level == '强势多头' else "✅"
        lines.append(f"{icon} {r.trend_level} | {r.name}({r.code})")
        lines.append(f"📍 现价 {r.price:.2f} | 多头排列 MA5>MA10>MA20")
        lines.append(f"📈 乖离率 {r.bias_ma5:.1f}% | {_describe_bias(r.bias_ma5)}")
        lines.append(f"⚡ 量比 {r.volume_ratio:.1f} | {_describe_volume(r.volume_ratio)}")
        lines.append("")
    lines.append(f"---\n生成时间: {schedule_time} | 仅供学习参考,不构成投资建议")
    return "\n".join(lines)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_stock_selector.py -v`
Expected: 全部通过(粗筛4 + 精筛6 + 编排2 + 格式化1 = 13 passed)

---

### Task 7: main.py 接入与 .env.example

**Files:**
- Modify: `main.py`(在 `run_full_analysis` 的大盘复盘之后加选股)
- Modify: `.env.example`(新增选股配置项)

**Interfaces:**
- Consumes: `run_selection`、`format_selection_report`(Task 5/6)、`pipeline.notifier`、`Config.selection_enabled`

- [ ] **Step 1: 在 `.env.example` 追加选股配置**

在 `.env.example` 中「实时行情增强数据配置」段之后追加:

```
# === 选股配置（每日选股报告）===
SELECTION_ENABLED=false        # 是否启用每日选股报告（true 则在大盘复盘后运行）
SELECTION_TOP_N=7              # 选股报告取 Top N
SELECTION_PRICE_MIN=3          # 现价下限（元）
SELECTION_PRICE_MAX=50         # 现价上限（元）
SELECTION_TURNOVER_MIN=1       # 换手率下限（%）
SELECTION_TURNOVER_MAX=15      # 换手率上限（%）
SELECTION_VOLUME_RATIO_MIN=1   # 量比下限
SELECTION_VOLUME_RATIO_MAX=8   # 量比上限
SELECTION_MV_MIN=5000000000    # 总市值下限（元）50亿
SELECTION_MV_MAX=200000000000  # 总市值上限（元）2000亿
SELECTION_CHANGE_PCT_MIN=-5    # 涨跌幅下限（%）
SELECTION_CHANGE_PCT_MAX=8     # 涨跌幅上限（%）
```

- [ ] **Step 2: 在 `run_full_analysis` 中大盘复盘之后接入选股**

在 `main.py` 的 `run_full_analysis` 函数中,大盘复盘 `if config.market_review_enabled ...` 代码块**之后**(第 259 行 `# 输出摘要` 之前)插入:

```python
        # 3. 选股模块（可选）：大盘复盘之后运行，产出独立选股报告，不并入个股分析
        if getattr(config, 'selection_enabled', False):
            from src.stock_selector import run_selection, format_selection_report, SelectionOutcome
            try:
                logger.info("===== 开始每日选股 =====")
                outcome = run_selection(pipeline.fetcher_manager)
                if outcome is None:
                    logger.error("选股失败：全A股快照获取失败，已跳过本次选股")
                elif outcome.results:
                    date_str = datetime.now().strftime('%Y-%m-%d')
                    report = format_selection_report(
                        outcome, date_str=date_str, schedule_time=config.schedule_time
                    )
                    filepath = pipeline.notifier.save_report_to_file(
                        report, f"selection_{datetime.now().strftime('%Y%m%d')}.md"
                    )
                    logger.info(f"选股报告已保存: {filepath}")
                    if not args.no_notify and pipeline.notifier.is_available():
                        if pipeline.notifier.send(report):
                            logger.info("选股报告推送成功")
                        else:
                            logger.warning("选股报告推送失败")
                else:
                    logger.info("选股：今日无达标股票，不推送")
            except Exception as e:
                logger.exception(f"选股模块异常（不影响当天其余任务）: {e}")
```

> 说明:设计文档第 2 节写「个股分析之前」,但 `run_full_analysis` 实际流程为个股分析→大盘复盘;为确保不抢数据源配额,选股放在大盘复盘之后(满足「大盘复盘之后」)。

- [ ] **Step 3: 语法检查 + 全量测试**

Run: `python -m py_compile main.py src/stock_selector.py && python -m pytest tests/test_stock_selector.py -v`
Expected: 无语法错误,13 passed

- [ ] **Step 4: 端到端手动验证(可选但推荐)**

Run: `SELECTION_ENABLED=true python main.py --no-notify`
Expected: 日志出现 `=== 开始每日选股 ===`、选股报告保存到 `logs/` 或 `./selection_YYYYMMDD.md`,无报错;当 `stock_zh_a_spot_em` 失败时日志降级为「全A股快照获取失败,已跳过」且不阻断个股分析。

---

## Self-Review

- **规范覆盖**:粗筛(3.1)→Task 2;精筛(3.2)+打分(3.3)→Task 3;快照复用/缓存→Task 4;架构两级漏斗→Task 5;报告(4)→Task 6;配置(3.4)+触发/集成→Task 1/7;错误/并发/测试(5)→各 Task。全部覆盖。
- **一致性问题(已修复)**:规范 3.3 打分含「弱多头 +1」,但 3.2 精筛已强制 `MA5>MA10>MA20`,弱多头无法通过→打分仅保留「强势多头+3 / 多头排列+2」,已写入 Global Constraints。
- **触发时序**:规范「个股分析之前」与 `run_full_analysis` 实际流程矛盾,已改为大盘复盘之后(见 Task 7 Step 2 说明)。
- **类型一致**:`coarse_filter→evaluate_trend→SelectionResult/Outcome→format_selection_report` 全链路类型对齐;`run_selection(fetcher_manager, params)` 与 `DataFetcherManager.get_daily_data(code, days=90)` 签名匹配。
- **占位符**:无 TODO/TBD;每步含完整代码。