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

import FeaturePanel from './FeaturePanel'
import {
  ApiError,
  apiBaseUrl,
  errorText,
  explainForClient,
  fetchReport,
  fetchScenarios,
  predict,
  sendFeedback,
} from './api'
import {
  CONTEXT_FIELDS,
  FORM_FIELDS,
  formToRequest,
  newTransactionId,
  scenarioToForm,
} from './form'
import { feedbackHeadline } from './feedback'
import { useLanguage } from './LanguageContext'
import { WAKE_UP_HINT_KEY, useSlowHint } from './useSlowHint'
import type { FieldSpec, FormState } from './form'
import type {
  ClientMessage,
  Decision,
  FeedbackAccepted,
  PredictionResponse,
  Scenario,
  TransactionRequest,
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
  /** Что именно отправили: отчёт собирается по тому же телу запроса. */
  body: TransactionRequest
}

const DECISION_CLASS: Record<Decision, string> = {
  APPROVE: 'approve',
  CHALLENGE: 'challenge',
  BLOCK: 'block',
}

export default function Simulator() {
  const { t, language } = useLanguage()
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [activeScenario, setActiveScenario] = useState<string>('')
  const [form, setForm] = useState<FormState>({})
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [error, setError] = useState<DisplayError | null>(null)
  const [loading, setLoading] = useState(false)
  // Хранится не переведённый текст, а то, что пришло с backend.
  // `null` — ошибки нет, пустая строка — ошибка без своего сообщения,
  // и тогда показывается наша формулировка. Перевод делается при
  // отрисовке: иначе сообщение осталось бы на языке, который был
  // выбран в момент сбоя, а эффект пришлось бы перезапускать при
  // каждой смене языка и заново дёргать backend.
  const [startupError, setStartupError] = useState<string | null>(null)
  const [persist, setPersist] = useState(true)
  // Ждём либо ответа на анализ, либо самой первой загрузки сценариев.
  const waking = useSlowHint(loading || (scenarios.length === 0 && startupError === null))

  // Пресеты берём с backend: тот же источник, что у автотестов и
  // docs/HAND_TESTING.md, поэтому кнопки не могут с ними разойтись.
  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const items = await fetchScenarios(language)
        if (cancelled) return
        setScenarios(items)
        if (items.length > 0) {
          setActiveScenario(items[0].key)
          setForm(scenarioToForm(items[0]))
        }
      } catch (cause) {
        if (cancelled) return
        setStartupError(cause instanceof ApiError ? cause.message : '')
      }
    }

    void load()
    return () => {
      cancelled = true
    }
    // Описания сценариев приходят с backend: смена языка их перезапрашивает.
  }, [language])

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
    const { body, invalid } = formToRequest(form, t)
    if (invalid.length > 0) {
      // Заведомо испорченный запрос не отправляем: иначе backend ответит 200
      // по другим данным, и пользователь не узнает, что его ввод потерян.
      setError({ title: t('sim.formInvalid'), details: invalid })
      setAnalysis(null)
      return
    }

    setLoading(true)
    setError(null)
    try {
      const sent = { ...body, persist }
      const result = await predict(sent, language)
      setAnalysis((previous) => ({
        seq: (previous?.seq ?? 0) + 1,
        result,
        persisted: persist,
        body: sent,
      }))
      // Следующий прогон — новая операция, и номер у неё должен быть
      // свой. Backend идемпотентен: тот же номер с другими данными —
      // это 409, а менять поля и нажимать Analyze снова симулятор
      // для того и сделан.
      setForm((previous) => ({ ...previous, transaction_id: newTransactionId() }))
    } catch (cause) {
      const failure = cause instanceof ApiError ? cause : new ApiError(String(cause), 0, null)
      const where = failure.status > 0 ? `HTTP ${failure.status}` : t('sim.network')
      setError({
        title: `${where} — ${errorText(failure, t)}`,
        details: failure.fieldErrors,
      })
      setAnalysis(null)
    } finally {
      setLoading(false)
    }
  }, [form, persist, t, language])

  const currentScenario = useMemo(
    () => scenarios.find((item) => item.key === activeScenario),
    [scenarios, activeScenario],
  )

  if (startupError !== null) {
    return (
      <section className="panel alert">
        <h2>{t('error.scenariosTitle')}</h2>
        <strong>{startupError || t('error.scenariosFailed')}</strong>
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
        <h2>{t('sim.scenarios')}</h2>
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
          // Описание сценария — не инженерный комментарий, а подпись
          // к кнопке: без неё непонятно, чем пресеты отличаются.
          // Скрывать его на казахском и английском было нечем оправдать
          // с тех пор, как backend отдаёт его переведённым.
          <p className="hint always-visible">
            {currentScenario.description} <br />
            <strong>{t('sim.expectation')}:</strong> {currentScenario.expectation}
          </p>
        )}
      </section>

      <section className="panel">
        <h2>{t('sim.transaction')}</h2>
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
          <summary>{t('sim.clientContext')}</summary>
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
            {loading ? t('sim.analyzing') : t('sim.analyze')}
          </button>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={persist}
              onChange={(event) => setPersist(event.target.checked)}
            />
            <span>{t('sim.persist')}</span>
          </label>
        </div>

        <p className="hint">
          После каждого анализа <code>transaction_id</code> обновляется: следующий прогон —
          новая операция. Backend идемпотентен, и тот же номер с другими данными он
          отклонит, а с теми же — вернёт прежний ответ, ничего не меняя.
        </p>

        {waking && <p className="hint always-visible">{t(WAKE_UP_HINT_KEY)}</p>}
      </section>

      {error && (
        <section className="panel alert">
          <h2>{t('error.title')}</h2>
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
          <ClientExplanation key={`client-${analysis.seq}`} analysis={analysis} />
          <TextReport key={`report-${analysis.seq}`} analysis={analysis} />
          <FeedbackControls key={analysis.seq} analysis={analysis} />
        </>
      )}
    </>
  )
}

