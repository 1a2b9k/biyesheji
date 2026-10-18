# 财经舆情智能分析平台

> 本科毕业设计 · v0.5（情感分析 + 瓶颈分析 + 多页签看板）
> 江西财经大学 · 虚拟现实技术专业

---

## 这是什么

面向 A 股个股的**财经新闻舆情监测与可视化系统**。

- **v0.1**:数据采集 + 存储 + 展示(不依赖任何 AI 环境,先跑通完整链路)
- **v0.2**:情感分析 —— 股吧标题三分类,TF-IDF 基线与 BERT 微调两条路线对比
- **v0.3**:前端视觉重设计为财经数据看板;挖出"中性类"这个真正的瓶颈
  (4 条可复现的证据,见 `data/experiments/NEUTRAL_ANALYSIS.md`)
- **v0.5**:看板按功能拆成四个页签(行情概览 / 情感分析 / 情感与收益 / 新闻列表),
  每页只渲染自己的图表

这样分层的理由:基础版能独立运行;情感分析作为增量接入,
**模型缺失时系统自动退化成 v0.1**,不影响采集与展示。

---

## 快速开始

**一键启动**:双击桌面上的「启动财经舆情平台」快捷方式,或直接跑

```bat
scripts\start-all.cmd
```

它会依次启动后端、等它就绪、启动前端、等它就绪,然后打开浏览器。
已经在跑的服务会被识别并跳过,所以重复双击是安全的。两个服务各占一个
命令行窗口,关掉窗口即停止。

快捷方式由 `scripts\make-shortcut.ps1` 生成(名字、目标、图标都可传参);
图标由 `tools\make_icon.py` 生成到 `assets\app.ico`,配色与前端图表同源。
两者都可以随时重建。

---

也可以照旧开两个终端手动启动。**先启动后端,再启动前端。**

```bat
REM 首次:装依赖(必须用包装器,不要用 python -m pip)
.python\python.exe .pysandbox\pipp.py install -r requirements.txt

REM 终端 1:后端 (http://127.0.0.1:8000)
scripts\start-backend.cmd

REM 终端 2:前端 (http://127.0.0.1:5173)
scripts\start-frontend.cmd
```

浏览器打开 **http://127.0.0.1:5173**,选择股票 → 点「采集最新数据」。

> 首次启动会自动建库并写入 3 只默认股票,但**没有任何行情和新闻**,
> 需要点一次「采集最新数据」。采集一只股票约 10–30 秒。

`requirements.txt` 是**手写**的,不是 `pip freeze` —— 本机解释器是共用的,
freeze 里混着 edge-tts / Flask / google-genai 等与项目无关的包。
清单按 `backend/` 与 `tools/` 里真实出现的 import 逐条核对,
并由 `backend/tests/test_requirements.py` 反向守护(新加 import 忘登记会测试失败)。
torch 的 CUDA 轮子不在 PyPI 主索引,装法见清单里的注释。

---

## 项目结构

