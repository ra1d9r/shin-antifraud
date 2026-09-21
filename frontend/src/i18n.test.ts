/**
 * Тесты словаря (брифинг §6).
 *
 * Забытый перевод не падает — он показывает русскую строку казахскому
 * или английскому пользователю. Заметить это можно только глазами
 * и только если специально смотреть, поэтому проверяет тест.
 */

import { describe, expect, it } from 'vitest'

import { DEFAULT_LANGUAGE, DICTIONARY, LANGUAGES, LANGUAGE_NAMES, translate } from './i18n'
import type { Language, TranslationKey } from './i18n'

const keys = Object.keys(DICTIONARY) as TranslationKey[]

describe('словарь', () => {
  it('знает ровно три языка, которые называет брифинг', () => {
    expect([...LANGUAGES]).toEqual(['ru', 'kk', 'en'])
    expect(LANGUAGES).toContain(DEFAULT_LANGUAGE)
  })

  it('у каждой строки есть все три перевода', () => {
    const missing: string[] = []
    for (const key of keys) {
      for (const language of LANGUAGES) {
        const value = DICTIONARY[key][language]
        if (typeof value !== 'string' || value.trim() === '') {
          missing.push(`${key}.${language}`)
        }
      }
    }
    expect(missing).toEqual([])
  })

  it('языки подписаны на самих себе', () => {
    // Иначе человек, ищущий свой язык, должен сначала понять текущий.
    expect(LANGUAGE_NAMES.ru).toBe('Рус')
    expect(LANGUAGE_NAMES.kk).toBe('Қаз')
    expect(LANGUAGE_NAMES.en).toBe('Eng')
  })

  it('казахский и английский не остались копией русского', () => {
    // Копия — самый вероятный вид забытого перевода: строку скопировали
    // в три поля и перевели два.
    //
    // Исключения перечислены поимённо, а не сняты условием: это
    // заимствования, которые в казахском пишутся так же, как в русском.
    // Список нужно пополнять руками — тогда новый забытый перевод
    // по-прежнему роняет тест.
    const SAME_IN_KAZAKH = new Set<string>([
      'adaptive.mode', // «Режим»
      'app.simulator', // «Симулятор»
      'sim.transaction', // «Транзакция»
      'model.title', // «Модель»
      'model.algorithm', // «Алгоритм»
      'common.transaction', // «Операция»
    ])

    const untranslated: string[] = []
    for (const key of keys) {
      const { ru, kk, en } = DICTIONARY[key]
      // Одинаковыми законно остаются только имена собственные и
      // термины вроде «Risk Score» — у них нет русских букв.
      if (!/[А-Яа-яЁё]/.test(ru)) continue
      if (kk === ru && !SAME_IN_KAZAKH.has(key)) untranslated.push(`${key}.kk`)
      if (en === ru) untranslated.push(`${key}.en`)
    }
    expect(untranslated).toEqual([])
  })

  it('в английском переводе не осталось кириллицы', () => {
    const cyrillic = keys.filter((key) => /[А-Яа-яЁё]/.test(DICTIONARY[key].en))
    expect(cyrillic).toEqual([])
  })

  it('переводит по ключу на выбранный язык', () => {
    expect(translate('app.dashboard', 'ru')).toBe('Дашборд')
    expect(translate('app.dashboard', 'en')).toBe('Dashboard')
    expect(translate('app.dashboard', 'kk')).toBe('Бақылау тақтасы')
  })

  it('неизвестный ключ возвращается как есть, а не пустой строкой', () => {
    // Пустая строка выглядела бы как вёрстка без текста, а ключ на
    // экране сразу говорит, чего не хватает.
    const unknown = 'no.such.key' as TranslationKey
    expect(translate(unknown, 'ru')).toBe('no.such.key')
  })

  it('решения и уровни риска переведены для каждого значения', () => {
    for (const decision of ['APPROVE', 'CHALLENGE', 'BLOCK']) {
      expect(keys).toContain(`decision.${decision}` as TranslationKey)
    }
    for (const level of ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']) {
      expect(keys).toContain(`level.${level}` as TranslationKey)
    }
  })

  it('язык по умолчанию — русский', () => {
    const language: Language = DEFAULT_LANGUAGE
    expect(language).toBe('ru')
  })
})
