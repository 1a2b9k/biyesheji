"""
数据采集层 —— 从公开接口拉行情与新闻。

行情与新闻都来自东方财富,日线在东财不通时回退腾讯。
这些接口都是公开、免注册、免 key 的。实测(2026-10-13):
  * K 线:贵州茅台 6019 条日线
  * 新闻:关键词搜索可返回标题/来源/时间/链接

设计要点:
  * 采集与解析分离 —— parse_* 是纯函数,不发网络请求,因此可以离线单元测试
  * 网络函数只负责拿原始 JSON,失败时抛异常,由上层决定是否重试
  * 日线有两个源(东财 + 腾讯),`fetch_kline` 内部做回退;
    两个源同为前复权,同一天的数据逐位一致,可以混存
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config

_KLINE_URL = (
    # 用 http 而不是 https:实测(2026-10-17)同一台机器上 push2his 的
    # https 端口会直接断连(RemoteDisconnected),http 端口稳定可用。
    # 这是行情接口特有的现象,新闻接口的 https 一直正常,所以不全局改。
    # 注:2026-10-17 之后连 http 端口也被整域拒绝,见下面的腾讯备用源。
    'http://push2his.eastmoney.com/api/qt/stock/kline/get'
    '?fields1=f1,f2,f3,f4,f5,f6'
    '&fields2=f51,f52,f53,f54,f55,f56,f57,f58'
    '&klt=101&fqt=1&secid={secid}&beg=0&end=20500101&lmt=100000'
)
_NEWS_URL = 'https://search-api-web.eastmoney.com/search/jsonp?cb=&param={param}'
_NEWS_REFERER = 'https://so.eastmoney.com/'

# 备用日线源。东财 push2his 自 2026-10-17 起整域拒绝连接
# (所有编号主机都在 0.2 秒内 RemoteDisconnected,不是限流),
# 腾讯这个接口稳定可用,且同为前复权 —— 实测同一交易日的
# 开/收/高/低/量与东财逐位一致,两个源的数据可以混存。
_TENCENT_KLINE_URL = (
    'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
    '?param={symbol},day,,,{count},qfq'
)
# 腾讯单次最多返回 640 根(约 2.5 年),再大也只给 640,所以不必调高。
_TENCENT_DEPTH = 640


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

    单行数值坏掉就跳过该行,不让一行脏数据带走整批。腾讯源的解析
    一直是这样做的,东财源原先直接 float() —— 一旦接口改了字段顺序,
    抛的是 ValueError 而不是"少了几行",调用方很难定位。
    """
    data = json.loads(raw_json_text)
    payload = data.get('data') or {}
    rows = payload.get('klines') or []

    out = []
    for row in rows:
        parts = str(row).split(',')
        if len(parts) < 8:
            continue
        try:
            out.append({
                'trade_date': str(parts[0]),
                'open': float(parts[1]),
                'close': float(parts[2]),
                'high': float(parts[3]),
                'low': float(parts[4]),
                'volume': float(parts[5]),
                'amount': float(parts[6]),
                'amplitude': float(parts[7]),
            })
        except (TypeError, ValueError):
            continue
    return out


def fetch_kline(code, market='SH'):
    """拉取日线。返回 dict 列表(按日期升序)。

    先走东财;东财不通时回退腾讯。两个源都是前复权,同一天的
    开/收/高/低/量实测逐位一致,所以回退不会让库里出现两套口径。

    只捕获"网络不通"和"返回体解析不了"这两类 —— 前者是已知的
    东财整域拒绝(2026-10-17 起),后者是接口改格式。其它异常
    (比如自己代码里的 NameError)应当照常抛出,否则真 bug 会被
    悄悄降级成"回退成功"。
    """
    try:
        return parse_kline(_http_get(_KLINE_URL.format(
            secid=to_secid(code, market))))
    except (urllib.error.URLError, OSError, ValueError):
        return parse_tencent_kline(
            _http_get(_tencent_url(code, market)), code, market)


def _tencent_url(code, market):
    """拼腾讯日线的请求地址。symbol 形如 sh600519。"""
    prefix = 'sh' if str(market).upper() == 'SH' else 'sz'
    return _TENCENT_KLINE_URL.format(
        symbol=prefix + str(code), count=_TENCENT_DEPTH)


def parse_tencent_kline(raw_json_text, code='', market='SH'):
    """解析腾讯日线返回。纯函数,可离线测试。

    每行格式:[日期, 开, 收, 高, 低, 成交量(手)]
    与东财相比少了成交额和振幅,这里补算:
      * 成交额取 量 x 100 x 收盘 作为近似(VWAP 拿不到,
        与东财真值相差约 1%,只用于展示)
      * 振幅取 (高 - 低) / 前收 x 100,与东财口径一致
    批次第一行没有前收,振幅记 0(该行通常已在库中被跳过)。
    """
    prefix = 'sh' if str(market).upper() == 'SH' else 'sz'
    key = prefix + str(code)

    data = json.loads(raw_json_text)
    node = (data.get('data') or {}).get(key) or {}
    # 前复权在 qfqday,不复权在 day;两个键都认,优先前复权。
    rows = node.get('qfqday') or node.get('day') or []

    out = []
    prev_close = None
    for row in rows:
        parts = list(row) if isinstance(row, (list, tuple)) else str(row).split(',')
        if len(parts) < 6:
            continue
        try:
            trade_date = str(parts[0])
            open_ = float(parts[1])
            close = float(parts[2])
            high = float(parts[3])
            low = float(parts[4])
            volume = float(parts[5])
        except (TypeError, ValueError):
            continue
        out.append({
            'trade_date': trade_date,
            'open': open_,
            'close': close,
            'high': high,
            'low': low,
            'volume': volume,
            'amount': round(volume * 100 * close, 2),
            'amplitude': (round((high - low) / prev_close * 100.0, 2)
                          if prev_close else 0.0),
        })
        prev_close = close
    return out


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
        url = _safe_http_url(it.get('url', ''))
        if not title or not url:
            continue
        out.append({
            'title': title,
            'url': url,
            'source': _strip_tags(str(it.get('mediaName', ''))).strip(),
            'publish_time': str(it.get('date', '')).strip(),
        })
    return out


def _safe_http_url(raw):
    """只接受 http/https 的绝对地址,其余返回空串。

    这些 url 会原样进前端 `<a :href>`,不校验 scheme 就等于把
    `javascript:` 交给浏览器。当前 6421 条实测全是 http,但仍要挡 —
    数据源是第三方接口,不能假设它永远干净。
    """
    url = str(raw or '').strip()
    if not url:
        return ''
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return ''
    return url


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
        except (urllib.error.URLError, OSError, ValueError):
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

