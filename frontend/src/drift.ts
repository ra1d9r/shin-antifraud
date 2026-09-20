/**
 * Показ сдвига распределения.
 *
 * Только подписи и форматирование. PSI, границы корзин и раскладка по ним
 * приходят с backend посчитанными: там же, где лежит эталон. Копия формулы
 * на клиенте однажды разошлась бы с той, по которой система себя судит.
 */

import type { DriftStatus } from './types'

export const DRIFT_STATUS_LABEL: Record<DriftStatus, string> = {
  STABLE: 'стабильно',
  MODERATE: 'умеренный сдвиг',
  SIGNIFICANT: 'существенный сдвиг',
  NOT_MEASURABLE: 'несравним',
  COLLECTING: 'копим наблюдения',
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
export function driftHeadline(observed: number, minimum: number, enough: boolean): string {
  if (enough) return `Наблюдений: ${observed}`
  const left = Math.max(0, minimum - observed)
  return `Наблюдений: ${observed} из ${minimum} — нужно ещё ${left}, чтобы называть числа`
}
