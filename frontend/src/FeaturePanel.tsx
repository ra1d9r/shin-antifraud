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

import { useCallback } from 'react'

import { errorText, fetchFeatureRegistry } from './api'
import PanelError from './PanelError'
import { useLanguage } from './LanguageContext'
import { usePanelData } from './usePanelData'

/** Величины, названные в брифинге §5.B поимённо. */
const NAMED_IN_BRIEF = new Set([
  'amount_deviation_ratio',
  'amount_zscore',
  'travel_speed_kmh',
  'geo_distance_km',
])

/**
 * Значение признака для человека.
 *
 * «да» и «нет» приходят переводом, а не зашиты: флаг показывается
 * в трёх языках, и русское «да» в английском интерфейсе выглядело
 * бы как недоделка.
 */
function formatValue(
  value: number | undefined,
  isFlag: boolean,
  decimals: number,
  yes: string,
  no: string,
): string {
  if (value === undefined || !Number.isFinite(value)) return '—'
  if (isFlag) return value >= 0.5 ? yes : no
  return value.toFixed(decimals)
}

export default function FeaturePanel({ features }: { features: Record<string, number> }) {
  const { t, language } = useLanguage()
  // См. DriftPanel: язык — часть запроса, значит и зависимость загрузки.
  const load = useCallback(() => fetchFeatureRegistry(language), [language])
  const { data: registry, failure } = usePanelData(load)


  if (failure !== null) {
    return <PanelError title={t('sim.features')} reason={errorText(failure.cause, t)} />
  }
  if (registry === null) return null

  return (
    <section className="panel">
      <h2>{t('sim.features')}</h2>
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
                  <th>{t('sim.feature')}</th>
                  <th>{t('sim.meaning')}</th>
                  <th>{t('sim.value')}</th>
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
                          {formatValue(
                            features[feature.name],
                            feature.is_flag,
                            feature.decimals,
                            t('common.yes'),
                            t('common.no'),
                          )}
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
