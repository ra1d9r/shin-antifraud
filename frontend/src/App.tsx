/**
 * Оболочка интерфейса Shin.
 *
 * Держит два вида работы с системой и переключение между ними:
 *
 * * **Дашборд** — весь поток транзакций разом: сколько фрода поймано,
 *   скольких честных клиентов задели, во что это обходится (брифинг §5.A).
 * * **Симулятор** — одна операция вручную и мгновенный вердикт (§5.E).
 *
 * Роутера здесь нет намеренно: два экрана не стоят зависимости и адресной
 * строки, а состояние вкладки жить между перезагрузками не обязано.
 */

import { useEffect, useState } from 'react'

import Dashboard from './Dashboard'
import Simulator from './Simulator'
import { WAKE_UP_HINT, useSlowHint } from './useSlowHint'
import { ApiError, apiBaseUrl, fetchAnalytics, fetchHealth, fetchModel } from './api'
import type { AnalyticsOverview, HealthResponse, ModelInfo } from './types'

type View = 'dashboard' | 'simulator'

/**
 * Почему аналитика не пришла.
 *
 * Различать причины приходится потому, что совет у них разный: артефакт
 * выгружают скриптом, а выключенный backend — поднимают. Раньше экран
 * показывал команду выгрузки в обоих случаях и лечил не ту болезнь.
 */
interface AnalyticsFailure {
  message: string
  /** Backend ответил, но сказал, что отчёта нет. */
  artifactMissing: boolean
}

export default function App() {
  const [view, setView] = useState<View>('dashboard')
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [analytics, setAnalytics] = useState<AnalyticsOverview | null>(null)
  const [model, setModel] = useState<ModelInfo | null>(null)
  const [modelError, setModelError] = useState<string>('')
  const [analyticsError, setAnalyticsError] = useState<AnalyticsFailure | null>(null)
  // Пока аналитика не пришла и не упала — мы ждём. Затянувшееся ожидание
  // объясняем сами, иначе оно неотличимо от зависшего интерфейса.
  const waking = useSlowHint(analytics === null && analyticsError === null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      // Три запроса ловятся порознь, а не одним Promise.all. Пока они были
      // вместе, падение любого гасило остальные: значок статуса и панель
      // модели просто исчезали, и человек не узнавал, что именно сломалось.
      try {
        const healthPayload = await fetchHealth()
        if (!cancelled) setHealth(healthPayload)
      } catch {
        // Отдельного сообщения не нужно: недоступный backend виден сразу
        // на обоих экранах, а здесь он только не покажет значок.
      }

      try {
        const modelPayload = await fetchModel()
        if (!cancelled) setModel(modelPayload)
      } catch (cause) {
        if (!cancelled) {
          setModelError(
            cause instanceof ApiError ? cause.message : 'Сведения о модели недоступны',
          )
        }
      }

      try {
        const payload = await fetchAnalytics()
        if (!cancelled) setAnalytics(payload)
      } catch (cause) {
        if (!cancelled) {
          setAnalyticsError({
            message: cause instanceof ApiError ? cause.message : 'Аналитика недоступна',
            // 503 отдаёт сам backend, когда артефакта нет. Всё остальное —
            // сеть, прокси или внутренняя ошибка, и выгрузка их не вылечит.
            artifactMissing: cause instanceof ApiError && cause.status === 503,
          })
        }
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <main className="page">
      <header className="header">
        <div>
          <h1>Shin — Anti-Fraud System</h1>
          {health && (
            <span className={`status ${health.model_loaded ? 'ok' : 'bad'}`}>
              {health.status} · модель {health.model_loaded ? 'загружена' : 'не загружена'} · XAI{' '}
              {health.explainer_method ?? '—'}
            </span>
          )}
        </div>
        <nav className="tabs">
          <button
            type="button"
            className={view === 'dashboard' ? 'tab active' : 'tab'}
            onClick={() => setView('dashboard')}
          >
            Дашборд
          </button>
          <button
            type="button"
            className={view === 'simulator' ? 'tab active' : 'tab'}
            onClick={() => setView('simulator')}
          >
            Симулятор
          </button>
        </nav>
      </header>

      {view === 'simulator' && <Simulator />}

      {view === 'dashboard' &&
        (analytics ? (
          <Dashboard data={analytics} model={model} modelError={modelError} />
        ) : (
          <section className="panel alert">
            <h2>{analyticsError ? 'Аналитика недоступна' : 'Загружаю аналитику'}</h2>
            <p>{analyticsError?.message ?? 'Загружаю…'}</p>

            {!analyticsError && waking && <p className="hint">{WAKE_UP_HINT}</p>}

            {analyticsError?.artifactMissing && (
              <>
                <p className="hint">
                  Отчёт по датасету выгружается заранее — расчёт занимает около двадцати
                  секунд, столько ждать в запросе нельзя. Выполните:
                </p>
                <pre>python backend/scripts/export_evaluation.py</pre>
              </>
            )}

            {analyticsError && !analyticsError.artifactMissing && (
              <p className="hint">
                Backend не ответил — выгружать отчёт бесполезно, пока он не поднят.
                Проверьте, что он запущен:
              </p>
            )}
            {analyticsError && !analyticsError.artifactMissing && (
              <pre>uvicorn app.main:app --reload --port 8000 --app-dir backend</pre>
            )}

            {analyticsError && (
              <p className="hint">
                Адрес backend: <code>{apiBaseUrl}</code>
              </p>
            )}
          </section>
        ))}
    </main>
  )
}
