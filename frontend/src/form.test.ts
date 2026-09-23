/**
 * Тесты чистой логики формы.
 *
 * Проверяется ровно то, из-за чего интерфейс однажды молча терял ввод:
 * нечисловое значение в числовом поле превращалось в `NaN`, `JSON.stringify`
 * делал из него `null`, backend читал это как «поле не передано» и отвечал
 * HTTP 200 по данным, которых пользователь не вводил.
 *
 * DOM здесь не нужен: `form.ts` — чистые функции, поэтому хватает vitest
 * без jsdom и без библиотек для рендера компонентов.
 */

import { describe, expect, it } from 'vitest'
import { ru } from './testTranslator'

import { CONTEXT_FIELDS, FORM_FIELDS, formToRequest, scenarioToForm } from './form'
import type { FormState } from './form'
import type { Scenario } from './types'

/** Пустая форма со всеми полями — отправляется только то, что заполнено. */
function form(overrides: FormState = {}): FormState {
  const state: FormState = {}
  for (const field of [...FORM_FIELDS, ...CONTEXT_FIELDS]) state[field.name] = ''
  return { ...state, ...overrides }
}

const SCENARIO = {
  key: 'normal',
  title: 'Normal transaction',
  transaction: {
    user_id: 'user_demo',
    amount: 100,
    timestamp: '2026-09-01T14:30:00',
    country: 'KZ',
    known_device_ids: ['dev_known_1', 'dev_known_2'],
    previous_timestamp: '2026-09-01T09:30:00',
    user_avg_amount: null,
  },
} as unknown as Scenario

describe('formToRequest', () => {
  it('пустые поля не попадают в запрос', () => {
    const { body, invalid } = formToRequest(form(), ru)

    expect(invalid).toEqual([])
    expect(Object.keys(body)).toEqual([])
  })

  it('числа разбираются в числа, а не в строки', () => {
    const { body } = formToRequest(form({ amount: '1500.5', account_age_days: '800' }), ru)

    expect(body).toMatchObject({ amount: 1500.5, account_age_days: 800 })
  })

  it('нечисловое значение называется поимённо и в запрос не попадает', () => {
    const { body, invalid } = formToRequest(form({ amount: 'abc' }), ru)

    expect(invalid).toEqual(['amount: ожидалось число, введено «abc»'])
    expect('amount' in body).toBe(false)
  })

  it('запятая вместо точки — обычная ошибка ввода, и она видна', () => {
    const { invalid } = formToRequest(form({ latitude: '51,16' }), ru)

    expect(invalid).toHaveLength(1)
  })

  it('Infinity не проходит: JSON.stringify превратил бы его в null', () => {
    const { body, invalid } = formToRequest(form({ amount: 'Infinity' }), ru)

    expect(invalid).toHaveLength(1)
    expect('amount' in body).toBe(false)
  })

  it('сообщаются сразу все испорченные поля, а не первое', () => {
    const { invalid } = formToRequest(form({ amount: 'x', latitude: 'y' }), ru)

    expect(invalid).toHaveLength(2)
  })

  it('контекстные числовые поля проверяются наравне с основными', () => {
    const { invalid } = formToRequest(form({ user_avg_amount: 'сто' }), ru)

    expect(invalid).toEqual(['user_avg_amount: ожидалось число, введено «сто»'])
  })

  it('список устройств разбирается по запятым, пустые элементы отбрасываются', () => {
    const { body } = formToRequest(form({ known_device_ids: 'dev_a, dev_b ,, dev_c' }), ru)

    expect(body.known_device_ids).toEqual(['dev_a', 'dev_b', 'dev_c'])
  })

  it('текстовые поля уходят как есть — нормализацию делает backend', () => {
    const { body } = formToRequest(form({ country: 'kz', merchant: 'Magnum' }), ru)

    expect(body).toMatchObject({ country: 'kz', merchant: 'Magnum' })
  })
})

describe('scenarioToForm', () => {
  it('время обрезается до минут: datetime-local не понимает секунды', () => {
    const state = scenarioToForm(SCENARIO)

    expect(state.timestamp).toBe('2026-09-01T14:30')
    expect(state.previous_timestamp).toBe('2026-09-01T09:30')
  })

  it('список устройств показывается через запятую', () => {
    expect(scenarioToForm(SCENARIO).known_device_ids).toBe('dev_known_1, dev_known_2')
  })

  it('пустое значение сценария даёт пустое поле, а не строку «null»', () => {
    expect(scenarioToForm(SCENARIO).user_avg_amount).toBe('')
  })
})

describe('сценарий -> форма -> запрос', () => {
  it('проходит круг без потерь и без жалоб', () => {
    const { body, invalid } = formToRequest(scenarioToForm(SCENARIO), ru)

    expect(invalid).toEqual([])
    expect(body.amount).toBe(100)
    expect(body.user_id).toBe('user_demo')
    expect(body.known_device_ids).toEqual(['dev_known_1', 'dev_known_2'])
  })
})
