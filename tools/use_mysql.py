"""
切换数据库 —— 一条命令在 SQLite 与 MySQL 之间切换,并自动建库建表。

用法:
    # 切到 MySQL(会先验证密码,再建库、建表)
    .python\\python.exe tools\\use_mysql.py --password 你的密码

    # 切回 SQLite
    .python\\python.exe tools\\use_mysql.py --sqlite

    # 只检查当前用的是哪个库、能否连通
    .python\\python.exe tools\\use_mysql.py --check

它做的事:
    1. 用给定密码试连 MySQL,密码错就立刻停下并说明(不写任何文件)
    2. 建库 fin_sentiment(若不存在)
    3. 把连接串写进工作区根目录的 .env(gitignore 已屏蔽,密码不进 git)
    4. 建表并报告结果

密码不会出现在任何提交里 —— 只写进 .env。
"""

import argparse
import os
import sys
import urllib.parse

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(_HERE)
_ENV_FILE = os.path.join(_WS, '.env')

DB_NAME = 'fin_sentiment'
HOST = '127.0.0.1'
PORT = 3306
USER = 'root'


def write_env(url):
    """把连接串写进 .env,保留其它已有配置。"""
    lines = []
    if os.path.isfile(_ENV_FILE):
        with open(_ENV_FILE, encoding='utf-8') as fh:
            lines = [ln for ln in fh.read().splitlines()
                     if not ln.strip().startswith('FIN_DATABASE_URL')]

    lines.append('FIN_DATABASE_URL=' + url)

    with open(_ENV_FILE, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')


def try_connect(password):
    """验证密码。返回 (ok, 说明)。"""
    try:
        import pymysql
    except ImportError:
        return False, 'pymysql 未安装'

    try:
        conn = pymysql.connect(host=HOST, port=PORT, user=USER,
                               password=password, connect_timeout=6)
    except pymysql.err.OperationalError as exc:
        code = exc.args[0] if exc.args else '?'
        if code == 1045:
            return False, '密码错误(MySQL 拒绝了认证)'
        return False, '连接失败: %s' % exc
    except Exception as exc:
        return False, '连接异常: %r' % exc

    with conn.cursor() as cur:
        cur.execute('SELECT VERSION()')
        version = cur.fetchone()[0]
    conn.close()
    return True, version


def create_database(password):
    """建库(若不存在)。"""
    import pymysql

    conn = pymysql.connect(host=HOST, port=PORT, user=USER,
                           password=password, connect_timeout=6)
    with conn.cursor() as cur:
        cur.execute(
            'CREATE DATABASE IF NOT EXISTS `%s` '
            'DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'
            % DB_NAME)
    conn.commit()
    conn.close()


def build_url(password):
    """拼连接串。密码做 URL 编码,避免特殊字符破坏 DSN。"""
    safe = urllib.parse.quote_plus(password)
    return 'mysql+pymysql://%s:%s@%s:%d/%s?charset=utf8mb4' % (
        USER, safe, HOST, PORT, DB_NAME)


def init_tables():
    """按当前配置建表。"""
    sys.path.insert(0, os.path.join(_WS, 'backend'))
    from app.db import init_db
    init_db()


def show_check():
    """报告当前配置与连通性。"""
    sys.path.insert(0, os.path.join(_WS, 'backend'))
    from app import config

    print('当前数据库类型: %s' % config.DB_BACKEND)
    print('连接串: %s' % _mask(config.DATABASE_URL))

    try:
        from app.db import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        print('连通性: 正常')
    except Exception as exc:
        print('连通性: 失败 -> %r' % exc)
        return 1
    return 0


def _mask(url):
    """隐藏连接串里的密码,避免打印到日志。"""
    if '@' not in url:
        return url
    head, _, tail = url.partition('@')
    if ':' not in head:
        return url
    scheme_user, _, _pw = head.rpartition(':')
    return scheme_user + ':****@' + tail


def main():
    ap = argparse.ArgumentParser(description='切换数据库')
    ap.add_argument('--password', help='MySQL root 密码')
    ap.add_argument('--sqlite', action='store_true', help='切回 SQLite')
    ap.add_argument('--check', action='store_true', help='只检查当前配置')
    args = ap.parse_args()

    if args.check:
        return show_check()

    if args.sqlite:
        write_env('')  # 空值 = 回退到内置 SQLite
        # 空行会被 config 当作未设置,故直接删掉该行更干净
        with open(_ENV_FILE, encoding='utf-8') as fh:
            kept = [ln for ln in fh.read().splitlines()
                    if not ln.strip().startswith('FIN_DATABASE_URL')]
        with open(_ENV_FILE, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(kept) + ('\n' if kept else ''))
        print('已切回 SQLite。')
        init_tables()
        print('建表完成。')
        return 0

    if not args.password:
        ap.error('需要 --password,或使用 --sqlite / --check')

    print('正在验证 MySQL 密码…')
    ok, info = try_connect(args.password)
    if not ok:
        print('失败: %s' % info)
        print('未修改任何文件。')
        return 2
    print('密码正确,MySQL %s' % info)

    print('正在建库 %s…' % DB_NAME)
    create_database(args.password)

    url = build_url(args.password)
    write_env(url)
    print('已写入 %s(该文件已被 gitignore)' % _ENV_FILE)

    print('正在建表…')
    init_tables()
    print()
    print('完成。重启后端即生效。')
    print('当前连接串: %s' % _mask(url))
    return 0


if __name__ == '__main__':
    sys.exit(main())
