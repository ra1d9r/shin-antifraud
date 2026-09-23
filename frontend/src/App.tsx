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
import LanguageSwitch, { CommentaryNote } from './LanguageSwitch'
import Simulator from './Simulator'
import { useLanguage } from './LanguageContext'
import { WAKE_UP_HINT_KEY, useSlowHint } from './useSlowHint'
import { ApiError, apiBaseUrl, errorText, fetchAnalytics, fetchHealth, fetchModel } from './api'
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
  /** Сама причина, а не готовый текст: язык может смениться после отказа. */
  cause: unknown
  /** Backend ответил, но сказал, что отчёта нет. */
  artifactMissing: boolean
}

export default function App() {
  const { t, language } = useLanguage()
  const [view, setView] = useState<View>('dashboard')
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [analytics, setAnalytics] = useState<AnalyticsOverview | null>(null)
  const [model, setModel] = useState<ModelInfo | null>(null)
  const [modelFailure, setModelFailure] = useState<{ cause: unknown } | null>(null)
  const [analyticsError, setAnalyticsError] = useState<AnalyticsFailure | null>(null)
  // Пока аналитика не пришла и не упала — мы ждём. Затянувшееся ожидание
  // объясняем сами, иначе оно неотличимо от зависшего интерфейса.
  const waking = useSlowHint(analytics === null && analyticsError === null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      // Параллельно и с независимым разбором каждого исхода.
      //
      // Через `Promise.all` было нельзя: падение любого запроса гасило
      // остальные, и значок статуса вместе с панелью модели исчезали молча.
      // Но и цепочка `await` подряд оказалась плохой — на бесплатном хостинге
      // первое обращение будит контейнер, и в худшем случае ожидание
      // утраивалось. `allSettled` даёт и то, и другое: один общий прогрев
      // и отдельная реакция на каждую неудачу.
      const [healthResult, modelResult, analyticsResult] = await Promise.allSettled([
        fetchHealth(),
        fetchModel(),
        fetchAnalytics(language),
      ])
      if (cancelled) return

      if (healthResult.status === 'fulfilled') {
        setHealth(healthResult.value)
      }
      // Отдельного сообщения про health не нужно: недоступный backend виден
      // сразу на обоих экранах, а здесь он только не покажет значок.

      if (modelResult.status === 'fulfilled') {
        setModel(modelResult.value)
      } else {
        const cause = modelResult.reason
        setModelFailure({ cause })
      }

      if (analyticsResult.status === 'fulfilled') {
        setAnalytics(analyticsResult.value)
      } else {
        const cause = analyticsResult.reason
        setAnalyticsError({
          cause,
          // 503 отдаёт сам backend, когда артефакта нет. Всё остальное —
          // сеть, прокси или внутренняя ошибка, и выгрузка их не вылечит.
          artifactMissing: cause instanceof ApiError && cause.status === 503,
        })
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  // Язык в зависимостях: причина устаревания отчёта и названия политик
  // приходят с backend уже переведёнными, и без перезапроса они
  // остались бы на прежнем языке до перезагрузки страницы.
  }, [language])

  return (
    <main className="page">
      <header className="header">
        <div>
          <h1>{t('app.title')}</h1>
          {health && (
            <span className={`status ${health.model_loaded ? 'ok' : 'bad'}`}>
              {health.status} ·{' '}
              {t(health.model_loaded ? 'app.modelLoaded' : 'app.modelMissing')} · XAI{' '}
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
            {t('app.dashboard')}
          </button>
          <button
            type="button"
            className={view === 'simulator' ? 'tab active' : 'tab'}
            onClick={() => setView('simulator')}
          >
            {t('app.simulator')}
          </button>
        </nav>
        <LanguageSwitch />
      </header>

      <CommentaryNote />

      {view === 'simulator' && <Simulator />}

      {view === 'dashboard' &&
        (analytics ? (
          <Dashboard
            data={analytics}
            model={model}
            modelError={
              modelFailure
                ? errorText(modelFailure.cause, t) || t('app.modelUnavailable')
                : ''
            }
          />
        ) : (
          <section className="panel alert">
            <h2>{analyticsError ? t('error.analyticsTitle') : t('error.analyticsLoading')}</h2>
            <p>
              {analyticsError
                ? errorText(analyticsError.cause, t) || t('error.analyticsTitle')
                : t('common.loading')}
            </p>

            {!analyticsError && waking && <p className="hint">{t(WAKE_UP_HINT_KEY)}</p>}

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
                {t('error.backendAddress')}: <code>{apiBaseUrl}</code>
              </p>
            )}
          </section>
        ))}
    </main>
  )
}
