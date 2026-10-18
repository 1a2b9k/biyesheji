<script setup>
/**
 * 新闻列表:标题 + 情感标签 + 来源/时间。
 *
 * 设计取向:做成"带日期的流水账"而不是卡片堆。新闻天然按时间排列,
 * 左侧固定一列日期(等宽数字)让时间轴一眼可见;情感标签用色块而非
 * 描边胶囊,因为色块在密集列表里更容易扫。
 *
 * 每条左侧有一根与情感同色的细竖线 —— 不用读文字就能看出整列的情绪分布,
 * 这是列表页唯一需要的"图表"。
 */
defineProps({
  news: { type: Array, default: () => [] },
})

const LABELS = {
  positive: { text: '利好', cls: 'pos' },
  negative: { text: '利空', cls: 'neg' },
  neutral: { text: '中性', cls: 'neu' },
}

function label(sentiment) {
  return LABELS[sentiment] || null
}

/** 从 "2026-10-12 16:08:01" 拆出日期与时刻,便于分栏显示。 */
function splitTime(s) {
  const t = String(s || '')
  const i = t.indexOf(' ')
  if (i < 0) return { date: t || '-', time: '' }
  return { date: t.slice(0, i), time: t.slice(i + 1, i + 6) }
}

/**
 * 只有 http(s) 地址才做成链接。
 *
 * 后端已经在入库时挡过一遍(`collector._safe_http_url`),但库里可能
 * 还留着加校验之前抓的旧数据;这里再挡一次,免得 `javascript:` 之类
 * 的地址进 `<a :href>`。
 *
 * @param {string} url
 * @returns {boolean}
 */
function isLink(url) {
  const s = String(url || '').trim().toLowerCase()
  return s.startsWith('http://') || s.startsWith('https://')
}
</script>

<template>
  <section class="panel">
    <header class="head">
      <h2>相关新闻</h2>
      <span class="count num">{{ news.length }}</span>
    </header>

    <p v-if="!news.length" class="empty">
      暂无新闻。点击右上角「采集最新数据」抓取。
    </p>

    <ul v-else class="list">
      <li
        v-for="n in news"
        :key="n.id"
        :class="label(n.sentiment)?.cls"
      >
        <div class="when num">
          <span class="d">{{ splitTime(n.publish_time).date }}</span>
          <span class="t">{{ splitTime(n.publish_time).time }}</span>
        </div>

        <div class="what">
          <a
            v-if="isLink(n.url)"
            :href="n.url"
            target="_blank"
            rel="noopener noreferrer"
            class="title"
          >
            {{ n.title }}
          </a>
          <span v-else class="title plain">{{ n.title }}</span>
          <div class="meta">
            <span v-if="label(n.sentiment)" class="tag">
              {{ label(n.sentiment).text }}
            </span>
            <span class="src">{{ n.source || '未知来源' }}</span>
          </div>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r);
  padding: 18px 22px 6px;
  margin-bottom: 16px;
}

.head {
  display: flex;
  align-items: baseline;
  gap: 9px;
  padding-bottom: 12px;
  border-bottom: 2px solid var(--ink);
  margin-bottom: 2px;
}
h2 {
  font-size: var(--fs-title);
  margin: 0;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.count {
  color: var(--muted);
  font-size: var(--fs-body);
  font-weight: 400;
}

.empty {
  color: var(--muted);
  font-size: var(--fs-body);
  padding: 22px 0;
  margin: 0;
}

.list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.list li {
  display: grid;
  grid-template-columns: 88px 1fr;
  gap: 16px;
  padding: 13px 0 13px 12px;
  border-bottom: 1px solid var(--line-2);
  border-left: 2px solid transparent;
  transition: background 0.12s ease;
}
.list li:last-child {
  border-bottom: none;
}
.list li:hover {
  background: var(--surface-2);
}

/* 左侧竖线颜色 = 情感。整列扫下来就能看出当天情绪倾向。 */
.list li.pos { border-left-color: var(--pos); }
.list li.neg { border-left-color: var(--neg); }
.list li.neu { border-left-color: var(--neu); }

.when {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding-top: 2px;
}
.when .d {
  font-size: var(--fs-label);
  color: var(--ink-2);
  font-weight: 600;
}
.when .t {
  font-size: 11px;
  color: var(--muted-2);
}

.what { min-width: 0; }

.title {
  color: var(--ink);
  font-size: var(--fs-lead);
  line-height: 1.5;
  display: block;
  transition: color 0.12s ease;
  text-wrap: pretty;
}

/* 可点的标题给出下划线线索:纯色文字看不出能点,用户不会去悬停。
   下划线颜色取浅色,不抢正文注意力。 */
a.title {
  text-decoration: underline;
  text-decoration-color: var(--line-2);
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
  cursor: pointer;
}
a.title:hover {
  color: var(--pos);
  text-decoration-color: currentColor;
}

/* 没有有效链接的标题:正常文字,不给可点的暗示 */
.title.plain {
  color: var(--ink-2);
}

.meta {
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: var(--fs-label);
  color: var(--muted);
}

/* 色块标签:实心浅底 + 同色文字,比描边胶囊更容易在列表里扫 */
.tag {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 2px;
  letter-spacing: 0.04em;
  white-space: nowrap;
}
.tag.pos { background: var(--pos-soft); color: var(--pos); }
.tag.neg { background: var(--neg-soft); color: var(--neg); }
.tag.neu { background: var(--neu-soft); color: var(--neu); }

.src { color: var(--muted); }

@media (max-width: 640px) {
  .list li {
    grid-template-columns: 1fr;
    gap: 6px;
  }
  .when {
    flex-direction: row;
    gap: 8px;
    align-items: baseline;
  }
}
</style>
