/**
 * 诊断页 —— 本次 React 改造的切入页面。
 *
 * 覆盖 Streamlit 版诊断页的全部交互：文本输入、图片上传、多轮追问、
 * 流式进度、结果展示、工单下载。历史页与统计页保留在 Streamlit，
 * 待验证这条链路稳定后再迁（避免一次替换太多导致回归面失控）。
 */

import { useCallback, useRef, useState } from 'react'
import { useDiagnosisStream } from '../hooks/useDiagnosisStream'
import { StateMachineView } from '../components/StateMachineView'
import { ResultView } from '../components/ResultView'
import { workorderUrl } from '../api/client'

const MAX_IMAGE_BYTES = 4 * 1024 * 1024

export function DiagnosePage() {
  const { state, start, abort, reset, buildContext } = useDiagnosisStream()
  const [input, setInput] = useState('')
  const [imagePreview, setImagePreview] = useState<string | null>(null)
  const [imageBase64, setImageBase64] = useState<string>('')
  const fileRef = useRef<HTMLInputElement>(null)

  const onPickImage = useCallback(async (file: File | undefined) => {
    if (!file) return
    if (file.size > MAX_IMAGE_BYTES) {
      alert(`图片过大（${(file.size / 1024 / 1024).toFixed(1)}MB），请压缩到 4MB 以内`)
      return
    }
    // 前端先压缩再传：后端 MAX_IMAGE_BASE64_CHARS 有上限，
    // 原图直传很容易在 4MB 文件上就超限（base64 会膨胀约 33%）
    const compressed = await compressImage(file)
    setImagePreview(compressed.dataUrl)
    setImageBase64(compressed.base64)
  }, [])

  const onSubmit = useCallback(() => {
    const text = input.trim()
    if (!text) return
    // 多轮追问时把历史上下文拼进去，与 Streamlit 版行为一致。
    // 后端每次请求都是无状态的，上下文只能由前端累积。
    const ctx = buildContext()
    const payload = ctx ? `${ctx}\n\n【本轮补充】${text}` : text
    start(payload, imageBase64)
  }, [input, imageBase64, start, buildContext])

  const workorderRecordId = state.result?.record_id ?? null
  const showWorkorderHint =
    !!state.result?.workorder?.工单编号 && !workorderRecordId && !state.result.followup_question

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '28px 24px' }}>
      <header style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 15, fontWeight: 500, margin: 0, color: 'var(--color-text-primary)' }}>
          FlawScope 故障诊断
        </h1>
        <p style={{ fontSize: 13, color: 'var(--color-text-secondary)', margin: '5px 0 0' }}>
          多智能体协作 · 混合检索 · 辩论式审核
        </p>
      </header>

      {/* 输入区 */}
      <div
        style={{
          border: '0.5px solid var(--color-border-tertiary)',
          borderRadius: 12,
          padding: 15,
          marginBottom: 18,
        }}
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="描述故障现象，例如：那台数控机床主轴转起来一顿一顿的，还有怪声，温度也高得离谱"
          rows={4}
          disabled={state.running}
          style={{
            width: '100%',
            boxSizing: 'border-box',
            border: 'none',
            outline: 'none',
            resize: 'vertical',
            fontSize: 13,
            lineHeight: 1.6,
            fontFamily: 'var(--font-sans)',
            background: 'transparent',
            color: 'var(--color-text-primary)',
          }}
        />

        {imagePreview && (
          <div style={{ marginTop: 8, position: 'relative', display: 'inline-block' }}>
            <img
              src={imagePreview}
              alt="设备照片预览"
              style={{ maxHeight: 110, borderRadius: 6, border: '0.5px solid var(--color-border-secondary)' }}
            />
            <button
              onClick={() => {
                setImagePreview(null)
                setImageBase64('')
                if (fileRef.current) fileRef.current.value = ''
              }}
              style={{
                position: 'absolute',
                top: -6,
                right: -6,
                width: 20,
                height: 20,
                borderRadius: '50%',
                border: 'none',
                background: '#A32D2D',
                color: '#fff',
                fontSize: 12,
                cursor: 'pointer',
                lineHeight: 1,
              }}
            >
              ×
            </button>
          </div>
        )}

        <div
          style={{
            display: 'flex',
            gap: 8,
            alignItems: 'center',
            marginTop: 10,
            paddingTop: 10,
            borderTop: '0.5px solid var(--color-border-tertiary)',
          }}
        >
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            style={{ display: 'none' }}
            onChange={(e) => void onPickImage(e.target.files?.[0])}
          />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={state.running}
            style={btnStyle(false, state.running)}
          >
            上传照片
          </button>

          {state.running ? (
            <button onClick={abort} style={btnStyle(true, false, '#A32D2D')}>
              中断诊断
            </button>
          ) : (
            <button onClick={onSubmit} disabled={!input.trim()} style={btnStyle(true, !input.trim())}>
              开始诊断
            </button>
          )}

          {!state.running && (state.result || state.error) && (
            <button onClick={reset} style={btnStyle(false, false)}>
              清空重来
            </button>
          )}

          <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--color-text-tertiary)' }}>
            {state.turns.length > 0 && `已进行 ${state.turns.length} 轮`}
          </span>
        </div>
      </div>

      {/* 状态机可视化：诊断中或已完成时显示 */}
      {(state.running || state.result) && (
        <StateMachineView
          visited={state.visited}
          active={state.active}
          debateRound={state.debateRound}
          running={state.running}
        />
      )}

      {/* 进度日志：保留原始 label，供想看细节的用户展开 */}
      {state.progressLog.length > 0 && (
        <details
          style={{
            marginBottom: 18,
            fontSize: 12,
            color: 'var(--color-text-secondary)',
          }}
        >
          <summary style={{ cursor: 'pointer', marginBottom: 6 }}>
            执行日志（{state.progressLog.length} 步）
          </summary>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              lineHeight: 1.7,
              padding: '8px 10px',
              background: 'var(--color-background-secondary)',
              borderRadius: 6,
            }}
          >
            {state.progressLog.map((line, i) => (
              <div key={i}>{line}</div>
            ))}
          </div>
        </details>
      )}

      {/* 错误 */}
      {state.error && (
        <div
          style={{
            padding: '10px 13px',
            borderRadius: 8,
            background: '#FCEBEB',
            border: '0.5px solid #A32D2D',
            color: '#791F1F',
            fontSize: 13,
            lineHeight: 1.6,
            marginBottom: 16,
          }}
        >
          {state.error}
          {state.retryAfter && (
            <div style={{ marginTop: 4, fontSize: 12 }}>
              系统当前并发已满（这是保护机制，不是你的请求有问题），建议 {state.retryAfter} 秒后重试。
            </div>
          )}
        </div>
      )}

      {/* 结果 */}
      {state.result && (
        <>
          <ResultView result={state.result} />
          {workorderRecordId ? (
            <a
              href={workorderUrl(workorderRecordId)}
              download
              style={{
                display: 'inline-block',
                marginTop: 6,
                padding: '7px 14px',
                borderRadius: 8,
                background: '#534AB7',
                color: '#fff',
                fontSize: 13,
                textDecoration: 'none',
              }}
            >
              下载工单（Markdown）
            </a>
          ) : (
            showWorkorderHint && (
              <p style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginTop: 6 }}>
                工单已生成但未落库（本次未返回记录 id），可稍后在历史页查看并下载。
              </p>
            )
          )}
        </>
      )}
    </div>
  )
}

