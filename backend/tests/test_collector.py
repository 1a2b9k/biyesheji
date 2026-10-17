"""
采集层单元测试。

全部用离线数据(接口返回的样本),不发真实网络请求 —— 这样测试快且稳定。
真实连通性由 tools/check_datasource.py 负责。
"""

import json

from app import collector


# ---------------------------------------------------------------- secid

def test_to_secid_shanghai():
    assert collector.to_secid('600519', 'SH') == '1.600519'


def test_to_secid_shenzhen():
    assert collector.to_secid('300750', 'SZ') == '0.300750'


def test_to_secid_lowercase_market():
    assert collector.to_secid('000001', 'sz') == '0.000001'


# ---------------------------------------------------------------- K 线

KLINE_SAMPLE = json.dumps({
    'rc': 0,
    'data': {
        'code': '600519',
        'name': '贵州茅台',
        'klines': [
            '2026-10-09,1255.42,1263.00,1282.00,1255.42,35111,4453223189.00,2.12',
            '2026-10-12,1262.95,1288.00,1288.00,1261.00,31556,4042857559.00,2.14',
            '2026-10-13,1287.00,1274.89,1288.48,1268.11,26573,3393315572.00,1.58',
        ],
    },
})


def test_parse_kline_count():
    rows = collector.parse_kline(KLINE_SAMPLE)
    assert len(rows) == 3


def test_parse_kline_fields():
    row = collector.parse_kline(KLINE_SAMPLE)[0]
    assert row['trade_date'] == '2026-10-09'
    assert row['open'] == 1255.42
    assert row['close'] == 1263.00
    assert row['high'] == 1282.00
    assert row['low'] == 1255.42
    assert row['volume'] == 35111.0
    assert row['amplitude'] == 2.12


def test_parse_kline_empty_payload():
    assert collector.parse_kline(json.dumps({'data': None})) == []
    assert collector.parse_kline(json.dumps({})) == []


def test_parse_kline_skips_malformed_rows():
    raw = json.dumps({'data': {'klines': ['bad,row', '2026-01-01,1,2,3,4,5,6,7']}})
    rows = collector.parse_kline(raw)
    assert len(rows) == 1
    assert rows[0]['trade_date'] == '2026-01-01'


# ---------------------------------------------------------------- 涨跌幅

def test_compute_change_pct():
    rows = collector.compute_change_pct(collector.parse_kline(KLINE_SAMPLE))
    # 第一天没有前值
    assert rows[0]['change_pct'] == 0.0
    # (1288.00 - 1263.00) / 1263.00 * 100 = 1.98
    assert rows[1]['change_pct'] == 1.98
    # (1274.89 - 1288.00) / 1288.00 * 100 = -1.02
    assert rows[2]['change_pct'] == -1.02


def test_compute_change_pct_empty():
    assert collector.compute_change_pct([]) == []


# ---------------------------------------------------------------- 腾讯备用源

# 真实返回的样本(2026-10-12 ~ 10-16,前复权)。
TENCENT_SAMPLE = json.dumps({
    'code': 0,
    'msg': '',
    'data': {
        'sh600519': {
            'qfqday': [
                ['2026-10-14', '1270.100', '1286.000', '1286.750', '1266.000',
                 '23773.000'],
                ['2026-10-15', '1286.000', '1312.970', '1317.760', '1282.000',
                 '57677.000'],
                ['2026-10-16', '1311.570', '1329.000', '1329.880', '1301.680',
                 '38502.000'],
            ],
            'qt': {'sh600519': ['1', '贵州茅台']},
        },
    },
})


def test_parse_tencent_kline_count():
    rows = collector.parse_tencent_kline(TENCENT_SAMPLE, '600519', 'SH')
    assert len(rows) == 3


def test_parse_tencent_kline_fields():
    row = collector.parse_tencent_kline(TENCENT_SAMPLE, '600519', 'SH')[1]
    assert row['trade_date'] == '2026-10-15'
    assert row['open'] == 1286.0
    assert row['close'] == 1312.97
    assert row['high'] == 1317.76
    assert row['low'] == 1282.0
    assert row['volume'] == 57677.0


def test_parse_tencent_kline_computes_amplitude_from_prev_close():
    rows = collector.parse_tencent_kline(TENCENT_SAMPLE, '600519', 'SH')
    # 第一行没有前收,振幅记 0
    assert rows[0]['amplitude'] == 0.0
    # (1317.76 - 1282.00) / 1286.00 * 100 = 2.78,与东财口径一致
    assert rows[1]['amplitude'] == 2.78
    # (1329.88 - 1301.68) / 1312.97 * 100 = 2.15
    assert rows[2]['amplitude'] == 2.15


