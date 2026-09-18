/**
 * 诊断流程的状态管理 hook。
 *
 * 这是前端最复杂的一块：需要同时管理
 *   - SSE 流的生命周期（启动 / 中断 / 重连语义）
 *   - 节点进度（用于状态机可视化）
 *   - 多轮追问的上下文累积（与 Streamlit 版行为对齐）
 *   - 并发闸门返回 503 时的重试语义
 *
 * 刻意不引入状态管理库：状态是单一的、由 reducer 收敛的，
 * 用 useReducer 已经足够表达。引入 Redux/Zustand 只会让"状态从哪来"更难讲清。
 */

import { useCallback, useReducer, useRef } from 'react'
import { diagnoseStream, ApiError } from '../api/client'
import type { DiagnosisRequest, DiagnosisResult, ProgressEvent } from '../types/contracts'
import { nodeFromLabel, type NodeId } from '../state/machine'

/** 一轮对话（用户输入 + 系统响应）。多轮追问时累积。 */
export interface Turn {
  userInput: string
  followupQuestion?: string
}

interface StreamState {
  /** 是否正在跑诊断 */
  running: boolean
  /** 已走过的节点 */
  visited: Set<NodeId>
  /** 当前正在执行的节点 */
  active: NodeId | null
  /** 实时进度文案（直接用后端 label，里面带序号，可读性好） */
  progressLog: string[]
  /** 辩论轮数（后端实时推） */
  debateRound: number
  /** 最终结果，null 表示还没出 */
  result: DiagnosisResult | null
  /** 错误信息，null 表示无错误 */
  error: string | null
  /** 被并发闸门挡下时的建议重试秒数 */
  retryAfter: number | null
  /** 本次累计的对话轮次，用于"多轮追问上下文" */
  turns: Turn[]
  /** 当前 correlation_id（诊断开始后即有） */
  correlationId: string | null
}

type Action =
  | { type: 'start'; userInput: string }
  | { type: 'progress'; payload: ProgressEvent }
  | { type: 'result'; payload: DiagnosisResult }
  | { type: 'error'; message: string; retryAfter?: number }
  | { type: 'reset' }

const initialState: StreamState = {
  running: false,
  visited: new Set(),
  active: null,
  progressLog: [],
  debateRound: 0,
  result: null,
  error: null,
  retryAfter: null,
  turns: [],
  correlationId: null,
}

function reducer(state: StreamState, action: Action): StreamState {
  switch (action.type) {
    case 'start':
      return {
        ...state,
        running: true,
        visited: new Set(),
        active: null,
        progressLog: [],
        debateRound: 0,
        result: null,
        error: null,
        retryAfter: null,
        turns: [...state.turns, { userInput: action.userInput }],
      }

    case 'progress': {
      const node = nodeFromLabel(action.payload.label)
      const visited = new Set(state.visited)
      // 上一次 active 的节点标记为已走过：后端推进到下一个节点时，
      // 前一个节点其实已经完成了。这样进度条才会持续向右。
      if (state.active && state.active !== node?.id) {
        visited.add(state.active)
      }
      if (node) visited.add(node.id)

      return {
        ...state,
        visited,
        active: node?.id ?? state.active,
        progressLog: [...state.progressLog, action.payload.label],
        debateRound: Math.max(state.debateRound, action.payload.debate_round),
        correlationId: action.payload.correlation_id || state.correlationId,
      }
    }

    case 'result':
      return {
        ...state,
        running: false,
        result: action.payload,
        // 收尾时把 active 清掉，否则最后一个节点会永远显示"进行中"
        active: null,
        debateRound: action.payload.debate_round,
        correlationId: action.payload.correlation_id || state.correlationId,
        // 追问轮次记进对话历史，下一轮把上下文带回去
        turns: action.payload.followup_question
          ? state.turns.map((t, i) =>
              i === state.turns.length - 1
                ? { ...t, followupQuestion: action.payload.followup_question }
                : t,
            )
          : state.turns,
      }

    case 'error':
      return {
        ...state,
        running: false,
        error: action.message,
        retryAfter: action.retryAfter ?? null,
        active: null,
      }

    case 'reset':
      return { ...initialState, turns: state.turns }

    default:
      return state
  }
}

export function useDiagnosisStream() {
  const [state, dispatch] = useReducer(reducer, initialState)
  // 保存中断函数。用 ref 而不是 state：它不参与渲染，
  // 且必须在组件重渲染之间保持同一个引用，否则中断按钮会失效。
  const abortRef = useRef<(() => void) | null>(null)

  const start = useCallback(
    (faultDescription: string, imageBase64?: string) => {
      // 若上一次还在跑，先中断，避免两条流同时往同一个 state 里写
      abortRef.current?.()
      dispatch({ type: 'start', userInput: faultDescription })

      const payload: DiagnosisRequest = { fault_description: faultDescription }
      if (imageBase64) payload.image_base64 = imageBase64

      abortRef.current = diagnoseStream(payload, {
        onProgress: (e) => dispatch({ type: 'progress', payload: e }),
        onResult: (r) => dispatch({ type: 'result', payload: r }),
        onError: (message) => {
          // 503 的语义是"系统忙"，不是"你的请求有问题"，
          // 要把 Retry-After 带出来让 UI 能给出可操作的建议
          const retryMatch = message.match(/建议 (\d+) 秒后重试/)
          dispatch({
            type: 'error',
            message,
            retryAfter: retryMatch?.[1] ? Number(retryMatch[1]) : undefined,
          })
        },
      })
    },
    [],
  )

  const abort = useCallback(() => {
    abortRef.current?.()
    abortRef.current = null
    dispatch({ type: 'error', message: '已手动中断本次诊断' })
  }, [])

  const reset = useCallback(() => {
    abortRef.current?.()
    abortRef.current = null
    dispatch({ type: 'reset' })
  }, [])

  /** 把多轮追问累积成一段完整上下文，与后端 append 逻辑对齐。 */
  const buildContext = useCallback((): string => {
    return state.turns
      .map((t, i) => {
        const head = `第${i + 1}轮：${t.userInput}`
        return t.followupQuestion ? `${head}\n（系统追问：${t.followupQuestion}）` : head
      })
      .join('\n')
  }, [state.turns])

  return { state, start, abort, reset, buildContext }
}

export { ApiError }
