"""
Markdown → Word 转换器的测试(tools/md_to_docx.py)。

这个工具产出的是要交给老师和教务系统的正式材料,格式错了很难发现
(Word 打开才看得出来),所以把几条最容易错的约定锁死在测试里:

  1. **中文字体必须写 w:eastAsia。** 只设 run.font.name 只影响 ASCII,
     中文会退回默认字体 —— 这是 python-docx 最经典的坑。
  2. **表格分隔行不能被当成正文。** `|---|---|` 若当普通段落渲染,
     论文表格里会多出一行乱码似的竖线。
  3. **代码块要原样保留缩进。** 技术路线图靠缩进表达层级,被吃掉就废了。
  4. **行内 `**粗体**` 与 `` `等宽` `` 要拆成多个 run**,不能被当作字面文本。
  5. **表格列数不齐时要补齐而不是崩。** 手写 Markdown 表格很容易少写一列。

不加载 Word、不做渲染:只读回 .docx 的 XML 结构做断言。
"""

import os
import sys
import zipfile

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_TOOLS = os.path.join(_REPO_ROOT, 'tools')
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import md_to_docx  # noqa: E402

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


# ---------------------------------------------------------------- 辅助

def _convert(tmp_path, md_text, name='out.docx'):
    out = str(tmp_path / name)
    md_to_docx.convert(md_text, out)
    return out


def _document_xml(path):
    with zipfile.ZipFile(path) as z:
        return z.read('word/document.xml').decode('utf-8')


def _paragraph_texts(path):
    """返回文档里每个段落的纯文本。"""
    from docx import Document
    doc = Document(path)
    return [p.text for p in doc.paragraphs]


def _east_asia_fonts(path):
    """收集文档里所有出现过的 w:eastAsia 取值。"""
    import re
    xml = _document_xml(path)
    return set(re.findall(r'w:eastAsia="([^"]+)"', xml))


# ---------------------------------------------------------------- 行内解析

def test_split_row_strips_outer_pipes():
    assert md_to_docx.split_row('| a | b |') == ['a', 'b']
    assert md_to_docx.split_row('a | b') == ['a', 'b']
    assert md_to_docx.split_row('| 只有一个 |') == ['只有一个']


def test_split_row_keeps_empty_cells():
    assert md_to_docx.split_row('| a |  | c |') == ['a', '', 'c']


@pytest.mark.parametrize('line,expected', [
    ('|---|---|', True),
    ('| --- | :---: |', True),
    ('|:--|--:|', True),
    ('| 内容 | 内容 |', False),
    ('没有竖线', False),
])
def test_is_table_sep(line, expected):
    assert md_to_docx.is_table_sep(line) is expected


def test_inline_regex_splits_bold_and_code():
    parts = md_to_docx._RE_INLINE.split('普通 **粗体** 与 `代码` 结束')
    assert '**粗体**' in parts
    assert '`代码`' in parts
    assert '普通 ' in parts


# ---------------------------------------------------------------- 字体

def test_chinese_font_is_written_as_east_asia(tmp_path):
    """中文必须落到 w:eastAsia,否则 Word 用默认字体渲染。"""
    path = _convert(tmp_path, '# 标题\n\n这是一段中文正文。\n')
    fonts = _east_asia_fonts(path)
    assert md_to_docx.BODY_FONT in fonts
    assert md_to_docx.HEAD_FONT in fonts


def test_code_block_uses_mono_font(tmp_path):
    path = _convert(tmp_path, '```\n数据 → 模型\n```\n')
    xml = _document_xml(path)
    assert md_to_docx.MONO_FONT in xml


def test_normal_style_has_east_asia_font(tmp_path):
    """Normal 样式的 rPr 里若没有 rFonts,中文会退回默认字体。"""
    path = _convert(tmp_path, '正文\n')
    xml = _document_xml(path)
    # 样式定义在 styles.xml
    with zipfile.ZipFile(path) as z:
        styles = z.read('word/styles.xml').decode('utf-8')
    assert 'w:eastAsia="%s"' % md_to_docx.BODY_FONT in styles


# ---------------------------------------------------------------- 结构

def test_headings_map_to_levels(tmp_path):
    path = _convert(tmp_path, '# 文档标题\n\n## 一级\n\n### 二级\n')
    from docx import Document
    doc = Document(path)
    styles = [p.style.name for p in doc.paragraphs if p.text.strip()]
    assert styles[0] == 'Title'
    assert 'Heading 1' in styles
    assert 'Heading 2' in styles


def test_table_becomes_real_table(tmp_path):
    md = '| 任务 | 准确率 |\n|---|---|\n| A | 0.754 |\n| B | 0.843 |\n'
    path = _convert(tmp_path, md)
    from docx import Document
    doc = Document(path)
    assert len(doc.tables) == 1
    t = doc.tables[0]
    assert len(t.rows) == 3
    assert len(t.columns) == 2
    assert t.cell(0, 0).text == '任务'
    assert t.cell(2, 1).text == '0.843'


def test_table_separator_not_rendered_as_text(tmp_path):
    """分隔行 |---|---| 不能变成正文段落。"""
    md = '| a | b |\n|---|---|\n| 1 | 2 |\n'
    path = _convert(tmp_path, md)
    texts = _paragraph_texts(path)
    assert not any('---' in t for t in texts)


