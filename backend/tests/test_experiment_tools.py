"""
训练与实验报告工具的测试。

这两处逻辑最容易出错,而且错了很难发现:
  1. apply_task 的样本筛选与标签重映射 —— 若切分错了,准确率会
     悄悄变化,但没有任何报错。任务 B 剔除中性后标签必须保持
     0/1 不变,否则 "negative" 会被算成 "positive"。
  2. experiment_report 读结果文件时的解析 —— 文件名约定
     <model>-<task>.json,而 "3class" 本身不含短横线,
     但 "academic-paper" 这种 model 名会,所以必须用 rpartition
     从右边切。

不加载模型、不跑训练:训练正确性由 data/experiments/*.json 里的
真实数字保证,这里只测纯逻辑。
"""

import json
import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_TOOLS = os.path.join(_REPO_ROOT, 'tools')
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import experiment_report  # noqa: E402
import train_sentiment  # noqa: E402


# ---------------------------------------------------------------- 任务切分

def test_3class_keeps_everything():
    texts = ['a', 'b', 'c']
    labels = [0, 1, 2]
    t, y, names = train_sentiment.apply_task(texts, labels, '3class')
    assert t == texts
    assert y == labels
    assert names == ['negative', 'positive', 'neutral']


def test_polarity_drops_neutral_and_keeps_labels():
    """剔除中性样本,但 0/1 编号不能重排。"""
    t, y, names = train_sentiment.apply_task(
        ['n', 'p', 'neu', 'n2'], [0, 1, 2, 0], 'polarity')
    assert t == ['n', 'p', 'n2']
    assert y == [0, 1, 0]
    assert names == ['negative', 'positive']


def test_polarity_all_neutral_gives_empty():
    t, y, names = train_sentiment.apply_task(['a'], [2], 'polarity')
    assert t == []
    assert y == []
    assert names == ['negative', 'positive']


def test_neutral_task_is_binary():
    """2 变 0(中性),0/1 变 1(有情感)。"""
    t, y, names = train_sentiment.apply_task(
        ['a', 'b', 'c'], [2, 0, 1], 'neutral')
    assert t == ['a', 'b', 'c']
    assert y == [0, 1, 1]
    assert names == ['neutral', 'sentiment']


def test_unknown_task_raises():
    with pytest.raises(SystemExit):
        train_sentiment.apply_task(['a'], [0], 'nope')


# ---------------------------------------------------------------- 清洗

@pytest.mark.parametrize('raw,expected', [
    ('  空格 前后 ', '空格前后'),
    ('换行\n制表\t', '换行制表'),
    ('', ''),
    ('正常标题', '正常标题'),
])
def test_clean_strips_whitespace(raw, expected):
    """分词前必须去空白,否则 jieba 会切出空白片段当特征。"""
    assert train_sentiment.clean(raw) == expected


# ---------------------------------------------------------------- 超参数

def test_hyperparams_are_pinned():
    """这些值写进了论文,改动必须是有意识的 —— 锁住防止误改。"""
    assert train_sentiment.SEED == 42
    assert train_sentiment.MAX_LEN == 64
    assert train_sentiment.BATCH_SIZE == 32
    assert train_sentiment.EPOCHS == 3
    assert train_sentiment.LR == 2e-5
    assert train_sentiment.LABELS == ['negative', 'positive', 'neutral']


# ---------------------------------------------------------------- 报告解析

def test_load_results_parses_filenames(tmp_path):
    (tmp_path / 'bert-3class.json').write_text(
        json.dumps({'accuracy': 0.75}), encoding='utf-8')
    (tmp_path / 'tfidf-polarity.json').write_text(
        json.dumps({'accuracy': 0.70}), encoding='utf-8')

    r = experiment_report.load_results(str(tmp_path))
    assert r[('3class', 'bert')]['accuracy'] == 0.75
    assert r[('polarity', 'tfidf')]['accuracy'] == 0.70


def test_load_results_splits_on_last_dash(tmp_path):
    """任务名不含短横线,但模型名可能含 —— 必须从右边切。"""
    (tmp_path / 'academic-paper-3class.json').write_text(
        json.dumps({'accuracy': 0.5}), encoding='utf-8')
    r = experiment_report.load_results(str(tmp_path))
    # 模型名不在已知集合里,应被跳过而不是猜成 'paper'
    assert r == {}


