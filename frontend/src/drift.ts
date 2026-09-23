/**
 * Показ сдвига распределения.
 *
 * Только подписи и форматирование. PSI, границы корзин и раскладка по ним
 * приходят с backend посчитанными: там же, где лежит эталон. Копия формулы
 * на клиенте однажды разошлась бы с той, по которой система себя судит.
 */

import type { TranslationKey, Translator } from './i18n'
import type { DriftStatus } from './types'

/**
 * Статус — ключом, а не готовой строкой.
 *
 * Модуль остаётся чистым: он не знает выбранного языка и не лезет
 * за ним в глобальное состояние. Переводит тот, кто рисует.
 */
export const DRIFT_STATUS_KEY: Record<DriftStatus, TranslationKey> = {
  STABLE: 'drift.statusStable',
  MODERATE: 'drift.statusModerate',
  SIGNIFICANT: 'drift.statusSignificant',
  NOT_MEASURABLE: 'drift.statusNotMeasurable',
  COLLECTING: 'drift.statusCollecting',
}

/**
 * Цвет статуса.
 *
 * «Несравним» и «копим» намеренно без цвета: это не хорошо и не плохо,
 * а отсутствие измерения, и зелёная метка выдавала бы его за успех.
 */
export function driftTone(status: DriftStatus): 'good' | 'warn' | 'bad' | undefined {
  if (status === 'STABLE') return 'good'
  if (status === 'MODERATE') return 'warn'
  if (status === 'SIGNIFICANT') return 'bad'
  return undefined
}

/** PSI или прочерк. Ноль вместо неизмеренного был бы враньём. */
export function formatPsi(psi: number | null): string {
  if (psi === null || !Number.isFinite(psi)) return '—'
  return psi.toFixed(3)
}

/** Доля корзины в процентах — для подписи под столбиком. */
export function formatBinShare(share: number): string {
  if (!Number.isFinite(share)) return '—'
  if (share === 0) return '0 %'
  if (share < 0.001) return '<0.1 %'
  return `${(share * 100).toFixed(1)} %`
}

/** Строка-заголовок панели: что происходит прямо сейчас. */
export function driftHeadline(
  observed: number,
  minimum: number,
  enough: boolean,
  t: Translator,
): string {
  if (enough) return t('drift.observations', { count: observed })
  const left = Math.max(0, minimum - observed)
  return t('drift.observationsShort', { observed, minimum, left })
}
