/**
 * Форма тестового интерфейса: описание полей и превращение их в запрос.
 *
 * Вынесено из `App.tsx` отдельным модулем не ради красоты, а чтобы это
 * можно было проверить тестом. Здесь чистые функции без React и без DOM —
 * значит, `form.test.ts` обходится одним vitest, без jsdom.
 *
 * Правил оценки риска тут нет и быть не может (ТЗ §11): вторая копия
 * разошлась бы с backend и начала бы показывать не то, что система решила.
 */

import type { TranslationKey, Translator } from './i18n'
import type { ClientContext, Scenario, TransactionFields, TransactionRequest } from './types'

/**
 * Как строка из поля превращается в значение запроса.
 *
 * `kind` нужен не для удобства ввода, а для разбора: без него числовые поля
 * разбирались вслепую, и `Number('abc')` уезжал в запрос как `null`.
 */
export type FieldKind = 'text' | 'number' | 'datetime' | 'list'

export interface FieldSpec {
  name: string
  label: string
  kind: FieldKind
  /** Уточнение в скобках после имени поля, если оно нужно. */
  hintKey?: TranslationKey
}

/** Поля формы из ТЗ §3. */
export const FORM_FIELDS: (FieldSpec & { name: keyof TransactionFields })[] = [
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

export const CONTEXT_FIELDS: (FieldSpec & { name: keyof ClientContext })[] = [
  { name: 'user_avg_amount', label: 'user_avg_amount', kind: 'number' },
  { name: 'user_amount_std', label: 'user_amount_std', kind: 'number' },
  { name: 'user_home_country', label: 'user_home_country', kind: 'text' },
  { name: 'user_typical_frequency', label: 'user_typical_frequency', kind: 'number' },
  {
    name: 'known_device_ids',
    label: 'known_device_ids',
    kind: 'list',
    hintKey: 'form.commaSeparated',
  },
  { name: 'previous_ip_address', label: 'previous_ip_address', kind: 'text' },
  { name: 'previous_timestamp', label: 'previous_timestamp', kind: 'datetime' },
  { name: 'previous_latitude', label: 'previous_latitude', kind: 'number' },
  { name: 'previous_longitude', label: 'previous_longitude', kind: 'number' },
  { name: 'txn_count_last_hour', label: 'txn_count_last_hour', kind: 'number' },
  { name: 'merchant_category', label: 'merchant_category', kind: 'text' },
]

/** Форма держит всё строками: пользователь должен иметь право ввести что угодно. */
export type FormState = Record<string, string>

/** Backend отдаёт время в ISO; `datetime-local` понимает минуты без зоны. */
export function toInputDateTime(value: unknown): string {
  if (typeof value !== 'string' || value === '') return ''
  return value.slice(0, 16)
}

export function scenarioToForm(scenario: Scenario): FormState {
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
    } else if (field.kind === 'datetime') {
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
 * Правил оценки риска здесь нет и быть не может (ТЗ §11): вторая копия
 * разошлась бы с backend. Единственная проверка на клиенте — что в числовом
 * поле действительно число, и это не бизнес-правило, а разбор ввода.
 *
 * Без неё `Number('abc')` давал `NaN`, `JSON.stringify` превращал его
 * в `null`, backend читал это как «поле не передано» и отвечал HTTP 200
 * по данным, которых пользователь не вводил. Молча — что хуже отказа.
 */
export interface ParsedForm {
  body: TransactionRequest
  invalid: string[]
}

export function formToRequest(form: FormState, t: Translator): ParsedForm {
  const body: Record<string, unknown> = {}
  const invalid: string[] = []

  const collect = (field: FieldSpec) => {
    const raw = form[field.name]?.trim() ?? ''
    if (raw === '') return

    if (field.kind === 'list') {
      body[field.name] = raw.split(',').map((item) => item.trim()).filter(Boolean)
      return
    }

    if (field.kind !== 'number') {
      body[field.name] = raw
      return
    }

    const parsed = Number(raw)
    if (Number.isFinite(parsed)) {
      body[field.name] = parsed
    } else {
      invalid.push(t('form.expectedNumber', { field: field.name, value: raw }))
    }
  }

  for (const field of FORM_FIELDS) collect(field)
  for (const field of CONTEXT_FIELDS) collect(field)

  return { body: body as unknown as TransactionRequest, invalid }
}

/**
 * Новый идентификатор операции.
 *
 * Нужен, потому что backend стал идемпотентным: повтор с тем же
 * `transaction_id`, но другими данными — это вторая операция под чужим
 * номером, и он отвечает 409. А симулятор для того и сделан, чтобы
 * менять поля и нажимать Analyze снова, — значит каждый прогон должен
 * быть новой операцией.
 *
 * Формат совпадает с тем, что генерирует схема, но контрактом не
 * является: backend принимает любую непустую строку до 128 символов.
 * Здесь важна только уникальность.
 */
export function newTransactionId(): string {
  const random = Math.random().toString(16).slice(2, 14).padEnd(12, '0')
  return `txn_${random}`
}
