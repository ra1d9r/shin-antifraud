/**
 * Панель графа связей на дашборде.
 *
 * Все остальные панели смотрят на операции по отдельности. Кольцо
 * мошенников так не увидеть: поодиночке его участники безупречны —
 * сумма обычная, страна привычная, устройство для каждого своё
 * привычное. Увидеть их можно только вместе.
 *
 * Панель самостоятельна и молчит об ошибках по тем же причинам, что
 * `FeedbackPanel`, `DriftPanel` и `ShadowPanel`.
 */

import { useEffect, useState } from 'react'

import Tile from './Tile'
import { fetchClusters } from './api'
import { formatCount, formatMoney } from './format'
import type { ClusterReport, LinkStrength } from './types'
import { useLanguage } from './LanguageContext'

const STRENGTH_LABEL: Record<LinkStrength, string> = {
  DEVICE: 'общее устройство',
  SUBNET_ONLY: 'только подсеть',
}

export default function GraphPanel() {
  const { t } = useLanguage()
  const [report, setReport] = useState<ClusterReport | null>(null)

  useEffect(() => {
    let cancelled = false

    fetchClusters()
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

  const strong = report.clusters.length - report.weak_clusters

  return (
    <section className="panel">
      <h2>{t('graph.title')}</h2>
      <p className="hint">
        Десять «разных» клиентов, заходящих с одного устройства, поодиночке выглядят
        безупречно: сумма обычная, страна привычная, устройство для каждого из них своё
        привычное. Ни признаки, ни модель, ни политики такого не видят — они смотрят
        на операцию по отдельности. Здесь клиенты связываются общими устройствами
        и подсетями.
      </p>

      <div className="tiles">
        <Tile label={t('graph.scanned')} value={formatCount(report.scanned_transactions)} />
        <Tile label={t('graph.users')} value={formatCount(report.known_users)} />
        <Tile
          label={t('graph.deviceGroups')}
          value={String(strong)}
          note={t('graph.badLink')}
          tone={strong > 0 ? 'bad' : undefined}
        />
        <Tile
          label={t('graph.subnetGroups')}
          value={String(report.weak_clusters)}
          note={t('graph.weakLink')}
          tone={report.weak_clusters > 0 ? 'warn' : undefined}
        />
      </div>

      <p className="hint">
        <strong>Связи не равнозначны.</strong> Один физический телефон у трёх «разных»
        людей объясняется плохо. А общую подсеть /24 делят корпоративный NAT, оператор
        мобильной связи и один провайдер в одном доме — сама по себе она не значит почти
        ничего. Поэтому связи не смешиваются в одно число, и сводной «оценки
        подозрительности» здесь нет: её пришлось бы придумать, а вес взять с потолка.
      </p>

      {report.clusters.length === 0 ? (
        <p className="hint">
          Связанных клиентов не найдено. В сгенерированном датасете колец нет{' '}
          <strong>по построению</strong>: идентификаторы устройств там собираются как{' '}
          <code>dev_&#123;номер клиента&#125;_&#123;n&#125;</code>, то есть пространство имён
          разделено по клиентам и пересечься не может. Из 8 414 устройств датасета у более
          чем одного клиента ровно одно, общих подсетей — ноль.
          <br />
          <br />
          Чтобы увидеть, как это работает, отправьте в симуляторе две-три операции
          от разных <code>user_id</code> с одним <code>device_id</code> — группа появится здесь.
        </p>
      ) : (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>{t('graph.clients')}</th>
                <th>{t('graph.link')}</th>
                <th>{t('graph.through')}</th>
                <th>{t('common.operations')}</th>
                <th>{t('graph.flagged')}</th>
                <th>{t('common.amount')}</th>
                <th>{t('graph.maxRisk')}</th>
              </tr>
            </thead>
            <tbody>
              {report.clusters.map((cluster) => (
                <tr key={cluster.users.join('|')}>
                  <td>
                    <strong>{cluster.size}</strong>{' '}
                    <span className="muted">{cluster.users.join(', ')}</span>
                  </td>
                  <td className={cluster.strength === 'DEVICE' ? 'error-text' : 'warn-text'}>
                    {STRENGTH_LABEL[cluster.strength]}
                  </td>
                  <td>
                    {cluster.shared_devices.map((device) => (
                      <div key={device}>
                        <code>{device}</code>
                      </div>
                    ))}
                    {cluster.shared_subnets.map((subnet) => (
                      <div key={subnet} className="muted">
                        <code>{subnet}.0/24</code>
                      </div>
                    ))}
                  </td>
                  <td>{cluster.transactions}</td>
                  <td>{cluster.flagged}</td>
                  <td>{formatMoney(cluster.total_amount)}</td>
                  <td>{cluster.max_risk_score}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="hint">
        Граф ничего не меняет в решениях — это анализ, а не политика. Правило «клиент
        делит устройство с заблокированным» напрашивается, но оно уже влияло бы
        на клиентов и требует отдельного разговора.
      </p>
    </section>
  )
}
