"""
文献综述(论文/文献综述.md)的交付前检查。

这篇综述是要交上去的正式材料,出错的地方都是"人眼扫一遍看不出来"的那类:
字数差几百、引了 [38] 却只列到 37 条、编号跳号、占位符没填。
所以把约定锁进测试里,改完随时能验一遍。

字数口径说明:
    学校要求 4000-5000 字。中文材料有两个常用口径 ——
    (a) 汉字个数; (b) Word「字数」= 汉字数 + 英文/数字词块数。
    两个口径都要落在区间内才算稳,所以下面两条都断言。
    参考文献表不计入正文篇幅。

不联网、不加载模型:纯文本断言。
"""

import os
import re

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_LIT_REVIEW = os.path.join(_REPO_ROOT, '论文', '文献综述.md')
_COLLECTION = os.path.join(_REPO_ROOT, '论文', '参考文献收集.md')

# 正文篇幅区间(学校要求)
_MIN_CHARS = 4000
_MAX_CHARS = 5000

# 结构应与开题报告书第二节的四个脉络一一对应
_REQUIRED_SECTIONS = [
    '文本情感分析的通用方法',
    '金融领域情感分析的专门研究',
    '投资者情绪与市场关系',
    '评价方法与标注质量',
]

_REF_MARKER = '## 参考文献'


# ---------------------------------------------------------------- 读取与切分

def _lit_review_text():
    if not os.path.isfile(_LIT_REVIEW):
        pytest.skip('尚无 论文/文献综述.md')
    with open(_LIT_REVIEW, encoding='utf-8') as fh:
        return fh.read()


def _split_body_refs(text):
    """把正文与参考文献表切开,返回 (正文, {编号: 条目行})。"""
    assert _REF_MARKER in text, '文献综述缺少「## 参考文献」章节'
    body, _, refs = text.partition(_REF_MARKER)
    entries = {}
    for line in refs.splitlines():
        m = re.match(r'^\[(\d+)\]\s+(.*)$', line.strip())
        if m:
            entries[int(m.group(1))] = m.group(2)
    return body, entries


def _cjk_count(text):
    """汉字个数。"""
    return len(re.findall(r'[\u4e00-\u9fff]', text))


def _word_metric(text):
    """Word「字数」口径:汉字数 + 英文/数字词块数。

    中英混排时 Word 把一个连续的英文/数字串算作一个"字",
    所以不能直接用 len(text)。
    """
    return _cjk_count(text) + len(
        re.findall(r'[A-Za-z0-9][A-Za-z0-9.\-]*', text))


# ---------------------------------------------------------------- 篇幅

def test_body_length_within_required_range():
    """正文汉字数必须落在 4000-5000 区间。"""
    body, _ = _split_body_refs(_lit_review_text())
    n = _cjk_count(body)
    assert _MIN_CHARS <= n <= _MAX_CHARS, (
        f'正文汉字数 {n} 超出要求区间 {_MIN_CHARS}-{_MAX_CHARS}')


def test_body_length_ok_under_word_metric_too():
    """按 Word「字数」口径(汉字 + 英数词块)也不能超上限。

    中英混排的稿子用两个口径算能差两三百字,只卡一个口径会在
    Word 里"字数"栏超限 —— 这里把另一个口径也钉住。
    """
    body, _ = _split_body_refs(_lit_review_text())
    n = _word_metric(body)
    assert _MIN_CHARS <= n <= _MAX_CHARS, (
        f'按 Word 字数口径 {n} 超出 {_MIN_CHARS}-{_MAX_CHARS}'
        f'(汉字 {_cjk_count(body)} + 英数词块)')


def test_reference_list_not_counted_as_body():
    """参考文献条目不能混进正文部分 —— 否则篇幅数字是虚的。

    注意不能拿作者名当判据:正文里本来就会写"赵妍妍等把任务归纳为…",
    那是正常的引用叙述。真正的泄漏是整条形如 `[n] 作者. 题名[J]…` 的条目行。
    """
    body, entries = _split_body_refs(_lit_review_text())
    assert entries, '参考文献表是空的'
    leaked = [ln.strip() for ln in body.splitlines()
              if re.match(r'^\[\d+\]\s+\S', ln.strip())]
    assert not leaked, f'参考文献条目混进了正文: {leaked[:3]}'


# ---------------------------------------------------------------- 引用完整性

