import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import NewsList from '../src/components/NewsList.vue'

const NEWS = [
  { id: 1, title: '贵州茅台重回A股股王', url: 'https://x/1', source: '新华财经', publish_time: '2026-10-12 16:08:01', sentiment: '' },
  { id: 2, title: '11只白酒股下跌', url: 'https://x/2', source: '北京商报', publish_time: '2026-10-13 17:15:22', sentiment: '' },
]

describe('NewsList', () => {
  it('渲染标题与来源', () => {
    const w = mount(NewsList, { props: { news: NEWS } })
    expect(w.text()).toContain('贵州茅台重回A股股王')
    expect(w.text()).toContain('新华财经')
    expect(w.findAll('li')).toHaveLength(2)
  })

  it('链接指向新闻地址且新窗口打开', () => {
    const w = mount(NewsList, { props: { news: NEWS } })
    const a = w.find('a')
    expect(a.attributes('href')).toBe('https://x/1')
    expect(a.attributes('target')).toBe('_blank')
  })

  it('无数据时给出提示', () => {
    const w = mount(NewsList, { props: { news: [] } })
    expect(w.text()).toContain('暂无新闻')
    expect(w.findAll('li')).toHaveLength(0)
  })

  it('sentiment 为空时不渲染情感标签', () => {
    const w = mount(NewsList, { props: { news: NEWS } })
    expect(w.findAll('.tag')).toHaveLength(0)
  })

  it('有 sentiment 时渲染对应标签', () => {
    const w = mount(NewsList, {
      props: {
        news: [
          { ...NEWS[0], sentiment: 'positive' },
          { ...NEWS[1], sentiment: 'negative' },
        ],
      },
    })
    const tags = w.findAll('.tag')
    expect(tags).toHaveLength(2)
    expect(tags[0].text()).toBe('利好')
    expect(tags[1].text()).toBe('利空')
  })

  it('整行带情感类名,便于用左侧竖线扫出情绪分布', () => {
    const w = mount(NewsList, {
      props: {
        news: [
          { ...NEWS[0], sentiment: 'positive' },
          { ...NEWS[1], sentiment: 'negative' },
        ],
      },
    })
    const rows = w.findAll('li')
    expect(rows[0].classes()).toContain('pos')
    expect(rows[1].classes()).toContain('neg')
  })

  it('未标注的行不带情感类名', () => {
    const w = mount(NewsList, { props: { news: NEWS } })
    const rows = w.findAll('li')
    expect(rows[0].classes()).not.toContain('pos')
    expect(rows[0].classes()).not.toContain('neg')
    expect(rows[0].classes()).not.toContain('neu')
  })

  it('发布时间拆成日期与时刻两栏', () => {
    const w = mount(NewsList, { props: { news: NEWS } })
    const when = w.find('.when')
    expect(when.find('.d').text()).toBe('2026-10-12')
    expect(when.find('.t').text()).toBe('16:08')
  })

  it('时间格式异常时不抛错', () => {
    const w = mount(NewsList, {
      props: { news: [{ ...NEWS[0], publish_time: '' }] },
    })
    expect(w.find('.when .d').text()).toBe('-')
    expect(w.find('.when .t').text()).toBe('')
  })

  it('非 http(s) 地址不渲染成链接', () => {
    // 后端入库时已用 collector._safe_http_url 挡过一次,但库里可能
    // 还留着加校验之前抓的旧数据。javascript: 落进 <a href> 就是 XSS。
    const w = mount(NewsList, {
      props: {
        news: [
          { ...NEWS[0], id: 1, url: 'javascript:alert(1)' },
          { ...NEWS[1], id: 2, url: 'data:text/html,<b>x</b>' },
        ],
      },
    })
    expect(w.findAll('a')).toHaveLength(0)
    expect(w.findAll('.title.plain')).toHaveLength(2)
    // 标题本身仍要显示出来
    expect(w.text()).toContain('贵州茅台重回A股股王')
  })

  it('空 url 时退化成纯文本', () => {
    const w = mount(NewsList, {
      props: { news: [{ ...NEWS[0], url: '' }] },
    })
    expect(w.findAll('a')).toHaveLength(0)
    expect(w.find('.title').text()).toBe('贵州茅台重回A股股王')
  })

  it('外部链接带 noreferrer', () => {
    const w = mount(NewsList, { props: { news: NEWS } })
    expect(w.find('a').attributes('rel')).toContain('noreferrer')
  })
})
