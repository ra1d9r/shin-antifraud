/**
 * Клиент backend.
 *
 * Здесь нет никакой логики оценки риска — только HTTP. Дублировать на
 * клиенте Risk Engine, пороги или расчёт признаков запрещено (ТЗ §11):
 * такая копия разойдётся с backend и начнёт показывать не то, что система
 * решила на самом деле.
 */

import type {
  ApiErrorBody,
  HealthResponse,
  PredictionResponse,
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch (cause) {
    // Сеть не ответила вовсе: backend не поднят или заблокирован CORS.
    throw new ApiError(
      `Backend недоступен по адресу ${BASE_URL}. Поднят ли он?`,
      0,
      null,
    )
  }

  if (!response.ok) {
    let body: ApiErrorBody | null = null
    try {
      body = (await response.json()) as ApiErrorBody
    } catch {
      body = null
    }
    throw new ApiError(
      body?.message ?? `HTTP ${response.status}`,
      response.status,
      body,
    )
  }

  return (await response.json()) as T
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

export const apiBaseUrl = BASE_URL
