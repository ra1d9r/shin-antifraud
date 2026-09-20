/**
 * Форматирование чисел для всех панелей.
 *
 * Вынесено, когда `Math.round(value).toLocaleString('ru-RU')` разошлось
 * по трём файлам, а `value.toLocaleString('ru-RU')` — ещё по трём. Копии
 * начали бы расходиться в мелочах: где-то остались бы копейки, где-то нет,
 * и одна и та же сумма выглядела бы на соседних панелях по-разному.
 */

/** Количество: разряды через пробел, дробной части нет по смыслу. */
export function formatCount(value: number): string {
  if (!Number.isFinite(value)) return '—'
  return value.toLocaleString('ru-RU')
}

/**
 * Сумма денег.
 *
 * Округляется до целого: на дашборде читают порядок величины, а копейки
 * в шестизначном числе только мешают его увидеть.
 */
export function formatMoney(value: number): string {
  if (!Number.isFinite(value)) return '—'
  return Math.round(value).toLocaleString('ru-RU')
}
