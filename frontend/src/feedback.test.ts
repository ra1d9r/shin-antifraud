/**
 * Тесты показа разметки.
 *
 * Считать здесь нечего — все величины приходят с backend. Проверяется
 * ровно одно: измеренное и неизмеренное не выглядят одинаково.
 */

import { describe, expect, it } from 'vitest'
import { ru } from './testTranslator'

import { feedbackHeadline, formatMeasuredShare } from './feedback'
import type { FeedbackSummary } from './types'

function summary(overrides: Partial<FeedbackSummary> = {}): FeedbackSummary {
  return {
    labeled_total: 0,
    correct: 0,
    incorrect: 0,
    correct_share: null,
    fraud_confirmed: 0,
    legit_confirmed: 0,
    true_positive: 0,
    false_positive: 0,
    true_negative: 0,
    false_negative: 0,
    precision: null,
    recall: null,
    fraud_amount_missed: 0,
    by_decision: [],
    rules: [],
    skipped_lines: 0,
    ...overrides,
  }
}

describe('доля, которую могли и не измерить', () => {
  it('null не превращается в ноль процентов', () => {
    // «Точность 0 %» напугала бы читателя измерением, которого не было.
    expect(formatMeasuredShare(null, ru)).toBe('не измерено')
    expect(formatMeasuredShare(undefined, ru)).toBe('не измерено')
  })

  it('настоящий ноль показывается как ноль', () => {
    expect(formatMeasuredShare(0, ru)).toBe('0.0 %')
  })

  it('доля переводится в проценты', () => {
    expect(formatMeasuredShare(0.6667, ru)).toBe('66.7 %')
    expect(formatMeasuredShare(1, ru)).toBe('100.0 %')
  })

  it('деление на ноль на стороне backend не доезжает как NaN', () => {
    expect(formatMeasuredShare(Number.NaN, ru)).toBe('не измерено')
  })
})

describe('строка подтверждения', () => {
  it('пустая разметка не притворяется результатом', () => {
    expect(feedbackHeadline(summary(), ru)).toBe('Разметки пока нет')
  })

  it('называет и объём разметки, и сколько раз система была права', () => {
    const line = feedbackHeadline(summary({ labeled_total: 7, correct: 5, incorrect: 2 }), ru)

    expect(line).toContain('7')
    expect(line).toContain('5 из 7')
  })
})
