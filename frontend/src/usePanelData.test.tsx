/**
 * Тесты на то, что упавшая панель не исчезает молча.
 *
 * Регрессия, ради которой написаны эти тесты, выглядела безобидно:
 * `fetch().catch(() => {})` и `return null`. Панель пропадала, и
 * отличить «не загрузилась» от «не сделали» было нельзя.
 *
 * Здесь три проверки, каждая закрывает свою половину поломки:
 * сообщение не теряется, оно доходит до разметки, и новая панель
 * не сможет вернуться к старому образцу незамеченной.
 *
 * Тесты не поднимают jsdom: `renderToStaticMarkup` отрисовывает
 * PanelError в чистом Node, а хук `usePanelData` проверяется через
 * вынесенную из него чистую `describeFailure`.
 */

import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { ApiError } from './api'
import { LanguageProvider } from './LanguageContext'
import PanelError from './PanelError'
import { describeFailure } from './usePanelData'

/**
 * Исходники всех панелей — читает Vite, а не node:fs.
 *
 * Глоб берёт папку целиком, а не список из шести файлов: панель,
 * добавленная завтра, попадёт под проверку сама, и её не придётся
 * вспоминать. Ради этого тесту и нужен исходный текст.
 */
const SOURCES = import.meta.glob('./*Panel.tsx', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

/** Панели, переведённые на usePanelData в этой правке. */
const CONVERTED = [
  'GraphPanel.tsx',
  'ShadowPanel.tsx',
  'DriftPanel.tsx',
  'FeedbackPanel.tsx',
  'AdaptivePanel.tsx',
  'FeaturePanel.tsx',
]

const named = (path: string) => path.replace('./', '')

describe('describeFailure', () => {
  it('передаёт формулировку backend дословно', () => {
    const cause = new ApiError('Буфер операций пуст: граф строить не на чем.', 503, null)
    expect(describeFailure(cause)).toBe('Буфер операций пуст: граф строить не на чем.')
  })

  it('передаёт дословно и сетевую ошибку — она называет адрес', () => {
    const cause = new Error('Backend недоступен по адресу http://localhost:8000. Поднят ли он?')
    expect(describeFailure(cause)).toContain('http://localhost:8000')
  })

  it('не теряет причину, даже если бросили голую строку', () => {
    expect(describeFailure('таймаут')).toBe('таймаут')
  })

  it('молчит вместо «null» и «[object Object]» — это не объяснения', () => {
    for (const cause of [null, undefined, {}, 404]) {
      expect(describeFailure(cause)).toBe('')
    }
  })

  it('пустое сообщение остаётся пустым, а не превращается в «Error»', () => {
    expect(describeFailure(new Error('   '))).toBe('')
    expect(describeFailure(new ApiError('', 500, null))).toBe('')
  })
})

describe('PanelError', () => {
  const markup = renderToStaticMarkup(
    <LanguageProvider>
      <PanelError title="Связи между клиентами" reason="Буфер операций пуст." />
    </LanguageProvider>,
  )

  it('называет панель, чтобы было видно, чего именно не хватает', () => {
    expect(markup).toContain('Связи между клиентами')
  })

  it('называет причину словами backend', () => {
    expect(markup).toContain('Буфер операций пуст.')
  })

  it('говорит, что панель недоступна, а не просто показывает пустоту', () => {
    expect(markup).toContain('Панель недоступна')
  })

  it('остаётся видимой: пояснение помечено always-visible', () => {
    // Комментарии скрыты на казахском и английском правилом в styles.css.
    // Причина отказа — не комментарий, её нельзя прятать вместе с ними.
    expect(markup).toContain('always-visible')
  })

  it('без причины говорит хотя бы то, что панель недоступна', () => {
    const bare = renderToStaticMarkup(
      <LanguageProvider>
        <PanelError title="Сдвиг распределения" reason="" />
      </LanguageProvider>,
    )
    expect(bare).toContain('Сдвиг распределения')
    expect(bare).toContain('Панель недоступна')
  })
})

describe('панели', () => {
  it('глоб действительно нашёл панели, а не пустоту', () => {
    // Иначе две проверки ниже прошли бы на пустом списке, ничего не проверив.
    const found = Object.keys(SOURCES).map(named)
    for (const name of CONVERTED) expect(found).toContain(name)
  })

  it('ни одна не глотает ошибку пустым catch', () => {
    const guilty = Object.entries(SOURCES)
      .filter(([, source]) => /\.catch\(\(\)\s*=>\s*\{\s*\}\)/.test(source))
      .map(([path]) => named(path))
    expect(guilty).toEqual([])
  })

  it('каждая, кто грузит данные хуком, умеет показать отказ', () => {
    const silent = Object.entries(SOURCES)
      .filter(([, source]) => source.includes('usePanelData(') && !source.includes('<PanelError'))
      .map(([path]) => named(path))
    expect(silent).toEqual([])
  })

  it('все шесть переведённых панелей правда пользуются хуком', () => {
    for (const name of CONVERTED) {
      expect(SOURCES[`./${name}`]).toContain('usePanelData(')
    }
  })
})
