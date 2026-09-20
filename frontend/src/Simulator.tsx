/**
 * Симулятор транзакций (ТЗ §8, брифинг §5.E).
 *
 * Задача — за десять секунд поменять параметры транзакции и увидеть новый
 * ответ системы. Поток: `Input -> POST /predict -> Display Response`.
 * Никаких mock-данных и никакой копии Risk Engine на клиенте.
 *
 * Сводная аналитика живёт в соседнем `Dashboard.tsx`: здесь одна операция,
 * там весь поток.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'

import { ApiError, apiBaseUrl, fetchScenarios, predict, sendFeedback } from './api'
import { CONTEXT_FIELDS, FORM_FIELDS, formToRequest, scenarioToForm } from './form'
import { VERDICT_LABEL, feedbackHeadline } from './feedback'
import { WAKE_UP_HINT, useSlowHint } from './useSlowHint'
import type { FieldSpec, FormState } from './form'
import type {
  Decision,
  FeedbackAccepted,
  PredictionResponse,
  Scenario,
  Verdict,
} from './types'

/** Что показать в блоке ошибки: заголовок и разбор по полям. */
interface DisplayError {
  title: string
  details: string[]
}

/**
 * Один прогон анализа.
 *
 * `persisted` запоминается вместе с ответом, а не читается из галочки:
 * галочку могли переключить уже после анализа, и тогда интерфейс
 * предлагал бы разметить операцию, которой в истории нет.
 *
 * `seq` отличает два одинаковых ответа подряд. Без него повторное нажатие
 * Analyze не сбрасывало бы блок разметки, и рядом со свежим вердиктом
 * висело бы подтверждение метки, поставленной на прошлый.
 */
interface Analysis {
  seq: number
  result: PredictionResponse
  persisted: boolean
}

const DECISION_CLASS: Record<Decision, string> = {
  APPROVE: 'approve',
  CHALLENGE: 'challenge',
  BLOCK: 'block',
}

export default function Simulator() {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [activeScenario, setActiveScenario] = useState<string>('')
  const [form, setForm] = useState<FormState>({})
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [error, setError] = useState<DisplayError | null>(null)
  const [loading, setLoading] = useState(false)
  const [startupError, setStartupError] = useState<string>('')
  const [persist, setPersist] = useState(true)
  // Ждём либо ответа на анализ, либо самой первой загрузки сценариев.
  const waking = useSlowHint(loading || (scenarios.length === 0 && startupError === ''))

  // Пресеты берём с backend: тот же источник, что у автотестов и
  // docs/HAND_TESTING.md, поэтому кнопки не могут с ними разойтись.
  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const items = await fetchScenarios()
        if (cancelled) return
        setScenarios(items)
        if (items.length > 0) {
          setActiveScenario(items[0].key)
          setForm(scenarioToForm(items[0]))
        }
      } catch (cause) {
        if (cancelled) return
        setStartupError(
          cause instanceof ApiError ? cause.message : 'Не удалось загрузить сценарии',
        )
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [])

  const applyScenario = useCallback((scenario: Scenario) => {
    setActiveScenario(scenario.key)
    setForm(scenarioToForm(scenario))
    setAnalysis(null)
    setError(null)
  }, [])

  const updateField = useCallback((name: string, value: string) => {
    setForm((previous) => ({ ...previous, [name]: value }))
  }, [])

  const analyze = useCallback(async () => {
    const { body, invalid } = formToRequest(form)
    if (invalid.length > 0) {
      // Заведомо испорченный запрос не отправляем: иначе backend ответит 200
      // по другим данным, и пользователь не узнает, что его ввод потерян.
      setError({ title: 'Форма заполнена неверно — запрос не отправлен', details: invalid })
      setAnalysis(null)
      return
    }

    setLoading(true)
    setError(null)
    try {
      const result = await predict({ ...body, persist })
      setAnalysis((previous) => ({
        seq: (previous?.seq ?? 0) + 1,
        result,
        persisted: persist,
      }))
    } catch (cause) {
      const failure = cause instanceof ApiError ? cause : new ApiError(String(cause), 0, null)
      setError({
        title: `${failure.status > 0 ? `HTTP ${failure.status}` : 'Сеть'} — ${failure.message}`,
        details: failure.fieldErrors,
      })
      setAnalysis(null)
    } finally {
      setLoading(false)
    }
  }, [form, persist])

  const currentScenario = useMemo(
    () => scenarios.find((item) => item.key === activeScenario),
    [scenarios, activeScenario],
  )

  if (startupError) {
    return (
      <section className="panel alert">
        <h2>Сценарии не загрузились</h2>
        <strong>{startupError}</strong>
        <p>
          Ожидаемый адрес backend: <code>{apiBaseUrl}</code>
        </p>
        <pre>uvicorn app.main:app --reload --port 8000 --app-dir backend</pre>
      </section>
    )
  }

  return (
    <>
      <section className="panel">
        <h2>Сценарии</h2>
        <div className="scenario-buttons">
          {scenarios.map((scenario) => (
            <button
              key={scenario.key}
              type="button"
              className={scenario.key === activeScenario ? 'chip active' : 'chip'}
              onClick={() => applyScenario(scenario)}
              title={scenario.description}
            >
              {scenario.title}
            </button>
          ))}
        </div>
        {currentScenario && (
          <p className="hint">
            {currentScenario.description} <br />
            <strong>Ожидание по ТЗ:</strong> {currentScenario.expectation}
          </p>
        )}
      </section>

      <section className="panel">
        <h2>Transaction</h2>
        <div className="grid">
          {FORM_FIELDS.map((field) => (
            <Field
              key={field.name}
              spec={field}
              value={form[field.name] ?? ''}
              onChange={updateField}
            />
          ))}
        </div>

        <details className="context">
          <summary>Контекст клиента — что система знает о нём до этой операции</summary>
          <p className="hint">
            Эти поля отправляются вместе с транзакцией. Если их очистить, система
            возьмёт данные из накопленного профиля, и повторные нажатия Analyze
            начнут давать разные ответы: устройство, засветившееся в прошлом
            запросе, перестанет быть новым.
          </p>
          <div className="grid">
            {CONTEXT_FIELDS.map((field) => (
              <Field
                key={field.name}
                spec={field}
                value={form[field.name] ?? ''}
                onChange={updateField}
              />
            ))}
          </div>
        </details>

        <div className="actions">
          <button type="button" className="primary" onClick={() => void analyze()} disabled={loading}>
            {loading ? 'Анализ…' : 'Analyze Transaction'}
          </button>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={persist}
              onChange={(event) => setPersist(event.target.checked)}
            />
            <span>сохранять в историю (persist)</span>
          </label>
        </div>

        {waking && <p className="hint">{WAKE_UP_HINT}</p>}
      </section>

      {error && (
        <section className="panel alert">
          <h2>Ошибка</h2>
          <p>
            <strong>{error.title}</strong>
          </p>
          {error.details.length > 0 && (
            <ul>
              {error.details.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          )}
        </section>
      )}

      {analysis && (
        <>
          <Result result={analysis.result} />
          <FeedbackControls key={analysis.seq} analysis={analysis} />
        </>
      )}
    </>
  )
}

