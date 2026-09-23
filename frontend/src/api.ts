/**
 * Клиент backend.
 *
 * Здесь нет никакой логики оценки риска — только HTTP. Дублировать на
 * клиенте Risk Engine, пороги или расчёт признаков запрещено (ТЗ §11):
 * такая копия разойдётся с backend и начнёт показывать не то, что система
 * решила на самом деле.
 */

import type { Language } from './i18n'
import type {
  AdaptiveThresholdsState,
  AnalyticsOverview,
  ApiErrorBody,
  ClientMessage,
  ClusterReport,
  CostApplied,
  CostState,
  CostUpdate,
  DriftReport,
  FeatureRegistry,
  FeedbackAccepted,
  FeedbackSummary,
  HealthResponse,
  ModelInfo,
  PolicyApplied,
  PolicyState,
  PolicyUpdate,
  PredictionResponse,
  Scenario,
  ScenarioList,
  ShadowComparison,
  StreamSummary,
  ThresholdsApplied,
  ThresholdsState,
  ThresholdUpdate,
  TransactionList,
  TransactionRequest,
  Verdict,
} from './types'
import { DEFAULT_LANGUAGE, translate } from './i18n'
import type { Substitutions, TranslationKey, Translator } from './i18n'

const BASE_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/$/, '')

/**
 * Ошибка API с разобранным телом ответа.
 *
 * `messageKey` заполнен, когда текст придумал сам клиент: такой текст
 * переводится словарём в момент показа. Ответ backend приходит готовой
 * строкой и кладётся в `message` — его формулировка точнее нашей, и
 * подменять её своей было бы потерей.
 */
export class ApiError extends Error {
  readonly status: number
  readonly body: ApiErrorBody | null
  readonly messageKey: TranslationKey | null
  readonly messageValues: Substitutions | null

  constructor(
    message: string,
    status: number,
    body: ApiErrorBody | null,
    localized?: { key: TranslationKey; values?: Substitutions },
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
    this.messageKey = localized?.key ?? null
    this.messageValues = localized?.values ?? null
  }

  /** Подробности валидации в виде «поле: причина». */
  get fieldErrors(): string[] {
    return (this.body?.details?.errors ?? []).map(
      (item) => `${item.field}: ${item.message}`,
    )
  }
}

/**
 * Сколько ждать backend, прежде чем признать запрос безнадёжным.
 *
 * У `fetch` нет таймаута по умолчанию: он ждёт вечно. Пока его не было,
 * зависший backend оставлял интерфейс с надписью «Анализ…» и заблокированной
 * кнопкой навсегда — без сообщения и без возможности повторить.
 *
 * Минута выглядит щедро — сам запрос укладывается в десятки миллисекунд даже
 * с построением SHAP-объяснения. Но на бесплатном хостинге сервис засыпает
 * после простоя, и первое обращение сначала будит контейнер: это тридцать
 * секунд и больше. С прежними пятнадцатью секундами жюри, открывшее ссылку
 * после паузы, видело бы ошибку таймаута вместо дашборда.
 */
const REQUEST_TIMEOUT_MS = 60_000

/**
 * Отдельный таймаут для прогона потока.
 *
 * Общей минуты мало: поток из трёхсот операций идёт полной цепочкой,
 * включая SHAP на каждую, и на бесплатном хостинге это десятки секунд
 * поверх возможного пробуждения контейнера.
 */
const STREAM_TIMEOUT_MS = 180_000

/**
 * Ожидание ответа ассистента.
 *
 * Обращение к языковой модели измеряется секундами, а не
 * миллисекундами, как остальные вызовы. Backend ждёт её
 * `LLM_TIMEOUT_SECONDS` и после этого сам отдаёт запасной текст,
 * так что клиенту достаточно запаса поверх этого срока.
 */
const ASSISTANT_TIMEOUT_MS = 45_000

/** Человеческое описание статуса, когда backend не прислал своего. */
function describeStatus(status: number): TranslationKey {
  if (status === 404) return 'api.notFound'
  if (status === 405) return 'api.methodNotAllowed'
  if (status === 408 || status === 504) return 'api.tooSlow'
  if (status >= 500) return 'api.serverError'
  return 'api.rejected'
}

/**
 * Текст ошибки на языке интерфейса.
 *
 * Порядок предпочтений: свой ключ — словарём, иначе сообщение backend
 * как есть. Пустая строка означает «пригодного объяснения нет»: она
 * не то же самое, что отсутствие ошибки, и место для неё в интерфейсе
 * всё равно отводится. `String(cause)` здесь не годится — строка «null»
 * человеку не объясняет ничего, а выглядит как недоделка.
 */
