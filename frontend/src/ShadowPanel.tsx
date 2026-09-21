/**
 * Панель теневого режима на дашборде.
 *
 * Кривая компромисса выше отвечает, что было бы на обучающем датасете.
 * Здесь — что происходит на сегодняшнем потоке при второй конфигурации,
 * и переключение можно оценить до того, как оно затронет клиентов.
 *
 * Решения теневой конфигурации нигде не показываются как решения системы:
 * это сравнение, а не второй вердикт.
 *
 * Панель самостоятельна и молчит об ошибках по тем же причинам, что
 * `FeedbackPanel` и `DriftPanel`.
 */

import { useEffect, useState } from 'react'

import Tile from './Tile'
import { fetchShadow } from './api'
import { formatMeasuredShare } from './feedback'
import { formatCount, formatMoney } from './format'
import { describeConfiguration } from './shadow'
import type { ShadowComparison } from './types'
import { useLanguage } from './LanguageContext'

const DECISION_CLASS: Record<string, string> = {
  APPROVE: 'approve',
  CHALLENGE: 'challenge',
  BLOCK: 'block',
}

export default function ShadowPanel() {
  const { t } = useLanguage()
  const [report, setReport] = useState<ShadowComparison | null>(null)

  useEffect(() => {
    let cancelled = false

    fetchShadow()
      .then((payload) => {
        if (!cancelled) setReport(payload)
      })
      .catch(() => {
        // Намеренно молча: см. комментарий к модулю.
      })

    return () => {
      cancelled = true
    }
  }, [])

  if (report === null) return null

  return (
    <section className="panel">
      <h2>{t('shadow.title')}</h2>
      <p className="hint">
        Вторая конфигурация видит те же настоящие операции и выносит свои решения.
        Они <strong>никуда не уходят</strong>: ответ системы от них не зависит, в историю
        они не попадают, деньги по ним не блокируются. Считаются только расхождения —
        чтобы переключение можно было оценить заранее, а не по факту.
      </p>

      {report.differs && (
        <p className="hint">
          Отличие теневой от основной: <strong>{report.difference}</strong>.
        </p>
      )}

      <div className="configs">
        <div className="config">
          <span className="tile-label">Основная — работает</span>
          <strong>{describeConfiguration(report.primary)}</strong>
        </div>
        <div className="config shadow">
          <span className="tile-label">Теневая — только считает</span>
          <strong>{describeConfiguration(report.shadow)}</strong>
        </div>
      </div>

      {!report.differs && (
        <p className="hint">
          <strong className="warn-text">
            Теневая конфигурация совпадает с основной — сравнивать нечего.
          </strong>{' '}
          Полное согласие ниже означает только это. Задайте отличие
          переменными <code>SHADOW_APPROVE_MAX</code>, <code>SHADOW_CHALLENGE_MAX</code>{' '}
          или <code>SHADOW_RULES_ENABLED</code>.
        </p>
      )}

      <div className="tiles">
        <Tile label="Операций сравнено" value={formatCount(report.observed)} />
        <Tile
          label="Решения совпали"
          value={formatMeasuredShare(report.agreement_share)}
          note={report.observed > 0 ? `${report.agreed} из ${report.observed}` : undefined}
        />
        <Tile
          label="Трение снялось бы"
          value={String(report.freed_count)}
          note={report.freed_amount > 0 ? `на ${formatMoney(report.freed_amount)}` : 'операций'}
          tone={report.freed_count > 0 ? 'good' : undefined}
        />
        <Tile
          label="Трение добавилось бы"
          value={String(report.tightened_count)}
          note={
            report.tightened_amount > 0
              ? `на ${formatMoney(report.tightened_amount)}`
              : 'операций'
          }
          tone={report.tightened_count > 0 ? 'warn' : undefined}
        />
      </div>

      <p className="hint">
        «Снялось бы» — операции, которые основная отправила на проверку или заблокировала,
        а теневая пропустила бы: меньше беспокойства клиентам, но и меньше пойманного фрода.
        «Добавилось бы» — наоборот. Перевод между CHALLENGE и BLOCK не считается ни тем
        ни другим: оба означают, что система сочла операцию подозрительной.
      </p>

      {report.matrix.length > 0 && (
        <>
          <h3>Кто что решил</h3>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Основная</th>
                  <th>Теневая</th>
                  <th>Операций</th>
                  <th>На сумму</th>
                </tr>
              </thead>
              <tbody>
                {report.matrix.map((cell) => {
                  const same = cell.primary === cell.shadow
                  return (
                    <tr key={`${cell.primary}-${cell.shadow}`}>
                      <td>
                        <span className={`decision ${DECISION_CLASS[cell.primary] ?? ''}`}>
                          {cell.primary}
                        </span>
                      </td>
                      <td>
                        <span className={`decision ${DECISION_CLASS[cell.shadow] ?? ''}`}>
                          {cell.shadow}
                        </span>
                      </td>
                      <td className={same ? 'muted' : ''}>{cell.count}</td>
                      <td className={same ? 'muted' : ''}>{formatMoney(cell.amount)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {report.recent.length > 0 && (
        <>
          <h3>Последние расхождения</h3>
          <p className="hint">
            Конкретные операции — с них начинают разбор, когда решают, переключать или нет.
          </p>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Операция</th>
                  <th>Сумма</th>
                  <th>Основная</th>
                  <th>Теневая</th>
                </tr>
              </thead>
              <tbody>
                {report.recent.map((item) => (
                  <tr key={`${item.transaction_id}-${item.at}`}>
                    <td>
                      <code>{item.transaction_id}</code>
                    </td>
                    <td>{formatMoney(item.amount)}</td>
                    <td>
                      <span className={`decision ${DECISION_CLASS[item.primary_decision] ?? ''}`}>
                        {item.primary_decision}
                      </span>{' '}
                      <span className="muted">({item.primary_score})</span>
                    </td>
                    <td>
                      <span className={`decision ${DECISION_CLASS[item.shadow_decision] ?? ''}`}>
                        {item.shadow_decision}
                      </span>{' '}
                      <span className="muted">({item.shadow_score})</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}
