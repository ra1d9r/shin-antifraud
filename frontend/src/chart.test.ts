/**
 * Тесты арифметики графика.
 *
 * Проверяется то, что ломается незаметно: у краёв округление выносит
 * порог за шкалу, а подсказка у правого края уезжает за картинку.
 * И то и другое выглядит как «иногда не работает».
 */

import { describe, expect, it } from 'vitest'

import { readoutX, thresholdAtPointer } from './chart'

describe('порог под курсором', () => {
  it('доля по ширине и есть порог', () => {
    expect(thresholdAtPointer(0, 400)).toBe(0)
    expect(thresholdAtPointer(200, 400)).toBe(50)
    expect(thresholdAtPointer(400, 400)).toBe(100)
  })

  it('не зависит от размера картинки на экране', () => {
    // viewBox растягивается по ширине панели: на телефоне множитель
    // другой, чем на мониторе, а порог обязан получиться тот же.
    expect(thresholdAtPointer(100, 400)).toBe(thresholdAtPointer(300, 1200))
  })

  it('за краями зажимается, а не выходит за шкалу', () => {
    // Иначе подсказка исчезала бы ровно у края, по которому и ведут:
    // точки с порогом 101 на кривой нет.
    expect(thresholdAtPointer(-15, 400)).toBe(0)
    expect(thresholdAtPointer(415, 400)).toBe(100)
  })

  it('скрытая вкладка нулевой ширины не делит на ноль', () => {
    expect(thresholdAtPointer(50, 0)).toBeNull()
    expect(thresholdAtPointer(50, Number.NaN)).toBeNull()
  })
})

describe('положение подсказки', () => {
  it('обычно справа от засечки', () => {
    expect(readoutX(100, 186, 720)).toBe(110)
  })

  it('у правого края переезжает налево', () => {
    // 600 + 186 + 14 больше 720 — справа не помещается.
    expect(readoutX(600, 186, 720)).toBe(404)
  })

  it('переехавшая подсказка целиком внутри картинки', () => {
    for (const mark of [0, 250, 500, 700, 720]) {
      const x = readoutX(mark, 186, 720)
      expect(x).toBeGreaterThanOrEqual(0)
      expect(x + 186).toBeLessThanOrEqual(720)
    }
  })
})
