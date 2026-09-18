/**
 * 诊断过程可视化：把 9 个节点的执行过程画成一条水平进度链。
 *
 * 这是相比 Streamlit 版最大的增量——原版只能显示一行行滚动的文字日志，
 * 看不出"走到哪了、还剩几步、辩论环走了没有"。诊断一次要几十秒，
 * 用户在这段时间里最需要的正是这个。
 *
 * 辩论环（review → rebuttal → final_review）单独用高亮标识：
 * 它是本项目多 Agent 架构的核心，也是"单 Agent 做不到"的论据所在。
 */

import type { NodeId, NodeState } from '../state/machine'
import { NODES, computeNodeStates } from '../state/machine'

interface Props {
  visited: Set<NodeId>
  active: NodeId | null
  debateRound: number
  running: boolean
}

const STATE_STYLE: Record<NodeState, { bg: string; border: string; text: string }> = {
  pending: { bg: '#F1EFE8', border: '#D3D1C7', text: '#888780' },
  active: { bg: '#E6F1FB', border: '#185FA5', text: '#042C53' },
  done: { bg: '#E1F5EE', border: '#0F6E56', text: '#04342C' },
}

export function StateMachineView({ visited, active, debateRound, running }: Props) {
  const states = computeNodeStates(visited, active)
  const debateEntered = visited.has('review') || active === 'review'

  return (
    <div style={{ marginBottom: 20 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 10,
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--color-text-primary)' }}>
          诊断过程
        </span>
        <span style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>
          {debateEntered ? (
            <>
              辩论环已触发 · 第 <b>{debateRound || 1}</b> 轮
            </>
          ) : running ? (
            '等待进入辩论环'
          ) : (
            ''
          )}
        </span>
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: 0,
          flexWrap: 'wrap',
        }}
      >
        {NODES.map((node, i) => {
          const s = states.get(node.id) ?? 'pending'
          const style = STATE_STYLE[s]
          const isActive = s === 'active'
          return (
            <div key={node.id} style={{ display: 'flex', alignItems: 'center' }}>
              <div
                title={node.detail}
                style={{
                  minWidth: 78,
                  padding: '7px 9px',
                  borderRadius: 8,
                  background: style.bg,
                  border: `0.5px solid ${style.border}`,
                  color: style.text,
                  fontSize: 12,
                  lineHeight: 1.35,
                  transition: 'background 0.25s, border-color 0.25s',
                  animation: isActive ? 'pulse 1.4s ease-in-out infinite' : undefined,
                  position: 'relative',
                }}
              >
                <div style={{ fontWeight: 500, whiteSpace: 'nowrap' }}>
                  {node.index} {node.title}
                </div>
                {node.inDebateLoop && (
                  <div
                    style={{
                      position: 'absolute',
                      top: 3,
                      right: 4,
                      width: 5,
                      height: 5,
                      borderRadius: '50%',
                      background: debateEntered ? '#854F0B' : '#D3D1C7',
                    }}
                    title="属于辩论环"
                  />
                )}
              </div>
              {i < NODES.length - 1 && (
                <div
                  style={{
                    width: 14,
                    height: 1.5,
                    background: s === 'done' ? '#0F6E56' : '#D3D1C7',
                    transition: 'background 0.25s',
                  }}
                />
              )}
            </div>
          )
        })}
      </div>

      {/* 辩论环的分组标注，让"这三步是循环的"在视觉上成立 */}
      {debateEntered && (
        <div
          style={{
            marginTop: 8,
            fontSize: 11,
            color: '#854F0B',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <span
            style={{
              display: 'inline-block',
              width: 26,
              height: 8,
              border: '0.5px solid #854F0B',
              borderTop: 'none',
              borderRadius: '0 0 4px 4px',
            }}
          />
          审核 ⇄ 反驳 可循环多轮，直到通过或达上限
        </div>
      )}

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.55; }
        }
        @media (prefers-reduced-motion: reduce) {
          * { animation: none !important; }
        }
      `}</style>
    </div>
  )
}
