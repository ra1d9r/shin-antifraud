/**
 * Загрузка данных панели с честным различением трёх состояний.
 *
 * ## Что было не так
 *
 * Шесть панелей — граф, дрейф, тень, разметка, адаптивный порог,
 * признаки — забирали данные одинаково: `fetch().catch(() => {})`,
 * а потом `if (data === null) return null`. Ошибка проглатывалась
 * целиком, и панель просто исчезала.
 *
 * Для одной панели это выглядело осознанным: пусть остальной дашборд
 * работает. Но если backend отвечает плохо, исчезают все шесть сразу,
 * и человек видит дашборд без половины содержимого — без единого слова
 * о том, что случилось. Отличить «панели нет» от «панель не сделали»
 * он не может.
 *
 * ## Три состояния вместо двух
 *
 * `loading` — ещё не ответили, показывать нечего и рано.
 * `error` — ответили плохо, и об этом надо сказать.
 * `data` — всё пришло.
 *
 * Различать первые два обязательно: пустота в начале загрузки нормальна,
 * пустота после ошибки — нет.
 */

import { useEffect, useState } from 'react'

export interface PanelData<T> {
  data: T | null
  error: string | null
  loading: boolean
}

/**
 * Превратить причину отказа в объяснение для человека.
 *
 * Сообщение backend точнее нашего: он знает, артефакт ли не выгружен,
 * модель ли не загружена или дело в сети. Своего текста здесь нет
 * намеренно — подменять объяснение сервера общим «что-то пошло не так»
 * значит терять единственное, что может помочь.
 *
 * Пустая строка означает «пригодного объяснения нет». Это не то же
 * самое, что отсутствие ошибки: панель всё равно скажет, что недоступна,
 * просто без второй половины фразы. `String(cause)` для такого случая
 * не годится — строка «null» человеку не объясняет ничего, а выглядит
 * как недоделка.
 */
export function describeFailure(cause: unknown): string {
  // ApiError наследует Error, так что одной проверки хватает на оба.
  if (cause instanceof Error) return cause.message.trim()
  if (typeof cause === 'string') return cause.trim()
  return ''
}

/**
 * Забрать данные панели один раз при монтировании.
 *
 * `load` обязан быть стабильным — обычная экспортированная функция
 * из `api.ts`. Стрелка, созданная в теле компонента, перезапускала бы
 * запрос на каждую отрисовку.
 */
export function usePanelData<T>(load: () => Promise<T>): PanelData<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    load()
      .then((payload) => {
        if (!cancelled) setData(payload)
      })
      .catch((cause: unknown) => {
        if (cancelled) return
        setError(describeFailure(cause))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [load])

  return { data, error, loading }
}