def test_table_ragged_rows_are_padded(tmp_path):
    """行内列数少于表头时补齐,不能崩。"""
    md = '| a | b | c |\n|---|---|---|\n| 1 |\n'
    path = _convert(tmp_path, md)
    from docx import Document
    doc = Document(path)
    t = doc.tables[0]
    assert len(t.columns) == 3
    assert t.cell(1, 1).text == ''


def test_ragged_row_with_extra_cells_is_ignored(tmp_path):
    """行内列数多于表头时,多余的丢弃,不能崩。"""
    md = '| a | b |\n|---|---|\n| 1 | 2 | 3 | 4 |\n'
    path = _convert(tmp_path, md)
    from docx import Document
    doc = Document(path)
    assert len(doc.tables[0].columns) == 2


def test_code_block_preserves_indentation(tmp_path):
    """技术路线图靠缩进表达层级。"""
    md = '```\n数据获取\n        │\n        ├─→ 路线一\n```\n'
    path = _convert(tmp_path, md)
    texts = _paragraph_texts(path)
    joined = '\n'.join(texts)
    assert '        ├─→ 路线一' in joined


def test_lists_become_list_styles(tmp_path):
    md = '- 第一项\n- 第二项\n\n1. 有序一\n2. 有序二\n'
    path = _convert(tmp_path, md)
    from docx import Document
    doc = Document(path)
    styles = [p.style.name for p in doc.paragraphs if p.text.strip()]
    assert 'List Bullet' in styles
    assert 'List Number' in styles


def test_ordered_list_does_not_keep_the_number(tmp_path):
    """编号交给 Word 的列表样式,文本里不能残留 '1.'。"""
    path = _convert(tmp_path, '1. 第一条\n')
    texts = [t for t in _paragraph_texts(path) if t.strip()]
    assert '第一条' in texts
    assert not any(t.strip().startswith('1.') for t in texts)


def test_bold_run_is_bold(tmp_path):
    path = _convert(tmp_path, '普通 **重点** 收尾\n')
    from docx import Document
    doc = Document(path)
    para = [p for p in doc.paragraphs if '重点' in p.text][0]
    bold_runs = [r for r in para.runs if r.text == '重点']
    assert bold_runs and bold_runs[0].font.bold is True


def test_inline_code_run_uses_mono(tmp_path):
    path = _convert(tmp_path, '切换 `FIN_SENTIMENT_MODEL` 环境变量\n')
    xml = _document_xml(path)
    assert md_to_docx.MONO_FONT in xml


def test_blockquote_is_indented(tmp_path):
    path = _convert(tmp_path, '> 这是一条提示\n')
    from docx import Document
    from docx.shared import Cm
    doc = Document(path)
    para = [p for p in doc.paragraphs if '提示' in p.text][0]
    # Word 把长度存成 twip,再读回来与 Cm() 差几百 EMU 是正常的
    assert abs(para.paragraph_format.left_indent - Cm(0.74)) < 1000


def test_horizontal_rule_is_dropped(tmp_path):
    path = _convert(tmp_path, '上\n\n---\n\n下\n')
    texts = _paragraph_texts(path)
    assert '上' in texts and '下' in texts
    assert not any(set(t.strip()) <= set('-') and t.strip() for t in texts)


def test_empty_document_does_not_crash(tmp_path):
    path = _convert(tmp_path, '')
    assert os.path.isfile(path)


def test_page_is_a4_with_thesis_margins(tmp_path):
    path = _convert(tmp_path, '正文\n')
    from docx import Document
    from docx.shared import Cm
    s = Document(path).sections[0]
    # Word 以 twip 存储长度,读回来与 Cm() 有几百 EMU 的舍入差
    assert abs(s.page_width - Cm(21.0)) < 1000
    assert abs(s.page_height - Cm(29.7)) < 1000
    assert abs(s.left_margin - Cm(3.17)) < 1000


# ---------------------------------------------------------------- CLI

def test_main_writes_default_output(tmp_path, monkeypatch, capsys):
    src = tmp_path / 'x.md'
    src.write_text('# 标题\n\n正文\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    assert md_to_docx.main([str(src)]) == 0
    assert (tmp_path / 'x.docx').is_file()


def test_main_respects_out_flag(tmp_path):
    src = tmp_path / 'x.md'
    src.write_text('正文\n', encoding='utf-8')
    dst = tmp_path / 'sub' / 'y.docx'
    assert md_to_docx.main([str(src), '-o', str(dst)]) == 0
    assert dst.is_file()


def test_main_missing_input_exits(tmp_path):
    with pytest.raises(SystemExit):
        md_to_docx.main([str(tmp_path / 'nope.md')])


# ---------------------------------------------------------------- 真实材料

def test_real_proposal_material_converts(tmp_path):
    """仓库里的开题报告书必须能一键转成 Word。"""
    src = os.path.join(_REPO_ROOT, '论文', '开题报告书.md')
    if not os.path.isfile(src):
        pytest.skip('尚无 论文/开题报告书.md')
    with open(src, encoding='utf-8') as fh:
        text = fh.read()
    out = _convert(tmp_path, text, 'proposal.docx')
    from docx import Document
    doc = Document(out)
    # 必须含真实实验数字,防止手抄错
    joined = '\n'.join(p.text for p in doc.paragraphs)
    for t in doc.tables:
        for row in t.rows:
            joined += '\n' + ' '.join(c.text for c in row.cells)
    assert '0.7540' in joined
    assert '8516' in joined
