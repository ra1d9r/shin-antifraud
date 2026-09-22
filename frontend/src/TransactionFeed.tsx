/**
 * Лента обработанных операций для аналитика.
 *
 * ## Зачем
 *
 * Дашборд показывал сводные числа — сколько поймано, сколько пропущено,
 * во что обошлось. Отдельной операции в нём не было видно ни одной,
 * хотя `GET /transactions` отдавал их с самого начала. Аналитику,
 * которому нужно разобрать конкретный случай, смотреть было нечего:
 * оставался Swagger.
 *
 * ## Что показывает
 *
 * Последние операции сверху вниз, с подсветкой того, что по ним
 * сработало: политики — отдельными метками, сильнейшая причина
 * от модели — строкой под ними. Это и есть «критические признаки»
 * для оперативного аудита: по ним видно, почему операция здесь,
 * не открывая её целиком.
 *
 * Фильтр «только задержанные» стоит рядом не для красоты: в обычном
 * потоке девять из десяти операций одобрены, и без фильтра лента —
 * это страница строк `APPROVE`, среди которых надо глазами искать
 * те три, ради которых её открыли.
 *
 * Разметка аналитика показывается тут же: таблица без пометки
 * «уже проверено» заставила бы разбирать одно и то же дважды.
 */

import { useCallback, useState } from 'react'

import { errorText, fetchTransactions } from './api'
import PanelError from './PanelError'
import { useLanguage } from './LanguageContext'
import { usePanelData } from './usePanelData'
import { useFormat } from './useFormat'
import type { Decision, TransactionRecord } from './types'

/** Сколько строк показывать. Лента для разбора, а не для выгрузки. */
const LIMIT = 25

const DECISION_CLASS: Record<Decision, string> = {
  APPROVE: 'approve',
  CHALLENGE: 'challenge',
  BLOCK: 'block',
}

export default function TransactionFeed() {
  const { t } = useLanguage()
  const { formatCount, formatMoney, formatDateTime } = useFormat()
  const [flaggedOnly, setFlaggedOnly] = useState(false)

  // Фильтр — часть запроса, а не отбор на клиенте: иначе «только
  // задержанные» показывало бы те из двадцати пяти последних, что
  // задержаны, а не двадцать пять последних задержанных.
  const load = useCallback(() => fetchTransactions(LIMIT, flaggedOnly), [flaggedOnly])
  const { data, failure } = usePanelData(load)

  if (failure !== null) {
    return <PanelError title={t('feed.title')} reason={errorText(failure.cause, t)} />
  }
  if (data === null) return null

  return (
    <section className="panel">
      <h2>{t('feed.title')}</h2>

      <p className="hint">
        Отдельная операция в сводных числах не видна, а разбирают именно её.
        Здесь последние {LIMIT} с тем, что по ним сработало: метки — политики,
        строка под ними — сильнейшая причина от модели.
      </p>

      <div className="feed-controls">
        <button
          type="button"
          className={flaggedOnly ? 'chip' : 'chip active'}
          onClick={() => setFlaggedOnly(false)}
        >
          {t('feed.showAll')}
        </button>
        <button
          type="button"
          className={flaggedOnly ? 'chip active' : 'chip'}
          onClick={() => setFlaggedOnly(true)}
        >
          {t('feed.showFlagged')}
        </button>
        <span className="hint always-visible">
          {t('feed.ofTotal', { total: formatCount(data.total) })}
        </span>
      </div>

      {data.items.length === 0 ? (
        <p className="hint always-visible">{t('feed.empty')}</p>
      ) : (
        <div className="table-scroll">
          <table className="feed">
            <thead>
              <tr>
                <th>{t('feed.time')}</th>
                <th>{t('feed.amount')}</th>
                <th>{t('feed.merchant')}</th>
                <th>{t('feed.score')}</th>
                <th>{t('feed.decision')}</th>
                <th>{t('feed.signals')}</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((record) => (
                <FeedRow
                  key={record.transaction_id}
                  record={record}
                  formatMoney={formatMoney}
                  formatDateTime={formatDateTime}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function FeedRow({
  record,
  formatMoney,
  formatDateTime,
}: {
  record: TransactionRecord
  formatMoney: (value: number) => string
  formatDateTime: (value: string) => string
}) {
  const { t } = useLanguage()

  return (
    <tr className={record.decision === 'APPROVE' ? undefined : 'row-flagged'}>
      <td className="muted nowrap">{formatDateTime(record.timestamp)}</td>
      <td className="nowrap">{formatMoney(record.amount)}</td>
      <td>
        {record.merchant}
        {/* Страна кодом намеренно: в таблице на двадцать пять строк
            название заняло бы полколонки, а код читается мгновенно. */}
        <span className="muted"> · {record.country}</span>
      </td>
      <td>
        <strong>{record.risk_score}</strong>
        {/* Когда политики подняли оценку, видно на сколько: без этого
            непонятно, чьё решение — модели или правила. */}
        {record.model_score !== record.risk_score && (
          <span className="muted"> ← {record.model_score}</span>
        )}
      </td>
      <td>
        <span className={`badge ${DECISION_CLASS[record.decision]}`}>
          {t(`decision.${record.decision}`)}
        </span>
        {record.verdict !== null && (
          <span className="muted"> · {t('feed.labelled')}</span>
        )}
      </td>
      <td className="signals">
        {record.triggered_rules.map((rule) => (
          <code key={rule} className="signal">
            {rule}
          </code>
        ))}
        {record.top_reason !== null && (
          <div className="muted top-reason">{record.top_reason}</div>
        )}
        {/* «Ничего» — только когда правда ничего. Раньше оно печаталось
            при пустом списке политик и вставало перед причиной от модели:
            строка читалась как «ничего не сработало — новое устройство». */}
        {record.triggered_rules.length === 0 && record.top_reason === null && (
          <span className="muted">{t('feed.noSignals')}</span>
        )}
      </td>
    </tr>
  )
}
