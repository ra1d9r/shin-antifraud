/**
 * Показ теневой конфигурации.
 *
 * Только подписи. Сравнение считает backend: обе конфигурации живут
 * в Risk Engine, и второй экземпляр порогов на клиенте разошёлся бы
 * с настоящим (ТЗ §11).
 */

import type { Configuration } from './types'

/** Конфигурация одной строкой — как её читает человек. */
export function describeConfiguration(config: Configuration): string {
  const policies = config.rules_enabled ? 'политики включены' : 'политики выключены'
  return `APPROVE ≤ ${config.approve_max} < CHALLENGE ≤ ${config.challenge_max} · ${policies}`
}
