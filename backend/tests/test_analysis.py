"""
多页采集与情感—股价关联分析的单元测试。

全部离线:网络函数用 monkeypatch 换掉,只验证拼接参数、去重、对齐与统计
的口径是否正确。真实连通性由 tools/check_datasource.py 负责。
"""

import json
import math

import pytest

from app import analysis, collector


# ------------------------------------------------------------ 多页新闻

def test_news_url_embeds_page_index():
    """页码必须真的写进请求参数,否则翻页会一直拿到第一页。"""
    url = collector._news_url('贵州茅台', 3, 20)
    assert 'pageIndex' in url
    # 参数是 URL 编码过的 JSON,编码后再找页码
    from urllib.parse import unquote
    assert '"pageIndex": 3' in unquote(url)
    assert '"pageSize": 20' in unquote(url)


def test_news_url_encodes_chinese_keyword():
    url = collector._news_url('贵州茅台', 1, 20)
    from urllib.parse import unquote
    assert '贵州茅台' in unquote(url)


def _fake_pages(pages):
    """构造 fetch_news_pages 的分页桩:pager 记录被请求过的页码。"""
    pager = {'requested': []}

    def fake_http(url, referer=None):
        from urllib.parse import unquote
        text = unquote(url)
        page = int(text.split('"pageIndex": ')[1].split(',')[0])
        pager['requested'].append(page)
        items = pages.get(page, [])
        return json.dumps({'result': {'cmsArticleWebOld': items}})

    return fake_http, pager


def test_fetch_news_pages_collects_all_pages(monkeypatch):
    pages = {
        1: [{'title': 'a', 'url': 'https://t/u1', 'mediaName': 's',
             'date': '2026-10-01'}],
        2: [{'title': 'b', 'url': 'https://t/u2', 'mediaName': 's',
             'date': '2026-10-02'}],
    }
    fake_http, pager = _fake_pages(pages)
    monkeypatch.setattr(collector, '_http_get', fake_http)

    rows = collector.fetch_news_pages('x', pages=2, page_size=20, sleep=0)
    assert [r['url'] for r in rows] == ['https://t/u1', 'https://t/u2']
    assert pager['requested'] == [1, 2]


def test_fetch_news_pages_dedupes_by_url(monkeypatch):
    """两页返回同一条新闻时只保留一份 —— 接口翻页偶尔会重叠。"""
    same = {'title': 'a', 'url': 'https://t/u1', 'mediaName': 's',
            'date': '2026-10-01'}
    pages = {1: [same], 2: [same]}
    fake_http, _ = _fake_pages(pages)
    monkeypatch.setattr(collector, '_http_get', fake_http)

    rows = collector.fetch_news_pages('x', pages=2, sleep=0)
    assert len(rows) == 1


def test_fetch_news_pages_stops_when_page_empty(monkeypatch):
    """翻到空页就停,不要傻乎乎地把剩下的页码都请求一遍。"""
    pages = {1: [{'title': 'a', 'url': 'https://t/u1', 'mediaName': 's',
                  'date': '2026-10-01'}]}
    fake_http, pager = _fake_pages(pages)
    monkeypatch.setattr(collector, '_http_get', fake_http)

    collector.fetch_news_pages('x', pages=5, sleep=0)
    assert pager['requested'] == [1, 2]  # 第 2 页空,不再往下翻


def test_fetch_news_pages_survives_network_error(monkeypatch):
    """第 2 页超时不该丢掉第 1 页已拿到的数据。"""
    calls = {'n': 0}

    def flaky(url, referer=None):
        calls['n'] += 1
        if calls['n'] > 1:
            raise OSError('boom')
        return json.dumps({'result': {'cmsArticleWebOld': [
            {'title': 'a', 'url': 'https://t/u1', 'mediaName': 's',
             'date': '2026-10-01'}]}})

    monkeypatch.setattr(collector, '_http_get', flaky)
    rows = collector.fetch_news_pages('x', pages=3, sleep=0)
    assert len(rows) == 1


def test_fetch_news_pages_pages_below_one_is_clamped(monkeypatch):
    fake_http, pager = _fake_pages({1: [
        {'title': 'a', 'url': 'https://t/u1', 'mediaName': 's',
         'date': '2026-10-01'}]})
    monkeypatch.setattr(collector, '_http_get', fake_http)
    collector.fetch_news_pages('x', pages=0, sleep=0)
    assert pager['requested'] == [1]


