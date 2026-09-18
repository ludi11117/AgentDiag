/**
 * 诊断结果展示。
 *
 * 两条硬约束在这里落地：
 *   1. **降级工单不得补空章节**（项目硬约束 20）：没有依据的字段就不渲染，
 *      不能因为"布局好看"给降级工单补出空的"维修方案"——那是编造。
 *   2. **RiskLevel 必须显著**：`required_review` / `degraded` 类结果不能
 *      和正常结果长得一样，否则操作工可能照着一张"待人工确认"的工单去拆机。
 */

import type { DiagnosisResult, DiagnosisStatus } from '../types/contracts'
import { isTerminalFailure } from '../types/contracts'

interface Props {
  result: DiagnosisResult
}

/** 状态 → 中文说明 + 配色。与 app.py 的状态横幅口径保持一致。 */
const STATUS_META: Record<string, { label: string; bg: string; border: string; text: string }> = {
  done: { label: '诊断完成', bg: '#E1F5EE', border: '#0F6E56', text: '#04342C' },
  need_more_info: { label: '需要补充信息', bg: '#FAEEDA', border: '#854F0B', text: '#412402' },
  insufficient_knowledge: {
    label: '知识库无相关依据，无法自动诊断',
    bg: '#FAEEDA',
    border: '#854F0B',
    text: '#412402',
  },
  llm_failed: {
    label: '模型服务调用失败',
    bg: '#FCEBEB',
    border: '#A32D2D',
    text: '#791F1F',
  },
  pending_human_review: {
    label: '转人工复核',
    bg: '#FCEBEB',
    border: '#A32D2D',
    text: '#791F1F',
  },
}

function statusMeta(status: DiagnosisStatus) {
  return (
    STATUS_META[status] ?? {
      label: status,
      bg: '#F1EFE8',
      border: '#888780',
      text: '#2C2C2A',
    }
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div
        style={{
          fontSize: 13,
          fontWeight: 500,
          color: 'var(--color-text-primary)',
          marginBottom: 7,
          paddingBottom: 5,
          borderBottom: '0.5px solid var(--color-border-tertiary)',
        }}
      >
        {title}
      </div>
      {children}
    </div>
  )
}

function Field({ label, value }: { label: string; value?: React.ReactNode }) {
  if (value === undefined || value === null || value === '') return null
  return (
    <div style={{ display: 'flex', gap: 10, marginBottom: 6, fontSize: 13, lineHeight: 1.6 }}>
      <span style={{ color: 'var(--color-text-secondary)', minWidth: 68, flexShrink: 0 }}>
        {label}
      </span>
      <span style={{ color: 'var(--color-text-primary)' }}>{value}</span>
    </div>
  )
}

