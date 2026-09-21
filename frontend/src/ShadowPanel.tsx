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


import Tile from './Tile'
import { fetchShadow } from './api'
import { formatMeasuredShare } from './feedback'
import { describeConfiguration } from './shadow'
import PanelError from './PanelError'
import { useLanguage } from './LanguageContext'
import { usePanelData } from './usePanelData'
import { useFormat } from './useFormat'

const DECISION_CLASS: Record<string, string> = {
  APPROVE: 'approve',
  CHALLENGE: 'challenge',
  BLOCK: 'block',
}

export default function ShadowPanel() {
  const { t } = useLanguage()
  const { formatCount, formatMoney } = useFormat()
  const { data: report, error } = usePanelData(fetchShadow)


  if (error !== null) return <PanelError title={t('shadow.title')} reason={error} />
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
          <span className="tile-label">{t('shadow.primaryLive')}</span>
          <strong>{describeConfiguration(report.primary)}</strong>
        </div>
        <div className="config shadow">
          <span className="tile-label">{t('shadow.shadowOnlyCounts')}</span>
          <strong>{describeConfiguration(report.shadow)}</strong>
        </div>
      </div>

      {!report.differs && (
        <p className="hint">
          <strong className="warn-text">
            {t('shadow.identical')}
          </strong>{' '}
          Полное согласие ниже означает только это. Задайте отличие
          переменными <code>SHADOW_APPROVE_MAX</code>, <code>SHADOW_CHALLENGE_MAX</code>{' '}
          или <code>SHADOW_RULES_ENABLED</code>.
        </p>
      )}

      <div className="tiles">
        <Tile label={t('shadow.compared')} value={formatCount(report.observed)} />
        <Tile
          label={t('shadow.agreed')}
          value={formatMeasuredShare(report.agreement_share)}
          note={report.observed > 0 ? `${report.agreed} из ${report.observed}` : undefined}
        />
        <Tile
          label={t('shadow.frictionRemoved')}
          value={String(report.freed_count)}
          note={report.freed_amount > 0 ? `на ${formatMoney(report.freed_amount)}` : 'операций'}
          tone={report.freed_count > 0 ? 'good' : undefined}
        />
        <Tile
          label={t('shadow.frictionAdded')}
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
          <h3>{t('shadow.whoDecided')}</h3>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('shadow.primary')}</th>
                  <th>{t('shadow.shadow')}</th>
                  <th>{t('common.operations')}</th>
                  <th>{t('common.forAmount')}</th>
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
          <h3>{t('shadow.lastDisagreements')}</h3>
          <p className="hint">
            Конкретные операции — с них начинают разбор, когда решают, переключать или нет.
          </p>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('common.transaction')}</th>
                  <th>{t('common.amount')}</th>
                  <th>{t('shadow.primary')}</th>
                  <th>{t('shadow.shadow')}</th>
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
