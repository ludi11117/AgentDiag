/**
 * 翻页与导出工具的测试。
 *
 * 为什么先测这两个：它们是**纯函数**，且承载了项目里两次踩过的坑——
 *   1. total 用 len(records) 导致"共 20 条"（被 LIMIT 截断）；
 *   2. 页码越界不夹取，用户停在空列表上误以为"没有记录"。
 * 这两条都是"改对了才算对"的地方，值得有断言守着。
 */

import { describe, expect, it } from 'vitest'
import { pageWindow, historySummary, statusMeta, formatTime, recordsToCsv, csvFilename } from './historyUtils'

describe('pageWindow', () => {
  it('normal: 首页 offset 为 0', () => {
    const w = pageWindow(100, 1, 20)
    expect(w.page).toBe(1)
    expect(w.offset).toBe(0)
    expect(w.pageCount).toBe(5)
    expect(w.clamped).toBe(false)
  })

  it('normal: 第 3 页 offset 正确', () => {
    const w = pageWindow(100, 3, 20)
    expect(w.page).toBe(3)
    expect(w.offset).toBe(40)
    expect(w.clamped).toBe(false)
  })

  it('边界: 页码超出总页数时夹回最后一页', () => {
    // 换了筛选条件后结果变少（原来第 5 页，现在只剩 1 页）
    const w = pageWindow(15, 5, 20)
    expect(w.page).toBe(1)
    expect(w.offset).toBe(0)
    expect(w.pageCount).toBe(1)
    expect(w.clamped).toBe(true)
  })

  it('边界: 页码小于 1 时夹回第 1 页', () => {
    const w = pageWindow(100, 0, 20)
    expect(w.page).toBe(1)
    expect(w.clamped).toBe(true)
  })

  it('边界: 负数页码', () => {
    const w = pageWindow(100, -3, 20)
    expect(w.page).toBe(1)
    expect(w.offset).toBe(0)
  })

  it('边界: total=0 时仍有 1 页（避免除以 0 与"第 1/0 页"）', () => {
    const w = pageWindow(0, 1, 20)
    expect(w.pageCount).toBe(1)
    expect(w.page).toBe(1)
    expect(w.offset).toBe(0)
  })

  it('边界: 总数恰为整页倍数', () => {
    const w = pageWindow(40, 2, 20)
    expect(w.pageCount).toBe(2)
    expect(w.page).toBe(2)
    expect(w.offset).toBe(20)
    expect(w.clamped).toBe(false)
  })

  it('边界: 总数比整页倍数多 1 —— 必须多出第 2 页', () => {
    const w = pageWindow(41, 2, 20)
    expect(w.pageCount).toBe(3)
    expect(w.clamped).toBe(false)
  })

  it('边界: pageSize 为 0 或负数时兜底为 1，不抛异常', () => {
    expect(pageWindow(10, 1, 0).pageCount).toBe(10)
    expect(pageWindow(10, 1, -5).pageCount).toBe(10)
  })

  it('反向: 合法页码不得被标记为夹取', () => {
    // 防止实现改成"永远返回 clamped: true"这种恒真退化的写法
    expect(pageWindow(100, 2, 20).clamped).toBe(false)
    expect(pageWindow(100, 5, 20).clamped).toBe(false)
  })
})

describe('historySummary', () => {
  it('总数大于当前显示数时必须体现"还有更多"', () => {
    // 这条直接对应踩过的坑：total 用 len(records) 会永久显示"共 20 条"
    const s = historySummary(500, 20)
    expect(s).toContain('500')
    expect(s).toContain('20')
  })

  it('总数等于显示数时只说总数', () => {
    const s = historySummary(20, 20)
    expect(s).toBe('共找到 20 条记录')
  })

  it('反向: 一页装得下时不得出现"当前显示"', () => {
    expect(historySummary(5, 5)).not.toContain('当前显示')
  })
})

describe('statusMeta', () => {
  it('已知状态返回中文标签，不用英文原值', () => {
    expect(statusMeta('done').label).toBe('诊断完成')
    expect(statusMeta('insufficient_knowledge').label).toBe('知识库无依据')
  })

  it('未知状态原样返回而不崩', () => {
    expect(statusMeta('weird_state').label).toBe('weird_state')
  })

  it('空状态给出兜底文案', () => {
    expect(statusMeta('').label).toBe('未知')
  })

  it('降级状态与正常状态配色必须不同（否则用户看不出降级）', () => {
    expect(statusMeta('done').bg).not.toBe(statusMeta('llm_failed').bg)
  })
})

describe('formatTime', () => {
  it('ISO 串截断到秒并使用空格分隔', () => {
    expect(formatTime('2026-09-18T15:42:26.123456')).toBe('2026-09-18 15:42:26')
  })

  it('空值返回占位符而不是 undefined', () => {
    expect(formatTime(undefined)).toBe('-')
    expect(formatTime('')).toBe('-')
  })
})

describe('recordsToCsv', () => {
  const sample = [
    {
      id: 1,
      created_at: '2026-09-18T15:00:00',
      status: 'done',
      fault_description: '主轴异响',
      workorder: { 工单编号: 'WO-001' },
      diagnosis: { 根因判断: '轴承磨损' },
      cost: { 预计成本: '1450元' },
      correlation_id: 'abc123',
    },
  ]

  it('含表头与数据行', () => {
    const csv = recordsToCsv(sample as never)
    const lines = csv.split('\n')
    expect(lines.length).toBe(2)
    expect(lines[0]).toContain('故障描述')
  })

  it('带 UTF-8 BOM 以便 Excel 正确识别中文', () => {
    expect(recordsToCsv(sample as never).charCodeAt(0)).toBe(0xfeff)
  })

  it('空数组返回空串，不产生只有表头的残缺文件', () => {
    expect(recordsToCsv([])).toBe('')
  })

  it('字段含逗号与引号时正确转义', () => {
    const csv = recordsToCsv([
      { id: 1, fault_description: '主轴"异响",伴随高温', status: 'done' },
    ] as never)
    // 引号需双写转义
    expect(csv).toContain('""异响""')
  })

  it('以 = + - @ 开头的内容加单引号，防 CSV 注入', () => {
    // 工单编号与故障描述都来自模型输出，不可信
    const csv = recordsToCsv([
      { id: 1, fault_description: '=cmd|calc', status: 'done' },
    ] as never)
    expect(csv).toContain("'=cmd|calc")
  })

  it('反向: 普通中文内容不得被加上防注入单引号', () => {
    const csv = recordsToCsv([{ id: 1, fault_description: '主轴异响', status: 'done' }] as never)
    expect(csv).toContain('"主轴异响"')
    expect(csv).not.toContain("\"'主轴异响\"")
  })
})

describe('csvFilename', () => {
  it('使用 flawscope 前缀（项目已改名，不得退回 agentdiag）', () => {
    const name = csvFilename(new Date('2026-09-18T15:04:05'))
    expect(name).toMatch(/^flawscope_records_/)
    expect(name).not.toContain('agentdiag')
  })

  it('时间部分补零到固定宽度', () => {
    const name = csvFilename(new Date('2026-01-02T03:04:05'))
    expect(name).toBe('flawscope_records_20260102_030405.csv')
  })
})