export function errorText(cause: unknown, t: Translator): string {
  if (cause instanceof ApiError) {
    return cause.messageKey
      ? t(cause.messageKey, cause.messageValues ?? undefined)
      : cause.message.trim()
  }
  if (cause instanceof Error) return cause.message.trim()
  if (typeof cause === 'string') return cause.trim()
  return ''
}

async function request<T>(
  path: string,
  init?: RequestInit,
  timeoutMs: number = REQUEST_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    let response: Response
    try {
      response = await fetch(`${BASE_URL}${path}`, {
        headers: { 'Content-Type': 'application/json' },
        ...init,
        // Сигнал ставится после развёртывания init намеренно: свой таймаут
        // важнее возможного чужого сигнала.
        signal: controller.signal,
      })
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') {
        throw new ApiError(
          `Backend не ответил за ${timeoutMs / 1000} секунд. ` +
            'Столько не занимает даже пробуждение уснувшего сервиса — ' +
            'похоже, он недоступен. Попробуйте обновить страницу.',
          0,
          null,
          { key: 'api.timedOut', values: { seconds: timeoutMs / 1000 } },
        )
      }
      // Сеть не ответила вовсе: backend не поднят или заблокирован CORS.
      // Исходная ошибка не сохраняется намеренно: TypeError: Failed to fetch
      // ничего не говорит человеку, который открыл тестовый интерфейс,
      // а вот адрес backend и вопрос «поднят ли он» говорят.
      throw new ApiError(`Backend недоступен по адресу ${BASE_URL}. Поднят ли он?`, 0, null, {
        key: 'api.unreachable',
        values: { url: BASE_URL },
      })
    }

    if (!response.ok) {
      let body: ApiErrorBody | null = null
      try {
        body = (await response.json()) as ApiErrorBody
      } catch {
        // Тело не JSON — body остаётся null, заданным выше.
      }
      // Без `describeStatus` сюда подставлялось «HTTP 500», и заголовок
      // ошибки в интерфейсе читался как «HTTP 500 — HTTP 500».
      const fallback = describeStatus(response.status)
      throw new ApiError(
        // В `message` — читаемый текст, а не ключ: он уходит в логи
        // и стектрейсы, где словаря нет.
        body?.message ?? translate(fallback, DEFAULT_LANGUAGE),
        response.status,
        body,
        body?.message ? undefined : { key: fallback },
      )
    }

    try {
      return (await response.json()) as T
    } catch {
      // Раньше разбор тела стоял вне try, и пользователь видел сырое
      // `SyntaxError: Failed to execute 'json' on 'Response'`, помеченное
      // как сетевая ошибка. Так выглядит ответ прокси, отдавшего HTML
      // с кодом 200, или оборванное соединение.
      throw new ApiError(
        'Backend ответил не в формате JSON. Между браузером и backend может стоять прокси.',
        response.status,
        null,
        { key: 'api.notJson' },
      )
    }
  } finally {
    // Снимаем таймер и после успеха: свой контроллер у каждого запроса, так
    // что сработка на завершённом ничему не повредит, но копить висящие
    // таймеры на каждый вызов незачем.
    clearTimeout(timer)
  }
}

/**
 * Отчёт по операции текстом — одна страница для тикета или письма.
 *
 * Собирается на backend, а не здесь: формулировки отчёта — часть того,
 * что система утверждает о решении, и вторая их версия на клиенте
 * разошлась бы с первой (ТЗ §11).
 *
 * Ответ приходит текстом, поэтому общий `request` не подходит: он
 * разбирает тело как JSON.
 */
