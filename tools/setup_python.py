"""
把工作区外的 Python 解释器「本地化」进工作区,让整套环境自洽。

用法:
    <任意可用的 python.exe> tools\\setup_python.py

背景(实测):
    本机 Python 装在 C:\\Users\\qp\\python312(embeddable 发行版),
    该目录在 DSH 沙箱工作区之外,因此:
      * 沙箱不允许往里写 —— pip 无法安装到 site-packages;
      * 无法修改 python312._pth —— 补丁与自装包都进不了 sys.path;
      * 该发行版忽略 PYTHONPATH —— 常规注入方案无效。

做法:
    解释器本体很小(约 25 MB;242 MB 全是第三方包),把它复制进
    <工作区>\\.python,然后改写 _pth,把补丁目录与自装包目录写进去。
    包仍装在 <工作区>\\.pylibs,由 pipp.py 通过 PYTHONUSERBASE 指定。

产出:
    .python\\python.exe          —— 以后一律用这个解释器
    .python\\python312._pth      —— 已加入 .pysandbox 与 .pylibs
"""

import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(_HERE)
_DST = os.path.join(_WS, '.python')
_PYLIBS = os.path.join(_WS, '.pylibs', 'Python312', 'site-packages')

# 解释器本体:根目录下的文件与这些子目录;Lib 只建空壳(包走 .pylibs)
_COPY_FILES = True
_SKIP_DIRS = {'Lib', '__pycache__'}

# _pth 的搜索顺序即 sys.path 顺序:
#   1. 本地解释器自带的标准库
#   2. .pysandbox  —— 沙箱兼容补丁(必须先于 site 导入)
#   3. .pylibs     —— 本工作区新装的包,优先级高于只读底座
#   4. 原 site-packages —— 只读底座(242 MB 既有包 + pip 本体,不复制)
_PTH_TEMPLATE = """python312.zip
.
..\\.pysandbox
..\\.pylibs\\Python312\\site-packages
Lib\\site-packages
{base_site_packages}

# 自动执行 site.main():导入 sitecustomize(沙箱兼容补丁)
import site
"""


def find_source():
    """定位源解释器:优先命令行参数,其次环境变量,最后当前解释器。"""
    if len(sys.argv) > 1:
        return sys.argv[1]
    env = os.environ.get('DSH_SRC_PYTHON')
    if env:
        return env
    return sys.executable


def main():
    src = find_source()
    src_dir = os.path.dirname(os.path.abspath(src))
    print('源解释器目录: %s' % src_dir)

    if os.path.abspath(src_dir) == os.path.abspath(_DST):
        print('源与目标相同,无需复制;仅重写 _pth。')

    # 1) 复制解释器本体
    if os.path.abspath(src_dir) != os.path.abspath(_DST):
        if os.path.isdir(_DST):
            shutil.rmtree(_DST)
        os.makedirs(_DST, exist_ok=True)

        copied = 0
        for name in os.listdir(src_dir):
            if name in _SKIP_DIRS:
                continue
            s = os.path.join(src_dir, name)
            d = os.path.join(_DST, name)
            if os.path.isdir(s):
                shutil.copytree(s, d, dirs_exist_ok=True)
                copied += 1
            else:
                shutil.copy2(s, d)
                copied += 1
        print('已复制 %d 个顶层项 -> %s' % (copied, _DST))

    # 2) 建目录骨架
    os.makedirs(os.path.join(_DST, 'Lib', 'site-packages'), exist_ok=True)
    os.makedirs(_PYLIBS, exist_ok=True)

    # 3) 改写 _pth(把原 site-packages 作为只读底座排在最后)
    base_site = os.path.join(src_dir, 'Lib', 'site-packages')
    pth = os.path.join(_DST, 'python312._pth')
    with open(pth, 'w', encoding='utf-8') as fh:
        fh.write(_PTH_TEMPLATE.format(base_site_packages=base_site))
    print('已写入 %s' % pth)
    print('只读底座: %s' % base_site)

    print()
    print('完成。以后请使用:')
    print('    %s' % os.path.join(_DST, 'python.exe'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