def test_load_results_ignores_unknown_and_junk(tmp_path):
    (tmp_path / 'notes.json').write_text('{}', encoding='utf-8')
    (tmp_path / 'readme.md').write_text('x', encoding='utf-8')
    (tmp_path / 'bert-3class.json.bak').write_text('{}', encoding='utf-8')
    assert experiment_report.load_results(str(tmp_path)) == {}


def test_load_results_missing_dir_is_empty():
    assert experiment_report.load_results('/no/such/dir') == {}


# ---------------------------------------------------------------- 渲染

def _result(**over):
    base = {
        'accuracy': 0.7540, 'macro_f1': 0.7491, 'weighted_f1': 0.7531,
        'per_class': {
            'negative': {'precision': 0.7197, 'recall': 0.6849,
                         'support': 641},
            'positive': {'precision': 0.7828, 'recall': 0.7346,
                         'support': 618},
            'neutral': {'precision': 0.7585, 'recall': 0.8186,
                        'support': 871},
        },
        'confusion_matrix': [[439, 81, 121], [58, 454, 106],
                             [113, 45, 713]],
        'n_train': 8516, 'n_test': 2130, 'elapsed_sec': 139.4,
        'majority_baseline': {'label': 'neutral', 'accuracy': 0.4089},
    }
    base.update(over)
    return base


def test_render_empty_points_at_training_command():
    out = experiment_report.render({})
    assert 'train_sentiment.py' in out
    assert '尚无实验结果' in out


def test_render_includes_both_models_and_delta():
    out = experiment_report.render({
        ('3class', 'tfidf'): _result(accuracy=0.6296, macro_f1=0.6204),
        ('3class', 'bert'): _result(),
    })
    assert 'TF-IDF' in out
    assert 'BERT' in out
    assert '+0.1244' in out      # 准确率提升
    assert '+0.1287' in out      # 宏 F1 提升


def test_render_computes_f1_when_absent():
    """老结果文件没有 f1 字段,应现算而不是渲染成 '-'。"""
    r = _result(per_class={
        'negative': {'precision': 0.5, 'recall': 0.5, 'support': 10},
    })
    out = experiment_report.render({('3class', 'bert'): r})
    assert '0.5000' in out


def test_render_handles_scalar_majority_baseline():
    """旧格式把多数类基线存成纯数字,也要能渲染。"""
    out = experiment_report.render({
        ('3class', 'bert'): _result(majority_baseline=0.4089),
    })
    assert '0.4089' in out
    assert '+0.3451' in out


def test_render_confusion_matrix_rows():
    out = experiment_report.render({('3class', 'bert'): _result()})
    assert '混淆矩阵' in out
    assert '| negative | 439 | 81 | 121 |' in out


def test_render_single_model_has_no_delta():
    out = experiment_report.render({('3class', 'bert'): _result()})
    assert '提升(acc)' in out
    # 只有一个模型时无法比较,不该出现编造的数字
    assert '+0.0000' not in out


def test_render_macro_row_has_precision_and_recall():
    """macro avg 行必须填出宏精确率与宏召回率。

    早先版本渲染成 `| macro avg | - | - | ...`,而这两个数完全
    可由 per_class 推出 —— 报告里留空会让读者以为没测。
    """
    out = experiment_report.render({('3class', 'bert'): _result()})
    # (0.7197+0.7828+0.7585)/3 = 0.7537, (0.6849+0.7346+0.8186)/3 = 0.7460
    assert '| macro avg | 0.7537 | 0.7460 | **0.7491** | 2130 |' in out


def test_macro_avg_from_per_class():
    mp, mr = experiment_report.macro_avg({
        'a': {'precision': 0.5, 'recall': 1.0},
        'b': {'precision': 1.0, 'recall': 0.0},
    })
    assert (mp, mr) == (0.75, 0.5)


def test_macro_avg_empty_or_partial_is_none():
    """缺字段时返回 None,让渲染层写 '-',而不是拿 0 冒充。"""
    assert experiment_report.macro_avg({}) == (None, None)
    assert experiment_report.macro_avg(None) == (None, None)
    assert experiment_report.macro_avg({'a': {'precision': 0.5}}) == (None, None)


