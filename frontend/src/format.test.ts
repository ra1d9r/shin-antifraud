/**
 * Тесты общего форматирования.
 *
 * Пока копии жили по файлам, разойтись они могли незаметно: одна и та же
 * сумма выглядела бы на соседних панелях по-разному, и заметить это можно
 * было только глазами.
 */

import { describe, expect, it } from 'vitest'

import { formatCount, formatMoney } from './format'
import { describeConfiguration } from './shadow'

describe('количество', () => {
  it('разряды разделяются', () => {
    // Русская локаль разделяет разряды неразрывным пробелом, и `\s`
    // в JS его покрывает — поэтому сравнение идёт по одним цифрам.
    expect(formatCount(99360).replace(/\s/g, '')).toBe('99360')
  })

  it('нечисло не показывается как NaN', () => {
    expect(formatCount(Number.NaN)).toBe('—')
    expect(formatCount(Number.POSITIVE_INFINITY)).toBe('—')
  })
})

describe('сумма', () => {
  it('копейки отбрасываются', () => {
    expect(formatMoney(2196.37).replace(/\s/g, '')).toBe('2196')
    expect(formatMoney(2196.62).replace(/\s/g, '')).toBe('2197')
  })

  it('ноль остаётся нулём', () => {
    expect(formatMoney(0)).toBe('0')
  })

  it('нечисло не показывается как NaN', () => {
    expect(formatMoney(Number.NaN)).toBe('—')
  })
})

describe('описание конфигурации', () => {
  it('называет пороги и судьбу политик', () => {
    const line = describeConfiguration({
      approve_max: 30,
      challenge_max: 70,
      critical_min: 90,
      rules_enabled: false,
    })

    expect(line).toContain('30')
    expect(line).toContain('70')
    expect(line).toContain('политики выключены')
  })

  it('включённые политики названы так же явно', () => {
    const line = describeConfiguration({
      approve_max: 4,
      challenge_max: 70,
      critical_min: 90,
      rules_enabled: true,
    })

    expect(line).toContain('политики включены')
  })
})
