/**
 * 诊断历史页。
 *
 * 相比 Streamlit 版的两处实质改进：
 *   1. **列表用表格而不是逐条 st.json**。原版每展开一条就渲染 7 个 st.json 块，
 *      记录一多整个页面卡住；这里改成紧凑表格 + 按需展开详情。
 *   2. 查询条件变化时自动回第 1 页（原版靠 session_state 的签名字段，逻辑分散）。
 *
 * 保留的能力：关键词搜索、状态筛选、每页条数、翻页（含越界夹取）、
 * 单条展开、CSV 导出、工单 Markdown 下载。搜索做了防抖，避免每敲一个字都打后端。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { listRecords, deleteRecord, workorderUrl, ApiError } from '../api/client'
import type { Diagnosis, DiagnosisRecord, RecordListResponse, WorkOrder } from '../types/contracts'
import {
  pageWindow,
  historySummary,
  statusMeta,
  formatTime,
  recordsToCsv,
  csvFilename,
} from './historyUtils'

const PAGE_SIZE_OPTIONS = [20, 50, 100, 200]

export function HistoryPage() {
  const [keywordInput, setKeywordInput] = useState('')
  const [keyword, setKeyword] = useState('')
  const [status, setStatus] = useState('')
  const [pageSize, setPageSize] = useState(20)
  const [page, setPage] = useState(1)
  const [data, setData] = useState<RecordListResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)
  const debounceRef = useRef<number | null>(null)

  // 搜索防抖：每敲一个字就打一次后端，既浪费也会让输入感觉卡顿
  useEffect(() => {
    if (debounceRef.current) window.clearTimeout(debounceRef.current)
    debounceRef.current = window.setTimeout(() => {
      setKeyword(keywordInput.trim())
      setPage(1) // 换关键词必须回第 1 页，否则停在第 3 页大概率是空的
    }, 300)
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current)
    }
  }, [keywordInput])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const resp = await listRecords({ keyword, status, limit: pageSize, offset: (page - 1) * pageSize })
      setData(resp)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `加载失败：${(e as Error).message}`)
    } finally {
      setLoading(false)
    }
  }, [keyword, status, pageSize, page])

  useEffect(() => {
    void load()
  }, [load])

  const total = data?.total ?? 0
  const records = data?.records ?? []
  const win = useMemo(() => pageWindow(total, page, pageSize), [total, page, pageSize])

  // 后端返回的 total 可能让当前页码越界（例如删掉了本页最后一条），
  // 检测到就夹回去——不夹的话用户会停在空列表上，误以为"没有记录"。
  useEffect(() => {
    if (win.clamped && win.page !== page) setPage(win.page)
  }, [win.clamped, win.page, page])

  const onStatusChange = useCallback((v: string) => {
    setStatus(v)
    setPage(1)
  }, [])

  const onPageSizeChange = useCallback((v: number) => {
    setPageSize(v)
    setPage(1)
  }, [])

  const onExportCsv = useCallback(() => {
    const csv = recordsToCsv(records as unknown as Record<string, unknown>[])
    if (!csv) return
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = csvFilename()
    a.click()
    URL.revokeObjectURL(url)
  }, [records])

  const onDelete = useCallback(
    async (id: number) => {
      if (!window.confirm(`确定删除记录 #${id}？此操作不可撤销。`)) return
      try {
        await deleteRecord(id)
        if (expanded === id) setExpanded(null)
        await load()
      } catch (e) {
        setError(e instanceof ApiError ? e.message : `删除失败：${(e as Error).message}`)
      }
    },
    [expanded, load],
  )

  const statuses = data?.statuses ?? []

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '28px 24px' }}>
      <h1 style={{ fontSize: 15, fontWeight: 500, margin: '0 0 18px', color: 'var(--color-text-primary)' }}>
        诊断历史
      </h1>

      {/* 筛选栏 */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
        <input
          value={keywordInput}
          onChange={(e) => setKeywordInput(e.target.value)}
          placeholder="搜索故障描述关键词，如：液压、E-203、主轴"
          style={{
            flex: '1 1 260px',
            padding: '7px 11px',
            fontSize: 13,
            borderRadius: 8,
            border: '0.5px solid var(--color-border-secondary)',
            background: 'transparent',
            color: 'var(--color-text-primary)',
            fontFamily: 'inherit',
          }}
        />
        <select
          value={status}
          onChange={(e) => onStatusChange(e.target.value)}
          style={selectStyle}
        >
          <option value="">全部状态</option>
          {statuses.map((s) => (
            <option key={s} value={s}>
              {statusMeta(s).label}
            </option>
          ))}
        </select>
        <select
          value={pageSize}
          onChange={(e) => onPageSizeChange(Number(e.target.value))}
          style={selectStyle}
        >
          {PAGE_SIZE_OPTIONS.map((n) => (
            <option key={n} value={n}>
              每页 {n} 条
            </option>
          ))}
        </select>
        <button onClick={onExportCsv} disabled={records.length === 0} style={btnStyle(false, records.length === 0)}>
          导出当前页 CSV
        </button>
      </div>

      <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 10 }}>
        {loading ? '加载中…' : historySummary(total, records.length)}
        {win.pageCount > 1 && ` · 第 ${win.page} / ${win.pageCount} 页`}
      </div>

      {error && (
        <div
          style={{
            padding: '9px 12px',
            borderRadius: 8,
            background: '#FCEBEB',
            border: '0.5px solid #A32D2D',
            color: '#791F1F',
            fontSize: 13,
            marginBottom: 12,
          }}
        >
          {error}
        </div>
      )}

      {/* 列表 */}
      {records.length > 0 ? (
        <div style={{ border: '0.5px solid var(--color-border-tertiary)', borderRadius: 10, overflow: 'hidden' }}>
          {records.map((r, i) => (
            <RecordRow
              key={r.id}
              record={r}
              isOpen={expanded === r.id}
              isLast={i === records.length - 1}
              onToggle={() => setExpanded(expanded === r.id ? null : r.id)}
              onDelete={() => void onDelete(r.id)}
            />
          ))}
        </div>
      ) : (
        !loading && (
          <div
            style={{
              padding: 28,
              textAlign: 'center',
              fontSize: 13,
              color: 'var(--color-text-secondary)',
              border: '0.5px solid var(--color-border-tertiary)',
              borderRadius: 10,
            }}
          >
            {total > 0
              ? '当前页没有记录，请回到第 1 页查看。'
              : '没有符合条件的记录。先进行一次诊断，记录会自动保存。'}
          </div>
        )
      )}

      {/* 翻页 */}
      {win.pageCount > 1 && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12, marginTop: 16 }}>
          <button onClick={() => setPage(1)} disabled={win.page <= 1} style={btnStyle(false, win.page <= 1)}>
            首页
          </button>
          <button onClick={() => setPage(win.page - 1)} disabled={win.page <= 1} style={btnStyle(false, win.page <= 1)}>
            上一页
          </button>
          <span style={{ fontSize: 13, color: 'var(--color-text-secondary)', minWidth: 90, textAlign: 'center' }}>
            第 {win.page} / {win.pageCount} 页
          </span>
          <button
            onClick={() => setPage(win.page + 1)}
            disabled={win.page >= win.pageCount}
            style={btnStyle(false, win.page >= win.pageCount)}
          >
            下一页
          </button>
          <button
            onClick={() => setPage(win.pageCount)}
            disabled={win.page >= win.pageCount}
            style={btnStyle(false, win.page >= win.pageCount)}
          >
            末页
          </button>
        </div>
      )}
    </div>
  )
}

