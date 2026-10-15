import axios from 'axios'

/**
 * 后端接口封装。
 *
 * 开发期通过 Vite 代理走 /api,避免跨域;生产可改 VITE_API_BASE。
 */
const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api',
  timeout: 120000,
})

/** 健康检查 */
export const getHealth = () => http.get('/health').then((r) => r.data)

/** 股票列表(含已入库数据量) */
export const listStocks = () => http.get('/stocks').then((r) => r.data)

/** 日线行情 */
export const getKlines = (code, limit = 120) =>
  http.get(`/stocks/${code}/klines`, { params: { limit } }).then((r) => r.data)

/** 新闻列表 */
export const getNews = (code, limit = 50) =>
  http.get(`/stocks/${code}/news`, { params: { limit } }).then((r) => r.data)

/** 概览 */
export const getOverview = (code) =>
  http.get(`/stocks/${code}/overview`).then((r) => r.data)

/** 触发一次采集 */
export const syncStock = (code) =>
  http.post(`/stocks/${code}/sync`).then((r) => r.data)

/** 情感模型状态(可用性 + 测试集指标) */
export const getSentimentInfo = () =>
  http.get('/sentiment/info').then((r) => r.data)

/** 单只股票的情感分布 */
export const getStockSentiment = (code, limit = 500) =>
  http.get(`/stocks/${code}/sentiment`, { params: { limit } }).then((r) => r.data)

export default http
