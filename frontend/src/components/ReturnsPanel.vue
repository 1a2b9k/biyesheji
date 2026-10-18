<script setup>
/**
 * 情感—收益关联面板:散点图 + 相关性读数 + 分组收益。
 *
 * 设计取向:
 *   - 相关性是「有没有」的问题,不是「多少」的问题,所以读数区
 *     把 p 值和样本量放在同一行,避免用户只看 r 就下结论。
 *   - 分组收益用三条横条对比(低/中/高情感组),横条长度即收益,
 *     正负用颜色区分,比表格更快看出单调性。
 *   - 样本不足时明确说「样本太少」而不是画一张空散点图 ——
 *     20 个点算出来的相关系数不该被当成结论。
 */
import { computed } from 'vue'

import EChart from './EChart.vue'
import { buildReturnsScatterOption } from '../utils/chart.js'

const props = defineProps({
  data: { type: Object, default: null },
})

const stats = computed(() => props.data?.stats ?? null)
const pairs = computed(() => props.data?.pairs ?? [])

const scatterOption = computed(() => buildReturnsScatterOption(pairs.value))

/** 样本数低于这个值时,相关系数不足以支撑结论。 */
const MIN_RELIABLE = 30

const n = computed(() => stats.value?.n ?? 0)
const reliable = computed(() => n.value >= MIN_RELIABLE)
const hasData = computed(() => n.value > 0)

/**
 * 取出一个数值,缺失时返回 null。
 *
 * 不能直接 `Number(v)`:相关系数在样本不足或某一侧方差为 0 时后端会返回
 * null,而 `Number(null) === 0` 且 `Number.isFinite(0)` 为真 —— 界面上就会
 * 显示成 `r=0.000`、`p<0.001` 并标绿「显著」,把「算不出来」讲成了
 * 「算出来是 0 且显著」。
 */
function toNum(v) {
  if (v === null || v === undefined || v === '') return null
  const x = Number(v)
  return Number.isFinite(x) ? x : null
}

function num(v, digits = 3) {
  const x = toNum(v)
  return x === null ? '-' : x.toFixed(digits)
}

function pct(v) {
  const x = toNum(v)
  return x === null ? '-' : (x >= 0 ? '+' : '') + x.toFixed(2) + '%'
}

/** p 值小于 0.001 时直接写「<0.001」,避免一长串 0。缺值写「-」。 */
const pText = computed(() => {
  const p = toNum(stats.value?.p_value)
  if (p === null) return '-'
  return p < 0.001 ? '< 0.001' : p.toFixed(3)
})

/** 相关性是否在 0.05 水平上显著。缺值时不算显著。 */
const significant = computed(() => {
  const p = toNum(stats.value?.p_value)
  return p !== null && p < 0.05
})

/** 相关系数是否存在(null 表示样本不足或方差为 0)。 */
const hasCorrelation = computed(() => toNum(stats.value?.pearson) !== null)

/** 分组收益:低/中/高情感组各自的平均次日收益。 */
const groups = computed(() => {
  const g = stats.value?.groups ?? {}
  return [
    { key: 'low', name: '低情感组', value: g.low },
    { key: 'mid', name: '中情感组', value: g.mid },
    { key: 'high', name: '高情感组', value: g.high },
  ]
})

/** 横条以最大绝对值为基准缩放,让三组可比。 */
const groupMax = computed(() => {
  const vals = groups.value.map((x) => Math.abs(toNum(x.value) ?? 0))
  return Math.max(...vals, 0.01)
})

function barWidth(v) {
  const x = Math.abs(toNum(v) ?? 0)
  return (x / groupMax.value) * 100
}

/** 分组收益的方向;缺值返回 0(按 0 处理,不标红绿)。 */
function groupSign(v) {
  const x = toNum(v)
  if (x === null) return 0
  return x >= 0 ? 1 : -1
}

/** 着色类:只在有值时给 up/down,缺值一律不上色。 */
function groupClass(v) {
  const sign = groupSign(v)
  if (sign === 0) return {}
  return sign > 0 ? { up: true } : { down: true }
}
</script>