def test_every_cited_number_has_a_reference_entry():
    """正文里引用的 [n] 必须在文末参考文献表里有对应条目。

    漏一条就是"引而不注",答辩时被问住很难解释。
    """
    body, entries = _split_body_refs(_lit_review_text())
    cited = {int(n) for n in re.findall(r'\[(\d+)\]', body)}
    assert cited, '正文里一处引用都没有'
    missing = sorted(cited - set(entries))
    assert not missing, f'正文引用了但文末没有的编号: {missing}'


def test_no_orphan_reference_entries():
    """参考文献表里不能有正文从未引用的条目(凑数嫌疑)。"""
    body, entries = _split_body_refs(_lit_review_text())
    cited = {int(n) for n in re.findall(r'\[(\d+)\]', body)}
    orphan = sorted(set(entries) - cited)
    assert not orphan, f'列在文末但正文从未引用的编号: {orphan}'


def test_reference_numbers_are_contiguous():
    """编号必须从 1 开始连续,不能跳号 —— 跳号说明删条目时漏改了。"""
    _, entries = _split_body_refs(_lit_review_text())
    nums = sorted(entries)
    assert nums == list(range(1, len(nums) + 1)), f'编号不连续: {nums}'


def test_reference_entries_look_like_gbt7714():
    """每条至少要有作者、题名与出处三要素,不能只写一个标题。"""
    _, entries = _split_refs_or_skip()
    for num, entry in sorted(entries.items()):
        assert len(entry) > 25, f'[{num}] 著录过短,缺出处信息: {entry}'
        assert re.search(r'\[(J|C|M|D|EB/OL|R)\]', entry), \
            f'[{num}] 缺文献类型标识([J]/[C]/[EB/OL] 等): {entry}'


def test_entries_carry_doi_or_arxiv_id():
    """每条都要带可访问标识(DOI / arXiv 号 / URL)。

    综述开头写明"元数据均经 Crossref / arXiv / ACL Anthology / 期刊官网
    逐条核实,并给出可访问来源",这条断言就是兑现那句话 ——
    缺标识的条目老师没法复核,等于自打脸。
    """
    _, entries = _split_refs_or_skip()
    for num, entry in sorted(entries.items()):
        assert re.search(r'DOI:?\s*10\.|arXiv:\d|https?://', entry), \
            f'[{num}] 缺可访问标识(DOI / arXiv / URL): {entry}'


def test_no_placeholder_markers_remain():
    """「待补」「待核」占位符必须清零 —— 交上去空着就是事故。"""
    text = _lit_review_text()
    for marker in ('待补', '待核', 'TODO', 'XXX'):
        assert marker not in text, f'文献综述里还留着占位符「{marker}」'


# ---------------------------------------------------------------- 结构

def test_structure_mirrors_proposal_section_two():
    """四个研究脉络的小节标题应与开题报告书第二节一致。

    综述是开题报告书第二节的扩写,标题对不上说明有一块没展开。
    """
    text = _lit_review_text()
    headings = [m.group(2).strip()
                for m in re.finditer(r'^(#{2,3})\s+(.*)$', text, re.M)]
    for want in _REQUIRED_SECTIONS:
        assert any(want in h for h in headings), \
            f'缺少与开题报告书第二节对应的小节: {want}'


def test_has_intro_and_gap_sections():
    """综述要有引言与「现有研究的不足」收口,不能只是文献罗列。"""
    text = _lit_review_text()
    assert re.search(r'^##\s+一、引言', text, re.M), '缺少引言'
    assert re.search(r'^##\s+.*不足.*切入点', text, re.M), \
        '缺少「现有研究的不足与本文切入点」章节'


# ---------------------------------------------------------------- 与已核实清单一致

def _collection_count():
    """参考文献收集.md 里已核实的条目数(推荐 26 + 补充 11)。"""
    if not os.path.isfile(_COLLECTION):
        pytest.skip('尚无 论文/参考文献收集.md')
    with open(_COLLECTION, encoding='utf-8') as fh:
        text = fh.read()
    numbered = re.findall(r'^\[(\d+)\]', text, re.M)
    supplemental = re.findall(r'^\[S(\d+)\]', text, re.M)
    return len(numbered) + len(supplemental)


def test_reference_count_matches_verified_collection():
    """综述条目数应等于《参考文献收集.md》中已核实的条目总数。

    用户明确交代过这批文献"已逐条核实、不需再联网核实",
    所以综述只能从这份清单里取,不能凭空多出条目。
    """
    _, entries = _split_body_refs(_lit_review_text())
    expected = _collection_count()
    assert len(entries) == expected, (
        f'综述列了 {len(entries)} 条,已核实清单是 {expected} 条')


def _split_refs_or_skip():
    return _split_body_refs(_lit_review_text())
