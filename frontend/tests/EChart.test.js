/**
 * EChart 封装的单元测试。
 *
 * 只测「封装层自己做的事」:挂载时 init、option 变化时 setOption、
 * 卸载时 dispose、以及给屏幕阅读器的替代描述。
 *
 * echarts 本身被替换成假对象 —— 真库在 jsdom 里拿不到可绘制尺寸,
 * init 只会得到 0 宽 0 高,测不出封装层的契约。
 */

import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const instances = []

vi.mock('echarts', () => ({
  init: vi.fn(() => {
    const chart = {
      setOption: vi.fn(),
      resize: vi.fn(),
      dispose: vi.fn(),
    }
    instances.push(chart)
    return chart
  }),
}))

import EChart from '../src/components/EChart.vue'

beforeEach(() => {
  instances.length = 0
})

describe('EChart', () => {
  it('挂载时初始化并推送一次配置', () => {
    const option = { series: [] }
    mount(EChart, { props: { option } })
    expect(instances).toHaveLength(1)
    expect(instances[0].setOption).toHaveBeenCalledTimes(1)
    // props 经过 Vue 的响应式包装,不是同一个对象引用,比对内容
    expect(instances[0].setOption.mock.calls[0][0]).toEqual(option)
  })

  it('option 变化时重新 setOption,且 notMerge 为真', () => {
    const w = mount(EChart, { props: { option: { series: [{ name: 'a' }] } } })
    w.setProps({ option: { series: [{ name: 'b' }] } })
    return w.vm.$nextTick().then(() => {
      // 切换股票时不能残留上一条曲线的数据,所以第二个参数必须是 true
      const calls = instances[0].setOption.mock.calls
      expect(calls.length).toBe(2)
      expect(calls[1][1]).toBe(true)
    })
  })

  it('卸载时 dispose,并移除 resize 监听', () => {
    const remove = vi.spyOn(window, 'removeEventListener')
    const w = mount(EChart, { props: { option: {} } })
    w.unmount()
    expect(instances[0].dispose).toHaveBeenCalledTimes(1)
    expect(remove.mock.calls.some((c) => c[0] === 'resize')).toBe(true)
    remove.mockRestore()
  })

  it('容器带 role="img" 与默认说明', () => {
    // canvas 对辅助技术完全不可见;没有 role/aria-label 时整张图会被读成空白
    const w = mount(EChart, { props: { option: {} } })
    const el = w.find('[role="img"]')
    expect(el.exists()).toBe(true)
    expect(el.attributes('aria-label')).toBe('数据图表')
  })

  it('传了 desc 时用它作 aria-label', () => {
    const w = mount(EChart, {
      props: { option: {}, desc: '贵州茅台最近 250 个交易日的 K 线与成交量' },
    })
    expect(w.find('[role="img"]').attributes('aria-label'))
      .toBe('贵州茅台最近 250 个交易日的 K 线与成交量')
  })

  it('height 落到内联样式', () => {
    const w = mount(EChart, { props: { option: {}, height: '460px' } })
    expect(w.find('[role="img"]').attributes('style')).toContain('height: 460px')
  })
})