/**
 * Объяснение решения клиенту (брифинг §6, LLM-ассистент).
 *
 * Отдельная кнопка, а не часть ответа на анализ: обращение к языковой
 * модели занимает секунды, а предсказание — десятки миллисекунд.
 *
 * Показывается, кто написал текст. Без этого шаблон было бы не отличить
 * от работы языковой модели, а заявлять чужую работу нельзя — особенно
 * ту, которой в этот момент нет.
 */
function ClientExplanation({ analysis }: { analysis: Analysis }) {
  const { language, t } = useLanguage()
  const [message, setMessage] = useState<ClientMessage | null>(null)
  const [loading, setLoading] = useState(false)
  const [failure, setFailure] = useState('')
  const [copied, setCopied] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setFailure('')
    setCopied(false)
    try {
      setMessage(await explainForClient(analysis.body, language))
    } catch (cause) {
      setFailure(errorText(cause, t) || t('assistant.failed'))
    } finally {
      setLoading(false)
    }
  }, [analysis.body, language, t])

  const copy = useCallback(async () => {
    if (!message) return
    try {
      await navigator.clipboard.writeText(message.text)
      setCopied(true)
    } catch {
      setFailure(t('report.copyFailed'))
    }
  }, [message, t])

  return (
    <section className="panel">
      <h2>{t('assistant.title')}</h2>
      <p className="hint">
        Готовый текст для клиента: почему у него попросили подтверждение и что
        делать дальше. Решение принимает модель — языковая модель только
        превращает уже принятое в человеческую фразу и не может его изменить.
      </p>

      <div className="scenario-buttons">
        <button type="button" className="chip" disabled={loading} onClick={() => void load()}>
          {loading ? t('assistant.writing') : message ? t('assistant.rewrite') : t('assistant.explain')}
        </button>
        {message && (
          <button type="button" className="chip" onClick={() => void copy()}>
            {copied ? t('report.copied') : t('report.copy')}
          </button>
        )}
      </div>

      {loading && (
        <p className="hint">
          Обращение к языковой модели занимает секунды, а не миллисекунды.
        </p>
      )}

      {failure && (
        <p className="hint">
          <strong className="error-text">{failure}</strong>
        </p>
      )}

      {message && (
        <>
          <p className="client-message">{message.text}</p>
          <p className="hint">
            {message.source === 'llm' ? (
              <>
                {t('assistant.writtenBy')} <code>{message.model}</code> —{' '}
                {(message.elapsed_ms / 1000).toFixed(1)} с.
              </>
            ) : (
              <>
                <strong>{t('assistant.noModel')}</strong>{' '}
                {message.fallback_reason} Он полноценный — собран из тех же фактов,
                — но выдавать его за работу ассистента было бы нечестно.
              </>
            )}
          </p>
          <details className="context">
            <summary>
              {t('assistant.whatGoesOut')} — {message.facts.length}
            </summary>
            <p className="hint">
              Только факты уже принятого решения. Ни идентификатора клиента,
              ни номера операции, ни IP здесь нет: языковой модели они не нужны,
              а уезжают они на чужой сервер.
            </p>
            <pre className="json">{message.facts.join('\n')}</pre>
          </details>
        </>
      )}
    </section>
  )
}

