"""
数据采集层 —— 从东方财富的公开接口拉行情与新闻。

这些接口都是公开、免注册、免 key 的。实测(2026-10-13):
  * K 线:贵州茅台 6019 条日线
  * 新闻:关键词搜索可返回标题/来源/时间/链接

设计要点:
  * 采集与解析分离 —— parse_* 是纯函数,不发网络请求,因此可以离线单元测试
  * 网络函数只负责拿原始 JSON,失败时抛异常,由上层决定是否重试
"""

import json
import re
import time
import urllib.parse
import urllib.request

from . import config

_KLINE_URL = (
    # 用 http 而不是 https:实测(2026-10-17)同一台机器上 push2his 的
    # https 端口会直接断连(RemoteDisconnected),http 端口稳定可用。
    # 这是行情接口特有的现象,新闻接口的 https 一直正常,所以不全局改。
    'http://push2his.eastmoney.com/api/qt/stock/kline/get'
    '?fields1=f1,f2,f3,f4,f5,f6'
    '&fields2=f51,f52,f53,f54,f55,f56,f57,f58'
    '&klt=101&fqt=1&secid={secid}&beg=0&end=20500101&lmt=100000'
)
_NEWS_URL = 'https://search-api-web.eastmoney.com/search/jsonp?cb=&param={param}'
_NEWS_REFERER = 'https://so.eastmoney.com/'


def to_secid(code, market):
    """把 (代码, 市场) 转成东财的 secid。

    东财规则:沪市前缀 1,深市前缀 0。
    """
    prefix = '1' if str(market).upper() == 'SH' else '0'
    return '%s.%s' % (prefix, code)


def _http_get(url, referer=None):
    req = urllib.request.Request(url)
    req.add_header('User-Agent', config.USER_AGENT)
    if referer:
        req.add_header('Referer', referer)
    with urllib.request.urlopen(req, timeout=config.REQUEST_TIMEOUT) as resp:
        return resp.read().decode('utf-8', 'replace')


# ---------------------------------------------------------------- K 线

def parse_kline(raw_json_text):
    """解析东财 K 线返回,产出 dict 列表。纯函数,可离线测试。

    每行格式:日期,开,收,高,低,成交量,成交额,振幅
    """
    data = json.loads(raw_json_text)
    payload = data.get('data') or {}
    rows = payload.get('klines') or []

    out = []
    for row in rows:
        parts = str(row).split(',')
        if len(parts) < 8:
            continue
        out.append({
            'trade_date': parts[0],
            'open': float(parts[1]),
            'close': float(parts[2]),
            'high': float(parts[3]),
            'low': float(parts[4]),
            'volume': float(parts[5]),
            'amount': float(parts[6]),
            'amplitude': float(parts[7]),
        })
    return out


def fetch_kline(code, market='SH'):
    """拉取日线。返回 dict 列表(按日期升序)。"""
    url = _KLINE_URL.format(secid=to_secid(code, market))
    return parse_kline(_http_get(url))


def compute_change_pct(klines):
    """按前一日收盘计算涨跌幅,就地写入 change_pct 字段。

    第一个交易日没有前值,记 0。
    """
    prev_close = None
    for row in klines:
        if prev_close:
            row['change_pct'] = round(
                (row['close'] - prev_close) / prev_close * 100.0, 2)
        else:
            row['change_pct'] = 0.0
        prev_close = row['close']
    return klines


# ---------------------------------------------------------------- 新闻

def parse_news(raw_text):
    """解析东财新闻搜索返回。纯函数,可离线测试。

    接口返回的是 jsonp 包装,需要先剥掉外层再解析。
    """
    text = raw_text.strip()
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        return []
    data = json.loads(text[start:end + 1])
    items = ((data.get('result') or {}).get('cmsArticleWebOld')) or []

    out = []
    for it in items:
        title = _strip_tags(str(it.get('title', ''))).strip()
        url = str(it.get('url', '')).strip()
        if not title or not url:
            continue
        out.append({
            'title': title,
            'url': url,
            'source': _strip_tags(str(it.get('mediaName', ''))).strip(),
            'publish_time': str(it.get('date', '')).strip(),
        })
    return out


def _strip_tags(text):
    """去掉接口返回里夹带的高亮标签。"""
    return re.sub(r'<[^>]+>', '', text)


def _news_url(keyword, page_index, page_size):
    """拼出某一页新闻搜索的请求地址。"""
    param = {
        'uid': '',
        'keyword': keyword,
        'type': ['cmsArticleWebOld'],
        'client': 'web',
        'clientType': 'web',
        'clientVersion': 'curr',
        'param': {'cmsArticleWebOld': {
            'searchScope': 'default',
            'sort': 'default',
            'pageIndex': page_index,
            'pageSize': page_size,
            'preTag': '',
            'postTag': '',
        }},
    }
    return _NEWS_URL.format(
        param=urllib.parse.quote(json.dumps(param, ensure_ascii=False)))


def fetch_news(keyword, page_size=20):
    """按关键词搜索新闻(只取第一页)。返回 dict 列表。"""
    return parse_news(
        _http_get(_news_url(keyword, 1, page_size), referer=_NEWS_REFERER))


def fetch_news_pages(keyword, pages=1, page_size=20, sleep=0.3):
    """按关键词翻多页新闻。返回 dict 列表(已按 url 去重)。

    分页是实测过的(2026-10-17):同一关键词第 1/2/3 页共 60 条 url 无重叠,
    翻到第 40 页仍有数据、日期可回溯到约 3 个月前。所以多翻几页能显著
    扩大样本量,这是把新闻从 89 条扩到几千条的主要手段。

    单页失败不抛异常 —— 已拿到的页仍然有价值,不该因为第 7 页超时
    就把前 6 页丢掉。调用方看返回条数即可判断是否全军覆没。

    sleep 是给接口留的间隔,避免连续请求被限流;测试里传 0。
    """
    if pages < 1:
        pages = 1

    out = []
    seen = set()
    for page in range(1, pages + 1):
        if page > 1 and sleep:
            time.sleep(sleep)
        try:
            rows = parse_news(
                _http_get(_news_url(keyword, page, page_size),
                          referer=_NEWS_REFERER))
        except Exception:  # noqa: BLE001
            break
        if not rows:
            break  # 没数据了,再翻也是空
        added = 0
        for row in rows:
            if row['url'] in seen:
                continue
            seen.add(row['url'])
            out.append(row)
            added += 1
        if added == 0:
            break  # 整页都是重复的,说明已经翻到底
    return out

