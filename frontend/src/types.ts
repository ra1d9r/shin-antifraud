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
  /** Только причины от модели, без политик и без шума. */
  model_reasons: string[]
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
  /**
   * Что решение означает для клиента — формулировкой backend.
   *
   * Не своей: пока копия жила здесь, она разошлась с текстовым
   * отчётом, и одно решение описывалось двумя разными фразами.
   */
  decision_meaning: string
  triggered_rules: TriggeredRule[]
  explanation: Explanation
  thresholds: Thresholds
  features: Record<string, number>
  processing_ms: number
}

/* ---------------------------------------- справочник признаков */

export interface FeatureInfo {
  index: number
  name: string
  description: string
  is_flag: boolean
  /** Знаков после запятой. Правило приходит с backend, а не решается тут. */
  decimals: number
  reason_high: string
}

export interface FeatureSection {
  section: string
  features: FeatureInfo[]
}

export interface FeatureRegistry {
  count: number
  sections: FeatureSection[]
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

/** Одна страна на карте аномалий (брифинг §6). */
export interface CountryStat {
  country: string
  latitude: number
  longitude: number
  rows: number
  fraud_rows: number
  /** Операции с решением, отличным от APPROVE. */
  flagged: number
  high_risk: boolean
  fraud_share: number
  flagged_share: number
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
  /** Доля настоящего фрода среди помеченного. null — не помечен никто. */
  precision: number | null
  /** Доля пойманного фрода от всего фрода в выборке. */
  recall: number | null
  f1: number | null
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
  /** Спасённый бюджет: деньги фрода, которые система не пропустила. */
  fraud_loss_prevented: number
  /** Деньги фрода, ушедшие с решением APPROVE. */
  fraud_loss_incurred: number
  /** Во что обошёлся бы весь фрод выборки без системы вовсе. */
  fraud_loss_exposure: number
  friction: number
  friction_share: number
  raised_by_rules: number
  /** Те же две обязательные метрики §5.A по решениям одной модели, без политик. */
  fraud_stopped_without_rules: number
  fraud_stopped_share_without_rules: number
  friction_without_rules: number
  friction_share_without_rules: number
  /** Разница по решениям целиком, а не сумма по строкам `rules`: политики пересекаются. */
  rules_gained_fraud: number
  rules_added_friction: number
  /**
   * География для карты аномалий; страны без координат сюда не попадают.
   *
   * Необязательное: артефакт мог быть выгружен до появления карты.
   */
  countries?: CountryStat[]
  rules: RuleStat[]
  cost_with_rules: number
  cost_without_rules: number
  rules_cost_delta: number
  curve: CurvePoint[]
  optimal_threshold: number
}

/* -------------------------------------------- разметка аналитика */

/**
 * Что аналитик сказал о вердикте системы.
 *
 * Он отвечает «система была права?», а не «это фрод?»: настоящую метку
 * backend выводит сам, зная, что система утверждала.
 */
export type Verdict = 'CORRECT' | 'INCORRECT'

export interface FeedbackRecord {
  transaction_id: string
  user_id: string
  verdict: Verdict
  /** Подтверждённая метка, выведенная из отметки и решения системы. */
  actual_fraud: boolean
  decision: Decision
  risk_score: number
  model_score: number
  amount: number
  triggered_rules: string[]
  labeled_at: string
  analyst?: string | null
  comment?: string | null
}

export interface DecisionFeedback {
  decision: Decision
  labeled: number
  fraud: number
  legit: number
}

export interface RuleFeedback {
  key: string
  labeled: number
  fraud: number
  legit: number
}

/**
 * Измеренное качество по подтверждённым меткам.
 *
 * Доли приходят `null`, когда делить не на что: «точность 0 %»
 * и «точность ещё не измерена» — разные утверждения.
 */
export interface FeedbackSummary {
  labeled_total: number
  correct: number
  incorrect: number
  correct_share: number | null
  fraud_confirmed: number
  legit_confirmed: number
  true_positive: number
  false_positive: number
  true_negative: number
  false_negative: number
  precision: number | null
  recall: number | null
  fraud_amount_missed: number
  by_decision: DecisionFeedback[]
  rules: RuleFeedback[]
  storage_path?: string | null
  /** Метки не доходят до диска и пропадут при перезапуске. */
  storage_error?: string | null
  skipped_lines: number
}

/** Ответ на разметку: метка и сразу пересчитанная сводка. */
export interface FeedbackAccepted {
  record: FeedbackRecord
  summary: FeedbackSummary
}

/* ------------------------------------------- дрейф распределения */

/**
 * Во что сложился PSI признака или всей картины.
 *
 * `COLLECTING` — наблюдений пока мало, чтобы называть число.
 * `NOT_MEASURABLE` — признак в обучающей выборке постоянен.
 */
export type DriftStatus =
  | 'STABLE'
  | 'MODERATE'
  | 'SIGNIFICANT'
  | 'NOT_MEASURABLE'
  | 'COLLECTING'

export interface FeatureDrift {
  name: string
  description: string
  status: DriftStatus
  /** null — сравнивать нечего или наблюдений мало. */
  psi: number | null
  labels: string[]
  expected: number[]
  observed: number[]
}

export interface DriftReport {
  status: DriftStatus
  observed_rows: number
  baseline_rows: number
  baseline_generated_at: string
  model_trained_at?: string | null
  min_observations: number
  enough_data: boolean
  drifted: number
  invalid_values: number
  features: FeatureDrift[]
}

/* ------------------------------------------------- теневой режим */

/** Одна конфигурация Risk Engine. */
export interface Configuration {
  approve_max: number
  challenge_max: number
  critical_min: number
  rules_enabled: boolean
}

export interface MatrixCell {
  primary: Decision
  shadow: Decision
  count: number
  amount: number
}

export interface Disagreement {
  transaction_id: string
  user_id: string
  amount: number
  primary_decision: Decision
  primary_score: number
  shadow_decision: Decision
  shadow_score: number
  at: string
}

/** Что дало бы переключение конфигурации на этом потоке. */
export interface ShadowComparison {
  enabled: boolean
  /** false — теневая совпадает с основной, и согласие ничего не означает. */
  differs: boolean
  difference: string
  primary: Configuration
  shadow: Configuration
  observed: number
  agreed: number
  disagreed: number
  agreement_share: number | null
  freed_count: number
  freed_amount: number
  tightened_count: number
  tightened_amount: number
  matrix: MatrixCell[]
  recent: Disagreement[]
}

/* ------------------------------------------------- граф связей */

/**
 * Чем связана группа и насколько этому можно верить.
 *
 * DEVICE — есть общее устройство, объясняется плохо.
 * SUBNET_ONLY — только общая подсеть, а её делят корпоративный NAT,
 * оператор связи и один провайдер в одном доме.
 */
export type LinkStrength = 'DEVICE' | 'SUBNET_ONLY'

export interface Cluster {
  users: string[]
  size: number
  shared_devices: string[]
  shared_subnets: string[]
  strength: LinkStrength
  transactions: number
  flagged: number
  total_amount: number
  max_risk_score: number
}

export interface ClusterReport {
  scanned_transactions: number
  known_users: number
  linked_users: number
  weak_clusters: number
  clusters: Cluster[]
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

/* ------------------------------------------- порождённый поток (§5.B) */

/**
 * Итог прогона потока.
 *
 * Разметка потока известна: операции порождены тем же генератором,
 * на котором обучалась модель. Поэтому качество считается прямо на
 * прогоне, а не берётся из выгруженной аналитики.
 */
export interface StreamSummary {
  requested: number
  processed: number
  seed: number
  pool_rows: number
  decisions: Record<string, number>
  average_risk_score: number
  raised_by_rules: number
  triggered_rules: Record<string, number>
  fraud_in_stream: number
  fraud_stopped: number
  fraud_missed: number
  false_positives: number
  processing_ms: number
}

/* ------------------------------------- адаптивный порог (брифинг §6) */

export interface SegmentThreshold {
  segment: string
  approve_max: number
  rows: number
  fraud_rows: number
  /** false — мошеннических операций не хватило, взят общий порог. */
  fitted: boolean
}

/**
 * Чего стоит режим на данных, которых он не видел при подборе.
 *
 * Без этих чисел таблица порогов ничего не утверждает.
 */
export interface AdaptiveValidation {
  folds: number
  gain_per_fold: number[]
  mean_gain: number
  /** Худшая часть. Отрицательная — режим там проиграл. */
  worst_gain: number
  positive_folds: number
  configured_approve_max: number
  configured_cost: number
  adaptive_cost: number
  configured_friction: number
  adaptive_friction: number
  configured_fraud_stopped: number
  adaptive_fraud_stopped: number
}

export interface AdaptiveThresholdsState {
  available: boolean
  enabled: boolean
  error?: string | null
  generated_at?: string | null
  rows?: number | null
  min_fraud_per_segment?: number | null
  fallback_approve_max?: number | null
  segments: SegmentThreshold[]
  validation?: AdaptiveValidation | null
}

/* --------------------------------- LLM-ассистент (брифинг §6) */

/**
 * Объяснение решения словами, обращёнными к клиенту.
 *
 * `source` обязателен к показу: без него шаблон было бы не отличить
 * от работы языковой модели, и интерфейс заявлял бы функциональность,
 * которой в этот момент нет.
 */
export interface ClientMessage {
  transaction_id: string
  decision: Decision
  text: string
  source: 'llm' | 'fallback'
  /** Язык, на котором написан текст. */
  language: 'ru' | 'kk' | 'en'
  model?: string | null
  fallback_reason?: string | null
  risk_score: number
  /** Ровно то, что ушло бы в запрос к языковой модели. */
  facts: string[]
  elapsed_ms: number
}

/**
 * Веса бизнес-метрики (брифинг §5.C).
 *
 * По ним считается кривая компромисса и оптимальный порог. Читаются
 * открыто: без них числа на кривой появляются ниоткуда.
 */
export interface CostState {
  fraud_loss_ratio: number
  fraud_fixed: number
  false_block: number
  false_challenge: number
  overridden: boolean
  changed_at: string | null
  writable: boolean
  curve_recomputable: boolean
}

/* ------------------- настройка на работающей системе (брифинг §4.5, §5.C) */

/** Одна правка порогов — строка журнала. */
export interface ThresholdChange {
  at: string
  approve_max: number
  challenge_max: number
  critical_min: number
  rules_enabled: boolean
  changed_by: string | null
  reason: string | null
}

/**
 * Действующие пороги Risk Engine и их происхождение.
 *
 * `writable` — задан ли на сервере `CONFIG_ADMIN_TOKEN`. Когда он false,
 * запись выключена целиком, и форма обязана это показать, а не выяснять
 * отказом после нажатия.
 */
export interface ThresholdsState {
  approve_max: number
  challenge_max: number
  critical_min: number
  rules_enabled: boolean
  overridden: boolean
  changed_at: string | null
  writable: boolean
  env_defaults: Record<string, number | boolean>
  history: ThresholdChange[]
}

/** Что отправляем при смене порогов. Все четыре величины обязательны. */
export interface ThresholdUpdate {
  approve_max: number
  challenge_max: number
  critical_min: number
  rules_enabled: boolean
  changed_by?: string
  reason?: string
}

/**
 * Что изменилось и что из-за этого сброшено.
 *
 * Последствия приходят с сервера, а не выводятся здесь: какие панели
 * смена порогов обнуляет, знает backend, и вторая версия этого знания
 * на клиенте разошлась бы с первой (ТЗ §11).
 */
export interface ThresholdsApplied {
  state: ThresholdsState
  shadow_reset: boolean
  analytics_marked_stale: boolean
  drift_kept: boolean
}

/**
 * Одна политика в форме настройки.
 *
 * `config_field` — имя поля, которым двигается её минимум. Приходит
 * с сервера, потому что с `key` совпадает не всегда.
 */
export interface PolicyEntry {
  key: string
  title: string
  min_score: number
  config_field: string
}

export interface PolicyState {
  policies: PolicyEntry[]
  velocity_txn_per_hour: number
  new_account_amount_ratio: number
  rules_enabled: boolean
  overridden: boolean
  changed_at: string | null
  writable: boolean
}

/**
 * Правка политик: только изменённые величины.
 *
 * Незаданное остаётся как есть — поэтому тип открытый по ключу, а не
 * перечисление полей: имена приходят в `config_field`, и повторять их
 * здесь значило бы завести на клиенте вторую копию контракта.
 */
export type PolicyUpdate = Record<string, number | string>

export interface PolicyApplied {
  state: PolicyState
  changed: Record<string, number>
  shadow_reset: boolean
  analytics_marked_stale: boolean
}

/** Правка весов бизнес-метрики: тоже только изменённые. */
export type CostUpdate = Record<string, number | string>

export interface CostApplied {
  state: CostState
  changed: Record<string, number>
  curve_recomputed: boolean
  optimal_threshold_before: number | null
  optimal_threshold_after: number | null
}

/**
 * Одна обработанная операция в ленте аналитика.
 *
 * Поля те же, что отдаёт `GET /transactions`. Полный IP не хранится —
 * только подсеть /24, по которой строится граф связей.
 */
export interface TransactionRecord {
  transaction_id: string
  user_id: string
  timestamp: string
  amount: number
  country: string
  merchant: string
  device_id: string
  risk_score: number
  model_score: number
  decision: Decision
  risk_level: RiskLevel
  triggered_rules: string[]
  top_reason: string | null
  ip_subnet: string | null
  verdict: Verdict | null
  actual_fraud: boolean | null
}

export interface TransactionList {
  total: number
  returned: number
  items: TransactionRecord[]
}