/**
 * Отчёт по операции текстом.
 *
 * Тот же ответ, что уже показан панелями выше, но в форме, которую можно
 * скопировать в тикет или в письмо клиентской службе. Собирает его
 * backend: формулировки — часть того, что система утверждает о решении,
 * и вторая их версия на клиенте разошлась бы с первой.
 *
 * Запрашивается по кнопке, а не вместе с анализом: страница текста нужна
 * далеко не на каждый прогон, а лишний килобайт на спящем хостинге
 * оплачивается ожиданием.
 */
function TextReport({ analysis }: { analysis: Analysis }) {
  const { t } = useLanguage()
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)
  const [failure, setFailure] = useState('')
  const [copied, setCopied] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setFailure('')
    try {
      setText(await fetchReport(analysis.body))
    } catch (cause) {
      setFailure(errorText(cause, t) || t('report.failed'))
    } finally {
      setLoading(false)
    }
  }, [analysis.body, t])

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
    } catch {
      // Буфер обмена недоступен без защищённого соединения и без
      // разрешения. Молча ничего не делать нельзя — человек нажал
      // кнопку и ждёт ответа, — поэтому говорим, что выделить можно
      // руками.
      setFailure(t('report.copyFailed'))
    }
  }, [text, t])

  return (
    <section className="panel">
      <h2>{t('report.title')}</h2>
      <p className="hint">
        Одна страница, которую можно скопировать целиком: в тикет, в письмо клиентской
        службе, в обоснование решения по обращению. Отчёт ничего не меняет — операция
        от него не попадёт ни в историю, ни в статистику.
      </p>

      <div className="scenario-buttons">
        <button type="button" className="chip" disabled={loading} onClick={() => void load()}>
          {loading ? t('report.building') : text ? t('report.rebuild') : t('report.show')}
        </button>
        {text && (
          <button type="button" className="chip" onClick={() => void copy()}>
            {copied ? t('report.copied') : t('report.copy')}
          </button>
        )}
      </div>

      {failure && (
        <p className="hint">
          <strong className="error-text">{failure}</strong>
        </p>
      )}

      {text && <pre className="json report">{text}</pre>}
    </section>
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
  const { t } = useLanguage()
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
        setFailure(errorText(cause, t) || t('sim.labelNotSaved'))
      } finally {
        setSending(null)
      }
    },
    [analysis.result.transaction_id, t],
  )

  if (!analysis.persisted) {
    return (
      <section className="panel">
        <h2>{t('sim.labelling')}</h2>
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
      <h2>{t('sim.systemRight')}</h2>
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
          {sending === 'CORRECT' ? t('sim.saving') : t('feedback.correct')}
        </button>
        <button
          type="button"
          className="chip"
          disabled={sending !== null}
          onClick={() => void submit('INCORRECT')}
        >
          {sending === 'INCORRECT' ? t('sim.saving') : t('feedback.incorrect')}
        </button>
      </div>

      {failure && (
        <p className="hint">
          <strong className="error-text">{failure}</strong>
        </p>
      )}

      {accepted && (
        <p className="hint always-visible">
          <strong>
            {t(accepted.record.actual_fraud ? 'sim.confirmedFraud' : 'sim.confirmedLegit')}
          </strong>
          . {feedbackHeadline(accepted.summary, t)}.
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
  const { t } = useLanguage()

  return (
    <label className="field">
      <span>
        {spec.label}
        {spec.hintKey !== undefined && ` (${t(spec.hintKey)})`}
      </span>
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
  const { t } = useLanguage()
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
          <span className="score-caption">{t('sim.scoreCaption')}</span>
        </div>
        <div className="verdict-meta">
          <div className="decision">{result.decision}</div>
          <div className="decision-meaning">{result.decision_meaning}</div>
          <div className="level">
            {t('sim.riskLevel')}: {t(`level.${result.risk_level}`)}
          </div>
          <div className="muted">
            {t('sim.modelGave')} {result.model_score}
            {result.raised_by_rules && ` → ${t('sim.raisedTo')} ${result.risk_score}`}
            {' · '}{t('sim.probability')} {result.probability.toFixed(4)}
            {' · '}{result.processing_ms} мс
          </div>
          <div className="muted">
            {t('sim.thresholds')}: APPROVE ≤ {result.thresholds.approve_max} &lt; CHALLENGE ≤{' '}
            {result.thresholds.challenge_max} &lt; BLOCK
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>{t('sim.reasons')}</h2>
        <p className="hint">{result.explanation.summary}</p>

        {result.triggered_rules.length > 0 && (
          <>
            <h3>{t('sim.policiesFired')}</h3>
            <ul>
              {result.triggered_rules.map((rule) => (
                <li key={rule.key}>
                  <code>{rule.key}</code> (минимум {rule.min_score}) — {rule.title}
                </li>
              ))}
            </ul>
          </>
        )}

        <h3>{t('sim.topFactors')}</h3>
        {increasing.length > 0 ? (
          <ul>
            {increasing.map((factor) => (
              <li key={factor.feature}>{factor.reason}</li>
            ))}
          </ul>
        ) : (
          <p className="hint always-visible">{t('sim.noFactors')}</p>
        )}
      </section>

      <section className="panel">
        <h2>{t('sim.contributions')}</h2>
        <p className="hint">
          {t('sim.method')}: <code>{result.explanation.method}</code>,{' '}
          {t('sim.units')}:{' '}
          <code>{result.explanation.units}</code>
          {result.explanation.units === 'logit' &&
            ' — вклад в логит базовой модели до калибровки; знак и порядок сохраняются.'}
        </p>
        {/* Обёртка прокрутки: таблица из четырёх столбцов с полосами вкладов
            не сжимается до 375 px и тянула за собой всю страницу. На дашборде
            таблицы обёрнуты с самого начала, а здесь обёртки не было. */}
        <div className="table-scroll">
        <table className="contributions">
          <thead>
            <tr>
              <th>{t('sim.feature')}</th>
              <th>{t('sim.value')}</th>
              <th>{t('sim.contribution')}</th>
              <th>{t('sim.direction')}</th>
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
                    {t(positive ? 'sim.raises' : 'sim.lowers')}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        </div>
      </section>

      <FeaturePanel features={result.features} />

      <section className="panel">
        <details>
          <summary>
            <h2 className="inline">{t('sim.rawJson')}</h2>
          </summary>
          <pre className="json">{JSON.stringify(result, null, 2)}</pre>
        </details>
      </section>
    </>
  )
}
