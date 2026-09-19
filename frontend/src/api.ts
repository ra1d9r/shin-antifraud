/**
 * Клиент backend.
 *
 * Здесь нет никакой логики оценки риска — только HTTP. Дублировать на
 * клиенте Risk Engine, пороги или расчёт признаков запрещено (ТЗ §11):
 * такая копия разойдётся с backend и начнёт показывать не то, что система
 * решила на самом деле.
 */

import type {
  AnalyticsOverview,
  ApiErrorBody,
  HealthResponse,
  PredictionResponse,
  ModelInfo,
  Scenario,
  ScenarioList,
  TransactionRequest,
} from './types'

const BASE_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/$/, '')

/** Ошибка API с разобранным телом ответа. */
export class ApiError extends Error {
  readonly status: number
  readonly body: ApiErrorBody | null

  constructor(message: string, status: number, body: ApiErrorBody | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
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
 * Пятнадцать секунд с большим запасом: самый тяжёлый запрос, `POST /predict`
 * с построением SHAP-объяснения, укладывается в десятки миллисекунд.
 */
const REQUEST_TIMEOUT_MS = 15_000

/** Человеческое описание статуса, когда backend не прислал своего. */
function describeStatus(status: number): string {
  if (status === 404) return 'Адрес не найден на backend'
  if (status === 405) return 'Метод не поддерживается'
  if (status === 408 || status === 504) return 'Backend не успел ответить'
  if (status >= 500) return 'Backend ответил ошибкой'
  return 'Запрос отклонён'
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)

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
          `Backend не ответил за ${REQUEST_TIMEOUT_MS / 1000} секунд. ` +
            'Он мог зависнуть или быть перегружен.',
          0,
          null,
        )
      }
      // Сеть не ответила вовсе: backend не поднят или заблокирован CORS.
      // Исходная ошибка не сохраняется намеренно: TypeError: Failed to fetch
      // ничего не говорит человеку, который открыл тестовый интерфейс,
      // а вот адрес backend и вопрос «поднят ли он» говорят.
      throw new ApiError(`Backend недоступен по адресу ${BASE_URL}. Поднят ли он?`, 0, null)
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
      throw new ApiError(body?.message ?? describeStatus(response.status), response.status, body)
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
      )
    }
  } finally {
    // Снимаем таймер и после успеха: свой контроллер у каждого запроса, так
    // что сработка на завершённом ничему не повредит, но копить висящие
    // таймеры на каждый вызов незачем.
    clearTimeout(timer)
  }
}

/** Анализ транзакции — основной вызов интерфейса. */
export function predict(transaction: TransactionRequest): Promise<PredictionResponse> {
  return request<PredictionResponse>('/predict', {
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
export async function fetchScenarios(): Promise<Scenario[]> {
  const payload = await request<ScenarioList>('/scenarios')
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
export function fetchAnalytics(): Promise<AnalyticsOverview> {
  return request<AnalyticsOverview>('/analytics/overview')
}

export function fetchModel(): Promise<ModelInfo> {
  return request<ModelInfo>('/model')
}

export const apiBaseUrl = BASE_URL
