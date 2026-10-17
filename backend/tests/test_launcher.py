"""
桌面快捷启动的测试。

这里测三样东西,它们各自对应一类"双击了没反应"的故障:

  1. `scripts/start-all.cmd` —— 一键启动器。必须纯 ASCII(和其余 .cmd 同样的
     cmd.exe/GBK 约束)、必须先等后端就绪再起前端(前端代理 /api 到 :8000,
     后端没起来时页面能打开但所有数据接口都 502,看起来像"系统坏了")。
  2. `scripts/make-shortcut.ps1` —— 建 .lnk。必须是 UTF-8 **带** BOM:
     快捷方式名是中文,而 Windows PowerShell 5.1 把无 BOM 的 .ps1 按 ANSI
     (本机 GBK)解码,PowerShell 7 按 UTF-8 —— 不带 BOM 就有一边读出乱码,
     而且不报错,只是桌面上多一个名字是问号的图标。
  3. `tools/make_icon.py` —— 图标。配色必须和前端 chart.js 一致,否则图标和
     页面上的涨跌色会打架。

真起服务的冒烟测试不放在这里(太慢),已有 `test_start_scripts.py` 覆盖。
"""

import os
import re
import subprocess

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_REPO_ROOT, 'scripts')
_ASSETS = os.path.join(_REPO_ROOT, 'assets')
_TOOLS = os.path.join(_REPO_ROOT, 'tools')
_PY = os.path.join(_REPO_ROOT, '.python', 'python.exe')

_START_ALL = os.path.join(_SCRIPTS, 'start-all.cmd')
_SHORTCUT_PS1 = os.path.join(_SCRIPTS, 'make-shortcut.ps1')
_ICON_PY = os.path.join(_TOOLS, 'make_icon.py')
_ICON = os.path.join(_ASSETS, 'app.ico')


# ------------------------------------------------------------ 一键启动脚本

def _start_all_text():
    return open(_START_ALL, encoding='ascii').read()


def test_start_all_exists():
    assert os.path.exists(_START_ALL), '缺少一键启动脚本 scripts/start-all.cmd'


def test_start_all_is_ascii_only():
    """cmd.exe 按 OEM 代码页(本机 GBK)解析 .cmd,非 ASCII 会破坏解析。"""
    raw = open(_START_ALL, 'rb').read()
    bad = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
    assert not bad, 'start-all.cmd 含非 ASCII 字节,首个位于偏移 %d' % bad[0][0]


def test_start_all_has_no_bom():
    raw = open(_START_ALL, 'rb').read(3)
    assert raw != b'\xef\xbb\xbf', 'start-all.cmd 不应带 UTF-8 BOM'


def test_start_all_calls_the_two_existing_scripts():
    """不许自己重写一遍启动命令 —— 那会让 start-backend 的沙箱约束失去作用。"""
    text = _start_all_text()
    assert 'start-backend.cmd' in text
    assert 'start-frontend.cmd' in text


def test_start_all_waits_for_backend_before_frontend():
    """前端代理 /api 到 :8000,后端没起来时页面能开但接口全 502。

    断言的是顺序:第一次等 8000 的位置必须早于第一次等 5173 的位置。
    """
    text = _start_all_text()
    first_backend = text.find('8000/api/health')
    first_frontend = text.find('5173/')
    assert first_backend != -1 and first_frontend != -1
    assert first_backend < first_frontend, '必须先等后端就绪再起前端'


def test_start_all_skips_services_already_running():
    """双击两次不该起两份进程(第二份会抢端口失败并弹出难看的报错)。"""
    text = _start_all_text()
    assert 'already up' in text
    # 两个服务各要有一处"已就绪则跳过"的检查
    assert text.count(':http_ok') >= 2


def test_start_all_opens_the_browser():
    text = _start_all_text()
    assert 'http://127.0.0.1:5173/' in text


def test_start_all_does_not_use_timeout_command():
    """`timeout` 需要 stdin,在重定向环境下直接报错退出(实测踩过)。

    `ping -n` 是等效且无 stdin 依赖的写法。
    """
    text = _start_all_text()
    assert 'timeout /t' not in text
    assert 'ping -n' in text


def test_start_all_uses_local_powershell_for_probing():
    """探测 HTTP 用 powershell,不用 curl —— 后者在旧版 Win10 上不保证存在。"""
    text = _start_all_text()
    assert 'Invoke-WebRequest' in text


# ------------------------------------------------------------ 快捷方式脚本

def _shortcut_text():
    return open(_SHORTCUT_PS1, encoding='utf-8-sig').read()


def _shortcut_code():
    """只取脚本里真正会执行的语句,去掉注释行。

    有几条断言要查"某个字符串没出现",而解释为什么不能那么写的注释里
    恰恰会提到那个字符串 —— 不剥注释就会把正确的注释判成违规。
    """
    lines = _shortcut_text().splitlines()
    return '\n'.join(ln for ln in lines if not ln.lstrip().startswith('#'))


def test_shortcut_script_exists():
    assert os.path.exists(_SHORTCUT_PS1), '缺少 scripts/make-shortcut.ps1'


def test_shortcut_script_has_utf8_bom():
    """带中文名的 .ps1 必须有 BOM,否则 5.1 按 GBK 解码成乱码且不报错。"""
    raw = open(_SHORTCUT_PS1, 'rb').read(3)
    assert raw == b'\xef\xbb\xbf', (
        'make-shortcut.ps1 应带 UTF-8 BOM(文件名含中文,见文件头注释)')