/**
 * Отметка вердикта — единственное место, где в систему попадает истина.
 *
 * Что именно значит «ошибочный», зависит от решения, и выводит это
 * backend: он знает, что утверждал. Клиент отправляет отметку и
 * показывает записанное — считать метку у себя значило бы завести вторую
 * копию правила и однажды разойтись с ней (ТЗ §11).
 */
function FeedbackControls({ analysis }: { analysis: Analysis }) {
  const [sending, setSending] = useState<Verdict | null>(null)
  const [accepted, setAccepted] = useState<FeedbackAccepted | null>(null)
  const [failure, setFailure] = useState('')

  const submit = useCallback(
    async (verdict: Verdict) => {
      setSending(verdict)
      setFailure('')
      try {
        setAccepted(await sendFeedback(analysis.result.transaction_id, verdict))
      } catch (cause) {
        setFailure(cause instanceof ApiError ? cause.message : 'Метку не удалось сохранить')
      } finally {
        setSending(null)
      }
    },
    [analysis.result.transaction_id],
  )

  if (!analysis.persisted) {
    return (
      <section className="panel">
        <h2>Разметка</h2>
        <p className="hint">
          Операция посчитана в режиме «что если»: галочка «сохранять в историю» была
          снята, и в истории её нет — размечать нечего. Повторите анализ с включённой
          галочкой, чтобы отметить вердикт.
        </p>
      </section>
    )
  }

  return (
    <section className="panel">
      <h2>Система права?</h2>
      <p className="hint">
        Отметка — не оценка интерфейса, а настоящая метка для системы. Из накопленного
        считается подтверждённое качество на вкладке «Дашборд», и оно же станет
        обучающей выборкой следующего цикла. Отметка учитывает, что именно система
        утверждала: подтверждённый BLOCK означает фрод, подтверждённый APPROVE —
        чистую операцию.
      </p>

      <div className="scenario-buttons">
        <button
          type="button"
          className="chip"
          disabled={sending !== null}
          onClick={() => void submit('CORRECT')}
        >
          {sending === 'CORRECT' ? 'Сохраняю…' : VERDICT_LABEL.CORRECT}
        </button>
        <button
          type="button"
          className="chip"
          disabled={sending !== null}
          onClick={() => void submit('INCORRECT')}
        >
          {sending === 'INCORRECT' ? 'Сохраняю…' : VERDICT_LABEL.INCORRECT}
        </button>
      </div>

      {failure && (
        <p className="hint">
          <strong className="error-text">{failure}</strong>
        </p>
      )}

      {accepted && (
        <p className="hint">
          Записано:{' '}
          <strong>
            {accepted.record.actual_fraud
              ? 'операция подтверждена как мошенническая'
              : 'операция подтверждена как добросовестная'}
          </strong>
          . {feedbackHeadline(accepted.summary)}.
          {accepted.summary.storage_error && (
            <>
              {' '}
              <span className="warn-text">{accepted.summary.storage_error}</span>
            </>
          )}
        </p>
      )}
    </section>
  )
}

