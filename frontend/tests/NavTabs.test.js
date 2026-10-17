/**
 * 导航页签组件测试。
 *
 * 这个组件是受控的(modelValue + update:modelValue),不自己持状态 ——
 * 所以这里测的是"它把点击正确上报了",而不是"它自己切了页"。
 * 父级负责真正切页,那部分由 App.test.js 覆盖。
 */

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import NavTabs from '../src/components/NavTabs.vue'

const TABS = [
  { key: 'overview', label: '行情概览', hint: '读数 · K 线', badge: 2 },
  { key: 'sentiment', label: '情感分析', hint: '分布 · 来源', badge: 0 },
  { key: 'news', label: '新闻列表', hint: '逐条标注', badge: 7 },
]

function mountTabs(props = {}) {
  return mount(NavTabs, { props: { tabs: TABS, modelValue: 'overview', ...props } })
}

describe('NavTabs', () => {
  it('按 tabs 渲染出对应数量的页签', () => {
    const w = mountTabs()
    expect(w.findAll('[role="tab"]')).toHaveLength(3)
  })

  it('渲染标签文字', () => {
    const w = mountTabs()
    expect(w.findAll('.label').map((n) => n.text())).toEqual([
      '行情概览', '情感分析', '新闻列表',
    ])
  })

  it('当前页签标记 aria-selected', () => {
    const w = mountTabs({ modelValue: 'sentiment' })
    const on = w.findAll('[role="tab"]').filter(
      (t) => t.attributes('aria-selected') === 'true')
    expect(on).toHaveLength(1)
    expect(on[0].attributes('data-tab')).toBe('sentiment')
  })

  it('点击未选中的页签时上报新 key', async () => {
    const w = mountTabs()
    await w.find('[data-tab="news"]').trigger('click')
    expect(w.emitted('update:modelValue')).toBeTruthy()
    expect(w.emitted('update:modelValue')[0]).toEqual(['news'])
  })

  it('点击已选中的页签也会上报 —— 父级自己决定是否忽略', async () => {
    const w = mountTabs()
    await w.find('[data-tab="overview"]').trigger('click')
    expect(w.emitted('update:modelValue')[0]).toEqual(['overview'])
  })

  it('badge 为 0 时照样显示', () => {
    // 0 是有用信息(该股没有这类数据),藏起来会让人以为还没加载
    const w = mountTabs()
    expect(w.find('[data-tab="sentiment"] .badge').text()).toBe('0')
  })

  it('badge 为 null/undefined 时不渲染', () => {
    const w = mountTabs({
      tabs: [{ key: 'a', label: '甲' }, { key: 'b', label: '乙', badge: null }],
    })
    expect(w.findAll('.badge')).toHaveLength(0)
  })

  it('hint 同时进 title 与可见文字', () => {
    const w = mountTabs()
    const tab = w.find('[data-tab="news"]')
    expect(tab.attributes('title')).toBe('逐条标注')
    expect(tab.find('.hint').text()).toBe('逐条标注')
  })

  it('没有 hint 时不渲染 hint 也不设 title', () => {
    const w = mountTabs({ tabs: [{ key: 'a', label: '甲' }] })
    expect(w.find('.hint').exists()).toBe(false)
    expect(w.find('[data-tab="a"]').attributes('title')).toBe('甲')
  })

  it('tabs 为空时不报错', () => {
    const w = mountTabs({ tabs: [] })
    expect(w.findAll('[role="tab"]')).toHaveLength(0)
  })
})
