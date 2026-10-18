/**
 * 新闻来源分布(条状列表)单元测试。
 *
 * 这个组件是从饼图改过来的:饼图要给每个来源分配颜色,十几个来源
 * 就变成一条彩虹,和页面里红绿数据语义色打架。改条状后颜色不承载
 * 信息,长度才是数据,所以测试重点是排序、截断与占比宽度。
 */

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SourceBreakdown from '../src/components/SourceBreakdown.vue'

/** 造 n 家来源,条数递减。 */
function sources(n) {
  return Array.from({ length: n }, (_, i) => ({
    source: `媒体${i + 1}`,
    count: n - i,
  }))
}

describe('SourceBreakdown', () => {
  it('按条数降序排列', () => {
    const w = mount(SourceBreakdown, {
      props: { sources: [
        { source: '少的', count: 1 },
        { source: '多的', count: 9 },
      ] },
    })
    const names = w.findAll('.name').map((n) => n.text())
    expect(names).toEqual(['多的', '少的'])
  })

  it('最长的一条占满宽度,其余按比例', () => {
    const w = mount(SourceBreakdown, {
      props: { sources: [
        { source: 'A', count: 10 },
        { source: 'B', count: 5 },
      ] },
    })
    const fills = w.findAll('.fill')
    expect(fills[0].attributes('style')).toContain('width: 100%')
    expect(fills[1].attributes('style')).toContain('width: 50%')
  })

  it('墨色阶梯:第一条最深,越往后越浅', () => {
    const w = mount(SourceBreakdown, {
      props: { sources: sources(4) },
    })
    const ops = w.findAll('.fill')
      .map((f) => Number(/opacity:\s*([\d.]+)/.exec(f.attributes('style'))[1]))
    for (let i = 1; i < ops.length; i += 1) {
      expect(ops[i]).toBeLessThan(ops[i - 1])
    }
  })

  it('超过 8 家时截断并合并其余', () => {
    const w = mount(SourceBreakdown, {
      props: { sources: sources(12) },
    })
    // 8 条明细 + 1 条「其他」
    expect(w.findAll('.rows li')).toHaveLength(9)
    expect(w.text()).toContain('其他 4 家')
    // 合并后的条数是后 4 家之和:4+3+2+1 = 10
    expect(w.find('.rest .n').text()).toBe('10')
  })

  it('恰好 8 家时不出现「其他」', () => {
    const w = mount(SourceBreakdown, {
      props: { sources: sources(8) },
    })
    expect(w.find('.rest').exists()).toBe(false)
  })

  it('统计总条数与来源家数', () => {
    const w = mount(SourceBreakdown, {
      props: { sources: [
        { source: 'A', count: 3 },
        { source: 'B', count: 2 },
      ] },
    })
    expect(w.text()).toContain('共 5 条')
    expect(w.text()).toContain('2 家')
  })

  it('用后端给的总数,不把只列出的前 10 家当全部', () => {
    // 真实数据:600519 有 52 家来源共 493 条新闻,而后端只给前 10 家的明细。
    // 把明细的 count 相加会得到 328 —— 少报 165 条,页面写「共 328 条」就是错的。
    const top10 = Array.from({ length: 10 }, (_, i) => ({
      source: `媒体${i + 1}`, count: 40 - i,
    }))
    const w = mount(SourceBreakdown, {
      props: { sources: top10, total: 493, sourceCount: 52 },
    })
    const text = w.text()
    expect(text).toContain('共 493 条')
    expect(text).toContain('52 家')
    // 明确告知下列只是前 10 家
    expect(text).toContain('下列仅前 10 家')
  })

  it('总数与已列出条数一致时不显示截断说明', () => {
    const w = mount(SourceBreakdown, {
      props: {
        sources: [{ source: 'A', count: 3 }, { source: 'B', count: 2 }],
        total: 5,
        sourceCount: 2,
      },
    })
    expect(w.text()).not.toContain('下列仅前')
  })

  it('空数据给出提示且不渲染条', () => {
    const w = mount(SourceBreakdown, { props: { sources: [] } })
    expect(w.text()).toContain('暂无新闻数据')
    expect(w.findAll('.fill')).toHaveLength(0)
  })

  it('count 为 0 的来源被过滤掉', () => {
    const w = mount(SourceBreakdown, {
      props: { sources: [
        { source: 'A', count: 3 },
        { source: '零', count: 0 },
      ] },
    })
    expect(w.findAll('.rows li')).toHaveLength(1)
  })

  it('缺少 source 字段时回退为未知来源', () => {
    const w = mount(SourceBreakdown, {
      props: { sources: [{ count: 2 }] },
    })
    expect(w.text()).toContain('未知来源')
  })
})