/**
 * Одно поле формы.
 *
 * Числа вводятся в текстовое поле намеренно. `type="number"` отдаёт пустую
 * строку, когда содержимое ему не нравится, — введённое значение исчезает
 * из состояния, и пользователь этого не видит. Здесь в состоянии остаётся
 * ровно то, что набрано, а разбор с явной ошибкой делает `formToRequest`.
 */
function Field({
  spec,
  value,
  onChange,
}: {
  spec: FieldSpec
  value: string
  onChange: (name: string, value: string) => void
}) {
  return (
    <label className="field">
      <span>{spec.label}</span>
      <input
        type={spec.kind === 'datetime' ? 'datetime-local' : 'text'}
        inputMode={spec.kind === 'number' ? 'decimal' : undefined}
        value={value}
        onChange={(event) => onChange(spec.name, event.target.value)}
      />
    </label>
  )
}

function Result({ result }: { result: PredictionResponse }) {
  const increasing = result.explanation.factors.filter(
    (factor) => factor.direction === 'INCREASES_RISK',
  )
  const maxContribution = Math.max(
    ...result.explanation.factors.map((factor) => Math.abs(factor.contribution)),
    1e-9,
  )

  return (
    <>
      <section className={`panel verdict ${DECISION_CLASS[result.decision]}`}>
        <div className="score">
          <span className="score-value">{result.risk_score}</span>
          <span className="score-caption">Risk Score / 100</span>
        </div>
        <div className="verdict-meta">
          <div className="decision">{result.decision}</div>
          <div className="level">Risk Level: {result.risk_level}</div>
          <div className="muted">
            модель дала {result.model_score}
            {result.raised_by_rules && ' → политики подняли до ' + result.risk_score}
            {' · '}вероятность {result.probability.toFixed(4)}
            {' · '}{result.processing_ms} мс
          </div>
          <div className="muted">
            пороги: APPROVE ≤ {result.thresholds.approve_max} &lt; CHALLENGE ≤{' '}
            {result.thresholds.challenge_max} &lt; BLOCK
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>Причины</h2>
        <p className="hint">{result.explanation.summary}</p>

        {result.triggered_rules.length > 0 && (
          <>
            <h3>Сработавшие политики</h3>
            <ul>
              {result.triggered_rules.map((rule) => (
                <li key={rule.key}>
                  <code>{rule.key}</code> (минимум {rule.min_score}) — {rule.title}
                </li>
              ))}
            </ul>
          </>
        )}

        <h3>Основные факторы риска</h3>
        {increasing.length > 0 ? (
          <ul>
            {increasing.map((factor) => (
              <li key={factor.feature}>{factor.reason}</li>
            ))}
          </ul>
        ) : (
          <p className="hint">Ни один признак заметно не повышает риск.</p>
        )}
      </section>

      <section className="panel">
        <h2>Feature Contributions</h2>
        <p className="hint">
          Метод: <code>{result.explanation.method}</code>, единицы вклада:{' '}
          <code>{result.explanation.units}</code>
          {result.explanation.units === 'logit' &&
            ' — вклад в логит базовой модели до калибровки; знак и порядок сохраняются.'}
        </p>
        <table className="contributions">
          <thead>
            <tr>
              <th>Признак</th>
              <th>Значение</th>
              <th>Вклад</th>
              <th>Направление</th>
            </tr>
          </thead>
          <tbody>
            {result.explanation.factors.map((factor) => {
              const positive = factor.direction === 'INCREASES_RISK'
              const width = (Math.abs(factor.contribution) / maxContribution) * 100
              return (
                <tr key={factor.feature}>
                  <td title={factor.description}>
                    <code>{factor.feature}</code>
                  </td>
                  <td>{factor.display_value}</td>
                  <td className="bar-cell">
                    <span className={positive ? 'bar up' : 'bar down'} style={{ width: `${width}%` }} />
                    <span className="bar-label">
                      {factor.contribution >= 0 ? '+' : ''}
                      {factor.contribution.toFixed(4)}
                    </span>
                  </td>
                  <td className={positive ? 'up-text' : 'down-text'}>
                    {positive ? 'повышает' : 'понижает'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <details>
          <summary>
            <h2 className="inline">Исходный JSON-ответ API</h2>
          </summary>
          <pre className="json">{JSON.stringify(result, null, 2)}</pre>
        </details>
      </section>
    </>
  )
}