def test_parse_news_rejects_non_http_urls():
    """非 http(s) 的 url 直接丢掉 —— 它会原样进前端 `<a :href>`。

    数据源是第三方接口,不能假设它永远干净:一条 `javascript:` 就等于
    在前端执行任意脚本。相对路径也一并拒掉(库里存了也打不开)。
    """
    raw = json.dumps({'result': {'cmsArticleWebOld': [
        {'title': 'js', 'url': 'javascript:alert(1)', 'mediaName': 's',
         'date': '2026-10-01'},
        {'title': 'data', 'url': 'data:text/html,<script>x</script>',
         'mediaName': 's', 'date': '2026-10-01'},
        {'title': 'rel', 'url': '/a/b.html', 'mediaName': 's',
         'date': '2026-10-01'},
        {'title': 'empty', 'url': '', 'mediaName': 's', 'date': '2026-10-01'},
        {'title': 'ok', 'url': 'https://t/ok', 'mediaName': 's',
         'date': '2026-10-01'},
        {'title': 'ok2', 'url': 'http://t/ok2', 'mediaName': 's',
         'date': '2026-10-01'},
    ]}})
    rows = collector.parse_news(raw)
    assert [r['url'] for r in rows] == ['https://t/ok', 'http://t/ok2']


# ------------------------------------------------------- 每日情感聚合

def test_daily_sentiment_polarity():
    rows = [
        {'publish_time': '2026-10-01 09:00:00', 'sentiment': 'positive'},
        {'publish_time': '2026-10-01 10:00:00', 'sentiment': 'positive'},
        {'publish_time': '2026-10-01 11:00:00', 'sentiment': 'negative'},
        {'publish_time': '2026-10-01 12:00:00', 'sentiment': 'neutral'},
    ]
    daily = analysis.daily_sentiment(rows)
    assert daily['2026-10-01']['n'] == 4
    assert daily['2026-10-01']['positive'] == 2
    assert daily['2026-10-01']['negative'] == 1
    assert daily['2026-10-01']['neutral'] == 1
    # (2 - 1) / 4 = 0.25
    assert daily['2026-10-01']['polarity'] == 0.25
    # (1 + 1 - 1 + 0) / 4 = 0.25
    assert daily['2026-10-01']['mean_value'] == 0.25


def test_daily_sentiment_all_negative_is_minus_one():
    rows = [{'publish_time': '2026-10-01 09:00:00', 'sentiment': 'negative'}]
    assert analysis.daily_sentiment(rows)['2026-10-01']['polarity'] == -1.0


def test_daily_sentiment_skips_unlabelled_and_bad_dates():
    rows = [
        {'publish_time': '2026-10-01 09:00:00', 'sentiment': ''},
        {'publish_time': 'bad', 'sentiment': 'positive'},
        {'publish_time': '', 'sentiment': 'positive'},
        {'publish_time': '2026-10-02 09:00:00', 'sentiment': 'positive'},
    ]
    daily = analysis.daily_sentiment(rows)
    assert list(daily) == ['2026-10-02']
    assert daily['2026-10-02']['n'] == 1


def test_daily_sentiment_ignores_unknown_label():
    rows = [{'publish_time': '2026-10-01 09:00:00', 'sentiment': 'weird'}]
    assert analysis.daily_sentiment(rows) == {}


def test_daily_sentiment_groups_by_day():
    rows = [
        {'publish_time': '2026-10-01 09:00:00', 'sentiment': 'positive'},
        {'publish_time': '2026-10-02 09:00:00', 'sentiment': 'negative'},
    ]
    daily = analysis.daily_sentiment(rows)
    assert len(daily) == 2
    assert daily['2026-10-01']['polarity'] == 1.0
    assert daily['2026-10-02']['polarity'] == -1.0


# ------------------------------------------------------------ 收益对齐

KLINES = [
    {'trade_date': '2026-10-01', 'change_pct': 1.0},
    {'trade_date': '2026-10-02', 'change_pct': 2.0},
    {'trade_date': '2026-10-05', 'change_pct': -3.0},
]