def test_shortcut_script_accepts_a_destination_override():
    """必须能把快捷方式建到别处,否则没法在测试里验证而不污染真实桌面。"""
    text = _shortcut_text()
    assert '$Destination' in text
    assert 'GetFolderPath' in text


def test_shortcut_script_targets_start_all():
    text = _shortcut_text()
    assert 'start-all.cmd' in text


def test_shortcut_script_does_not_wrap_in_cmd_exe():
    """TargetPath 直接指向 .cmd;塞进 cmd.exe /c "..." 是引号出错的经典来源。"""
    code = _shortcut_code()
    assert 'cmd.exe' not in code
    assert 'cmd /c' not in code


def test_shortcut_script_guards_against_overwrite():
    text = _shortcut_text()
    assert '$Force' in text
    assert 'already exists' in text


def test_shortcut_script_sets_working_directory():
    """工作目录必须是仓库根,否则 .cmd 里的相对路径全错。"""
    text = _shortcut_text()
    assert 'WorkingDirectory' in text


def test_shortcut_script_only_sets_icon_when_present():
    """空字符串赋给 IconLocation 会留下字面量 ',0',Windows 就退回通用图标。"""
    text = _shortcut_text()
    assert '$hasIcon' in text
    # 赋值语句必须包在 if ($hasIcon) 里
    assert re.search(r'if\s*\(\s*\$hasIcon\s*\)\s*\{\s*\$lnk\.IconLocation', text)


@pytest.mark.skipif(os.name != 'nt', reason='WScript.Shell is Windows-only')
def test_shortcut_script_actually_creates_a_working_lnk(tmp_path):
    """真跑一次,把 .lnk 建到临时目录,再读回属性核对。"""
    out = tmp_path / 'desk'
    out.mkdir()
    proc = subprocess.run(
        ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
         '-File', _SHORTCUT_PS1, '-Destination', str(out), '-Force'],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=120)
    assert proc.returncode == 0, '建快捷方式失败:\n%s\n%s' % (proc.stdout, proc.stderr)

    lnks = list(out.glob('*.lnk'))
    assert len(lnks) == 1, '应恰好生成一个 .lnk,实际 %r' % [p.name for p in lnks]
    lnk = lnks[0]

    # 中文名要能原样落地(这是 BOM 那条断言的端到端验证)
    assert lnk.stem == '启动财经舆情平台', '快捷方式名乱码: %r' % lnk.stem

    read = subprocess.run(
        ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
         '-Command',
         "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
         "Write-Output $s.TargetPath; Write-Output $s.WorkingDirectory" % lnk],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=120)
    lines = [ln.strip() for ln in read.stdout.splitlines() if ln.strip()]
    assert lines, '读回快捷方式属性失败:\n%s' % read.stderr
    target = lines[0].replace('/', '\\')
    assert target.lower().endswith('scripts\\start-all.cmd'), target
    assert lines[1].rstrip('\\').lower() == _REPO_ROOT.lower(), lines[1]


# ------------------------------------------------------------ 图标

def test_icon_generator_exists():
    assert os.path.exists(_ICON_PY), '缺少 tools/make_icon.py'


def test_icon_file_exists():
    assert os.path.exists(_ICON), (
        '缺少 assets/app.ico —— 跑 .python\\python.exe tools\\make_icon.py 生成')


def test_icon_is_a_real_ico_with_all_sizes():
    """Windows 会按场景(16 任务栏 / 32 桌面 / 256 大图标)挑不同尺寸。"""
    from PIL import Image

    with Image.open(_ICON) as im:
        assert im.format == 'ICO', im.format
        sizes = sorted(im.info.get('sizes', []))
    expected = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                (128, 128), (256, 256)]
    assert sizes == expected, sizes


def test_icon_palette_matches_frontend():
    """图标配色和前端 chart.js 必须同源,否则图标和页面涨跌色打架。"""
    sys_path_backup = list(__import__('sys').path)
    __import__('sys').path.insert(0, _TOOLS)
    try:
        import make_icon
    finally:
        __import__('sys').path[:] = sys_path_backup

    chart = open(os.path.join(_REPO_ROOT, 'frontend', 'src', 'utils', 'chart.js'),
                 encoding='utf-8').read()
    for name in ('POS', 'NEG', 'NEU'):
        value = getattr(make_icon, name).lower()
        assert value in chart.lower(), (
            'make_icon.%s = %s 在前端 chart.js 里找不到' % (name, value))


def test_icon_render_is_square_and_transparent_corner():
    """圆角外的四个角必须是透明的,否则贴到浅色桌面上会露出黑方块。"""
    import sys
    sys.path.insert(0, _TOOLS)
    try:
        import make_icon
        im = make_icon.render(64)
    finally:
        sys.path.remove(_TOOLS)

    assert im.size == (64, 64)
    assert im.mode == 'RGBA'
    for xy in ((0, 0), (63, 0), (0, 63), (63, 63)):
        assert im.getpixel(xy)[3] == 0, '角落 %r 不透明' % (xy,)
    # 中心必须是不透明的墨色底
    assert im.getpixel((32, 32))[3] == 255
