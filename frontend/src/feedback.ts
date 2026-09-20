/**
 * Показ накопленной разметки.
 *
 * Только форматирование: ни одна величина здесь не считается. Матрицу
 * ошибок, точность и полноту считает backend — копия этих формул
 * на клиенте разошлась бы с той, по которой система себя оценивает.
 */

import type { FeedbackSummary, Verdict } from './types'

/** Подписи кнопок. Аналитик отвечает про вердикт, а не про транзакцию. */
export const VERDICT_LABEL: Record<Verdict, string> = {
  CORRECT: 'Вердикт верный',
  INCORRECT: 'Вердикт ошибочный',
}

/**
 * Доля, которую могли и не измерить.
 *
 * `null` приходит, когда делить не на что. Показать вместо него ноль
 * значило бы соврать: «точность 0 %» и «точность ещё не измерена» —
 * разные утверждения, и второе не повод пугать читателя.
 */
export function formatMeasuredShare(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return 'не измерено'
  return `${(value * 100).toFixed(1)} %`
}

/** Строка подтверждения после разметки: сколько накоплено и что это дало. */
export function feedbackHeadline(summary: FeedbackSummary): string {
  if (summary.labeled_total === 0) return 'Разметки пока нет'

  const labeled = `Размечено операций: ${summary.labeled_total}`
  const verdicts = `система права в ${summary.correct} из ${summary.labeled_total}`
  return `${labeled} — ${verdicts}`
}