function RecordRow({
  record,
  isOpen,
  isLast,
  onToggle,
  onDelete,
}: {
  record: DiagnosisRecord
  isOpen: boolean
  isLast: boolean
  onToggle: () => void
  onDelete: () => void
}) {
  const meta = statusMeta(record.status)
  // 不能用 `?? {}`：空对象字面量会被推断成 `{}`，与 Partial<WorkOrder> 组成联合后
  // 读取 `wo.根因` 就会报 "does not exist on type '{}'"。
  // 这里的兜底语义是"没有就当作空工作单"，本来就是 Partial 的零值。
  const wo: Partial<WorkOrder> = record.workorder ?? {}
  const dg: Partial<Diagnosis> = record.diagnosis ?? {}
  const rootCause = (dg.根因判断 || wo.根因 || '—').slice(0, 60)
  const hasWorkorder = !!wo.工单编号

  return (
    <div style={{ borderBottom: isLast ? 'none' : '0.5px solid var(--color-border-tertiary)' }}>
      <div
        onClick={onToggle}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '9px 13px',
          cursor: 'pointer',
          background: isOpen ? 'var(--color-background-secondary)' : 'transparent',
          fontSize: 13,
        }}
      >
        <span style={{ color: 'var(--color-text-tertiary)', minWidth: 34, fontFamily: 'var(--font-mono)', fontSize: 12 }}>
          {record.id}
        </span>
        <span style={{ color: 'var(--color-text-secondary)', minWidth: 132, fontSize: 12 }}>
          {formatTime(record.created_at)}
        </span>
        <span
          style={{
            padding: '2px 8px',
            borderRadius: 5,
            background: meta.bg,
            color: meta.color,
            fontSize: 12,
            whiteSpace: 'nowrap',
          }}
        >
          {meta.label}
        </span>
        <span
          style={{
            flex: 1,
            color: 'var(--color-text-primary)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={record.fault_description}
        >
          {record.fault_description}
        </span>
        <span style={{ color: 'var(--color-text-tertiary)', fontSize: 12, minWidth: 16 }}>
          {isOpen ? '▾' : '▸'}
        </span>
      </div>

      {isOpen && (
        <div
          style={{
            padding: '4px 13px 15px 59px',
            background: 'var(--color-background-secondary)',
            fontSize: 13,
            lineHeight: 1.65,
          }}
        >
          <Field label="最终根因" value={rootCause} />
          <Field label="工单编号" value={wo.工单编号} />
          <Field label="追踪 ID" value={record.correlation_id} />

          {wo.风险等级 && (
            <div
              style={{
                marginTop: 8,
                padding: '7px 10px',
                borderRadius: 6,
                background: '#FAEEDA',
                border: '0.5px solid #EF9F27',
                color: '#412402',
              }}
            >
              ⚠ {wo.风险等级}
              {wo.风险说明 && <div style={{ marginTop: 3 }}>{wo.风险说明}</div>}
            </div>
          )}

          {/* 按需展开原始 JSON：默认收起，不必为看一个字段渲染 7 个 JSON 块 */}
          <details style={{ marginTop: 10 }}>
            <summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--color-text-secondary)' }}>
              查看完整数据（诊断 / 审核 / 辩论 / 成本 / 工单）
            </summary>
            <pre
              style={{
                marginTop: 8,
                padding: 11,
                borderRadius: 6,
                background: 'var(--color-background-primary)',
                border: '0.5px solid var(--color-border-tertiary)',
                fontSize: 11.5,
                lineHeight: 1.55,
                overflow: 'auto',
                maxHeight: 340,
                fontFamily: 'var(--font-mono)',
              }}
            >
              {JSON.stringify(record, null, 2)}
            </pre>
          </details>

          <div style={{ display: 'flex', gap: 8, marginTop: 11 }}>
            {hasWorkorder && (
              <a href={workorderUrl(record.id)} download style={{ ...btnStyle(true, false), textDecoration: 'none' }}>
                下载工单 Markdown
              </a>
            )}
            <button
              onClick={(e) => {
                e.stopPropagation()
                const blob = new Blob([JSON.stringify(record, null, 2)], { type: 'application/json' })
                const url = URL.createObjectURL(blob)
                const a = document.createElement('a')
                a.href = url
                a.download = `record_${record.id}.json`
                a.click()
                URL.revokeObjectURL(url)
              }}
              style={btnStyle(false, false)}
            >
              导出 JSON
            </button>
            <button onClick={onDelete} style={btnStyle(false, false, '#A32D2D')}>
              删除
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function Field({ label, value }: { label: string; value?: React.ReactNode }) {
  if (!value) return null
  return (
    <div style={{ display: 'flex', gap: 10, marginTop: 3 }}>
      <span style={{ color: 'var(--color-text-secondary)', minWidth: 64, flexShrink: 0, fontSize: 12 }}>
        {label}
      </span>
      <span style={{ color: 'var(--color-text-primary)' }}>{value}</span>
    </div>
  )
}

const selectStyle = {
  padding: '7px 10px',
  fontSize: 13,
  borderRadius: 8,
  border: '0.5px solid var(--color-border-secondary)',
  background: 'transparent',
  color: 'var(--color-text-primary)',
  fontFamily: 'inherit',
} as const

function btnStyle(primary: boolean, disabled: boolean, overrideColor?: string) {
  return {
    padding: '7px 13px',
    borderRadius: 8,
    fontSize: 13,
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.45 : 1,
    border: primary ? 'none' : '0.5px solid var(--color-border-secondary)',
    background: overrideColor ?? (primary ? '#534AB7' : 'transparent'),
    color: primary ? '#fff' : overrideColor ?? 'var(--color-text-primary)',
    fontFamily: 'inherit',
  } as const
}
