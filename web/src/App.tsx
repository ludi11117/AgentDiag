/**
 * 应用外壳：顶部导航 + 页面切换。
 *
 * 用 location.hash 做路由而不是引入 react-router：
 * 只有两个页面、不需要嵌套路由 / 路由守卫 / 数据预取，
 * 引入一个 30KB 的库换来 `useState` 就能做到的事，不划算。
 * 换成 hash 而非 pushState 是因为 hash 路由不需要服务端配合
 * ——刷新 /history 时 nginx 不必特殊配置（虽然我们也配了 try_files）。
 */

import { useEffect, useState } from 'react'
import { DiagnosePage } from './pages/DiagnosePage'
import { HistoryPage } from './pages/HistoryPage'

type Route = 'diagnose' | 'history'

const ROUTES: { key: Route; label: string }[] = [
  { key: 'diagnose', label: '故障诊断' },
  { key: 'history', label: '诊断历史' },
]

function parseHash(): Route {
  const h = window.location.hash.replace(/^#\/?/, '')
  return h === 'history' ? 'history' : 'diagnose'
}

export function App() {
  const [route, setRoute] = useState<Route>(parseHash)

  // 支持浏览器前进/后退：不监听的话，用户按后退键 URL 变了但页面不切
  useEffect(() => {
    const onHashChange = () => setRoute(parseHash())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const go = (r: Route) => {
    window.location.hash = `#/${r}`
    setRoute(r)
  }

  return (
    <div>
      <nav
        style={{
          borderBottom: '0.5px solid var(--color-border-tertiary)',
          padding: '0 24px',
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          position: 'sticky',
          top: 0,
          background: 'var(--color-background-primary)',
          zIndex: 10,
        }}
      >
        <span
          style={{
            fontSize: 13,
            fontWeight: 500,
            marginRight: 20,
            padding: '13px 0',
            color: 'var(--color-text-primary)',
          }}
        >
          FlawScope
        </span>
        {ROUTES.map((r) => {
          const active = route === r.key
          return (
            <button
              key={r.key}
              onClick={() => go(r.key)}
              style={{
                padding: '13px 12px',
                fontSize: 13,
                border: 'none',
                background: 'transparent',
                cursor: 'pointer',
                color: active ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
                fontWeight: active ? 500 : 400,
                // 用下边框而不是背景色做选中态：这个位置背景色会显得很重
                borderBottom: active ? '2px solid #534AB7' : '2px solid transparent',
                fontFamily: 'inherit',
              }}
            >
              {r.label}
            </button>
          )
        })}
        <a
          href="/api/docs"
          target="_blank"
          rel="noreferrer"
          style={{
            marginLeft: 'auto',
            fontSize: 12,
            color: 'var(--color-text-tertiary)',
            textDecoration: 'none',
          }}
        >
          API 文档
        </a>
      </nav>

      {route === 'diagnose' ? <DiagnosePage /> : <HistoryPage />}
    </div>
  )
}
