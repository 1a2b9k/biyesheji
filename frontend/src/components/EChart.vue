/**
 * ECharts 的轻量 Vue 封装。
 *
 * 只做三件事:初始化、数据变化时更新、卸载时销毁。
 * 单独封装是为了让页面组件不必关心 ECharts 的生命周期。
 */
<script setup>
import * as echarts from 'echarts'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  option: { type: Object, required: true },
  height: { type: String, default: '420px' },
  /** 图表的文字替代描述,给屏幕阅读器与图片搜索用。 */
  desc: { type: String, default: '' },
})

const el = ref(null)
let chart = null

function render() {
  if (!chart) return
  // notMerge=true:切换股票时避免残留上一条曲线的数据
  chart.setOption(props.option, true)
}

function resize() {
  if (chart) chart.resize()
}

onMounted(() => {
  chart = echarts.init(el.value)
  render()
  window.addEventListener('resize', resize)
})

watch(() => props.option, render, { deep: true })

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  if (chart) {
    chart.dispose()
    chart = null
  }
})
</script>

<template>
  <!--
    role="img" + aria-label:canvas 对辅助技术是完全不可见的,
    整张图会被读成空白。至少给出「这里是一张什么图」。
  -->
  <div
    ref="el"
    role="img"
    :aria-label="desc || '数据图表'"
    :style="{ width: '100%', height }"
  />
</template>
