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
  <div ref="el" :style="{ width: '100%', height }" />
</template>
