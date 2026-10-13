"""
应用配置。

数据库地址的解析顺序(先命中先用):
  1. 环境变量 FIN_DATABASE_URL
  2. 工作区根目录的 .env 文件里的 FIN_DATABASE_URL
  3. 内置默认值 —— 工作区内 data/ 下的 SQLite

为什么要有 .env 这一层:
    切换 MySQL 需要写密码,而**密码绝不能进 git**。
    .env 已被 .gitignore 屏蔽,因此可以安全存放本机配置;
    仓库里只保留 .env.example 作为模板。

因此换库不需要改任何代码,只需在 .env 里写一行。
"""

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_BACKEND)

# 数据目录放在工作区内的 data/ 下(已被 .gitignore 屏蔽)
DATA_DIR = os.environ.get('FIN_DATA_DIR') or os.path.join(_ROOT, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

DEFAULT_SQLITE = 'sqlite:///' + os.path.join(DATA_DIR, 'fin.db').replace('\\', '/')
_ENV_FILE = os.path.join(_ROOT, '.env')


def _load_env_file(path):
    """极简 .env 解析:每行 KEY=VALUE,# 开头为注释。

    不引入 python-dotenv 依赖,因为只需要这一个功能。
    已存在的环境变量优先,不被文件覆盖。
    """
    values = {}
    if not os.path.isfile(path):
        return values
    try:
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, value = line.partition('=')
                values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


_ENV = _load_env_file(_ENV_FILE)

DATABASE_URL = (
    os.environ.get('FIN_DATABASE_URL')
    or _ENV.get('FIN_DATABASE_URL')
    or DEFAULT_SQLITE
)

# 供自检与文档使用:让调用方知道当前用的是哪种库
DB_BACKEND = 'mysql' if DATABASE_URL.startswith('mysql') else 'sqlite'

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