def test_align_uses_next_trading_day():
    """lag=1 时用的是下一个交易日的收益,不是当天 —— 避免前视偏差。"""
    daily = {'2026-10-01': {'polarity': 1.0, 'mean_value': 1.0, 'n': 1}}
    pairs = analysis.align_with_returns(daily, KLINES, lag=1)
    assert len(pairs) == 1
    assert pairs[0]['date'] == '2026-10-01'
    assert pairs[0]['ret_date'] == '2026-10-02'
    assert pairs[0]['return'] == 2.0


def test_align_lag_zero_uses_same_day():
    daily = {'2026-10-01': {'polarity': 1.0, 'mean_value': 1.0, 'n': 1}}
    pairs = analysis.align_with_returns(daily, KLINES, lag=0)
    assert pairs[0]['ret_date'] == '2026-10-01'
    assert pairs[0]['return'] == 1.0


def test_align_maps_weekend_to_next_trading_day():
    """周末的新闻归到它之前最后一个交易日,再往后推 lag 天。

    10-03(周六)之前最后一个交易日是 10-02,lag=1 -> 10-05 的收益。
    这条测试钉住的是"先定位所属交易日、再推 lag"这个顺序:如果反过来
    先找下一个交易日(10-05)再推一天,就会错推到不存在的 10-06。
    """
    daily = {'2026-10-03': {'polarity': 1.0, 'mean_value': 1.0, 'n': 1}}
    pairs = analysis.align_with_returns(daily, KLINES, lag=1)
    assert len(pairs) == 1
    assert pairs[0]['date'] == '2026-10-03'
    assert pairs[0]['ret_date'] == '2026-10-05'
    assert pairs[0]['return'] == -3.0


def test_align_drops_days_without_future_return():
    """最后一个交易日没有"下一个交易日",对应样本要丢掉而不是当 0 收益。"""
    daily = {'2026-10-05': {'polarity': 1.0, 'mean_value': 1.0, 'n': 1}}
    assert analysis.align_with_returns(daily, KLINES, lag=1) == []


def test_align_empty_inputs():
    assert analysis.align_with_returns({}, KLINES) == []
    assert analysis.align_with_returns({'2026-10-01': {}}, []) == []


# ------------------------------------------------------------ 统计汇总

def test_summarize_detects_positive_relation():
    # 情感越高、次日收益越高 -> 相关系数应接近 1
    pairs = [{'polarity': p, 'return': p * 2.0, 'n': 1}
             for p in (-1.0, -0.5, 0.0, 0.5, 1.0)]
    stats = analysis.summarize(pairs)
    assert stats['n'] == 5
    assert stats['pearson'] == pytest.approx(1.0, abs=1e-6)
    assert stats['spearman'] == pytest.approx(1.0, abs=1e-6)
    assert stats['groups']['low'] < stats['groups']['high']


def test_summarize_detects_negative_relation():
    pairs = [{'polarity': p, 'return': -p * 2.0, 'n': 1}
             for p in (-1.0, -0.5, 0.0, 0.5, 1.0)]
    stats = analysis.summarize(pairs)
    assert stats['pearson'] == pytest.approx(-1.0, abs=1e-6)
    assert stats['groups']['low'] > stats['groups']['high']


def test_summarize_hit_rate():
    # 两个样本方向都对,一个错
    pairs = [
        {'polarity': 1.0, 'return': 1.0, 'n': 1},
        {'polarity': -1.0, 'return': -1.0, 'n': 1},
        {'polarity': 1.0, 'return': -1.0, 'n': 1},
    ]
    stats = analysis.summarize(pairs)
    assert stats['hit_n'] == 3
    assert stats['hit_rate'] == pytest.approx(2 / 3, abs=1e-4)


def test_summarize_hit_rate_skips_flat_samples():
    """情感为 0 或收益为 0 的样本无法判断方向,不计入命中率分母。"""
    pairs = [
        {'polarity': 0.0, 'return': 1.0, 'n': 1},
        {'polarity': 1.0, 'return': 0.0, 'n': 1},
        {'polarity': 1.0, 'return': 1.0, 'n': 1},
    ]
    stats = analysis.summarize(pairs)
    assert stats['hit_n'] == 1
    assert stats['hit_rate'] == 1.0


def test_summarize_too_few_samples_returns_none_correlation():
    """样本太少时不给相关系数,免得报出一个不可靠的数。"""
    stats = analysis.summarize([{'polarity': 1.0, 'return': 1.0, 'n': 1}])
    assert stats['n'] == 1
    assert stats['pearson'] is None
    assert stats['p_value'] is None


