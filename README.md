# 财经舆情智能分析平台

> 本科毕业设计 · v0.1 基础版
> 江西财经大学 · 虚拟现实技术专业

---

## 这是什么

面向 A 股个股的**财经新闻舆情监测与可视化系统**。

**v0.1 的范围**:数据采集 + 存储 + 展示。
**不含情感分析** —— 那是 v0.2 的内容(数据库字段已预留)。

这样分层的理由:基础版不依赖任何 AI 环境,可以先跑通完整链路;
情感分析作为后续增量接入,失败也不影响系统主体。

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
│   │   ├── service.py           业务:入库、去重、同步
│   │   └── main.py              FastAPI 应用与接口
│   ├── tests/                   29 个测试
│   └── pytest.ini
├── frontend/                    前端 (Vue3 + Vite + ECharts)
│   ├── src/
│   │   ├── api/index.js         接口封装
│   │   ├── utils/chart.js       图表配置构造(纯函数,可单测)
│   │   ├── components/          EChart / StockBar / OverviewCards / NewsList
│   │   └── App.vue              主页面
│   └── tests/                   32 个测试
├── tools/                       环境与验证工具
│   └── use_mysql.py             一条命令切换数据库
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
| POST | `/api/stocks/{code}/sync` | 触发采集 |

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

当前:**71 个测试全部通过**(后端 39 + 前端 32)。

测试原则:
- 采集解析用**离线样本**测(不发网络请求,快且稳定)
- 接口用**临时库**测(不碰开发数据)
- 图表配置抽成**纯函数**测(不依赖浏览器)
- 页面用 **jsdom 真实挂载**测(验证组件组合,不只是单个函数)

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

## 已知限制

- **无法在沙箱内跑无头浏览器**(Chrome / Edge 均崩溃),
  因此界面验证靠 jsdom 集成测试 + 人工查看,不能自动截图
- 新闻搜索结果是滚动的,老新闻会被挤出窗口 —— 系统靠"拉取即落库"保留快照
- v0.1 不含情感分析,`news.sentiment` 字段为空

---

## 后续计划

| 版本 | 内容 |
|---|---|
| **v0.1** ✅ | 采集 + 存储 + 展示(**当前**) |
| v0.2 | 情感分析模块(预训练推理 → 微调) |
| v0.3 | 自选股、情感预警订阅、历史回溯 |
| v0.4 | 对比实验、混淆矩阵、性能数据(论文素材) |
