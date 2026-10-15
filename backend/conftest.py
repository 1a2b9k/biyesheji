"""
pytest 全局配置。

唯一的职责:把 pytest 的临时目录从系统 Temp 挪到工作区内。

原因:DSH 沙箱下受限进程无法读写系统临时目录,pytest 默认会把
`tmp_path` 建在 `%TEMP%\\pytest-of-<user>` 下,于是每个用到
`tmp_path` 的用例都会报 `PermissionError: [WinError 5]`。
工作区内的 `.tmp` 是可写的,放这里同时也让临时文件随仓库一起
被 .gitignore 收走,不会污染系统盘。
"""

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(_HERE)
# 注意:目录名不要用 "pytest"。早期一次运行(在 .pysandbox 补丁生效前)
# 建出的 .tmp\pytest 是 0o700 目录,沙箱下既进不去也删不掉;
# 若继续用它当 basetemp,pytest 清理时会在 iterdir() 上直接抛
# PermissionError,整个会话的 tmp_path fixture 全废。
_BASETEMP = os.path.join(_WS, '.tmp', 'pytest-work')


def pytest_configure(config):
    # 只有用户没显式指定 --basetemp 时才改,避免覆盖命令行意图
    if not config.option.basetemp:
        config.option.basetemp = _BASETEMP