```
biyesheji/
├── backend/                     后端 (FastAPI + SQLAlchemy)
│   ├── app/
│   │   ├── config.py            配置(数据库地址、默认股票、采集参数)
│   │   ├── db.py                引擎与会话
│   │   ├── models.py            数据模型:Stock / Kline / News
│   │   ├── collector.py         数据采集(东财 + 腾讯备用)+ 解析
│   │   ├── service.py           业务:入库、去重、同步、情感回填
│   │   ├── analysis.py          情感指数与收益的关联分析(纯函数)
│   │   ├── sentiment.py         情感推理(懒加载;缺模型时自动降级)
│   │   └── main.py              FastAPI 应用与接口
│   ├── tests/                   609 个测试
│   ├── conftest.py              把 pytest 临时目录挪进工作区(沙箱需要)
│   └── pytest.ini
├── frontend/                    前端 (Vue3 + Vite + ECharts)
│   ├── src/
│   │   ├── api/index.js         接口封装
│   │   ├── utils/chart.js       图表配置构造(纯函数,可单测)
│   │   ├── components/          EChart / StockBar / NavTabs / OverviewCards / NewsList / SentimentPanel / SourceBreakdown / ReturnsPanel
│   │   └── App.vue              主页面(四页签:概览 / 情感 / 关联 / 新闻)
│   └── tests/                   100 个测试
├── tools/                       环境、下载与实验工具
│   ├── collect_corpus.py        批量采集(多股票 x 多页新闻)
│   ├── analyze_sentiment_returns.py  情感指数 vs 次日收益
│   ├── train_sentiment.py       情感对比实验(TF-IDF 基线 + BERT 微调)
│   ├── analyze_neutral.py       中性类瓶颈分析(问句统计 / 错误流向 / 句式切分)
│   ├── experiment_report.py     从实验结果 JSON 生成 Markdown 报告
│   ├── train_multitask.py       改进实验:多任务(共享编码器 + 3 头)与 4 分类标签重构
│   ├── ensemble_sentiment.py    改进实验:多种子集成 + McNemar / bootstrap 显著性检验
│   ├── ablation_study.py        改进实验:六类负面结论的可复现证据
│   ├── check_env.py             环境自检
│   ├── fetch_model.py           预训练模型下载
│   ├── make_figures.py          生成论文 13 张图(读 data/,输出到 论文/figures/)
│   ├── make_icon.py             生成 assets/app.ico(快捷方式图标,7 种尺寸)
│   ├── md_to_docx.py            Markdown → Word(支持表格、插图与目录域)
│   └── use_mysql.py             一条命令切换数据库
├── data/experiments/            实验结果 JSON + REPORT.md + NEUTRAL_ANALYSIS.md + ABLATION.md(已进版本库)
├── 论文/                        开题报告书 / 文献综述 / 论文写作大纲 / 毕业论文初稿 / 答辩口径卡
│   ├── figures/                 13 张论文插图(由 make_figures.py 生成)
│   │                            (.md 进库,.docx 为构建产物;初稿是底稿,须学生本人改写)
├── scripts/                     一键启动 / 测试脚本
│   ├── start-all.cmd            一键启动(后端+前端+开浏览器,可重复执行)
│   ├── make-shortcut.ps1        生成桌面快捷方式(UTF-8 带 BOM)
│   ├── start-backend.cmd        只启后端
│   └── start-frontend.cmd       只启前端
├── assets/app.ico               快捷方式图标(由 tools/make_icon.py 生成)
├── requirements.txt             依赖清单(手写,按真实 import 核对)
├── .env.example                 配置模板(复制为 .env)
└── 文档/                        学校通知原件
```

---

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + Vite + ECharts + axios |
| 后端 | FastAPI + SQLAlchemy + Uvicorn |
| 数据库 | SQLite(默认)/ MySQL(可选,改一行配置) |
| 测试 | pytest + Vitest + @vue/test-utils |

---

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/stocks` | 股票列表(含数据量) |
| GET | `/api/stocks/{code}/klines?limit=120` | 日线行情(limit 上限 20000) |
| GET | `/api/stocks/{code}/news?limit=50` | 新闻列表 |
| GET | `/api/stocks/{code}/overview` | 概览(最新价、来源分布) |
| GET | `/api/stocks/{code}/sentiment?limit=500` | 单只股票的情绪统计与按日聚合 |
| GET | `/api/stocks/{code}/returns?lag=1&min_news=1` | 情感指数与未来收益的关联分析 |
| POST | `/api/stocks/{code}/sync?news_pages=1` | 触发采集(行情 + 新闻 + 情感回填) |
| GET | `/api/sentiment/info` | 情感模型可用性与指标 |
| POST | `/api/sentiment/analyze` | 对任意文本批量判情感(最多 200 条) |

自动生成的接口文档:**http://127.0.0.1:8000/docs**

---

## 批量采集与分析

单只股票单次采集只覆盖最近 20 条新闻,样本量不足以做统计分析。
仓库里带两个命令行工具:

```bat
REM 批量采集:13 只股票 x 25 页 x 20 条/页,约 5000 条新闻
.python\python.exe tools\collect_corpus.py --pages 25 --sleep 1.2