function btnStyle(primary: boolean, disabled: boolean, overrideColor?: string) {
  return {
    padding: '7px 14px',
    borderRadius: 8,
    fontSize: 13,
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.45 : 1,
    border: primary ? 'none' : '0.5px solid var(--color-border-secondary)',
    background: overrideColor ?? (primary ? '#534AB7' : 'transparent'),
    color: primary ? '#fff' : 'var(--color-text-primary)',
    transition: 'opacity 0.15s',
  } as const
}

/** 把图片压到最长边 1280px、JPEG 质量 0.85，避免 base64 超限。 */
async function compressImage(file: File): Promise<{ dataUrl: string; base64: string }> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = () => reject(new Error('读取图片失败'))
    reader.readAsDataURL(file)
  })

  const img = await new Promise<HTMLImageElement>((resolve, reject) => {
    const el = new Image()
    el.onload = () => resolve(el)
    el.onerror = () => reject(new Error('图片解码失败'))
    el.src = dataUrl
  })

  const maxEdge = 1280
  const scale = Math.min(1, maxEdge / Math.max(img.width, img.height))
  if (scale === 1 && file.size < 1024 * 1024) {
    return { dataUrl, base64: dataUrl.split(',')[1] ?? '' }
  }

  const canvas = document.createElement('canvas')
  canvas.width = Math.round(img.width * scale)
  canvas.height = Math.round(img.height * scale)
  const ctx = canvas.getContext('2d')
  if (!ctx) return { dataUrl, base64: dataUrl.split(',')[1] ?? '' }
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height)

  const out = canvas.toDataURL('image/jpeg', 0.85)
  return { dataUrl: out, base64: out.split(',')[1] ?? '' }
}
