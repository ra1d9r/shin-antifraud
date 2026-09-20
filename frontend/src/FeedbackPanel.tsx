/**
 * Панель накопленной разметки на дашборде.
 *
 * Остальной дашборд считает по датасету: там разметка известна заранее
 * и не меняется. Здесь — то, что подтвердили люди в работающей системе,
 * поэтому данные живые и грузятся отдельным запросом.
 *
 * Панель самостоятельна намеренно. Она читает сводку сама при появлении
 * на экране, а не получает её сверху: вкладки размонтируются при
 * переключении, так что открытый дашборд всегда показывает свежее число
 * меток — включая те, что только что поставили в симуляторе.
 *
 * Своей ошибки панель не показывает. Дашборд не про неё, а сообщение
 * «не удалось загрузить разметку» поверх честно загрузившейся аналитики
 * выглядело бы так, будто сломалось всё.
 */

import { useEffect, useState } from 'react'

import Tile from './Tile'
import { fetchFeedbackSummary } from './api'
import { formatMeasuredShare } from './feedback'
import { formatMoney } from './format'
import type { FeedbackSummary } from './types'

const DECISION_CLASS: Record<string, string> = {
  APPROVE: 'approve',
  CHALLENGE: 'challenge',
  BLOCK: 'block',
}

export default function FeedbackPanel() {
  const [summary, setSummary] = useState<FeedbackSummary | null>(null)

  useEffect(() => {
    let cancelled = false

    fetchFeedbackSummary()
      .then((payload) => {
        if (!cancelled) setSummary(payload)
      })
      .catch(() => {
        // Намеренно молча: см. комментарий к модулю.
      })

    return () => {
      cancelled = true
    }
  }, [])

  if (summary === null) return null

  return (
    <section className="panel">
      <h2>Разметка аналитика</h2>
      <p className="hint">
        Всё остальное на этой странице — то, что система думает о себе по обучающему
        датасету. Здесь единственные числа, которые подтвердил человек: аналитик
        разобрал операцию и сказал, права ли была система.
      </p>

      {summary.storage_error && (
        <p className="hint warn-text">
          <strong>{summary.storage_error}</strong>
        </p>
      )}

      {summary.labeled_total === 0 ? (
        <p className="hint">
          Пока не размечено ни одной операции. Проанализируйте транзакцию в симуляторе
          и отметьте вердикт верным или ошибочным — метка появится здесь.
        </p>
      ) : (
        <>
          <div className="tiles">
            <Tile label="Размечено операций" value={String(summary.labeled_total)} />
            <Tile
              label="Вердикт признан верным"
              value={formatMeasuredShare(summary.correct_share)}
              note={`${summary.correct} из ${summary.labeled_total}`}
              tone={summary.incorrect === 0 ? 'good' : undefined}
            />
            <Tile
              label="Точность на подтверждённом"
              value={formatMeasuredShare(summary.precision)}
              note={`${summary.true_positive} фрода из ${
                summary.true_positive + summary.false_positive
              } помеченных`}
            />
            <Tile
              label="Ложных срабатываний"
              value={String(summary.false_positive)}
              note="честных клиентов побеспокоили зря"
              tone={summary.false_positive > 0 ? 'warn' : 'good'}
            />
            <Tile
              label="Пропущено фрода"
              value={String(summary.false_negative)}
              note={
                summary.fraud_amount_missed > 0
                  ? `на ${formatMoney(summary.fraud_amount_missed)}`
                  : undefined
              }
              tone={summary.false_negative > 0 ? 'bad' : 'good'}
            />
          </div>

          <p className="hint">
            <strong>Почему полноты здесь нет.</strong> Размеченное — не случайная выборка:
            аналитик разбирает то, что система пометила. Пропущенный фрод попадает в
            разметку, только когда о нём сообщил клиент, поэтому полнота по этим данным
            была бы завышена и с метриками модели не сравнивалась бы. Точность смещена
            куда меньше и потому показана.
          </p>

          {summary.by_decision.length > 0 && (
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>Решение</th>
                    <th>Размечено</th>
                    <th>Оказалось фродом</th>
                    <th>Оказалось честным</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.by_decision.map((row) => (
                    <tr key={row.decision}>
                      <td>
                        <span className={`decision ${DECISION_CLASS[row.decision] ?? ''}`}>
                          {row.decision}
                        </span>
                      </td>
                      <td>{row.labeled}</td>
                      <td>{row.fraud}</td>
                      <td>{row.legit}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {summary.rules.length > 0 && (
            <>
              <h3>Политики на подтверждённых операциях</h3>
              <p className="hint">
                То же, что таблица политик выше, но по живым данным, а не по датасету.
                Политика, которая раз за разом срабатывает на подтверждённо честных
                клиентах, приносит одно трение.
              </p>
              <div className="table-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Политика</th>
                      <th>Срабатываний в разметке</th>
                      <th>Подтверждённый фрод</th>
                      <th>Ложные</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.rules.map((rule) => (
                      <tr key={rule.key}>
                        <td>
                          <code>{rule.key}</code>
                        </td>
                        <td>{rule.labeled}</td>
                        <td>{rule.fraud}</td>
                        <td className={rule.fraud === 0 ? 'warn-text' : ''}>{rule.legit}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </section>
  )
}
