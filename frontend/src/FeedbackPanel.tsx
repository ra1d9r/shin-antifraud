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


import Tile from './Tile'
import { errorText, fetchFeedbackSummary } from './api'
import { formatMeasuredShare } from './feedback'
import PanelError from './PanelError'
import { useLanguage } from './LanguageContext'
import { usePanelData } from './usePanelData'
import { useFormat } from './useFormat'

const DECISION_CLASS: Record<string, string> = {
  APPROVE: 'approve',
  CHALLENGE: 'challenge',
  BLOCK: 'block',
}

export default function FeedbackPanel() {
  const { t } = useLanguage()
  const { formatMoney } = useFormat()
  const { data: summary, failure } = usePanelData(fetchFeedbackSummary)


  if (failure !== null) {
    return <PanelError title={t('feedback.title')} reason={errorText(failure.cause, t)} />
  }
  if (summary === null) return null

  return (
    <section className="panel">
      <h2>{t('feedback.title')}</h2>
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
            <Tile label={t('feedback.labeled')} value={String(summary.labeled_total)} />
            <Tile
              label={t('feedback.verdictRight')}
              value={formatMeasuredShare(summary.correct_share, t)}
              note={t('common.outOf', { shown: summary.correct, total: summary.labeled_total })}
              tone={summary.incorrect === 0 ? 'good' : undefined}
            />
            <Tile
              label={t('feedback.measuredPrecision')}
              value={formatMeasuredShare(summary.precision, t)}
              note={t('feedback.fraudOfFlagged', {
                hits: summary.true_positive,
                flagged: summary.true_positive + summary.false_positive,
              })}
            />
            <Tile
              label={t('feedback.falsePositives')}
              value={String(summary.false_positive)}
              note={t('feedback.botheredInVain')}
              tone={summary.false_positive > 0 ? 'warn' : 'good'}
            />
            <Tile
              label={t('feedback.fraudMissed')}
              value={String(summary.false_negative)}
              note={
                summary.fraud_amount_missed > 0
                  ? t('common.noteForAmount', { amount: formatMoney(summary.fraud_amount_missed) })
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
                    <th>{t('common.decision')}</th>
                    <th>{t('feedback.marked')}</th>
                    <th>{t('feedback.turnedFraud')}</th>
                    <th>{t('feedback.turnedHonest')}</th>
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
              <h3>{t('feedback.policiesOnConfirmed')}</h3>
              <p className="hint">
                То же, что таблица политик выше, но по живым данным, а не по датасету.
                Политика, которая раз за разом срабатывает на подтверждённо честных
                клиентах, приносит одно трение.
              </p>
              <div className="table-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th>{t('rules.policy')}</th>
                      <th>{t('feedback.firedInLabels')}</th>
                      <th>{t('feedback.confirmedFraud')}</th>
                      <th>{t('feedback.falseOnes')}</th>
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
