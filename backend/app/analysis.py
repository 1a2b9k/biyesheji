"""
情感与股价的关联分析。

思路(对应论文第四章的"情感—股价关联"实验):
  1. 把一只股票的新闻按发布日聚合成"当日情感指数";
  2. 把情感指数与随后交易日的涨跌幅对齐 —— 新闻当天收盘后才被读到,
     所以用的是"下一个交易日"的收益,而不是当天;
  3. 算相关系数、分组收益,看情绪是否真的含有对未来收益的信息。

设计要点:
  * 聚合与对齐都是纯函数,不碰数据库也不发网络请求,可以离线单元测试;
  * 情感指数的口径跟 Antweiler & Frank(2004) 的 bullishness 一致:
    (正面条数 - 负面条数) / 总条数,落在 [-1, 1],0 表示多空均衡;
  * 同时保留"按情感分组的次日平均收益",因为相关系数只能说明单调关系
    的强弱,分组收益更能看出方向是否可用。
"""

import math

# 三分类标签到数值的映射:正面 +1、负面 -1、中性 0。
# 中性记 0 而不是丢掉 —— 丢掉会让"当天既有正面也有中性"的样本失真,
# 也会让样本量凭空变小。
LABEL_VALUE = {'positive': 1.0, 'negative': -1.0, 'neutral': 0.0}


def _date_of(publish_time):
    """从 'YYYY-MM-DD HH:MM:SS' 里取日期部分。取不到返回 None。"""
    text = str(publish_time or '').strip()
    if len(text) < 10:
        return None
    day = text[:10]
    if len(day) != 10 or day[4] != '-' or day[7] != '-':
        return None
    return day


def daily_sentiment(rows):
    """把新闻按发布日聚合成情感指数。

    rows: [{'publish_time': str, 'sentiment': str}, ...]
    返回 {日期: {'n': 总条数, 'positive': .., 'negative': .., 'neutral': ..,
                 'polarity': (正-负)/n, 'mean_value': 均值, 'mean_score': 均值}}

    polarity 是主要指标,bullishness 口径;mean_value 是把标签映射成
    +1/0/-1 后的均值,两者在有中性样本时会略有差别,一起返回便于对比。
    """
    buckets = {}
    for row in rows:
        day = _date_of(row.get('publish_time'))
        if day is None:
            continue
        label = str(row.get('sentiment') or '').strip()
        if label not in LABEL_VALUE:
            continue
        b = buckets.setdefault(day, {'n': 0, 'positive': 0, 'negative': 0,
                                     'neutral': 0, 'value_sum': 0.0,
                                     'score_sum': 0.0, 'score_n': 0})
        b['n'] += 1
        b[label] += 1
        b['value_sum'] += LABEL_VALUE[label]
        score = row.get('sentiment_score')
        if score is not None:
            try:
                b['score_sum'] += float(score)
                b['score_n'] += 1
            except (TypeError, ValueError):
                pass

    out = {}
    for day, b in buckets.items():
        n = b['n']
        out[day] = {
            'n': n,
            'positive': b['positive'],
            'negative': b['negative'],
            'neutral': b['neutral'],
            'polarity': round((b['positive'] - b['negative']) / n, 4),
            'mean_value': round(b['value_sum'] / n, 4),
            'mean_score': (round(b['score_sum'] / b['score_n'], 4)
                           if b['score_n'] else None),
        }
    return out


def align_with_returns(daily, klines, lag=1):
    """把每日情感指数与"之后第 lag 个交易日"的涨跌幅对齐。

    为什么不用当天:新闻发布在盘中或盘后,当天的涨跌已经发生了,拿当天
    收益去回归会引入前视偏差。lag=1 表示用下一个交易日的收益。

    daily : daily_sentiment 的返回
    klines: [{'trade_date': 'YYYY-MM-DD', 'change_pct': float}, ...] 升序
    返回   : [{'date', 'polarity', 'mean_value', 'n', 'return', 'ret_date'}, ...]

    非交易日(周末/节假日)的新闻归到它之前最后一个交易日,再往后推 lag
    天。这样周六的消息对应周一的收益,而不是被"先找下个交易日、再推一天"
    的写法错推到周二。
    """
    if not daily or not klines:
        return []

    dates = [k['trade_date'] for k in klines]
    returns = {}
    for k in klines:
        try:
            returns[k['trade_date']] = float(k.get('change_pct') or 0.0)
        except (TypeError, ValueError):
            returns[k['trade_date']] = 0.0

    out = []
    for day in sorted(daily):
        stat = daily[day]
        # 找到 day 之前(含当天)最后一个交易日,作为这条新闻所属的交易日
        idx = None
        for i, d in enumerate(dates):
            if d <= day:
                idx = i
            else:
                break
        if idx is None:
            continue  # 新闻早于最早的行情,没有基准日
        target = idx + lag
        if target >= len(dates):
            continue
        ret_date = dates[target]
        out.append({
            'date': day,
            'polarity': stat['polarity'],
            'mean_value': stat['mean_value'],
            'n': stat['n'],
            'ret_date': ret_date,
            'return': returns[ret_date],
        })
    return out


