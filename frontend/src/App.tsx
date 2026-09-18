/**
 * Минимальный тестовый интерфейс Shin (ТЗ §8).
 *
 * Одна страница. Задача — за 10 секунд поменять параметры транзакции
 * и увидеть новый ответ системы. Это не production dashboard: здесь нет
 * авторизации, аналитики, графиков и роутинга.
 *
 * Поток: `Input -> POST /predict -> Display Response`. Никаких mock-данных.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'

import { ApiError, apiBaseUrl, fetchHealth, fetchScenarios, predict } from './api'
import { CONTEXT_FIELDS, FORM_FIELDS, formToRequest, scenarioToForm } from './form'
import type { FieldSpec, FormState } from './form'
import type { Decision, HealthResponse, PredictionResponse, Scenario } from './types'

/** Что показать в блоке ошибки: заголовок и разбор по полям. */
interface DisplayError {
  title: string
  details: string[]
}

const DECISION_CLASS: Record<Decision, string> = {
  APPROVE: 'approve',
  CHALLENGE: 'challenge',
  BLOCK: 'block',
}

export default function App() {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [activeScenario, setActiveScenario] = useState<string>('')
  const [form, setForm] = useState<FormState>({})
  const [result, setResult] = useState<PredictionResponse | null>(null)
  const [error, setError] = useState<DisplayError | null>(null)
  const [loading, setLoading] = useState(false)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [startupError, setStartupError] = useState<string>('')
  const [persist, setPersist] = useState(true)

  // Пресеты берём с backend: тот же источник, что у автотестов и
  // docs/HAND_TESTING.md, поэтому кнопки не могут с ними разойтись.
  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const [items, healthPayload] = await Promise.all([fetchScenarios(), fetchHealth()])
        if (cancelled) return
        setScenarios(items)
        setHealth(healthPayload)
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
    setResult(null)
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
      setResult(null)
      return
    }

    setLoading(true)
    setError(null)
    try {
      setResult(await predict({ ...body, persist }))
    } catch (cause) {
      const failure = cause instanceof ApiError ? cause : new ApiError(String(cause), 0, null)
      setError({
        title: `${failure.status > 0 ? `HTTP ${failure.status}` : 'Сеть'} — ${failure.message}`,
        details: failure.fieldErrors,
      })
      setResult(null)
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
      <main className="page">
        <h1>Shin — Test Interface</h1>
        <div className="alert">
          <strong>{startupError}</strong>
          <p>
            Ожидаемый адрес backend: <code>{apiBaseUrl}</code>
          </p>
          <pre>uvicorn app.main:app --reload --port 8000 --app-dir backend</pre>
        </div>
      </main>
    )
  }

  return (
    <main className="page">
      <header className="header">
        <h1>Shin — Test Interface</h1>
        {health && (
          <span className={`status ${health.model_loaded ? 'ok' : 'bad'}`}>
            {health.status} · модель {health.model_loaded ? 'загружена' : 'не загружена'} · XAI{' '}
            {health.explainer_method ?? '—'}
          </span>
        )}
      </header>

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

      {result && <Result result={result} />}
    </main>
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
