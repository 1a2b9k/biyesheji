"""
批量采集多只股票的行情与新闻,把样本量做大。

用法:
    .python\\python.exe tools\\collect_corpus.py                  # 默认池子,每只 5 页
    .python\\python.exe tools\\collect_corpus.py --pages 10       # 每只翻 10 页
    .python\\python.exe tools\\collect_corpus.py --codes 600519,300750
    .python\\python.exe tools\\collect_corpus.py --no-kline       # 只采新闻
    .python\\python.exe tools\\collect_corpus.py --dry-run        # 只看要采哪些,不落库

设计说明:
  * 采集是幂等的 —— 新闻按 url 判重、行情按 (code, trade_date) 判重,
    所以重复跑不会产生脏数据,中断后直接重跑即可。
  * 每只股票独立 try/except:某只失败不影响其余的,最后统一汇报。
  * 情感标注只处理 sentiment 为空的行,因此已经标过的不再重算,
    第二次跑会明显更快。
  * 东财接口对高频请求会限流(实测连续请求后直接断连),所以每只股票
    之间留 --sleep 秒的间隔;被限流时可以调大这个值再重跑。
"""

import argparse
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_WS, 'backend'))

from app import config, models, service  # noqa: E402
from app.db import SessionLocal  # noqa: E402


def _parse_args(argv=None):
    ap = argparse.ArgumentParser(description='批量采集股票行情与新闻')
    ap.add_argument('--codes', default='',
                    help='只采这些代码,逗号分隔;留空表示用默认池子')
    ap.add_argument('--pages', type=int, default=5,
                    help='每只股票新闻翻页数(默认 5,每页 20 条)')
    ap.add_argument('--page-size', type=int, default=20,
                    help='每页条数(默认 20)')
    ap.add_argument('--sleep', type=float, default=1.0,
                    help='每只股票之间的间隔秒数(默认 1.0,防风控)')
    ap.add_argument('--no-kline', action='store_true',
                    help='只采新闻,不采行情')
    ap.add_argument('--dry-run', action='store_true',
                    help='只打印计划,不实际采集')
    return ap.parse_args(argv)


def _select_stocks(codes_arg):
    """按 --codes 过滤默认池子;代码不在池子里也允许,名字临时用代码。"""
    pool = config.all_stocks()
    if not codes_arg.strip():
        return pool

    wanted = [c.strip() for c in codes_arg.split(',') if c.strip()]
    by_code = {code: (code, name, mkt) for code, name, mkt in pool}
    out = []
    for code in wanted:
        out.append(by_code.get(code, (code, code, 'SH')))
    return out


def _db_snapshot(db):
    """当前库里的数据量,用来算本次新增。"""
    from sqlalchemy import func, select

    def count(model):
        return db.scalar(select(func.count()).select_from(model)) or 0

    return {
        'stocks': count(models.Stock),
        'klines': count(models.Kline),
        'news': count(models.News),
        'annotated': db.scalar(
            select(func.count()).select_from(models.News)
            .where(models.News.sentiment != '')) or 0,
    }


def main(argv=None):
    args = _parse_args(argv)
    stocks = _select_stocks(args.codes)

    print('数据库: %s' % config.DB_BACKEND)
    print('待采股票: %d 只,新闻 %d 页 x %d 条/页'
          % (len(stocks), args.pages, args.page_size))
    for code, name, mkt in stocks:
        print('  %s %s %s' % (code, mkt, name))
    if args.dry_run:
        print('\n--dry-run: 未实际采集')
        return 0

    db = SessionLocal()
    try:
        before = _db_snapshot(db)
        print('\n采集前: 股票 %(stocks)d / 行情 %(klines)d / 新闻 %(news)d '
              '/ 已标注 %(annotated)d' % before)

        results = []
        for idx, (code, name, market) in enumerate(stocks, 1):
            print('\n[%d/%d] %s %s ...' % (idx, len(stocks), code, name),
                  flush=True)
            started = time.time()
            try:
                stats = service.sync_stock(
                    db, code, name, market,
                    news_size=args.page_size,
                    news_pages=args.pages,
                )
                stats['elapsed'] = round(time.time() - started, 1)
                results.append(stats)
                print('  行情 +%d / 新闻 +%d / 标注 %d (%ss)'
                      % (stats['kline_added'], stats['news_added'],
                         stats['sentiment_added'], stats['elapsed']))
                for err in stats['errors']:
                    print('  ! %s' % err)
            except Exception as exc:  # noqa: BLE001
                print('  失败: %s: %s' % (type(exc).__name__, exc))
                results.append({'code': code, 'name': name,
                                'kline_added': 0, 'news_added': 0,
                                'sentiment_added': 0,
                                'errors': ['%s: %s' % (type(exc).__name__, exc)]})

            if idx < len(stocks) and args.sleep:
                time.sleep(args.sleep)

        after = _db_snapshot(db)
        print('\n采集后: 股票 %(stocks)d / 行情 %(klines)d / 新闻 %(news)d '
              '/ 已标注 %(annotated)d' % after)
        print('本次新增: 行情 %d / 新闻 %d / 标注 %d'
              % (after['klines'] - before['klines'],
                 after['news'] - before['news'],
                 after['annotated'] - before['annotated']))

        failed = [r for r in results if r.get('errors')]
        if failed:
            print('\n有 %d 只股票报告了错误:' % len(failed))
            for r in failed:
                print('  %s %s: %s' % (r['code'], r['name'],
                                       '; '.join(r['errors'])))
        return 0
    finally:
        db.close()


if __name__ == '__main__':
    sys.exit(main())
