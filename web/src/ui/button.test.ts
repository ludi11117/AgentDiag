/**
 * 按钮样式（`src/ui/button.ts`）。
 *
 * 这份测试的直接动因是一个**真实 bug**：这个函数原本在 `DiagnosePage.tsx` 与
 * `HistoryPage.tsx` 里各有一份副本，两版都把文字色绑在了 `primary` 上，
 * 于是危险按钮 `btnStyle(false, false, '#A32D2D')` 得到深色文字 + 深红背景
 * （历史页那版更是**红底红字**，按钮整个隐形）。
 *
 * 这个 bug 逃过了类型检查、逃过了构建、也逃过了肉眼 review——**只有真的渲染出来才看见**。
 * 所以下面测的不是"颜色好不好看"，而是两条能被机器判定的不变式。
 */

import { describe, expect, it } from 'vitest'
import { btnStyle } from './button'

/** 把 `rgb(255, 255, 255)` / `#A32D2D` 之类归一成大写十六进制，便于比较。 */
function normalize(color: string): string {
  const hex = color.trim().toUpperCase()
  if (!hex.startsWith('#')) throw new Error(`只接受 #RRGGBB，收到：${color}`)
  return hex
}

describe('btnStyle', () => {
  it('主按钮：实心主色 + 白字', () => {
    const s = btnStyle(true, false)
    expect(s.color).toBe('#fff')
    expect(s.background).not.toBe('transparent')
    expect(s.border).toBe('none')
  })

  it('次级按钮：透明底 + 主题文字色 + 有边框', () => {
    const s = btnStyle(false, false)
    expect(s.background).toBe('transparent')
    expect(s.color).toBe('var(--color-text-primary)')
    expect(s.border).not.toBe('none')
  })

  describe('危险按钮（overrideColor）', () => {
    const DANGER = '#A32D2D'

    it('文字必须是白色而不是与背景同色（否则红底红字，按钮隐形）', () => {
      const s = btnStyle(false, false, DANGER)
      // 这是那个真实 bug 的核心断言：修复前这里是 DANGER，等于把文字画没了
      expect(s.color).toBe('#fff')
      expect(s.color).not.toBe(s.background)
    })

    it('背景与文字不能相同（对任意覆盖色都成立）', () => {
      for (const c of ['#A32D2D', '#534AB7', '#1F7A3D']) {
        const s = btnStyle(false, false, c)
        expect(normalize(s.color)).not.toBe(normalize(c))
      }
    })

    it('有了背景色就不该再画边框（实心按钮不需要）', () => {
      expect(btnStyle(false, false, DANGER).border).toBe('none')
    })

    it('覆盖色优先于 primary 的背景色', () => {
      // primary=true 且给了 overrideColor 时，以 overrideColor 为准
      expect(btnStyle(true, false, DANGER).background).toBe(DANGER)
    })
  })

  it('禁用时降低透明度并显示 not-allowed', () => {
    const s = btnStyle(false, true)
    expect(s.opacity).toBeLessThan(1)
    expect(s.cursor).toBe('not-allowed')
  })

  it('不禁用时是可点击光标、完全不透明', () => {
    const s = btnStyle(false, false)
    expect(s.cursor).toBe('pointer')
    expect(s.opacity).toBe(1)
  })
})
