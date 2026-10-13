"""
数据源连通性实测 —— 验证毕设方案 A 依赖的财经数据源是否真的可用。

用法:
    .python\\python.exe tools\\check_datasource.py

它做真实的网络请求,并把关键结论打印出来;退出码非 0 表示有数据源不可用。
这些请求都是公开、免注册、免 key 的接口。

数据源:
  1. 东方财富 K 线接口  —— 日线行情
  2. 东方财富新闻搜索  —— 财经资讯
"""

import json
import sys
import urllib.parse
import urllib.request

TIMEOUT = 20
_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')

failures = []


def report(ok, label, detail=''):
    print('  [%s] %-40s %s' % ('PASS' if ok else 'FAIL', label, detail))
    if not ok:
        failures.append(label)


def get(url, referer=None):
    req = urllib.request.Request(url)
    req.add_header('User-Agent', _UA)
    if referer:
        req.add_header('Referer', referer)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.read()


print('=== Data source check ===')
print()

# ---- 1. 东方财富 K 线 ----
try:
    secid = '1.600519'  # 贵州茅台(沪市)
    url = (
        'https://push2his.eastmoney.com/api/qt/stock/kline/get'
        '?fields1=f1,f2,f3,f4,f5,f6'
        '&fields2=f51,f52,f53,f54,f55,f56,f57,f58'
        '&klt=101&fqt=1&secid=%s&beg=0&end=20500101&lmt=100000' % secid
    )
    status, body = get(url)
    data = json.loads(body.decode('utf-8'))
    klines = (data.get('data') or {}).get('klines') or []
    name = (data.get('data') or {}).get('name', '?')
    report(status == 200 and len(klines) > 0,
           'EastMoney K-line',
           'HTTP %d, %s, %d 条日线' % (status, name, len(klines)))
    if klines:
        print('        最新一条: %s' % klines[-1])
except Exception as exc:
    report(False, 'EastMoney K-line', '%s: %s' % (type(exc).__name__, exc))

# ---- 2. 东方财富新闻搜索 ----
try:
    param = {
        'uid': '',
        'keyword': '贵州茅台',
        'type': ['cmsArticleWebOld'],
        'client': 'web',
        'clientType': 'web',
        'clientVersion': 'curr',
        'param': {'cmsArticleWebOld': {
            'searchScope': 'default', 'sort': 'default',
            'pageIndex': 1, 'pageSize': 10,
            'preTag': '<em>', 'postTag': '</em>'}},
    }
    url = ('https://search-api-web.eastmoney.com/search/jsonp'
           '?cb=&param=' + urllib.parse.quote(json.dumps(param, ensure_ascii=False)))
    status, body = get(url, referer='https://so.eastmoney.com/')
    text = body.decode('utf-8', 'replace')
    start, end = text.find('{'), text.rfind('}')
    data = json.loads(text[start:end + 1])
    items = (((data.get('result') or {}).get('cmsArticleWebOld')) or [])
    report(status == 200 and len(items) > 0,
           'EastMoney news search',
           'HTTP %d, %d 条结果' % (status, len(items)))
    if items:
        first = items[0]
        print('        标题: %s' % str(first.get('title', ''))[:60])
        print('        来源: %s  时间: %s' % (first.get('mediaName', '?'),
                                              first.get('date', '?')))
except Exception as exc:
    report(False, 'EastMoney news search', '%s: %s' % (type(exc).__name__, exc))

print()
if failures:
    print('RESULT: %d source(s) FAILED -> %s' % (len(failures), ', '.join(failures)))
    sys.exit(1)
print('RESULT: all data sources reachable')
sys.exit(0)