def test_parse_tencent_kline_estimates_amount():
    row = collector.parse_tencent_kline(TENCENT_SAMPLE, '600519', 'SH')[2]
    # 量(手) x 100 x 收盘。东财真值 5075530000,相差约 0.8%
    assert row['amount'] == 38502.0 * 100 * 1329.0


def test_parse_tencent_kline_accepts_shenzhen_key():
    raw = json.dumps({'data': {'sz300750': {
        'qfqday': [['2026-10-16', '1', '2', '3', '0.5', '100']]}}})
    rows = collector.parse_tencent_kline(raw, '300750', 'SZ')
    assert len(rows) == 1
    assert rows[0]['close'] == 2.0


def test_parse_tencent_kline_falls_back_to_day_key():
    raw = json.dumps({'data': {'sh600519': {
        'day': [['2026-10-16', '1', '2', '3', '0.5', '100']]}}})
    assert len(collector.parse_tencent_kline(raw, '600519', 'SH')) == 1


def test_parse_tencent_kline_skips_bad_rows():
    raw = json.dumps({'data': {'sh600519': {
        'qfqday': [['2026-10-16'], ['bad', 'x', 'y', 'z', 'w', 'v'],
                   ['2026-10-15', '1', '2', '3', '0.5', '100']]}}})
    rows = collector.parse_tencent_kline(raw, '600519', 'SH')
    assert len(rows) == 1
    assert rows[0]['trade_date'] == '2026-10-15'


def test_parse_tencent_kline_empty_payload():
    assert collector.parse_tencent_kline(json.dumps({}), '600519', 'SH') == []
    assert collector.parse_tencent_kline(
        json.dumps({'data': None}), '600519', 'SH') == []
    assert collector.parse_tencent_kline(
        json.dumps({'data': {'sh600519': {}}}), '600519', 'SH') == []


def test_tencent_url_uses_market_prefix():
    assert 'sh600519' in collector._tencent_url('600519', 'SH')
    assert 'sz300750' in collector._tencent_url('300750', 'SZ')


def test_fetch_kline_falls_back_to_tencent(monkeypatch):
    """东财不通时必须自动回退腾讯,而不是把异常抛给上层。"""
    def boom(url, referer=None):
        raise OSError('RemoteDisconnected')

    def ok(url, referer=None):
        return TENCENT_SAMPLE

    monkeypatch.setattr(collector, '_http_get', boom)
    # 第一次调用(东财)抛错,第二次(腾讯)返回样本
    calls = []

    def dispatch(url, referer=None):
        calls.append(url)
        if 'push2his' in url:
            raise OSError('RemoteDisconnected')
        return TENCENT_SAMPLE

    monkeypatch.setattr(collector, '_http_get', dispatch)
    rows = collector.fetch_kline('600519', 'SH')
    assert len(rows) == 3
    assert len(calls) == 2
    assert 'gtimg' in calls[1]


def test_fetch_kline_uses_eastmoney_when_available(monkeypatch):
    """东财正常时不该多打一次腾讯。"""
    calls = []

    def only_eastmoney(url, referer=None):
        calls.append(url)
        return KLINE_SAMPLE

    monkeypatch.setattr(collector, '_http_get', only_eastmoney)
    rows = collector.fetch_kline('600519', 'SH')
    assert len(rows) == 3
    assert len(calls) == 1
    assert 'push2his' in calls[0]


# ---------------------------------------------------------------- 新闻

NEWS_SAMPLE = (
    '{"result":{"cmsArticleWebOld":['
    '{"title":"<em>贵州茅台</em>重回A股股王","url":"https://x.com/1",'
    '"mediaName":"新华财经","date":"2026-10-12 16:08:01"},'
    '{"title":"11只白酒股下跌","url":"https://x.com/2",'
    '"mediaName":"北京商报","date":"2026-10-13 17:15:22"}'
    ']}}'
)


def test_parse_news_count():
    assert len(collector.parse_news(NEWS_SAMPLE)) == 2


def test_parse_news_strips_highlight_tags():
    row = collector.parse_news(NEWS_SAMPLE)[0]
    assert row['title'] == '贵州茅台重回A股股王'
    assert '<em>' not in row['title']


def test_parse_news_fields():
    row = collector.parse_news(NEWS_SAMPLE)[0]
    assert row['url'] == 'https://x.com/1'
    assert row['source'] == '新华财经'
    assert row['publish_time'] == '2026-10-12 16:08:01'


def test_parse_news_handles_jsonp_wrapper():
    wrapped = 'jQuery123(' + NEWS_SAMPLE + ')'
    assert len(collector.parse_news(wrapped)) == 2


def test_parse_news_skips_incomplete_items():
    raw = '{"result":{"cmsArticleWebOld":[{"title":"","url":"u"},{"title":"t","url":""}]}}'
    assert collector.parse_news(raw) == []


def test_parse_news_garbage_returns_empty():
    assert collector.parse_news('not json at all') == []
    assert collector.parse_news('') == []