def test_summarize_constant_series_has_no_correlation():
    """全 0 的情感指数没有方差,相关系数无定义,应返回 None 而不是崩溃。"""
    pairs = [{'polarity': 0.0, 'return': float(i), 'n': 1} for i in range(5)]
    stats = analysis.summarize(pairs)
    assert stats['pearson'] is None


def test_p_value_range():
    """p 值必须落在 [0, 1],且强相关应给出小 p。"""
    assert 0.0 <= analysis._p_value_two_sided(0.9, 30) <= 1.0
    assert analysis._p_value_two_sided(0.9, 30) < 0.001
    assert analysis._p_value_two_sided(0.0, 30) == pytest.approx(1.0, abs=1e-6)


# ------------------------------------------------ 精确 t 分布(不是正态近似)

def test_p_value_matches_exact_t_distribution():
    """p 值必须是精确 t 分布的值,不能是正态近似。

    正态近似在小样本下会系统性地低估 p 值。这里钉住的 600276 那组
    (r=0.2829, n=48)是真实踩过的坑:正态近似给 0.0455(跨过 0.05),
    精确 t 分布给 0.0514(没跨过)。如果谁把实现改回 erfc 近似,这条会红。
    """
    # 期望值由 scipy.stats.t.sf 独立算出,保留 4 位
    cases = [
        (0.2829, 48, 0.0514),
        (-0.2370, 61, 0.0659),
        (0.5000, 10, 0.1411),
        (0.1000, 5, 0.8729),
        (0.9500, 8, 0.0003),
        (-0.6000, 4, 0.4000),
    ]
    for r, n, expected in cases:
        got = analysis._p_value_two_sided(r, n)
        assert got == pytest.approx(expected, abs=2e-4), (r, n, got, expected)


def test_p_value_is_not_normal_approximation():
    """把正态近似的结果与精确值区分开 —— 两者在 n 小的时候确实不同。"""
    r, n = 0.2829, 48
    t = r * math.sqrt((n - 2) / (1 - r * r))
    normal_approx = 2 * 0.5 * math.erfc(abs(t) / math.sqrt(2))
    exact = analysis._p_value_two_sided(r, n)
    assert normal_approx == pytest.approx(0.0455, abs=1e-4)
    assert exact == pytest.approx(0.0514, abs=1e-4)
    assert exact > normal_approx  # 正态近似确实偏小


def test_p_value_large_n_converges_to_normal():
    """大样本下 t 分布与正态近似几乎一致 —— 差异只在小样本上才咬人。"""
    r, n = 0.1, 5000
    t = r * math.sqrt((n - 2) / (1 - r * r))
    normal_approx = math.erfc(abs(t) / math.sqrt(2))
    assert analysis._p_value_two_sided(r, n) == pytest.approx(
        normal_approx, abs=1e-3)


def test_p_value_handles_degenerate_inputs():
    assert analysis._p_value_two_sided(None, 30) is None
    assert analysis._p_value_two_sided(0.5, 2) is None
    assert analysis._p_value_two_sided(1.0, 30) == 0.0
    assert analysis._p_value_two_sided(-1.0, 30) == 0.0


# -------------------------------------------------- 伪重复:按收益日合并

def test_merge_collapses_pairs_sharing_one_return_day():
    """同一个收益日上的多个新闻日必须合并成一个样本。

    这正是非交易日/长假的形态:周末两天的新闻都对齐到同一个周一收益。
    不合并的话同一个收益被算两次,n 虚高、p 值偏小。
    """
    pairs = [
        {'date': '2026-10-03', 'polarity': 1.0, 'mean_value': 1.0,
         'n': 2, 'ret_date': '2026-10-05', 'return': -3.0},
        {'date': '2026-10-04', 'polarity': -0.5, 'mean_value': -0.5,
         'n': 4, 'ret_date': '2026-10-05', 'return': -3.0},
    ]
    merged = analysis.merge_pairs_by_return_day(pairs)
    assert len(merged) == 1
    m = merged[0]
    assert m['ret_date'] == '2026-10-05'
    assert m['return'] == -3.0
    assert m['n'] == 6            # 条数相加
    assert m['days'] == 2         # 合并了 2 个新闻日
    assert m['date'] == '2026-10-03'   # 取最早的那个新闻日
    # polarity 按 n 加权:(1.0*2 + (-0.5)*4) / 6 = 0
    assert m['polarity'] == pytest.approx(0.0, abs=1e-6)


