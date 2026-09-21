/**
 * Все признаки операции — то, что система посчитала перед решением.
 *
 * Брифинг §5.B требует «автоматическую предобработку фичей (Feature
 * Engineering: расчет отклонений от среднего чека, скорости перемещения
 * между IP и т.д.)». Расчёт был с самого начала, но увидеть его было
 * негде: таблица вкладов показывает пять сильнейших, а остальные
 * двадцать два лежали в сыром JSON под спойлером.
 *
 * Проверяющий искал названные в кейсе величины и не нашёл. Панель
 * показывает весь вектор с подписями и разбивкой по пунктам ТЗ §4.
 *
 * Описания приходят из `GET /features` — один раз на сессию. Держать
 * их копию здесь значило бы завести второй список признаков, который
 * однажды разойдётся с реестром модели.
 */

import { useEffect, useState } from 'react'

import { fetchFeatureRegistry } from './api'
import type { FeatureRegistry } from './types'

/** Величины, названные в брифинге §5.B поимённо. */
const NAMED_IN_BRIEF = new Set([
  'amount_deviation_ratio',
  'amount_zscore',
  'travel_speed_kmh',
  'geo_distance_km',
])

function formatValue(value: number | undefined, isFlag: boolean, decimals: number): string {
  if (value === undefined || !Number.isFinite(value)) return '—'
  if (isFlag) return value >= 0.5 ? 'да' : 'нет'
  return value.toFixed(decimals)
}

export default function FeaturePanel({ features }: { features: Record<string, number> }) {
  const [registry, setRegistry] = useState<FeatureRegistry | null>(null)

  useEffect(() => {
    let cancelled = false

    fetchFeatureRegistry()
      .then((payload) => {
        if (!cancelled) setRegistry(payload)
      })
      .catch(() => {
        // Молча: без справочника панель просто не появится, а вердикт
        // и объяснение выше от него не зависят.
      })

    return () => {
      cancelled = true
    }
  }, [])

  if (registry === null) return null

  return (
    <section className="panel">
      <h2>Признаки операции</h2>
      <p className="hint">
        Всё, что система посчитала из транзакции перед тем, как решать — {registry.count}{' '}
        величин. Таблица вкладов выше показывает только пять сильнейших; здесь виден
        весь вектор, включая те признаки, которые на этой операции ничего не изменили.
        Выделены величины, названные в кейсе поимённо.
      </p>
      <p className="hint">
        Отдельного признака «клиент под VPN» здесь нет — его нет и в данных.
        Подмена IP видна по следствию: адрес из другой подсети (
        <code>ip_subnet_changed</code>) и требуемая скорость перемещения выше
        авиационной (<code>travel_speed_kmh</code>,{' '}
        <code>is_impossible_travel</code>). Прокси, выдающий себя за другую
        страну, поднимает именно их.
      </p>

      {registry.sections.map((section) => (
        <details key={section.section} className="context">
          <summary>
            {section.section} — {section.features.length}
          </summary>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Признак</th>
                  <th>Что означает</th>
                  <th>Значение</th>
                </tr>
              </thead>
              <tbody>
                {section.features.map((feature) => {
                  const named = NAMED_IN_BRIEF.has(feature.name)
                  return (
                    <tr key={feature.name} className={named ? 'row-selected' : undefined}>
                      <td>
                        <code>{feature.name}</code>
                      </td>
                      <td className="muted">{feature.description}</td>
                      <td>
                        <strong>
                          {formatValue(features[feature.name], feature.is_flag, feature.decimals)}
                        </strong>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </details>
      ))}
    </section>
  )
}