<template>
  <section class="panel">
    <header class="head">
      <h2>情感与收益</h2>
      <span class="meta num">
        情感指数 vs 次日涨跌幅 · {{ n }} 个股票-日样本
      </span>
    </header>

    <p v-if="!hasData" class="empty">
      还没有可用的配对样本。先采集新闻并完成情感标注,
      再确保该股票有对应的日线行情。
    </p>

    <template v-else>
      <!-- 读数区:p 值和样本量与 r 并列,防止只看 r 就下结论 -->
      <ul class="stats">
        <li>
          <span class="k">Pearson r</span>
          <b class="v num">{{ num(stats.pearson) }}</b>
        </li>
        <li>
          <span class="k">Spearman ρ</span>
          <b class="v num">{{ num(stats.spearman) }}</b>
        </li>
        <li>
          <span class="k">p 值</span>
          <b class="v num" :class="{ sig: significant }">{{ pText }}</b>
        </li>
        <li>
          <span class="k">方向命中率</span>
          <b class="v num">
            {{ stats.hit_n ? num(stats.hit_rate) : '-' }}
            <small v-if="stats.hit_n" class="sub num">n={{ stats.hit_n }}</small>
          </b>
        </li>
      </ul>

      <p v-if="!reliable" class="warn">
        样本仅 {{ n }} 个,低于 {{ MIN_RELIABLE }} 个时相关系数波动很大,
        下面的数值只作参考,不宜作为结论。
      </p>

      <p v-if="!hasCorrelation" class="warn">
        这一组样本算不出相关系数(样本过少,或某一侧取值全相同导致方差为零),
        所以 r 与 p 值显示为「-」。这不是「相关性为零」,而是「无法估计」。
      </p>

      <!-- 分组收益:横条长度即平均收益 -->
      <h3>分组平均次日收益</h3>
      <ul class="groups">
        <li v-for="g in groups" :key="g.key">
          <span class="gname">{{ g.name }}</span>
          <div class="track">
            <div
              class="fill"
              :class="groupClass(g.value)"
              :style="{ width: barWidth(g.value) + '%' }"
            />
          </div>
          <span class="gval num" :class="groupClass(g.value)">
            {{ pct(g.value) }}
          </span>
        </li>
      </ul>

      <h3>散点与拟合线 <span class="hint">每点为一个交易日</span></h3>
      <EChart :option="scatterOption" height="300px" />
    </template>
  </section>
</template>

<style scoped>
.panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r);
  padding: 18px 22px;
  margin-bottom: 16px;
}

.head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
  padding-bottom: 12px;
  border-bottom: 2px solid var(--ink);
  margin-bottom: 14px;
}
h2 {
  font-size: var(--fs-title);
  margin: 0;
  font-weight: 600;
  letter-spacing: -0.01em;
}
h3 {
  font-size: var(--fs-label);
  margin: 18px 0 8px;
  color: var(--muted);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.meta {
  font-size: var(--fs-label);
  color: var(--muted);
  margin-left: auto;
}

.empty {
  color: var(--muted);
  font-size: var(--fs-body);
  padding: 10px 0 6px;
  margin: 0;
}

/* —— 读数区 —— */
.stats {
  list-style: none;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin: 0;
  padding: 0;
}
.stats li {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.k {
  font-size: var(--fs-label);
  color: var(--muted);
  font-weight: 600;
}
.v {
  font-size: var(--fs-title);
  color: var(--ink);
  font-weight: 600;
}
.v.sig {
  color: var(--pos);
}
.sub {
  font-size: 10px;
  color: var(--muted-2);
  font-weight: 400;
  margin-left: 4px;
}

.warn {
  background: var(--surface-2);
  border-left: 3px solid var(--muted-2);
  color: var(--muted);
  font-size: var(--fs-label);
  padding: 8px 12px;
  margin: 14px 0 0;
  border-radius: 2px;
}

/* —— 分组收益横条 —— */
.groups {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}
.groups li {
  display: grid;
  grid-template-columns: 80px 1fr 66px;
  align-items: center;
  gap: 10px;
}
.gname {
  font-size: var(--fs-label);
  color: var(--muted);
  font-weight: 600;
}
.track {
  height: 5px;
  background: var(--line-2);
  border-radius: 3px;
  overflow: hidden;
}
.fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.35s ease;
}
.gval {
  font-size: var(--fs-label);
  font-weight: 600;
  text-align: right;
}
.up { color: var(--pos); }
.down { color: var(--neg); }
.fill.up { background: var(--pos); }
.fill.down { background: var(--neg); }

.hint {
  font-size: 10px;
  color: var(--muted-2);
  font-weight: 400;
  letter-spacing: 0;
  text-transform: none;
}

@media (max-width: 900px) {
  .stats { grid-template-columns: repeat(2, 1fr); }
  .meta { margin-left: 0; }
}
</style>
