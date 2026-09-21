/**
 * Показ теневой конфигурации.
 *
 * Только подписи. Сравнение считает backend: обе конфигурации живут
 * в Risk Engine, и второй экземпляр порогов на клиенте разошёлся бы
 * с настоящим (ТЗ §11).
 */

import type { Translator } from './i18n'
import type { Configuration } from './types'

/**
 * Конфигурация одной строкой — как её читает человек.
 *
 * Переводчик приходит параметром: модуль остаётся чистым и не тянет
 * за собой React, а язык остаётся видимой зависимостью, а не глобалом.
 */
export function describeConfiguration(config: Configuration, t: Translator): string {
  const policies = t(config.rules_enabled ? 'shadow.policiesOn' : 'shadow.policiesOff')
  return `APPROVE ≤ ${config.approve_max} < CHALLENGE ≤ ${config.challenge_max} · ${policies}`
}
