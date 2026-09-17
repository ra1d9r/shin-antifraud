/**
 * Типы, зеркалящие Pydantic-схемы backend.
 *
 * Источник правды — `backend/app/schemas/`. Здесь только зеркало: frontend
 * ничего не вычисляет сам, он отображает то, что вернул API.
 */

export type Decision = 'APPROVE' | 'CHALLENGE' | 'BLOCK'
export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
export type ImpactDirection = 'INCREASES_RISK' | 'DECREASES_RISK'

/** Поля транзакции из ТЗ §3 — то, что показывает форма. */
export interface TransactionFields {
  transaction_id: string
  user_id: string
  amount: number
  timestamp: string
  merchant: string
  country: string
  device_id: string
  ip_address: string
  latitude: number
  longitude: number
  transaction_frequency: number
  previous_transaction_amount: number
  previous_transaction_country: string
  account_age_days: number
}

/**
 * Контекст клиента (решение D-4 в ТЗ).
 *
 * Отправляется вместе с транзакцией. Без него система берёт данные из
 * накопленного профиля, и повторные нажатия Analyze дают разные ответы:
 * устройство, только что засветившееся в запросе, перестаёт быть новым.
 * Для инструмента ручной проверки это выглядело бы как дефект.
 */
export interface ClientContext {
  user_avg_amount?: number | null
  user_amount_std?: number | null
  user_home_country?: string | null
  user_typical_frequency?: number | null
  known_device_ids?: string[] | null
  previous_ip_address?: string | null
  previous_timestamp?: string | null
  previous_latitude?: number | null
  previous_longitude?: number | null
  txn_count_last_hour?: number | null
  merchant_category?: string | null
}

export type TransactionRequest = TransactionFields &
  ClientContext & {
    /** false — посчитать ответ, не меняя состояние системы. */
    persist?: boolean
  }

export interface TriggeredRule {
  key: string
  title: string
  min_score: number
}

export interface RiskFactor {
  feature: string
  value: number
  display_value: string
  contribution: number
  direction: ImpactDirection
  reason: string
  description: string
}

export interface Explanation {
  method: string
  /** `logit` — вклад в логит базовой модели, `probability` — в вероятность. */
  units: string
  base_value: number
  summary: string
  reasons: string[]
  policy_reasons: string[]
  factors: RiskFactor[]
}

export interface Thresholds {
  approve_max: number
  challenge_max: number
  critical_min: number
}

export interface PredictionResponse {
  transaction_id: string
  user_id: string
  timestamp: string
  /** Итоговая оценка после политик Risk Engine. */
  risk_score: number
  /** Оценка, которую дала только модель. */
  model_score: number
  probability: number
  decision: Decision
  risk_level: RiskLevel
  raised_by_rules: boolean
  triggered_rules: TriggeredRule[]
  explanation: Explanation
  thresholds: Thresholds
  features: Record<string, number>
  processing_ms: number
}

/** Готовый сценарий из `GET /scenarios`. */
export interface Scenario {
  key: string
  title: string
  description: string
  expectation: string
  changed_from_normal: string[]
  transaction: TransactionRequest
}

export interface ScenarioList {
  items: Scenario[]
}

export interface HealthResponse {
  status: string
  app_name: string
  version: string
  model_loaded: boolean
  explainer_method: string | null
  rules_enabled: boolean
  transactions_processed: number
}

/** Единый формат ошибки backend. */
export interface ApiErrorBody {
  error_code: string
  message: string
  details?: { errors?: { field: string; message: string }[] }
}
