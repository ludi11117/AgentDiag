/**
 * 按钮样式的唯一来源。
 *
 * 为什么单独抽出来：这个函数原本在 `DiagnosePage.tsx` 和 `HistoryPage.tsx` 里
 * **各有一份几乎一样的副本**，而且两份的 bug 还不一样——
 *
 *   - DiagnosePage 版：`color: primary ? '#fff' : ...`
 *     ⇒ `btnStyle(false, false, '#A32D2D')`（危险操作）得到"深色文字 + 深红背景"，
 *       浅色主题下删除按钮几乎读不出来。
 *   - HistoryPage 版：`color: primary ? '#fff' : overrideColor ?? ...`
 *     ⇒ 文字色被设成和背景同一个 `#A32D2D`，**红底红字**，完全隐形。
 *
 * 两份副本的存在让"修好一个"变成"以为修好了"——我第一次只改了 DiagnosePage 那份，
 * 而历史页用的是它自己那份，页面看起来毫无变化。所以这里不是"顺手整理"，
 * 而是消除一个会让人误判修复状态的重复。
 */

/**
 * @param primary      是否主按钮（实心主色）
 * @param disabled     是否禁用（降透明度 + not-allowed）
 * @param overrideColor 覆盖背景色，用于危险操作（如 `#A32D2D`）
 */
export function btnStyle(primary: boolean, disabled: boolean, overrideColor?: string) {
  // 文字色必须跟着**背景**走：只要有背景色（主色或 overrideColor），文字就该是白的。
  // 判断依据是 `filled` 而不是 `primary`——后者会漏掉 overrideColor 这条路径。
  const filled = primary || !!overrideColor
  return {
    padding: '7px 13px',
    borderRadius: 8,
    fontSize: 13,
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.45 : 1,
    border: filled ? 'none' : '0.5px solid var(--color-border-secondary)',
    background: overrideColor ?? (primary ? '#534AB7' : 'transparent'),
    color: filled ? '#fff' : 'var(--color-text-primary)',
    fontFamily: 'inherit',
    transition: 'opacity 0.15s',
  } as const
}
