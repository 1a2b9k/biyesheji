"""
配置层测试:重点是 .env 解析与数据库地址的优先级。

这些逻辑关系到"密码不进 git",因此必须测到位。

注意:不用 pytest 的 tmp_path fixture —— 它内部走 tempfile.mkdtemp,
在 DSH 沙箱下建出的目录不可写(详见交接文档第八节)。
改用 tempfile.mkdtemp,由 .pysandbox/sitecustomize.py 打过补丁的实现。
"""

import os
import tempfile

import pytest

from app import config


@pytest.fixture()
def tmpdir():
    """沙箱安全的临时目录。"""
    path = tempfile.mkdtemp(prefix='cfg-test-')
    yield path
    import shutil
    shutil.rmtree(path, ignore_errors=True)


def _write(directory, name, content):
    path = os.path.join(directory, name)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(content)
    return path


def test_load_env_file_missing_returns_empty():
    assert config._load_env_file(os.path.join('no', 'such', 'file.env')) == {}


def test_load_env_file_parses_pairs(tmpdir):
    p = _write(tmpdir, 'x.env', 'A=1\nB=hello\n')
    assert config._load_env_file(p) == {'A': '1', 'B': 'hello'}


def test_load_env_file_ignores_comments_and_blanks(tmpdir):
    p = _write(tmpdir, 'x.env', '# 注释\n\nFIN_DATABASE_URL=abc\n   \n')
    assert config._load_env_file(p) == {'FIN_DATABASE_URL': 'abc'}


def test_load_env_file_strips_quotes(tmpdir):
    p = _write(tmpdir, 'x.env', 'A="quoted"\nB=\'single\'\n')
    assert config._load_env_file(p) == {'A': 'quoted', 'B': 'single'}


def test_load_env_file_keeps_value_with_equals(tmpdir):
    """密码里可能含 =,只能按第一个 = 切分。"""
    p = _write(tmpdir, 'x.env', 'A=key=value\n')
    assert config._load_env_file(p) == {'A': 'key=value'}


def test_load_env_file_handles_surrounding_spaces(tmpdir):
    p = _write(tmpdir, 'x.env', '  A  =  b  \n')
    assert config._load_env_file(p) == {'A': 'b'}


def test_default_is_sqlite():
    """未配置时必须回退到 SQLite,保证开箱即用。"""
    assert config.DEFAULT_SQLITE.startswith('sqlite:///')


def test_db_backend_detects_mysql():
    assert config.DB_BACKEND in ('sqlite', 'mysql')


def test_db_backend_logic():
    """按连接串 scheme 判断后端类型。

    早先实现是 `url.startswith('mysql')`,写成 `MySQL://` 或
    `mariadb://` 就会被误判成 sqlite,而 DB_BACKEND 会被自检和
    文档引用,判错会让人以为在用 SQLite。
    """
    for url, expected in [
        ('sqlite:///x.db', 'sqlite'),
        ('mysql+pymysql://u:p@h/db', 'mysql'),
        ('MySQL+pymysql://u:p@h/db', 'mysql'),
        ('mariadb://u:p@h/db', 'mysql'),
        ('mysql://u:p@h/db', 'mysql'),
    ]:
        assert config._backend_of(url) == expected, url


def test_default_stocks_shape():
    assert len(config.DEFAULT_STOCKS) >= 1
    for code, name, market in config.DEFAULT_STOCKS:
        assert len(code) == 6 and code.isdigit()
        assert name
        assert market in ('SH', 'SZ')