def test_evaluate_stores_f1_and_macro_pr():
    """evaluate 必须把 f1 与宏精确率/召回率一并落盘。

    报告工具虽然能从 per_class 现算,但结果文件本身应当是自洽的,
    否则任何直接读 json 的下游(比如论文里的表格脚本)都得重算。
    """
    y_true = [0, 1, 2, 0, 1, 2]
    y_pred = [0, 1, 2, 0, 2, 2]
    m = train_sentiment.evaluate(y_true, y_pred, ['negative', 'positive', 'neutral'])
    assert 'f1' in m['per_class']['negative']
    assert 'macro_precision' in m
    assert 'macro_recall' in m
    # negative: 2 个真实,2 个预测对 -> p=r=f1=1.0
    assert m['per_class']['negative']['f1'] == 1.0
    # neutral: 2 个真实全对,但 positive 的第 2 条被误判成 neutral,
    # 所以 pred_total=3 -> f1 = 2*2/(2+3) = 0.8
    assert m['per_class']['neutral']['recall'] == 1.0
    assert m['per_class']['neutral']['f1'] == 0.8
    # positive: 2 个真实,1 个预测对(另一个被预测成 neutral)
    assert m['per_class']['positive']['recall'] == 0.5
    assert m['macro_recall'] == round((1.0 + 0.5 + 1.0) / 3, 4)


def test_evaluate_macro_f1_consistent_with_stored_f1():
    """存下来的 macro_f1 必须与逐类 f1 的均值一致。

    两者走的是不同代码路径(sklearn 算的 vs 我们从混淆矩阵推的),
    对不上就说明混淆矩阵或标签顺序错了。
    """
    y_true = [0, 1, 2] * 5
    y_pred = [0, 1, 1, 2, 0, 2, 1, 1, 0, 0, 2, 2, 0, 1, 2]
    names = ['negative', 'positive', 'neutral']
    m = train_sentiment.evaluate(y_true, y_pred, names)
    ours = sum(v['f1'] for v in m['per_class'].values()) / 3
    assert abs(ours - m['macro_f1']) < 5e-4, (ours, m['macro_f1'])


# ---------------------------------------------------------------- CLI

def test_main_writes_file(tmp_path, capsys):
    exp = tmp_path / 'exp'
    exp.mkdir()
    (exp / 'bert-3class.json').write_text(
        json.dumps(_result(), ensure_ascii=False), encoding='utf-8')
    out = tmp_path / 'REPORT.md'

    rc = experiment_report.main(['--exp-dir', str(exp), '-o', str(out)])
    assert rc == 0
    assert out.exists()
    assert 'BERT' in out.read_text(encoding='utf-8')


def test_main_prints_without_output_flag(tmp_path, capsys):
    exp = tmp_path / 'exp'
    exp.mkdir()
    (exp / 'bert-3class.json').write_text(
        json.dumps(_result(), ensure_ascii=False), encoding='utf-8')

    rc = experiment_report.main(['--exp-dir', str(exp)])
    assert rc == 0
    assert 'BERT' in capsys.readouterr().out


def test_main_on_empty_dir_still_succeeds(tmp_path):
    """没有实验结果不算错误 —— 新克隆的仓库还没训练过。"""
    exp = tmp_path / 'exp'
    exp.mkdir()
    assert experiment_report.main(['--exp-dir', str(exp)]) == 0


# ---------------------------------------------------------------- 真实产物

def test_real_experiment_files_are_consistent():
    """本机跑过的实验结果必须自洽 —— 数字对不上说明写入逻辑坏了。"""
    exp_dir = os.path.join(_REPO_ROOT, 'data', 'experiments')
    results = experiment_report.load_results(exp_dir)
    if not results:
        pytest.skip('本机尚未训练模型')
    for (task, model), r in results.items():
        assert 0.0 <= r['accuracy'] <= 1.0, (task, model)
        assert 0.0 <= r['macro_f1'] <= 1.0, (task, model)
        assert r['n_test'] > 0
        cm = r.get('confusion_matrix')
        if cm:
            # 混淆矩阵总和必须等于测试样本数
            assert sum(sum(row) for row in cm) == r['n_test'], (task, model)
