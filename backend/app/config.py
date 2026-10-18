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

def _backend_of(url):
    """从 DATABASE_URL 判断后端类型。

    只看 scheme 部分(`mysql+pymysql://` 取到 `mysql`),不用 startswith
    硬比 —— 写成 `MySQL://` 或带驱动后缀时 startswith 会误判成 sqlite。
    """
    scheme = url.split(':', 1)[0].strip().lower()
    scheme = scheme.split('+', 1)[0]
    if scheme in ('mysql', 'mariadb'):
        return 'mysql'
    if scheme in ('sqlite', ''):
        return 'sqlite'
    return scheme


# 供自检与文档使用:让调用方知道当前用的是哪种库
DB_BACKEND = _backend_of(DATABASE_URL)

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

# 批量采集用的扩展股票池(代码, 名称, 市场)。
# 挑选标准:成交活跃、新闻量大,且覆盖白酒/新能源/银行/保险/券商/地产/
# 医药/电子等不同行业 —— 行业分散能让情感-股价关联分析不至于只反映
# 单一板块的行情。
#
# 为什么写死而不是调接口动态取:东财的行情列表接口(push2/clist)对高频
# 请求会直接断连,实测连续几次就被拒且短时间内不恢复;而按成交额动态
# 取池子还会让实验结果不可复现 —— 论文里的样本必须是固定的。
EXTENDED_STOCKS = [
    ('601318', '中国平安', 'SH'),
    ('600036', '招商银行', 'SH'),
    ('000858', '五粮液', 'SZ'),
    ('002594', '比亚迪', 'SZ'),
    ('600030', '中信证券', 'SH'),
    ('601899', '紫金矿业', 'SH'),
    ('600276', '恒瑞医药', 'SH'),
    ('002415', '海康威视', 'SZ'),
    ('000651', '格力电器', 'SZ'),
    ('600887', '伊利股份', 'SH'),
]


def all_stocks():
    """默认股票 + 扩展池,按代码去重。"""
    seen = set()
    out = []
    for item in list(DEFAULT_STOCKS) + list(EXTENDED_STOCKS):
        if item[0] in seen:
            continue
        seen.add(item[0])
        out.append(item)
    return out