export function ResultView({ result }: Props) {
  const meta = statusMeta(result.status)
  const failed = isTerminalFailure(result.status)
  const wo = result.workorder ?? {}
  const dg = result.diagnosis ?? {}
  const cost = result.cost ?? {}
  const hasDiagnosis = Object.keys(dg).length > 0
  const hasWorkorder = Object.keys(wo).length > 0

  return (
    <div>
      {/* 状态横幅：降级 / 失败必须一眼可辨 */}
      <div
        style={{
          padding: '10px 13px',
          borderRadius: 8,
          background: meta.bg,
          border: `0.5px solid ${meta.border}`,
          color: meta.text,
          fontSize: 13,
          fontWeight: 500,
          marginBottom: 16,
        }}
      >
        {meta.label}
        {result.correlation_id && (
          <span
            style={{
              float: 'right',
              fontWeight: 400,
              fontSize: 12,
              opacity: 0.75,
              fontFamily: 'var(--font-mono)',
            }}
          >
            {result.correlation_id}
          </span>
        )}
      </div>

      {/* 追问：这是"信息不足"分支的唯一出路，必须比诊断结果更显眼 */}
      {result.followup_question && (
        <div
          style={{
            padding: '11px 13px',
            borderRadius: 8,
            background: 'var(--color-background-secondary)',
            border: '0.5px solid var(--color-border-secondary)',
            fontSize: 13,
            lineHeight: 1.6,
            marginBottom: 16,
          }}
        >
          <b>需要你补充：</b>
          {result.followup_question}
        </div>
      )}

      {/* 诊断结论。降级时不渲染"根因判断"框——那是编造 */}
      {hasDiagnosis && (
        <Section title="诊断结论">
          <Field label="报警代码" value={dg.报警代码} />
          <Field label="根因判断" value={dg.根因判断} />
          <Field label="依据" value={dg.依据} />
          {dg.排查建议 && dg.排查建议.length > 0 && (
            <Field
              label="排查建议"
              value={
                <ol style={{ margin: 0, paddingLeft: 18 }}>
                  {dg.排查建议.map((s, i) => (
                    <li key={i} style={{ marginBottom: 3 }}>
                      {s}
                    </li>
                  ))}
                </ol>
              }
            />
          )}
        </Section>
      )}

      {/* 辩论过程：只在真的辩论过时展示，且明确标出轮数与结果 */}
      {result.debate_round > 0 && (
        <Section title={`辩论过程（${result.debate_round} 轮）`}>
          {result.review && Object.keys(result.review).length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 4 }}>
                审核意见
              </div>
              <Field label="结论" value={(result.review as Record<string, string>).审核意见} />
              <Field label="理由" value={(result.review as Record<string, string>).理由} />
            </div>
          )}
          {result.rebuttal && Object.keys(result.rebuttal).length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 4 }}>
                诊断师反驳
              </div>
              <Field label="最终根因" value={result.rebuttal.最终根因} />
              <Field label="反驳理由" value={result.rebuttal.反驳理由} />
              <Field label="置信度" value={result.rebuttal.置信度} />
            </div>
          )}
          {result.final_review && Object.keys(result.final_review).length > 0 && (
            <div>
              <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 4 }}>
                最终复审
              </div>
              <Field label="结论" value={result.final_review.审核意见} />
              <Field
                label="置信度"
                value={
                  result.final_review.置信度 !== undefined
                    ? `${result.final_review.置信度}%`
                    : undefined
                }
              />
            </div>
          )}
        </Section>
      )}

      {/* 成本。N/A 是有效信息，不能当成"没有"直接隐藏 */}
      {(cost.预计成本 || cost.备件清单?.length || cost.计费提示) && (
        <Section title="成本核算">
          <Field label="备件清单" value={cost.备件清单?.join('、')} />
          <Field label="预计工时" value={cost.预计工时} />
          <Field label="预计成本" value={cost.预计成本} />
          {/* 计费提示是"未覆盖备件"的兜底说明，必须显示，否则用户以为报价是完整的 */}
          {cost.计费提示 && (
            <div
              style={{
                marginTop: 6,
                fontSize: 12,
                color: '#854F0B',
                padding: '6px 9px',
                background: '#FAEEDA',
                borderRadius: 6,
                border: '0.5px solid #EF9F27',
              }}
            >
              {cost.计费提示}
            </div>
          )}
        </Section>
      )}

      {/* 工单：只渲染实际存在的字段，缺失的不补占位（硬约束 20） */}
      {hasWorkorder && (
        <Section title="维修工单">
          {wo.风险等级 && (
            <div
              style={{
                padding: '8px 11px',
                borderRadius: 6,
                background: failed ? '#FCEBEB' : '#FAEEDA',
                border: `0.5px solid ${failed ? '#A32D2D' : '#EF9F27'}`,
                color: failed ? '#791F1F' : '#412402',
                fontSize: 13,
                fontWeight: 500,
                marginBottom: 10,
              }}
            >
              ⚠ {wo.风险等级}
              {wo.风险说明 && (
                <div style={{ fontWeight: 400, marginTop: 4, lineHeight: 1.55 }}>
                  {wo.风险说明}
                </div>
              )}
            </div>
          )}
          <Field label="工单编号" value={wo.工单编号} />
          <Field label="故障现象" value={wo.故障现象} />
          <Field label="根因" value={wo.根因} />
          <Field label="维修方案" value={wo.维修方案} />
          <Field label="备件清单" value={wo.备件清单?.join('、')} />
          <Field label="预计成本" value={wo.预计成本} />
          <Field label="安全注意" value={wo.安全注意事项} />
        </Section>
      )}

      {/* Token 用量：可观测性的对外呈现 */}
      {result.token_usage && Object.keys(result.token_usage).length > 0 && (
        <Section title="本次用量">
          <div style={{ display: 'flex', gap: 24, fontSize: 13 }}>
            {result.token_usage.总Token !== undefined && (
              <div>
                <div style={{ color: 'var(--color-text-secondary)', fontSize: 12 }}>Token</div>
                <div style={{ fontWeight: 500 }}>
                  {Number(result.token_usage.总Token).toLocaleString()}
                </div>
              </div>
            )}
            {result.token_usage.总耗时 !== undefined && (
              <div>
                <div style={{ color: 'var(--color-text-secondary)', fontSize: 12 }}>耗时</div>
                <div style={{ fontWeight: 500 }}>
                  {(Number(result.token_usage.总耗时) / 1000).toFixed(1)}s
                </div>
              </div>
            )}
            <div>
              <div style={{ color: 'var(--color-text-secondary)', fontSize: 12 }}>辩论轮数</div>
              <div style={{ fontWeight: 500 }}>{result.debate_round}</div>
            </div>
          </div>
        </Section>
      )}
    </div>
  )
}
