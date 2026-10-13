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
