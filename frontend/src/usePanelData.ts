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

import { ApiError } from './api'

export interface PanelData<T> {
  data: T | null
  error: string | null
  loading: boolean
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
        // Сообщение backend точнее нашего: он знает, артефакт ли
        // не выгружен, модель ли не загружена или дело в сети.
        setError(cause instanceof ApiError ? cause.message : String(cause))
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
