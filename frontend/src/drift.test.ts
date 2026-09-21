/**
 * Тесты показа сдвига распределения.
 *
 * PSI считает backend. Здесь проверяется только то, что неизмеренное
 * не выглядит как измеренное: ни числом, ни зелёной меткой.
 */

import { describe, expect, it } from 'vitest'
import { ru } from './testTranslator'

import { DRIFT_STATUS_KEY, driftHeadline, driftTone, formatBinShare, formatPsi } from './drift'
import type { DriftStatus } from './types'

describe('цвет статуса', () => {
  it('стабильное зелёное, существенный сдвиг красный', () => {
    expect(driftTone('STABLE')).toBe('good')
    expect(driftTone('MODERATE')).toBe('warn')
    expect(driftTone('SIGNIFICANT')).toBe('bad')
  })

  it('отсутствие измерения не красится вовсе', () => {
    // Зелёная метка выдавала бы «сравнивать нечего» за успех.
    expect(driftTone('NOT_MEASURABLE')).toBeUndefined()
    expect(driftTone('COLLECTING')).toBeUndefined()
  })

  it('у каждого статуса есть подпись', () => {
    const all: DriftStatus[] = [
      'STABLE',
      'MODERATE',
      'SIGNIFICANT',
      'NOT_MEASURABLE',
      'COLLECTING',
    ]
    for (const status of all) {
      expect(ru(DRIFT_STATUS_KEY[status])).toBeTruthy()
    }
  })
})

describe('PSI', () => {
  it('null показывается прочерком, а не нулём', () => {
    expect(formatPsi(null)).toBe('—')
  })

  it('настоящий ноль остаётся нулём', () => {
    expect(formatPsi(0)).toBe('0.000')
  })

  it('число округляется до трёх знаков', () => {
    expect(formatPsi(0.12345)).toBe('0.123')
  })
})

describe('доля корзины', () => {
  it('пустая корзина и почти пустая различимы', () => {
    // «0 %» на непустой корзине заставил бы искать ошибку в данных.
    expect(formatBinShare(0)).toBe('0 %')
    expect(formatBinShare(0.0001)).toBe('<0.1 %')
  })

  it('обычная доля в процентах', () => {
    expect(formatBinShare(0.257)).toBe('25.7 %')
  })
})

describe('заголовок панели', () => {
  it('пока наблюдений мало — говорит, сколько ещё нужно', () => {
    expect(driftHeadline(40, 200, false, ru)).toContain('ещё 160')
  })

  it('когда хватает — просто называет число', () => {
    const line = driftHeadline(512, 200, true, ru)

    expect(line).toContain('512')
    expect(line).not.toContain('ещё')
  })
})