REM 情感指数 vs 次日收益:逐股票 + 全样本汇总,可写 JSON
.python\python.exe tools\analyze_sentiment_returns.py --out data/experiments/returns.json
```

`collect_corpus.py` 的股票池是 `backend/app/config.py` 里的
`DEFAULT_STOCKS` + `EXTENDED_STOCKS`(写死而非动态拉取:
接口限流不可靠,且论文样本必须可复现)。每只股票独立 try/except,
一只失败不影响其余;已入库的新闻按 url 去重,重复跑是安全的。

`analyze_sentiment_returns.py` 的口径:`polarity = (正面 - 负面) / 当日新闻数`,
即 Antweiler & Frank(2004) 的 bullishness;收益取之后第 `lag` 个交易日的
涨跌幅(`lag=1` 为次日)。新闻按「发布日之前(含当天)最后一个交易日」归属,
周末新闻归到周五,再加 lag —— 这样周六的新闻不会被错推到周二。

---

## 数据来源

| 数据 | 接口 | 说明 |
|---|---|---|
| 日线行情(主) | 东方财富 `push2his` | 免注册免 key,实测单只 6000+ 条 |
| 日线行情(备) | 腾讯 `ifzq.gtimg.cn` | 主源不通时自动接管,同为前复权 |
| 财经新闻 | 东方财富搜索 | 关键词检索,含标题/来源/时间/链接,支持分页 |

**日线有主备两个源。** 东财 `push2his` 自 2026-10-17 起整域拒绝连接
(所有编号主机都在 0.2 秒内 `RemoteDisconnected`,不是限流,冷却后不复原),
因此 `collector.fetch_kline` 内部做了回退:东财失败就改走腾讯,上层无感。

两个源**同为前复权**,实测同一交易日的开/收/高/低/量**逐位一致**
(600519 的 640 个重叠交易日,差异数全为 0),所以混存不会出现两套口径。
腾讯只给 6 个字段,少了成交额和振幅,由 `parse_tencent_kline` 补算:
振幅取 `(高 - 低) / 前收 × 100`(与东财口径一致,已逐日核对),
成交额取 `量 × 100 × 收盘` 作为近似(VWAP 拿不到,与东财真值相差约 1%,仅用于展示)。
腾讯单次最多返回 640 根(约 2.5 年),更早的历史靠库里已有的存量。

实测(2026-10-17):13 只股票共 72235 条日线、6420 条新闻,
全部完成情感标注。**增量更新已验证** —— 删掉最新交易日再同步,
`kline_added=1` 且数据完整还原。

数据源连通性可随时自检:

```bat
.python\python.exe tools\check_datasource.py
```

日线只要主备**有一个通**就算通过(另一个不通会打 `[INFO]` 提示走备用源)。

---

## 运行测试

```bat
scripts\test-all.cmd
```

当前:**860 个测试全部通过**(后端 609 + 前端 118 + 技能安装 133)。

测试原则:
- 采集解析用**离线样本**测(不发网络请求,快且稳定)
- 接口用**临时库**测(不碰开发数据)
- 图表配置抽成**纯函数**测(不依赖浏览器)
- 页面用 **jsdom 真实挂载**测(验证组件组合,不只是单个函数)
- 情感分析用**假模型**测(不加载 400 MB 权重,重点测降级路径)
- 训练与报告工具的纯逻辑单测(任务切分、版本挑选、文件名解析)

---

## 配置

数据库默认用 **SQLite**(零配置,开箱即用)。切换到 **MySQL** 用一条命令:

```bat
.python\python.exe tools\use_mysql.py --password 你的密码
```

它会:验证密码 → 建库 `fin_sentiment` → 把连接串写进 `.env` → 建表。
**密码只写进 `.env`,该文件已被 gitignore,不会进版本库。**

切回 SQLite:

```bat
.python\python.exe tools\use_mysql.py --sqlite
```

查看当前用的是哪个库、能否连通:

```bat
.python\python.exe tools\use_mysql.py --check
```

> 也可以手工配置:复制 `.env.example` 为 `.env`,填入 `FIN_DATABASE_URL`。
> 密码含特殊字符(`@ : / #`)时需做 URL 编码,如 `@` → `%40`。

---

## 情感分析

两条路线各自训练、公平对比,结果在 `data/experiments/REPORT.md`。

```bat
REM 训练(三个任务各跑两条路线,GPU 上约 6 分钟)
.python\python.exe tools\train_sentiment.py --model both --task 3class
.python\python.exe tools\train_sentiment.py --model both --task polarity
.python\python.exe tools\train_sentiment.py --model both --task neutral

REM 由结果 JSON 生成 Markdown 报告(论文实验章节素材)
.python\python.exe tools\experiment_report.py -o data\experiments\REPORT.md
```

