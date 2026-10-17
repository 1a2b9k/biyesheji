"""
数据源连通性实测 —— 验证毕设方案 A 依赖的财经数据源是否真的可用。

用法:
    .python\\python.exe tools\\check_datasource.py

它做真实的网络请求,并把关键结论打印出来;退出码非 0 表示有数据源不可用。
这些请求都是公开、免注册、免 key 的接口。

数据源:
  1. 东方财富 K 线接口  —— 日线行情(主源,2026-10-17 起被整域拒绝)
  2. 腾讯 K 线接口      —— 日线行情(备用源,主源不通时自动接管)
  3. 东方财富新闻搜索  —— 财经资讯

判定标准:日线只要**两个源有一个通**就算通过,因为 collector.fetch_kline
内部会自动回退;两个都不通才算失败。
"""

import json
import sys
import urllib.parse
import urllib.request

TIMEOUT = 20
_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')

failures = []


def report(ok, label, detail='', fatal=True):
    """打印一行结果。fatal=False 的失败只提示,不计入退出码。"""
    print('  [%s] %-40s %s' % ('PASS' if ok else 'FAIL', label, detail))
    if not ok and fatal:
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

# ---- 1. 东方财富 K 线(主源) ----
kline_ok = False
try:
    secid = '1.600519'  # 贵州茅台(沪市)
    url = (
        'http://push2his.eastmoney.com/api/qt/stock/kline/get'
        '?fields1=f1,f2,f3,f4,f5,f6'
        '&fields2=f51,f52,f53,f54,f55,f56,f57,f58'
        '&klt=101&fqt=1&secid=%s&beg=0&end=20500101&lmt=100000' % secid
    )
    status, body = get(url)
    data = json.loads(body.decode('utf-8'))
    klines = (data.get('data') or {}).get('klines') or []
    name = (data.get('data') or {}).get('name', '?')
    kline_ok = status == 200 and len(klines) > 0
    report(kline_ok, 'EastMoney K-line (primary)',
           'HTTP %d, %s, %d 条日线' % (status, name, len(klines)),
           fatal=False)
    if klines:
        print('        最新一条: %s' % klines[-1])
except Exception as exc:
    report(False, 'EastMoney K-line (primary)',
           '%s: %s' % (type(exc).__name__, exc), fatal=False)

# ---- 2. 腾讯 K 线(备用源) ----
tencent_ok = False
try:
    url = ('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
           '?param=sh600519,day,,,10,qfq')
    status, body = get(url)
    data = json.loads(body.decode('utf-8'))
    node = (data.get('data') or {}).get('sh600519') or {}
    rows = node.get('qfqday') or node.get('day') or []
    tencent_ok = status == 200 and len(rows) > 0
    report(tencent_ok, 'Tencent K-line (fallback)',
           'HTTP %d, %d 条日线' % (status, len(rows)))
    if rows:
        print('        最新一条: %s' % rows[-1])
except Exception as exc:
    report(False, 'Tencent K-line (fallback)',
           '%s: %s' % (type(exc).__name__, exc))

# 日线两个源都不通才算失败 —— 单源不通有回退兜着。
if not (kline_ok or tencent_ok):
    failures.append('K-line (both sources down)')
    print('  [FAIL] K-line: 主源与备用源都不通,日线无法更新')
elif not kline_ok:
    print('  [INFO] 主源不可用,采集将自动走腾讯备用源')

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
