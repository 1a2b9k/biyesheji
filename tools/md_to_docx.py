"""
Markdown → Word(.docx) 转换器 —— 让论文材料能从纯文本重新生成。

为什么需要这个脚本:
    开题报告书、文献综述、论文正文这些材料要交给老师和教务系统,
    必须是可以直接打开的 .docx;但 .docx 是二进制,改一个字看不出改了哪里,
    也没法 diff。所以约定:论文材料一律先用 Markdown 写(可版本管理、
    可 diff、可 grep),再一条命令导出 Word。
    这样"论文里的每个数字都能重跑出来"这条原则才延伸到文档层。

用法:
    .python\\python.exe tools\\md_to_docx.py 论文\\开题报告书.md
    .python\\python.exe tools\\md_to_docx.py 论文\\开题报告书.md -o 论文\\开题报告书.docx

支持的语法(够用即可,不做完整 Markdown 实现):
    # / ## / ### / ####     标题(# 为文档标题)
    **粗体**  `等宽`         行内格式
    - / * / +                无序列表
    1. 2.                    有序列表
    >                        引用
    | a | b |                表格(第二行为 ---|--- 分隔行)
    ```                      代码块(等宽字体,保留缩进)
    ---                      分隔线(忽略)

退出码 0 = 成功。
"""

import argparse
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(_HERE)

# 中文字体必须显式设置 w:eastAsia,只设 run.font.name 只影响 ASCII,
# 中文会退回默认字体 —— 这是 python-docx 最常见的坑。
BODY_FONT = '宋体'
HEAD_FONT = '黑体'
MONO_FONT = 'Consolas'

BODY_SIZE = 12.0     # 小四
CODE_SIZE = 10.5     # 五号

_RE_INLINE = re.compile(r'(\*\*.+?\*\*|`[^`]+`)')
_RE_ULIST = re.compile(r'^\s*[-*+]\s+(.*)$')
_RE_OLIST = re.compile(r'^\s*(\d+)[.)]\s+(.*)$')
_RE_HEAD = re.compile(r'^(#{1,6})\s+(.*)$')
_RE_TABLE_SEP = re.compile(r'^\s*\|?[\s:|-]+\|[\s:|-]*$')


# ------------------------------------------------------------------ 字体工具

