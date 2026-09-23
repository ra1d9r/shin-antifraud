/**
 * Тесты проекции карты (брифинг §6).
 *
 * Арифметика проекции — ровно то место, где ошибка не видна глазами.
 * Перепутанный знак долготы переносит операцию на другое полушарие,
 * а перевёрнутая широта — в другое, и на карте без подложки это
 * выглядит просто как другая точка.
 */

import { describe, expect, it } from 'vitest'

import { labelAnchor, project, radius, tone } from './map'

const BOX = { width: 720, height: 360 }

describe('проекция', () => {
  it('нулевая точка попадает в центр', () => {
    expect(project(0, 0, BOX)).toEqual({ x: 360, y: 180 })
  })

  it('восток правее запада', () => {
    const east = project(0, 90, BOX)
    const west = project(0, -90, BOX)

    expect(east.x).toBeGreaterThan(west.x)
  })

  it('север выше юга', () => {
    // Y в SVG растёт вниз, поэтому у северной точки он должен быть
    // МЕНЬШЕ. Именно здесь проще всего ошибиться знаком.
    const north = project(60, 0, BOX)
    const south = project(-60, 0, BOX)

    expect(north.y).toBeLessThan(south.y)
  })

  it('края карты совпадают с границами холста', () => {
    expect(project(90, -180, BOX)).toEqual({ x: 0, y: 0 })
    expect(project(-90, 180, BOX)).toEqual({ x: BOX.width, y: BOX.height })
  })

  it('Астана оказывается там, где ей положено', () => {
    // Казахстан: северное полушарие, восточная долгота — значит правее
    // и выше центра.
    const astana = project(51.1694, 71.4491, BOX)

    expect(astana.x).toBeGreaterThan(BOX.width / 2)
    expect(astana.y).toBeLessThan(BOX.height / 2)
  })

  it('Каракас оказывается левее и ниже Астаны', () => {
    // Венесуэла: западная долгота, почти экватор.
    const caracas = project(10.4806, -66.9036, BOX)
    const astana = project(51.1694, 71.4491, BOX)

    expect(caracas.x).toBeLessThan(astana.x)
    expect(caracas.y).toBeGreaterThan(astana.y)
  })
})

describe('размер точки', () => {
  it('растёт по площади, а не по радиусу', () => {
    // Вчетверо больше операций — вдвое больший радиус сверх минимума:
    // глаз сравнивает площади, поэтому по площади и масштабируем.
    const min = 4
    const max = 26
    const quarter = radius(2500, 10000, min, max)
    const full = radius(10000, 10000, min, max)

    expect(full).toBeCloseTo(max, 5)
    expect(quarter - min).toBeCloseTo((full - min) / 2, 5)
  })

  it('никогда не исчезает и не разрастается', () => {
    expect(radius(1, 100000)).toBeGreaterThanOrEqual(4)
    expect(radius(100000, 100000)).toBeLessThanOrEqual(26)
  })

  it('вырожденные данные не ломают расчёт', () => {
    // Пустой датасет — не ошибка, а вырожденный случай: точка просто
    // рисуется минимальной, а не превращается в NaN и не исчезает.
    expect(radius(0, 0)).toBe(4)
    expect(Number.isFinite(radius(10, 0))).toBe(true)
  })
})

describe('цвет по доле фрода', () => {
  it('делит на три ступени', () => {
    expect(tone(0)).toBe('low')
    expect(tone(0.05)).toBe('low')
    expect(tone(0.1)).toBe('medium')
    expect(tone(0.4)).toBe('medium')
    expect(tone(0.5)).toBe('high')
    expect(tone(1)).toBe('high')
  })
})

describe('подпись', () => {
  it('у правого края уходит влево, чтобы не обрезаться', () => {
    expect(labelAnchor(BOX.width - 10, BOX)).toEqual({ dx: -6, anchor: 'end' })
  })

  it('в остальных местах стоит справа от точки', () => {
    expect(labelAnchor(100, BOX)).toEqual({ dx: 6, anchor: 'start' })
  })
})
