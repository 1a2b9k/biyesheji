"""
情感—股价关联分析(论文第四章实验)。

把已入库的新闻情感与日线行情对齐,算情感指数与随后交易日收益的相关性,
产出可写进论文的统计结果。

用法:
    .python\\python.exe tools\\analyze_sentiment_returns.py
    .python\\python.exe tools\\analyze_sentiment_returns.py --codes 600519,300750
    .python\\python.exe tools\\analyze_sentiment_returns.py --lag 1 --min-news 3
    .python\\python.exe tools\\analyze_sentiment_returns.py --out data/experiments/returns.json

口径说明(写论文时必须交代清楚):
  * 情感指数 polarity = (正面条数 - 负面条数) / 当日总条数,即
    Antweiler & Frank(2004) 的 bullishness 口径,取值 [-1, 1]。
  * 收益用**下一个交易日**的涨跌幅,不是当天 —— 新闻多在盘后发布,
    用当天收益会引入前视偏差。
  * 非交易日的新闻归到它之前最后一个交易日,再往后推 lag 天。
  * 相关系数用 Pearson,并同时报 Spearman(抗异常值)和 p 值。
  * 样本量小的股票单独看没有意义,所以同时给出全样本汇总。

退出码 0 = 成功。
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_WS, 'backend'))

from sqlalchemy import select  # noqa: E402

from app import analysis, models  # noqa: E402
from app.db import SessionLocal  # noqa: E402


def _parse_args(argv=None):
    ap = argparse.ArgumentParser(description='情感与股价关联分析')
    ap.add_argument('--codes', default='',
                    help='只分析这些代码,逗号分隔;留空表示全部分析')
    ap.add_argument('--lag', type=int, default=1,
                    help='情感对应的未来第几个交易日收益(默认 1)')
    ap.add_argument('--min-news', type=int, default=1,
                    help='当天新闻条数少于此值的样本丢弃(默认 1)')
    ap.add_argument('--out', default='',
                    help='把结果写成 JSON 到这个路径')
    return ap.parse_args(argv)


def _load(db, code):
    """取一只股票的新闻与行情。"""
    news = db.scalars(
        select(models.News)
        .where(models.News.code == code, models.News.sentiment != '')
        .order_by(models.News.publish_time)
    ).all()
    klines = db.scalars(
        select(models.Kline)
        .where(models.Kline.code == code)
        .order_by(models.Kline.trade_date)
    ).all()

    rows = [{'publish_time': n.publish_time, 'sentiment': n.sentiment,
             'sentiment_score': n.sentiment_score} for n in news]
    ks = [{'trade_date': k.trade_date, 'change_pct': k.change_pct}
          for k in klines]
    return rows, ks


def _fmt(value, digits=4):
    if value is None:
        return 'n/a'
    return ('%.' + str(digits) + 'f') % value


def main(argv=None):
    args = _parse_args(argv)

    db = SessionLocal()
    try:
        codes = [c.strip() for c in args.codes.split(',') if c.strip()]
        stmt = select(models.Stock).order_by(models.Stock.code)
        if codes:
            stmt = stmt.where(models.Stock.code.in_(codes))
        stocks = db.scalars(stmt).all()

        if not stocks:
            print('没有可分析的股票。先跑 tools/collect_corpus.py 采集数据。')
            return 1

        print('数据库: %s   lag=%d   最少新闻条数=%d'
              % (__import__('app.config', fromlist=['x']).DB_BACKEND,
                 args.lag, args.min_news))
        print()

        per_stock = []
        all_pairs = []
        for stock in stocks:
            rows, ks = _load(db, stock.code)
            if not rows or not ks:
                print('%s %s: 新闻 %d 条 / 行情 %d 条 -> 跳过'
                      % (stock.code, stock.name, len(rows), len(ks)))
                continue

            out = analysis.analyze(rows, ks, lag=args.lag)
            pairs = [p for p in out['pairs'] if p['n'] >= args.min_news]
            stats = analysis.summarize(pairs)
            stats['lag'] = args.lag
            stats['days_with_news'] = len(out['daily'])

            per_stock.append({
                'code': stock.code,
                'name': stock.name,
                'news_total': len(rows),
                'kline_total': len(ks),
                'stats': stats,
            })
            all_pairs.extend(pairs)

            print('%s %s  新闻 %d 条 / 有情感的日子 %d 天 / 可用样本 %d 天'
                  % (stock.code, stock.name, len(rows),
                     stats['days_with_news'], stats['n']))
            print('   polarity 均值 %s  次日收益均值 %s%%'
                  % (_fmt(stats['polarity_mean']),
                     _fmt(stats['return_mean'], 3)))
            print('   Pearson %s (p=%s)  Spearman %s'
                  % (_fmt(stats['pearson']), _fmt(stats['p_value']),
                     _fmt(stats['spearman'])))
            if stats['groups']:
                g = stats['groups']
                print('   分组次日收益: 低 %s%% / 中 %s%% / 高 %s%%'
                      % (_fmt(g.get('low'), 3), _fmt(g.get('mid'), 3),
                         _fmt(g.get('high'), 3)))
            print('   方向命中率 %s (n=%d)'
                  % (_fmt(stats['hit_rate']), stats['hit_n']))
            print()

        if not per_stock:
            print('所有股票都缺数据,无法分析。')
            return 1

        overall = analysis.summarize(all_pairs)
        overall['lag'] = args.lag

        print('=' * 62)
        print('全样本汇总(合并 %d 只股票、%d 个股票-日样本)'
              % (len(per_stock), overall['n']))
        print('  Pearson  %s   p=%s' % (_fmt(overall['pearson']),
                                        _fmt(overall['p_value'])))
        print('  Spearman %s' % _fmt(overall['spearman']))
        if overall['groups']:
            g = overall['groups']
            print('  分组次日收益: 低 %s%% / 中 %s%% / 高 %s%%'
                  % (_fmt(g.get('low'), 3), _fmt(g.get('mid'), 3),
                     _fmt(g.get('high'), 3)))
        print('  方向命中率 %s (n=%d)'
              % (_fmt(overall['hit_rate']), overall['hit_n']))

        result = {
            'lag': args.lag,
            'min_news': args.min_news,
            'per_stock': per_stock,
            'overall': overall,
        }

        if args.out:
            path = args.out
            if not os.path.isabs(path):
                path = os.path.join(_WS, path)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2)
            print('\n结果已写入 %s' % path)

        return 0
    finally:
        db.close()


if __name__ == '__main__':
    sys.exit(main())
