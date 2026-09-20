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

/* ------------------------------------------------- аналитика по датасету */

/** Разбивка решений: сколько легальных и мошеннических получили каждое. */
export interface DecisionRow {
  decision: Decision
  legit: number
  fraud: number
}

/** Политика и её предельный вклад сверх решения модели. */
export interface RuleStat {
  key: string
  title: string
  min_score: number
  legit_hits: number
  fraud_hits: number
  precision: number
  gained_fraud: number
  added_friction: number
  /** null — политика не поймала ничего сверх модели, то есть даёт только трение. */
  checks_per_fraud: number | null
}

/** Точка кривой компромисса при одном пороге чувствительности. */
export interface CurvePoint {
  threshold: number
  fraud_missed: number
  fraud_stopped: number
  friction: number
  fraud_loss: number
  friction_cost: number
  total_cost: number
}

export interface AnalyticsOverview {
  generated_at: string
  /** Метка модели, на которой посчитан отчёт. */
  model_trained_at?: string | null
  model_algorithm?: string | null
  /** Отчёт посчитан на другой модели, чем загружена сейчас. */
  stale: boolean
  stale_reason?: string | null
  rows: number
  fraud_rows: number
  legit_rows: number
  fraud_rate: number
  total_amount: number
  thresholds: { approve_max: number; challenge_max: number; critical_min: number }
  rules_enabled: boolean
  decisions: DecisionRow[]
  fraud_blocked: number
  fraud_stopped: number
  fraud_missed: number
  fraud_stopped_share: number
  friction: number
  friction_share: number
  raised_by_rules: number
  rules: RuleStat[]
  cost_with_rules: number
  cost_without_rules: number
  rules_cost_delta: number
  curve: CurvePoint[]
  optimal_threshold: number
}

/** Сведения о модели из GET /model. */
export interface ModelInfo {
  loaded: boolean
  algorithm?: string | null
  calibration_method?: string | null
  feature_count?: number | null
  trained_at?: string | null
  roc_auc?: number | null
  pr_auc?: number | null
  precision?: number | null
  recall?: number | null
  f1?: number | null
}
