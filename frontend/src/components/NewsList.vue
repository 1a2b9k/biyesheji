<script setup>
/**
 * 新闻列表。
 *
 * v0.1 只展示标题/来源/时间;情感标签在 v0.2 接入后自动显示
 * (后端字段已预留,为空时不渲染标签)。
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
</script>

<template>
  <section class="panel">
    <h2>相关新闻 <span class="count">{{ news.length }}</span></h2>

    <p v-if="!news.length" class="empty">暂无新闻,点击右上角「采集最新数据」。</p>

    <ul v-else class="list">
      <li v-for="n in news" :key="n.id">
        <a :href="n.url" target="_blank" rel="noopener" class="title">
          {{ n.title }}
        </a>
        <span v-if="label(n.sentiment)" class="tag" :class="label(n.sentiment).cls">
          {{ label(n.sentiment).text }}
        </span>
        <div class="meta">
          <span>{{ n.source || '未知来源' }}</span>
          <span>{{ n.publish_time }}</span>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.panel {
  background: #fff; border-radius: 6px; padding: 16px 18px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.07);
}
h2 { font-size: 15px; margin: 0 0 12px; color: #303133; }
.count { color: #909399; font-weight: 400; font-size: 13px; }
.empty { color: #909399; font-size: 13px; }
.list { list-style: none; margin: 0; padding: 0; }
.list li {
  padding: 11px 0; border-bottom: 1px solid #f0f2f5;
}
.list li:last-child { border-bottom: none; }
.title {
  color: #303133; text-decoration: none; font-size: 14px; line-height: 1.5;
}
.title:hover { color: #409eff; }
.meta {
  margin-top: 5px; font-size: 12px; color: #909399;
  display: flex; gap: 14px;
}
.tag {
  font-size: 11px; padding: 1px 7px; border-radius: 3px;
  margin-left: 8px; white-space: nowrap;
}
.tag.pos { background: #fef0f0; color: #f56c6c; }
.tag.neg { background: #f0f9eb; color: #67c23a; }
.tag.neu { background: #f4f4f5; color: #909399; }
</style>