| 任务 | TF-IDF + 逻辑回归 | BERT 微调 |
|---|---|---|
| 三分类(负面/正面/中性) | 0.6296 | **0.7540** |
| 二分类极性(剔除中性) | 0.7546 | **0.8435** |
| 二分类(中性 vs 有情感) | 0.7352 | **0.8099** |

模型权重不进版本库(392 MB),需要时重新训练或下载:

```bat
.python\python.exe tools\fetch_model.py          REM 下载 bert-base-chinese
```

**没有模型时系统照常运行** —— 采集与展示不受影响,只是新闻不带情感标签。

### 瓶颈分析:中性类为什么是短板

`data/experiments/NEUTRAL_ANALYSIS.md`(重跑:`.python\python.exe tools\analyze_neutral.py --train`)

四条证据:

| # | 证据 | 关键数字 |
|---|---|---|
| 1 | 问句统计 | 中性类样本 **48.28%** 以问号结尾(负面 22.78% / 正面 9.27%);全部问句中 **68.39%** 被标成中性 |
| 2 | 错误流向 | 524 个错误中 **385 个(73.47%)牵涉中性边界**,极性互错仅 139 个(26.53%),**2.8 倍** |
| 3 | 按句式切分 | 问句组 acc 更高(0.7882 vs 0.7403)但宏 F1 更低(0.6492 vs 0.7379);问句组正面类召回率仅 **0.2885**(陈述句组 0.7756) |
| 4 | 剔除问句重训 | 删掉 2528 条问句样本后 acc **-0.0103**、宏 F1 **-0.0086** —— 问句**并非纯噪声** |

结论:**"中性"是复合标签**,把"真的没有态度"和"只是在提问"混成了一类,
模型在这条边界上系统性犯错。改进方向见报告的第五节。

### 情感指数与收益:相关但不显著

`data/experiments/returns.json`(重跑:`.python\python.exe tools\analyze_sentiment_returns.py --out data/experiments/returns.json`)

13 只股票、**6420 条已标注新闻**、**744 个股票-日样本**,`lag=1`(次日):

| 口径 | 值 |
|---|---|
| Pearson r | **-0.0019**(p=0.9579) |
| Spearman ρ | 0.0090 |
| 分组次日收益 | 低情感 -0.097% / 中 0.026% / 高 -0.062% |
| 方向命中率 | 0.4778(n=496) |

**结论是负面的**:在全样本上,情感指数与次日收益没有可检出的线性关系。
单只股票里只有恒瑞医药 600276 达到 p<0.05(Pearson 0.2829, p=0.0455),
13 只股票做 13 次检验,按多重比较预期就该有约 0.65 个假阳性 ——
一个显著结果不构成证据。

值得记录的是**样本量对结论的影响**:第一轮只有 1296 条新闻(228 个样本)时,
Pearson 是 +0.0526;扩到 6420 条后掉到 -0.0019。小样本下的相关系数
基本是噪声,这也是为什么这个实验值得做到 5000 条以上再下结论。

---

## 已知限制

- **沙箱内跑无头浏览器会崩溃**（受限进程不能开命名管道，Chrome 的 mojo IPC 依赖它）。
  **提权后可正常截图**：`--headless=new --no-sandbox --disable-gpu --virtual-time-budget=6000
  --user-data-dir=<工作区内> --screenshot=<路径>`。这是唯一能自动看到真实渲染的方式，
  与 jsdom 测试互补（前者测逻辑，后者测渲染）
- 新闻搜索结果是滚动的,老新闻会被挤出窗口 —— 系统靠"拉取即落库"保留快照
- 情感分析模型权重不进版本库,干净检出需先训练或下载
- 情感—收益关联在全样本上不显著,且只有 13 只股票,不足以支撑"板块级"结论
- 标签体系本身有复合性缺陷(见上)

---

## 后续计划

| 版本 | 内容 |
|---|---|
| **v0.1** ✅ | 采集 + 存储 + 展示 |
| **v0.2** ✅ | 情感分析(两条路线对比 + 后端接口 + 前端展示) |
| **v0.3** ✅ | 前端视觉重设计 + 中性类瓶颈分析(标注体系缺陷) |
| **v0.4** ✅ | 扩充到 13 只股票 / 6420 条新闻 + 情感指数与收益关联分析 |
| **v0.5** ✅ | 前端按功能拆成四个页签(概览 / 情感 / 关联 / 新闻),不再堆在一页(**当前**) |
| v0.6 | 自选股、情感预警订阅、定时增量采集 |