def set_font(run, name=BODY_FONT, size=None, bold=None, mono=False):
    """设置 run 的字体,中英文都覆盖。

    中文必须通过 w:eastAsia 指定,否则 Word 用默认中文字体渲染。
    """
    from docx.oxml.ns import qn
    from docx.shared import Pt

    ascii_name = MONO_FONT if mono else name
    run.font.name = ascii_name
    rpr = run._element.get_or_add_rPr()
    # get_or_add_rFonts() 会在缺失时新建,直接 .rFonts 可能是 None
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn('w:ascii'), ascii_name)
    rfonts.set(qn('w:hAnsi'), ascii_name)
    # 代码块里的制表符/框线字符走东亚字体,否则会显示成方框
    rfonts.set(qn('w:eastAsia'), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold


def add_runs(paragraph, text, size=None):
    """把一行文本写进段落,识别 **粗体** 与 `等宽`。"""
    for part in _RE_INLINE.split(text):
        if not part:
            continue
        if part.startswith('**') and part.endswith('**') and len(part) > 4:
            run = paragraph.add_run(part[2:-2])
            set_font(run, size=size, bold=True)
        elif part.startswith('`') and part.endswith('`') and len(part) > 2:
            run = paragraph.add_run(part[1:-1])
            set_font(run, size=size, mono=True)
        else:
            run = paragraph.add_run(part)
            set_font(run, size=size)


# ------------------------------------------------------------------ 表格解析

def split_row(line):
    """把 `| a | b |` 切成 ['a', 'b']。"""
    s = line.strip()
    if s.startswith('|'):
        s = s[1:]
    if s.endswith('|'):
        s = s[:-1]
    return [c.strip() for c in s.split('|')]


def is_table_sep(line):
    """判断是不是表格的分隔行(|---|---|)。"""
    s = line.strip()
    if '|' not in s:
        return False
    return bool(_RE_TABLE_SEP.match(s))


# ------------------------------------------------------------------ 主转换

def convert(md_text, out_path):
    """把 Markdown 文本写成 .docx,返回写入路径。"""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    doc = Document()

    # 页面: A4 + 论文常用页边距
    for section in doc.sections:
        section.page_width = Cm(21.0)
        section.page_height = Cm(29.7)
        section.top_margin = Cm(2.54)
        section.bottom_margin = Cm(2.54)
        section.left_margin = Cm(3.17)
        section.right_margin = Cm(3.17)

    # 正文样式: 宋体小四、1.5 倍行距
    normal = doc.styles['Normal']
    normal.font.size = Pt(BODY_SIZE)
    normal.paragraph_format.line_spacing = 1.5
    # 样式里的 rPr 可能没有 rFonts 子元素,必须用 get_or_add_rFonts()
    from docx.oxml.ns import qn
    normal.element.get_or_add_rPr().get_or_add_rFonts().set(
        qn('w:eastAsia'), BODY_FONT)

    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.strip()

        # --- 代码块
        if stripped.startswith('```'):
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith('```'):
                buf.append(lines[i])
                i += 1
            i += 1  # 跳过结束的 ```
            for cl in buf:
                p = doc.add_paragraph()
                p.paragraph_format.line_spacing = 1.0
                p.paragraph_format.space_after = Pt(0)
                run = p.add_run(cl if cl.strip() else ' ')
                set_font(run, size=CODE_SIZE, mono=True)
            continue

        # --- 表格
        if stripped.startswith('|') and i + 1 < len(lines) \
                and is_table_sep(lines[i + 1]):
            header = split_row(lines[i])
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                rows.append(split_row(lines[i]))
                i += 1
            ncol = len(header)
            table = doc.add_table(rows=1 + len(rows), cols=ncol)
            table.style = 'Table Grid'
            for c, text in enumerate(header):
                cell = table.cell(0, c)
                cell.text = ''
                add_runs(cell.paragraphs[0], text, size=BODY_SIZE - 1)
                for run in cell.paragraphs[0].runs:
                    run.font.bold = True
            for r, row in enumerate(rows, start=1):
                for c in range(ncol):
                    cell = table.cell(r, c)
                    cell.text = ''
                    val = row[c] if c < len(row) else ''
                    add_runs(cell.paragraphs[0], val, size=BODY_SIZE - 1)
            doc.add_paragraph()
            continue

        # --- 标题
        m = _RE_HEAD.match(stripped)
        if m:
            level = len(m.group(1))
            style = 'Title' if level == 1 else 'Heading %d' % (level - 1)
            p = doc.add_paragraph(style=style)
            add_runs(p, m.group(2))
            for run in p.runs:
                set_font(run, name=HEAD_FONT)
            i += 1
            continue

        # --- 无序列表
        m = _RE_ULIST.match(line)
        if m:
            p = doc.add_paragraph(style='List Bullet')
            add_runs(p, m.group(1))
            i += 1
            continue

        # --- 有序列表
        m = _RE_OLIST.match(line)
        if m:
            p = doc.add_paragraph(style='List Number')
            add_runs(p, m.group(2))
            i += 1
            continue

        # --- 引用
        if stripped.startswith('>'):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.74)
            add_runs(p, stripped.lstrip('> ').strip())
            for run in p.runs:
                run.font.italic = True
            i += 1
            continue

        # --- 分隔线 / 空行
        if not stripped or set(stripped) <= set('-*_') and len(stripped) >= 3:
            i += 1
            continue

        # --- 普通段落
        p = doc.add_paragraph()
        p.paragraph_format.first_line_indent = Pt(BODY_SIZE * 2)
        add_runs(p, stripped)
        i += 1

    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    doc.save(out_path)
    return out_path


def main(argv=None):
    ap = argparse.ArgumentParser(description='Markdown → Word(.docx)')
    ap.add_argument('input', help='输入的 .md 文件')
    ap.add_argument('-o', '--out', default=None,
                    help='输出的 .docx(默认与输入同目录同名)')
    args = ap.parse_args(argv)

    if not os.path.isfile(args.input):
        raise SystemExit('输入文件不存在: %s' % args.input)

    with open(args.input, encoding='utf-8') as fh:
        md_text = fh.read()

    out = args.out
    if not out:
        base = os.path.splitext(args.input)[0]
        out = base + '.docx'

    convert(md_text, out)
    print('已生成 %s' % os.path.relpath(out, _WS))
    return 0


if __name__ == '__main__':
    sys.exit(main())
