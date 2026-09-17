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
import type {
  ClientContext,
  Decision,
  HealthResponse,
  PredictionResponse,
  Scenario,
  TransactionFields,
  TransactionRequest,
} from './types'

/** Поля формы из ТЗ §3. `kind` задаёт тип поля ввода. */
const FORM_FIELDS: { name: keyof TransactionFields; label: string; kind: 'text' | 'number' | 'datetime' }[] = [
  { name: 'transaction_id', label: 'transaction_id', kind: 'text' },
  { name: 'user_id', label: 'user_id', kind: 'text' },
  { name: 'amount', label: 'amount', kind: 'number' },
  { name: 'timestamp', label: 'timestamp', kind: 'datetime' },
  { name: 'merchant', label: 'merchant', kind: 'text' },
  { name: 'country', label: 'country', kind: 'text' },
  { name: 'device_id', label: 'device_id', kind: 'text' },
  { name: 'ip_address', label: 'ip_address', kind: 'text' },
  { name: 'latitude', label: 'latitude', kind: 'number' },
  { name: 'longitude', label: 'longitude', kind: 'number' },
  { name: 'transaction_frequency', label: 'transaction_frequency', kind: 'number' },
  { name: 'previous_transaction_amount', label: 'previous_transaction_amount', kind: 'number' },
  { name: 'previous_transaction_country', label: 'previous_transaction_country', kind: 'text' },
  { name: 'account_age_days', label: 'account_age_days', kind: 'number' },
]

const CONTEXT_FIELDS: { name: keyof ClientContext; label: string }[] = [
  { name: 'user_avg_amount', label: 'user_avg_amount' },
  { name: 'user_amount_std', label: 'user_amount_std' },
  { name: 'user_home_country', label: 'user_home_country' },
  { name: 'user_typical_frequency', label: 'user_typical_frequency' },
  { name: 'known_device_ids', label: 'known_device_ids (через запятую)' },
  { name: 'previous_ip_address', label: 'previous_ip_address' },
  { name: 'previous_timestamp', label: 'previous_timestamp' },
  { name: 'previous_latitude', label: 'previous_latitude' },
  { name: 'previous_longitude', label: 'previous_longitude' },
  { name: 'txn_count_last_hour', label: 'txn_count_last_hour' },
  { name: 'merchant_category', label: 'merchant_category' },
]

/** Форма держит всё строками: пользователь должен иметь право ввести что угодно. */
type FormState = Record<string, string>

const DECISION_CLASS: Record<Decision, string> = {
  APPROVE: 'approve',
  CHALLENGE: 'challenge',
  BLOCK: 'block',
}

/** Backend отдаёт время в ISO; `datetime-local` понимает минуты без зоны. */
function toInputDateTime(value: unknown): string {
  if (typeof value !== 'string' || value === '') return ''
  return value.slice(0, 16)
}

function scenarioToForm(scenario: Scenario): FormState {
  // Читаем тело сценария как словарь: имена полей формы совпадают с именами
  // полей запроса, и перебирать их по списку проще, чем по одному.
  const source = scenario.transaction as unknown as Record<string, unknown>
  const state: FormState = {}

  for (const field of FORM_FIELDS) {
    const value = source[field.name]
    state[field.name] =
      field.kind === 'datetime' ? toInputDateTime(value) : value == null ? '' : String(value)
  }

  for (const field of CONTEXT_FIELDS) {
    const value = source[field.name]
    if (value == null) {
      state[field.name] = ''
    } else if (Array.isArray(value)) {
      state[field.name] = value.join(', ')
    } else if (field.name === 'previous_timestamp') {
      state[field.name] = toInputDateTime(value)
    } else {
      state[field.name] = String(value)
    }
  }

  return state
}

/**
 * Форма -> тело запроса. Пустые поля не отправляются вовсе.
 *
 * Значения собираются из строк, поэтому результат приводится к типу запроса
 * без проверки: валидация — забота backend. Так и задумано, иначе на клиенте
 * появилась бы вторая копия правил, которая разойдётся с серверной.
 */
function formToRequest(form: FormState): TransactionRequest {
  const body: Record<string, unknown> = {}

  for (const field of FORM_FIELDS) {
    const raw = form[field.name]?.trim() ?? ''
    if (raw === '') continue
    body[field.name] = field.kind === 'number' ? Number(raw) : raw
  }

  for (const field of CONTEXT_FIELDS) {
    const raw = form[field.name]?.trim() ?? ''
    if (raw === '') continue

    if (field.name === 'known_device_ids') {
      body[field.name] = raw.split(',').map((item) => item.trim()).filter(Boolean)
    } else if (
      field.name === 'user_home_country' ||
      field.name === 'previous_ip_address' ||
      field.name === 'previous_timestamp' ||
      field.name === 'merchant_category'
    ) {
      body[field.name] = raw
    } else {
      body[field.name] = Number(raw)
    }
  }

  return body as unknown as TransactionRequest
}

export default function App() {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [activeScenario, setActiveScenario] = useState<string>('')
  const [form, setForm] = useState<FormState>({})
  const [result, setResult] = useState<PredictionResponse | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
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
    setLoading(true)
    setError(null)
    try {
      const response = await predict({ ...formToRequest(form), persist })
      setResult(response)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause : new ApiError(String(cause), 0, null))
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
            <label key={field.name} className="field">
              <span>{field.label}</span>
              <input
                type={field.kind === 'datetime' ? 'datetime-local' : field.kind === 'number' ? 'number' : 'text'}
                step={field.kind === 'number' ? 'any' : undefined}
                value={form[field.name] ?? ''}
                onChange={(event) => updateField(field.name, event.target.value)}
              />
            </label>
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
              <label key={field.name} className="field">
                <span>{field.label}</span>
                <input
                  type={field.name === 'previous_timestamp' ? 'datetime-local' : 'text'}
                  value={form[field.name] ?? ''}
                  onChange={(event) => updateField(field.name, event.target.value)}
                />
              </label>
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
            <strong>
              {error.status > 0 ? `HTTP ${error.status}` : 'Сеть'} — {error.message}
            </strong>
          </p>
          {error.fieldErrors.length > 0 && (
            <ul>
              {error.fieldErrors.map((item) => (
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
