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


def merge_pairs_by_return_day(pairs):
    """把落在同一个收益日上的多个新闻日合并成一个样本。

    为什么必须合并:非交易日(周末、长假)的新闻会被 align_with_returns 归到
    它之前最后一个交易日,再往后推 lag 天,于是**多个新闻日会共享同一个
    收益值**。如果不合并,同一个收益就被重复计入若干次,样本量虚高、
    相关系数的显著性被高估 —— 这在统计上叫伪重复(pseudo-replication)。

    本课题的真实情况:13 只股票共 744 个"股票-日"样本,但只有 575 个唯一
    的(股票, 收益日)组合,169 条是重复的;最极端的是 601899 在国庆假期后
    的第一个交易日,七个自然日的新闻共享同一个 -1.41% 收益,被算了 7 次。

    合并口径:同一收益日内,polarity 与 mean_value 按当天新闻条数 n 加权
    平均(新闻多的那天对当天情绪的贡献本来就更大),n 相加,并记下合并了
    几个新闻日(days)。这样每个输出样本仍然只对应一个收益观测。

    pairs: align_with_returns 的返回(或已经过滤过的子集)
    返回  : 按 ret_date 升序的新列表,元素字段与输入一致,另加 days
    """
    buckets = {}
    for p in pairs:
        key = p['ret_date']
        b = buckets.get(key)
        if b is None:
            buckets[key] = {
                'date': p['date'],
                'ret_date': key,
                'return': p['return'],
                'polarity': p['polarity'] * p['n'],
                'mean_value': p['mean_value'] * p['n'],
                'n': p['n'],
                'days': 1,
            }
            continue
        b['polarity'] += p['polarity'] * p['n']
        b['mean_value'] += p['mean_value'] * p['n']
        b['n'] += p['n']
        b['days'] += 1
        if p['date'] < b['date']:
            b['date'] = p['date']

    out = []
    for key in sorted(buckets):
        b = buckets[key]
        total = b['n'] or 1
        out.append({
            'date': b['date'],
            'ret_date': key,
            'return': b['return'],
            'polarity': round(b['polarity'] / total, 4),
            'mean_value': round(b['mean_value'] / total, 4),
            'n': b['n'],
            'days': b['days'],
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


def _betacf(a, b, x):
    """不完全 Beta 函数的连分式部分(Numerical Recipes 的 betacf)。

    用修正 Lentz 算法迭代,收敛慢时退回一个足够小的值而不是抛异常 ——
    这里只是算一个 p 值,不该让统计函数把整个接口带崩。
    """
    tiny = 1e-30
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-16:
            break
    return h


def _betai(a, b, x):
    """正则化不完全 Beta 函数 I_x(a, b)。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_front = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                 + a * math.log(x) + b * math.log(1.0 - x))
    front = math.exp(log_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _p_value_two_sided(r, n):
    """相关系数的双侧 p 值(精确 t 分布,不是正态近似)。

    检验统计量 t = r * sqrt((n-2)/(1-r^2)),自由度 df = n-2,服从 t 分布。
    双侧 p 值 = P(|T| >= |t|) = I_{df/(df+t^2)}(df/2, 1/2),其中 I 是
    正则化不完全 Beta 函数。

    早先的版本用正态近似(0.5 * erfc(z/sqrt(2)))算尾部概率,样本量小时
    会系统性地低估 p 值 —— 在本课题的数据上,600276 的 p 值因此从 0.0514
    被算成 0.0455,正好跨过 0.05 这条线。所以这里改成精确解,不引入
    scipy(后端运行时依赖里没有它),用连分式自己实现不完全 Beta 函数。
    """
    if r is None or n < 3:
        return None
    if abs(r) >= 1.0:
        return 0.0
    df = n - 2
    t = r * math.sqrt(df / (1 - r * r))
    p = _betai(df / 2.0, 0.5, df / (df + t * t))
    return round(min(1.0, max(0.0, p)), 4)


def _mean(values):
    return sum(values) / len(values) if values else None


def summarize(pairs):
    """对 align_with_returns(或合并后的)结果做统计汇总。

    调用方应先经 merge_pairs_by_return_day 合并同一收益日的样本,否则
    样本量会虚高、p 值会偏小(见该函数的说明)。

    返回 dict,包含:
      * n            : 可用样本数(合并后即收益日数)
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


def analyze(rows, klines, lag=1, merge=True):
    """一站式:新闻行 + 行情行 -> 每日情感指数 + 相关性汇总。

    merge=True(默认)时把落在同一收益日的样本合并,再统计。返回的 pairs
    也是合并后的 —— 后续画散点图、做分组收益都该用合并后的口径,否则
    同一个收益点会在图上被画出好几个点,视觉上也会误导读者的判断。
    传 merge=False 可拿到逐新闻日的原始对齐结果(仅用于排查对齐问题)。
    """
    daily = daily_sentiment(rows)
    aligned = align_with_returns(daily, klines, lag=lag)
    pairs = merge_pairs_by_return_day(aligned) if merge else aligned
    stats = summarize(pairs)
    stats['lag'] = lag
    stats['days_with_news'] = len(daily)
    stats['aligned_n'] = len(aligned)
    return {'daily': daily, 'pairs': pairs, 'stats': stats}
