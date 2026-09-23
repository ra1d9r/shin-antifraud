/**
 * Показ накопленной разметки.
 *
 * Только форматирование: ни одна величина здесь не считается. Матрицу
 * ошибок, точность и полноту считает backend — копия этих формул
 * на клиенте разошлась бы с той, по которой система себя оценивает.
 */

import type { Translator } from './i18n'
import type { FeedbackSummary } from './types'


/**
 * Доля, которую могли и не измерить.
 *
 * `null` приходит, когда делить не на что. Показать вместо него ноль
 * значило бы соврать: «точность 0 %» и «точность ещё не измерена» —
 * разные утверждения, и второе не повод пугать читателя.
 */
export function formatMeasuredShare(
  value: number | null | undefined,
  t: Translator,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return t('common.notMeasured')
  }
  return `${(value * 100).toFixed(1)} %`
}

/**
 * Строка подтверждения после разметки: сколько накоплено и что это дало.
 *
 * Фраза собирается словарём целиком, а не из двух половин: в казахском
 * «{total} ішінен {correct}» ставит числа в другом порядке, и склейка
 * дала бы верные числа в неверных местах.
 */
export function feedbackHeadline(summary: FeedbackSummary, t: Translator): string {
  if (summary.labeled_total === 0) return t('feedback.noLabels')
  return t('feedback.headline', { total: summary.labeled_total, correct: summary.correct })
}
