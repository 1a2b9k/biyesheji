# 财经舆情智能分析平台

> 本科毕业设计 · v0.3（情感分析 + 瓶颈分析 + 看板视觉）
> 江西财经大学 · 虚拟现实技术专业

---

## 这是什么

面向 A 股个股的**财经新闻舆情监测与可视化系统**。

- **v0.1**:数据采集 + 存储 + 展示(不依赖任何 AI 环境,先跑通完整链路)
- **v0.2**:情感分析 —— 股吧标题三分类,TF-IDF 基线与 BERT 微调两条路线对比
- **v0.3**:前端视觉重设计为财经数据看板;挖出"中性类"这个真正的瓶颈
  (4 条可复现的证据,见 `data/experiments/NEUTRAL_ANALYSIS.md`)

这样分层的理由:基础版能独立运行;情感分析作为增量接入,
**模型缺失时系统自动退化成 v0.1**,不影响采集与展示。

---

## 快速开始

需要两个终端。**先启动后端,再启动前端。**

```bat
REM 终端 1:后端 (http://127.0.0.1:8000)
scripts\start-backend.cmd

REM 终端 2:前端 (http://127.0.0.1:5173)
scripts\start-frontend.cmd
```

浏览器打开 **http://127.0.0.1:5173**,选择股票 → 点「采集最新数据」。

> 首次启动会自动建库并写入 3 只默认股票,但**没有任何行情和新闻**,
> 需要点一次「采集最新数据」。采集一只股票约 10–30 秒。

---

## 项目结构

```
biyesheji/
├── backend/                     后端 (FastAPI + SQLAlchemy)
│   ├── app/
│   │   ├── config.py            配置(数据库地址、默认股票、采集参数)
│   │   ├── db.py                引擎与会话
│   │   ├── models.py            数据模型:Stock / Kline / News
│   │   ├── collector.py         数据采集(东财接口)+ 解析
│   │   ├── service.py           业务:入库、去重、同步、情感回填
│   │   ├── sentiment.py         情感推理(懒加载;缺模型时自动降级)
│   │   └── main.py              FastAPI 应用与接口
│   ├── tests/                   203 个测试
│   ├── conftest.py              把 pytest 临时目录挪进工作区(沙箱需要)
│   └── pytest.ini
├── frontend/                    前端 (Vue3 + Vite + ECharts)
│   ├── src/
│   │   ├── api/index.js         接口封装
│   │   ├── utils/chart.js       图表配置构造(纯函数,可单测)
│   │   ├── components/          EChart / StockBar / OverviewCards / NewsList / SentimentPanel / SourceBreakdown
│   │   └── App.vue              主页面
│   └── tests/                   67 个测试
├── tools/                       环境、下载与实验工具
│   ├── train_sentiment.py       情感对比实验(TF-IDF 基线 + BERT 微调)
│   ├── analyze_neutral.py       中性类瓶颈分析(问句统计 / 错误流向 / 句式切分)
│   ├── experiment_report.py     从实验结果 JSON 生成 Markdown 报告
│   ├── check_env.py             环境自检
│   ├── fetch_model.py           预训练模型下载
│   └── use_mysql.py             一条命令切换数据库
├── data/experiments/            实验结果 JSON + REPORT.md + NEUTRAL_ANALYSIS.md(已进版本库)
├── scripts/                     一键启动 / 测试脚本
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
| GET | `/api/stocks/{code}/klines?limit=120` | 日线行情 |
| GET | `/api/stocks/{code}/news?limit=50` | 新闻列表 |
| GET | `/api/stocks/{code}/overview` | 概览(最新价、来源分布) |
| GET | `/api/stocks/{code}/sentiment?limit=500` | 单只股票的情绪统计与按日聚合 |
| POST | `/api/stocks/{code}/sync` | 触发采集(行情 + 新闻 + 情感回填) |
| GET | `/api/sentiment/info` | 情感模型可用性与指标 |
| POST | `/api/sentiment/analyze` | 对任意文本批量判情感(最多 200 条) |

自动生成的接口文档:**http://127.0.0.1:8000/docs**

---

## 数据来源

| 数据 | 接口 | 说明 |
|---|---|---|
| 日线行情 | 东方财富 `push2his` | 免注册免 key,实测单只 6000+ 条 |
| 财经新闻 | 东方财富搜索 | 关键词检索,含标题/来源/时间/链接 |

实测(2026-10-13):贵州茅台 6019 条日线、宁德时代 2022 条、平安银行 8494 条。

---

## 运行测试

```bat
scripts\test-all.cmd
```

当前:**403 个测试全部通过**(后端 203 + 前端 67 + 技能安装 133)。

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

---

## 已知限制

- **沙箱内跑无头浏览器会崩溃**（受限进程不能开命名管道，Chrome 的 mojo IPC 依赖它）。
  **提权后可正常截图**：`--headless=new --no-sandbox --disable-gpu --virtual-time-budget=6000
  --user-data-dir=<工作区内> --screenshot=<路径>`。这是唯一能自动看到真实渲染的方式，
  与 jsdom 测试互补（前者测逻辑，后者测渲染）
- 新闻搜索结果是滚动的,老新闻会被挤出窗口 —— 系统靠"拉取即落库"保留快照
- 情感分析模型权重不进版本库,干净检出需先训练或下载
- 数据集只有 3 只股票,不足以支撑"板块级"结论;标签体系本身有复合性缺陷(见上)

---

## 后续计划

| 版本 | 内容 |
|---|---|
| **v0.1** ✅ | 采集 + 存储 + 展示 |
| **v0.2** ✅ | 情感分析(两条路线对比 + 后端接口 + 前端展示) |
| **v0.3** ✅ | 前端视觉重设计 + 中性类瓶颈分析(标注体系缺陷)(**当前**) |
| v0.4 | 自选股、情感预警订阅、情感与股价关联性分析 |
