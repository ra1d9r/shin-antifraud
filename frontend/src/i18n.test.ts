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
      'cost.metric', // «Метрика»
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

/**
 * Страж против возврата русского текста в компоненты.
 *
 * Прошлая правка перевела заголовки и подписи, но пропустила сноски
 * под плитками и подписи на графиках — 24 строки, видимые на каждой
 * вкладке. Поймать это можно было только глазами и только на
 * английском, поэтому теперь проверяет тест.
 *
 * Проверяются значения свойств: `note={...}`, `label={...}` и прочие,
 * которые попадают на экран. Комментарии под правило не подходят
 * по форме — они остаются русскими намеренно (см. шапку i18n.ts).
 */
const COMPONENTS = import.meta.glob('./*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

/** `note="русский"`, `label={'русский'}`, `title={`русский ${x}`}`. */
const VISIBLE_PROP = /\b(note|label|title|value|placeholder|summary)=\{?\s*(['"`])((?:(?!\2)[\s\S])*?)\2/g

describe('русский текст не возвращается в компоненты', () => {
  const skip = new Set(['./i18n.ts', './testTranslator.ts'])

  it('подписи и сноски берутся из словаря, а не пишутся в коде', () => {
    const guilty: string[] = []

    for (const [path, source] of Object.entries(COMPONENTS)) {
      if (skip.has(path) || path.includes('.test.')) continue
      for (const match of source.matchAll(VISIBLE_PROP)) {
        const text = match[3]
        if (/[А-Яа-яЁё]/.test(text)) {
          guilty.push(`${path.replace('./', '')}: ${match[1]}=«${text.slice(0, 50)}»`)
        }
      }
    }

    expect(guilty).toEqual([])
  })

  it('сам страж работает: подложенная строка была бы поймана', () => {
    // Иначе регулярное выражение могло бы тихо перестать совпадать,
    // и проверка выше проходила бы на пустом множестве всегда.
    const planted = `<Tile note={'оценка поднята политиками'} />`
    const found = [...planted.matchAll(VISIBLE_PROP)].filter((m) => /[А-Яа-яЁё]/.test(m[3]))
    expect(found).toHaveLength(1)
  })
})