def test_merge_keeps_distinct_return_days_separate():
    pairs = [
        {'date': '2026-10-01', 'polarity': 1.0, 'mean_value': 1.0,
         'n': 1, 'ret_date': '2026-10-02', 'return': 2.0},
        {'date': '2026-10-02', 'polarity': -1.0, 'mean_value': -1.0,
         'n': 1, 'ret_date': '2026-10-05', 'return': -3.0},
    ]
    merged = analysis.merge_pairs_by_return_day(pairs)
    assert [m['ret_date'] for m in merged] == ['2026-10-02', '2026-10-05']
    assert all(m['days'] == 1 for m in merged)


def test_merge_is_idempotent():
    """已经是合并结果再合一次,样本数不变 —— 避免重复调用把数算错。"""
    pairs = [
        {'date': '2026-10-03', 'polarity': 1.0, 'mean_value': 1.0,
         'n': 2, 'ret_date': '2026-10-05', 'return': -3.0},
        {'date': '2026-10-04', 'polarity': -0.5, 'mean_value': -0.5,
         'n': 4, 'ret_date': '2026-10-05', 'return': -3.0},
    ]
    once = analysis.merge_pairs_by_return_day(pairs)
    twice = analysis.merge_pairs_by_return_day(once)
    assert len(once) == len(twice) == 1
    assert once[0]['n'] == twice[0]['n'] == 6
    assert once[0]['polarity'] == twice[0]['polarity']


def test_merge_empty():
    assert analysis.merge_pairs_by_return_day([]) == []


def test_analyze_merges_by_default_and_reports_both_counts():
    """analyze 默认合并;pairs 与 stats['n'] 是合并后的,aligned_n 是合并前。"""
    # 三个新闻日:10-03/10-04 是周末(共享 10-05 的收益),10-05 落在 10-06
    rows = [
        {'publish_time': '2026-10-03 09:00:00', 'sentiment': 'positive'},
        {'publish_time': '2026-10-04 09:00:00', 'sentiment': 'negative'},
        {'publish_time': '2026-10-05 09:00:00', 'sentiment': 'positive'},
    ]
    klines = [
        {'trade_date': '2026-10-02', 'change_pct': 1.0},
        {'trade_date': '2026-10-05', 'change_pct': -3.0},
        {'trade_date': '2026-10-06', 'change_pct': 2.0},
    ]
    out = analysis.analyze(rows, klines, lag=1)
    assert out['stats']['aligned_n'] == 3     # 合并前 3 条对齐结果
    assert out['stats']['n'] == 2             # 合并后 2 个收益日
    assert len(out['pairs']) == 2
    assert [p['ret_date'] for p in out['pairs']] == ['2026-10-05', '2026-10-06']


def test_analyze_merge_false_keeps_raw_alignment():
    rows = [
        {'publish_time': '2026-10-03 09:00:00', 'sentiment': 'positive'},
        {'publish_time': '2026-10-04 09:00:00', 'sentiment': 'negative'},
    ]
    klines = [
        {'trade_date': '2026-10-02', 'change_pct': 1.0},
        {'trade_date': '2026-10-05', 'change_pct': -3.0},
    ]
    out = analysis.analyze(rows, klines, lag=1, merge=False)
    assert len(out['pairs']) == 2
    assert out['stats']['n'] == 2
    assert all('days' not in p for p in out['pairs'])


def test_ranks_handles_ties():
    assert analysis._ranks([1.0, 2.0, 2.0, 3.0]) == [1.0, 2.5, 2.5, 4.0]


# ------------------------------------------------------------ 一站式

def test_analyze_end_to_end():
    rows = [
        {'publish_time': '2026-10-01 09:00:00', 'sentiment': 'positive'},
        {'publish_time': '2026-10-02 09:00:00', 'sentiment': 'negative'},
    ]
    out = analysis.analyze(rows, KLINES, lag=1)
    assert out['stats']['lag'] == 1
    assert out['stats']['days_with_news'] == 2
    assert len(out['pairs']) == 2
    assert len(out['daily']) == 2