export async function fetchReport(transaction: TransactionRequest): Promise<string> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)

  try {
    let response: Response
    try {
      response = await fetch(`${BASE_URL}/report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(transaction),
        signal: controller.signal,
      })
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') {
        throw new ApiError(`Backend не ответил за ${REQUEST_TIMEOUT_MS / 1000} секунд`, 0, null, {
          key: 'api.noAnswerIn',
          values: { seconds: REQUEST_TIMEOUT_MS / 1000 },
        })
      }
      throw new ApiError(`Backend недоступен по адресу ${BASE_URL}. Поднят ли он?`, 0, null, {
        key: 'api.unreachable',
        values: { url: BASE_URL },
      })
    }

    if (!response.ok) {
      // Ошибка приходит в общем JSON-контракте, даже когда успех — текст.
      let body: ApiErrorBody | null = null
      try {
        body = (await response.json()) as ApiErrorBody
      } catch {
        // Тело не JSON — body остаётся null.
      }
      const fallback = describeStatus(response.status)
      throw new ApiError(
        // В `message` — читаемый текст, а не ключ: он уходит в логи
        // и стектрейсы, где словаря нет.
        body?.message ?? translate(fallback, DEFAULT_LANGUAGE),
        response.status,
        body,
        body?.message ? undefined : { key: fallback },
      )
    }

    return await response.text()
  } finally {
    clearTimeout(timer)
  }
}

/**
 * Анализ транзакции — основной вызов интерфейса.
 *
 * Язык влияет только на пояснения: решение, оценка и вектор признаков
 * от него не зависят и зависеть не могут. Проверено тестом на backend.
 */
export function predict(
  transaction: TransactionRequest,
  language: Language,
): Promise<PredictionResponse> {
  return request<PredictionResponse>(`/predict?language=${language}`, {
    method: 'POST',
    body: JSON.stringify(transaction),
  })
}

/**
 * Готовые сценарии для кнопок-пресетов.
 *
 * Берутся с backend, а не зашиты в клиент: тогда пресеты не могут
 * разойтись с автотестами и с документом `docs/HAND_TESTING.md`,
 * которые используют тот же источник.
 */
export async function fetchScenarios(language: Language): Promise<Scenario[]> {
  const payload = await request<ScenarioList>(`/scenarios?language=${language}`)
  return payload.items
}

export function fetchHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health')
}

/**
 * Сводная аналитика по всему датасету — источник данных для дашборда.
 *
 * Отличается от /stats: тот считает по операциям, прошедшим через систему
 * за время работы, а здесь — весь датасет, где известна разметка. Поэтому
 * только тут есть пропущенный фрод и ложные срабатывания.
 */
export function fetchAnalytics(language: Language): Promise<AnalyticsOverview> {
  // Язык нужен ради двух вещей, которые читает человек: причины
  // устаревания отчёта и названий политик. Остальное здесь — числа.
  return request<AnalyticsOverview>(`/analytics/overview?language=${language}`)
}

/**
 * Справочник признаков — описания к числам вектора.
 *
 * Отдельным запросом, а не вместе с предсказанием: описания не меняются
 * от транзакции к транзакции, и возить их в каждом ответе было бы
 * расточительством.
 */
export function fetchFeatureRegistry(language: Language): Promise<FeatureRegistry> {
  return request<FeatureRegistry>(`/features?language=${language}`)
}

export function fetchModel(): Promise<ModelInfo> {
  return request<ModelInfo>('/model')
}

/**
 * Отметить вердикт верным или ошибочным.
 *
 * Настоящую метку («был ли это фрод») клиент не вычисляет: он не знает
 * и не должен знать, что система считает подозрительным. Вывод делает
 * backend, зная собственное решение по операции.
 *
 * Ответ приносит и метку, и пересчитанную сводку — отдельный запрос
 * за ней был бы лишним кругом по сети.
 */
export function sendFeedback(
  transactionId: string,
  verdict: Verdict,
  extra?: { analyst?: string; comment?: string },
): Promise<FeedbackAccepted> {
  return request<FeedbackAccepted>(
    `/transactions/${encodeURIComponent(transactionId)}/feedback`,
    { method: 'POST', body: JSON.stringify({ verdict, ...extra }) },
  )
}

/** Измеренное качество по накопленной разметке. */
export function fetchFeedbackSummary(): Promise<FeedbackSummary> {
  return request<FeedbackSummary>('/feedback/summary')
}

/**
 * Сдвиг распределения признаков относительно обучающего.
 *
 * Считает backend: PSI, границы корзин и раскладка по ним живут там же,
 * где эталон, и на клиент приходят готовыми.
 */
export function fetchDrift(language: Language): Promise<DriftReport> {
  return request<DriftReport>(`/monitoring/drift?language=${language}`)
}

/**
 * Что дало бы переключение конфигурации на этом потоке.
 *
 * Решения теневой конфигурации не приходят в ответе на /predict
 * намеренно: поле в основном ответе — это поле, которое кто-нибудь
 * однажды прочитает по ошибке и покажет клиенту.
 */
export function fetchShadow(): Promise<ShadowComparison> {
  return request<ShadowComparison>('/monitoring/shadow')
}

/**
 * Клиенты, связанные общим устройством или подсетью.
 *
 * Граф строится на backend по буферу обработанных операций: там же
 * лежит история, и второй её копии на клиенте быть не должно.
 */
export function fetchClusters(): Promise<ClusterReport> {
  return request<ClusterReport>('/graph/clusters')
}

export const apiBaseUrl = BASE_URL

/**
 * Прогнать порождённый поток операций через систему.
 *
 * Наблюдение за дрейфом, теневая конфигурация и история операций
 * показывают что-либо только на потоке: на свежем экземпляре системы
 * они пусты, и понять, работают ли панели, нельзя.
 *
 * Таймаут свой и больше общего: каждая операция идёт полной цепочкой
 * с построением SHAP-объяснения, и три сотни на бесплатном хостинге —
 * это десятки секунд, а не привычные миллисекунды.
 */
export function runStream(count: number): Promise<StreamSummary> {
  return request<StreamSummary>(
    '/predict/stream',
    { method: 'POST', body: JSON.stringify({ count }) },
    STREAM_TIMEOUT_MS,
  )
}

/**
 * Подобранные пороги по категориям мерчанта и чего они стоят.
 *
 * Таблица приходит даже при выключенном режиме: решать, включать ли
 * его, вслепую нельзя.
 */
export function fetchAdaptive(): Promise<AdaptiveThresholdsState> {
  return request<AdaptiveThresholdsState>('/config/adaptive')
}

/**
 * Объяснить решение клиенту человеческим языком.
 *
 * Решение принимает модель, языковая модель только формулирует уже
 * принятое. Таймаут свой: обращение к внешнему провайдеру измеряется
 * секундами, а не миллисекундами, как остальные вызовы.
 */
export function explainForClient(
  transaction: TransactionRequest,
  language: Language,
): Promise<ClientMessage> {
  return request<ClientMessage>(
    `/explain/client?language=${language}`,
    { method: 'POST', body: JSON.stringify(transaction) },
    ASSISTANT_TIMEOUT_MS,
  )
}

/**
 * Веса бизнес-метрики — чем система меряет свои ошибки.
 *
 * Чтение открыто, пароль нужен только для записи: знать, по какой
 * метрике посчитан оптимум, полезно всем, кто на него смотрит.
 */
export function fetchCostWeights(): Promise<CostState> {
  return request<CostState>('/config/cost')
}

/**
 * Заголовки запроса на запись настроек.
 *
 * `Content-Type` повторяется здесь намеренно. В `request` он стоит
 * до развёртывания `init`, поэтому переданные заголовки заменяют его
 * целиком, а не дополняют: отправив один только `X-Admin-Token`,
 * мы бы послали JSON без указания типа и получили отказ, который
 * выглядел бы как неверный пароль.
 */
function adminHeaders(token: string): HeadersInit {
  return { 'Content-Type': 'application/json', 'X-Admin-Token': token }
}

/**
 * Действующие пороги Risk Engine, их происхождение и журнал правок.
 *
 * Чтение открыто: те же три числа видны в каждом ответе `/predict`.
 */
export function fetchThresholds(): Promise<ThresholdsState> {
  return request<ThresholdsState>('/config/thresholds')
}

/**
 * Сменить пороги на работающей системе.
 *
 * Проверка «пороги возрастают» здесь не делается: её делает backend
 * и отвечает разбором по полям. Вторая её копия на клиенте — ровно
 * то, что запрещает ТЗ §11, и разошлась бы с первой при первом же
 * изменении диапазонов.
 */
export function updateThresholds(
  update: ThresholdUpdate,
  token: string,
): Promise<ThresholdsApplied> {
  return request<ThresholdsApplied>('/config/thresholds', {
    method: 'POST',
    headers: adminHeaders(token),
    body: JSON.stringify(update),
  })
}

/**
 * Пороги политик — «корректировать веса рисков» из брифинга §4.5.
 *
 * Язык нужен: названия политик уходят человеку, а не в код.
 */
export function fetchPolicies(language: Language): Promise<PolicyState> {
  return request<PolicyState>(`/config/policies?language=${language}`)
}

/** Скорректировать веса рисков. Отправляются только изменённые величины. */
export function updatePolicies(update: PolicyUpdate, token: string): Promise<PolicyApplied> {
  return request<PolicyApplied>('/config/policies', {
    method: 'POST',
    headers: adminHeaders(token),
    body: JSON.stringify(update),
  })
}

/**
 * Настроить бизнес-метрику (брифинг §5.C).
 *
 * Решения от этого не меняются: веса переводят уже принятые решения
 * в деньги. Меняется кривая компромисса и оптимальный порог на ней.
 */
export function updateCostWeights(update: CostUpdate, token: string): Promise<CostApplied> {
  return request<CostApplied>('/config/cost', {
    method: 'POST',
    headers: adminHeaders(token),
    body: JSON.stringify(update),
  })
}

/**
 * Лента обработанных операций для аналитика.
 *
 * `flagged` — всё, что система не пропустила: CHALLENGE и BLOCK вместе.
 * Отбирает backend, а не клиент: иначе «только задержанные» показывало
 * бы те из двадцати пяти последних, что задержаны, а не двадцать пять
 * последних задержанных.
 */
export function fetchTransactions(
  limit: number,
  language: Language,
  flagged?: boolean,
): Promise<TransactionList> {
  // Язык нужен ради причины: она собирается на backend при чтении,
  // а не хранится готовой строкой. Хранилась бы — лента говорила бы
  // на языке того запроса, которым операцию обработали.
  const query = new URLSearchParams({ limit: String(limit), language })
  if (flagged) query.set('flagged', 'true')
  return request<TransactionList>(`/transactions?${query.toString()}`)
}
