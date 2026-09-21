/**
 * Тесты общего форматирования.
 *
 * Пока копии жили по файлам, разойтись они могли незаметно: одна и та же
 * сумма выглядела бы на соседних панелях по-разному, и заметить это можно
 * было только глазами.
 */

import { describe, expect, it } from 'vitest'
import { ru } from './testTranslator'

import { CURRENCY, formatCount, formatDateTime, formatMoney, localeOf } from './format'
import { describeConfiguration } from './shadow'

/** Только цифры: разделитель разрядов у каждой локали свой. */
const digits = (value: string) => value.replace(/[^\d]/g, '')

describe('количество', () => {
  it('разряды разделяются', () => {
    expect(digits(formatCount(99360))).toBe('99360')
  })

  it('нечисло не показывается как NaN', () => {
    expect(formatCount(Number.NaN)).toBe('—')
    expect(formatCount(Number.POSITIVE_INFINITY)).toBe('—')
  })
})

describe('сумма', () => {
  it('копейки отбрасываются', () => {
    expect(digits(formatMoney(2196.37))).toBe('2196')
    expect(digits(formatMoney(2196.62))).toBe('2197')
  })

  it('ноль остаётся нулём', () => {
    expect(digits(formatMoney(0))).toBe('0')
  })

  it('валюта подписана', () => {
    // Брифинг ведёт счёт в тенге (§10), а генератор выдаёт суммы без
    // единицы. Без подписи жюри, сверяющее числа с примером из кейса,
    // не понимало бы, те же это деньги или другие.
    expect(formatMoney(1000)).toContain(CURRENCY)
    expect(formatMoney(1000, 'en')).toContain(CURRENCY)
    expect(formatMoney(1000, 'kk')).toContain(CURRENCY)
  })

  it('нечисло не показывается как NaN и без валюты', () => {
    expect(formatMoney(Number.NaN)).toBe('—')
  })
})

describe('локаль', () => {
  it('казахский форматируется как русский, а не как английский', () => {
    // В Казахстане разряды разделяют пробелом. Данные ICU у локали `kk`
    // разнятся от среды к среде — Node даёт пробел, браузер запятую, —
    // поэтому язык привязан к `ru-RU` явно.
    expect(localeOf('kk')).toBe(localeOf('ru'))
    expect(localeOf('en')).toBe('en-US')
  })

  it('английский разделяет разряды иначе, чем русский', () => {
    // Ради этого локаль и стала параметром: пока было жёстко `ru-RU`,
    // в английском режиме заголовки шли по-английски, а числа
    // по-русски.
    expect(formatCount(99360, 'en')).toContain(',')
    expect(formatCount(99360, 'ru')).not.toContain(',')
  })

  it('казахский разделяет разряды пробелом, а не запятой', () => {
    // Проверяется само свойство, а не равенство русскому: равенство
    // проходило в Node и ломалось в браузере, где ICU для `kk` даёт
    // запятую. Живая проверка это нашла, тест — нет.
    const kazakh = formatCount(99360, 'kk')

    expect(kazakh).not.toContain(',')
    expect(kazakh).toMatch(/99\s360/)
  })

  it('дата тоже зависит от языка', () => {
    const moment = '2026-09-21T13:00:00Z'

    expect(formatDateTime(moment, 'ru')).not.toBe(formatDateTime(moment, 'en'))
    expect(formatDateTime(moment, 'ru')).toContain('2026')
  })

  it('испорченная дата не показывается как Invalid Date', () => {
    expect(formatDateTime('не дата')).toBe('—')
    expect(formatDateTime('')).toBe('—')
  })
})

describe('описание конфигурации', () => {
  it('называет пороги и судьбу политик', () => {
    const line = describeConfiguration({
      approve_max: 30,
      challenge_max: 70,
      critical_min: 90,
      rules_enabled: false,
    }, ru)

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
    }, ru)

    expect(line).toContain('политики включены')
  })
})
