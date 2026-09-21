/**
 * Адаптивный порог по категории мерчанта (брифинг §6).
 *
 * Панель показывает три вещи, и третья важнее первых двух: подобранные
 * пороги, применяются ли они сейчас — и чего режим стоит на данных,
 * которых не видел при подборе. Таблица без последнего была бы набором
 * чисел, выданным за улучшение.
 *
 * Отрицательные результаты показываются наравне с положительными.
 * Худшая часть проверки у нас отрицательная, и прятать её значило бы
 * заявить работу, которой не было.
 */

import { useEffect, useState } from 'react'

import { fetchAdaptive } from './api'
import { formatCount, formatMoney } from './format'
import Tile from './Tile'
import type { AdaptiveThresholdsState } from './types'

/**
 * Разница со знаком.
 *
 * Минус типографский, а не дефис: иначе в соседних плитках «−900»
 * и «-14» выглядели бы разными видами числа.
 */
function signed(value: number, format: (value: number) => string = formatMoney): string {
  const sign = value > 0 ? '+' : value < 0 ? '−' : ''
  return `${sign}${format(Math.abs(value))}`
}

export default function AdaptivePanel() {
  const [state, setState] = useState<AdaptiveThresholdsState | null>(null)

  useEffect(() => {
    let cancelled = false

    fetchAdaptive()
      .then((payload) => {
        if (!cancelled) setState(payload)
      })
      .catch(() => {
        // Молча: без панели остальной дашборд работает как прежде.
      })

    return () => {
      cancelled = true
    }
  }, [])

  if (state === null || !state.available) return null

  const check = state.validation

  return (
    <section className="panel">
      <h2>Адаптивный порог по категории мерчанта</h2>
      <p className="hint">
        Чувствительность подстраивается под категорию: граница «пропустить или
        проверить» у каждой своя. Ни один порог не назначен руками — каждый
        подобран как минимум той же функции стоимости, по которой построена
        кривая выше.
      </p>
      <p className="hint">
        Интуиция здесь ошибается знаком. Кажется, что у криптобирж и обменников
        порог надо опускать, раз через них выводят украденное, — а подобранный
        оказывается <strong>выше</strong> общего: модель уже учитывает категорию
        признаком, и низкий порог поверх этого просто заваливает проверками
        честные операции.
      </p>

      <div className="tiles">
        <Tile
          label="Режим"
          value={state.enabled ? 'включён' : 'выключен'}
          note={state.enabled ? 'пороги применяются к решениям' : 'решения на общем пороге'}
          tone={state.enabled ? 'good' : undefined}
        />
        <Tile
          label="Сегментов"
          value={String(state.segments.length)}
          note={`свой порог у ${state.segments.filter((item) => item.fitted).length}`}
        />
        <Tile
          label="Общий запасной порог"
          value={String(state.fallback_approve_max ?? '—')}
          note="для категорий без своего"
        />
      </div>

      {check && (
        <>
          <h3>Чего это стоит</h3>
          <p className="hint">
            Проверка перекрёстная, на {check.folds} частях: порог сегмента
            подбирается без тех операций, на которых потом считается результат.
            Подбор и проверка на одних данных показали бы выигрыш, которого нет.
          </p>
          <div className="tiles">
            <Tile
              label="Выигрыш против одного порога"
              value={signed(check.mean_gain)}
              note={`в среднем; положительных частей ${check.positive_folds} из ${check.folds}`}
              tone={check.mean_gain > 0 ? 'good' : 'bad'}
            />
            <Tile
              label="Худшая часть проверки"
              value={signed(check.worst_gain)}
              note={check.worst_gain < 0 ? 'там режим проиграл' : 'выиграл везде'}
              tone={check.worst_gain < 0 ? 'warn' : 'good'}
            />
            <Tile
              label="Трение против настройки"
              value={signed(check.adaptive_friction - check.configured_friction, formatCount)}
              note={`${formatCount(check.configured_friction)} → ${formatCount(
                check.adaptive_friction,
              )} задержанных честных операций`}
              tone={check.adaptive_friction < check.configured_friction ? 'good' : 'bad'}
            />
            <Tile
              label="Пойманный фрод"
              value={signed(
                check.adaptive_fraud_stopped - check.configured_fraud_stopped,
                formatCount,
              )}
              note={`${formatCount(check.configured_fraud_stopped)} → ${formatCount(
                check.adaptive_fraud_stopped,
              )} операций`}
              tone={
                check.adaptive_fraud_stopped < check.configured_fraud_stopped ? 'warn' : 'good'
              }
            />
          </div>
          <p className="hint">
            Сравнение с действующей настройкой <code>approve_max = </code>
            {check.configured_approve_max}: стоимость{' '}
            {formatMoney(check.configured_cost)} против{' '}
            {formatMoney(check.adaptive_cost)}. Главный эффект — меньше
            побеспокоенных честных клиентов, и он куплен несколькими
            пропущенными операциями.
          </p>
          <p className="hint">
            Время суток брифинг называет наравне с категорией, и оно тоже
            проверялось: сегментация по нему в среднем <strong>проигрывает</strong>,
            поэтому не применяется.
          </p>
        </>
      )}

      <h3>Подобранные пороги</h3>
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>Категория</th>
              <th>Порог</th>
              <th>Операций</th>
              <th>Из них фрод</th>
            </tr>
          </thead>
          <tbody>
            {state.segments.map((item) => (
              <tr key={item.segment}>
                <td>
                  <code>{item.segment}</code>
                </td>
                <td>
                  <strong>{item.approve_max}</strong>
                  {!item.fitted && <span className="muted"> — общий</span>}
                </td>
                <td>{formatCount(item.rows)}</td>
                <td>{formatCount(item.fraud_rows)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">
        Подобрано {state.generated_at ? new Date(state.generated_at).toLocaleString('ru-RU') : '—'}{' '}
        по {formatCount(state.rows ?? 0)} операциям. Категории, где мошеннических
        операций меньше {state.min_fraud_per_segment}, своего порога не получают:
        на десятке случаев минимум определяется одной крупной операцией, а не
        закономерностью.
      </p>
    </section>
  )
}
