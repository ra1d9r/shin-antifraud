/**
 * Форматирование, связанное с выбранным языком.
 *
 * Компонент берёт отсюда те же `formatCount` и `formatMoney`, что были
 * раньше, но уже знающие язык. Так локаль не приходится протаскивать
 * шестьюдесятью девятью аргументами через все панели — и при этом она
 * остаётся настоящей зависимостью отрисовки, а не скрытым глобалом:
 * смена языка перерисовывает дерево, и числа меняют формат вместе
 * с подписями.
 */

import { useMemo } from 'react'

import { formatCount, formatDateTime, formatMoney } from './format'
import { useLanguage } from './LanguageContext'

export function useFormat() {
  const { language } = useLanguage()

  return useMemo(
    () => ({
      formatCount: (value: number) => formatCount(value, language),
      formatMoney: (value: number) => formatMoney(value, language),
      formatDateTime: (value: string) => formatDateTime(value, language),
    }),
    [language],
  )
}
