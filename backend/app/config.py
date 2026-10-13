"""
应用配置。

数据库默认用 SQLite(零配置,开箱即用);要切到 MySQL 只需设置环境变量:

    set FIN_DATABASE_URL=mysql+pymysql://root:<密码>@127.0.0.1:3306/fin_sentiment?charset=utf8mb4

这样做的原因:开发阶段不依赖本机 MySQL 的账号密码,换库不动代码。
"""

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_BACKEND)

# 数据目录放在工作区内的 data/ 下(已被 .gitignore 屏蔽)
DATA_DIR = os.environ.get('FIN_DATA_DIR') or os.path.join(_ROOT, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

DEFAULT_SQLITE = 'sqlite:///' + os.path.join(DATA_DIR, 'fin.db').replace('\\', '/')

DATABASE_URL = os.environ.get('FIN_DATABASE_URL') or DEFAULT_SQLITE

# 采集参数
REQUEST_TIMEOUT = int(os.environ.get('FIN_REQUEST_TIMEOUT', '20'))
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0 Safari/537.36'
)

# 默认关注的股票(代码, 名称, 市场)
DEFAULT_STOCKS = [
    ('600519', '贵州茅台', 'SH'),
    ('300750', '宁德时代', 'SZ'),
    ('000001', '平安银行', 'SZ'),
]