def _pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None, None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None, None
    return num / (dx * dy), n


def _ranks(values):
    """平均秩(处理并列)。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs, ys):
    if len(xs) < 3:
        return None
    rho, _ = _pearson(_ranks(xs), _ranks(ys))
    return rho


def _p_value_two_sided(r, n):
    """相关系数的双侧 p 值(用 t 分布近似)。

    t = r * sqrt((n-2)/(1-r^2)),自由度 n-2。这里用正态近似算尾部概率,
    样本量几十以上时与精确 t 分布差别很小;小样本下 p 值偏小,所以结论
    里同时报 n,让人自己判断。
    """
    if r is None or n < 3:
        return None
    if abs(r) >= 1.0:
        return 0.0
    t = r * math.sqrt((n - 2) / (1 - r * r))
    # 正态尾概率的近似(Abramowitz-Stegun 7.1.26 的 erf 近似)
    z = abs(t)
    p_one = 0.5 * math.erfc(z / math.sqrt(2))
    return round(min(1.0, 2 * p_one), 4)


def _mean(values):
    return sum(values) / len(values) if values else None


def summarize(pairs):
    """对 align_with_returns 的结果做统计汇总。

    返回 dict,包含:
      * n            : 可用样本天数
      * pearson / spearman / p_value : 情感指数与次日收益的相关性
      * polarity_mean / return_mean  : 各自的均值
      * groups       : 按情感指数三分的分组平均收益(低/中/高)
      * hit_rate     : 情感方向与次日涨跌方向一致的占比
      * lag          : 由调用方填入
    """
    xs = [p['polarity'] for p in pairs]
    ys = [p['return'] for p in pairs]
    n = len(xs)

    pearson, _ = _pearson(xs, ys)
    spearman = _spearman(xs, ys)

    groups = {}
    if n >= 3:
        ordered = sorted(pairs, key=lambda p: p['polarity'])
        third = max(1, n // 3)
        groups = {
            'low': round(_mean([p['return'] for p in ordered[:third]]), 4),
            'mid': round(_mean([p['return'] for p in ordered[third:n - third]]), 4),
            'high': round(_mean([p['return'] for p in ordered[n - third:]]), 4),
        }

    # 方向命中率:情感为正且次日涨 / 情感为负且次日跌,都算命中;
    # 情感为 0 或收益为 0 的样本无法判断方向,不计入分母。
    hit = 0
    hit_n = 0
    for p in pairs:
        if p['polarity'] == 0 or p['return'] == 0:
            continue
        hit_n += 1
        if (p['polarity'] > 0) == (p['return'] > 0):
            hit += 1

    return {
        'n': n,
        'pearson': round(pearson, 4) if pearson is not None else None,
        'spearman': round(spearman, 4) if spearman is not None else None,
        'p_value': _p_value_two_sided(pearson, n),
        'polarity_mean': round(_mean(xs), 4) if xs else None,
        'return_mean': round(_mean(ys), 4) if ys else None,
        'groups': groups,
        'hit_rate': round(hit / hit_n, 4) if hit_n else None,
        'hit_n': hit_n,
    }


def analyze(rows, klines, lag=1):
    """一站式:新闻行 + 行情行 -> 每日情感指数 + 相关性汇总。"""
    daily = daily_sentiment(rows)
    pairs = align_with_returns(daily, klines, lag=lag)
    stats = summarize(pairs)
    stats['lag'] = lag
    stats['days_with_news'] = len(daily)
    return {'daily': daily, 'pairs': pairs, 'stats': stats}
