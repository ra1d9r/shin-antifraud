/**
 * Карта аномалий (брифинг §6).
 *
 * Брифинг §6: «Интерактивная карта аномалий: визуализация геолокаций
 * подозрительных попыток входа/платежей».
 *
 * ## Почему без картографической библиотеки
 *
 * Leaflet или MapLibre притащили бы зависимость и, что важнее, запросы
 * к чужому серверу тайлов: карта переставала бы рисоваться без интернета
 * и подглядывала бы за тем, кто её открыл. Здесь тридцать одна точка,
 * и всё, что для них нужно, — линейная проекция и круг.
 *
 * Подложки с очертаниями материков нет намеренно. Нарисовать её от руки
 * значило бы поставить береговые линии наугад, а карта, где Каспий не
 * там, хуже честной сетки координат. Вместо неё — градусная сетка
 * с подписями: проекция видна, положение точки проверяемо.
 *
 * ## Что показывает
 *
 * Размер кружка — объём операций, цвет — доля фрода, обводка — страна
 * из списка повышенного риска. Наведение показывает точные числа:
 * на карте видно, где смотреть, а не сколько именно.
 */

import { useMemo, useState } from 'react'

import { useLanguage } from './LanguageContext'
import { useFormat } from './useFormat'
import { labelAnchor, project, radius, tone } from './map'
import type { AnalyticsOverview, CountryStat } from './types'

const BOX = { width: 720, height: 360 }

/** Шаг градусной сетки. Тридцать градусов — достаточно, чтобы
 *  сориентироваться, и достаточно редко, чтобы не рябило. */
const GRID_STEP = 30

export default function MapPanel({ data }: { data: AnalyticsOverview }) {
  const { t } = useLanguage()
  const [hovered, setHovered] = useState<CountryStat | null>(null)

  // Артефакт мог быть выгружен до появления карты: он лежит файлом
  // на диске и живёт дольше кода. Без этой подстраховки падала бы
  // не карта, а весь дашборд вместе с ней.
  const countries = useMemo(() => data.countries ?? [], [data.countries])
  const maxRows = useMemo(
    () => countries.reduce((most, item) => Math.max(most, item.rows), 0),
    [countries],
  )

  if (countries.length === 0) return null

  const meridians = []
  for (let longitude = -180; longitude <= 180; longitude += GRID_STEP) {
    const { x } = project(0, longitude, BOX)
    meridians.push({ longitude, x })
  }
  const parallels = []
  for (let latitude = -60; latitude <= 60; latitude += GRID_STEP) {
    const { y } = project(latitude, 0, BOX)
    parallels.push({ latitude, y })
  }

  const shown = hovered ?? mostSuspicious(countries)

  return (
    <section className="panel">
      <h2>{t('map.title')}</h2>
      <p className="hint">
        Где система видит операции и где среди них концентрируется фрод. Размер
        кружка — объём операций, цвет — доля мошеннических среди них, кольцо —
        страна из списка повышенного риска.
      </p>
      <p className="hint">
        Подложки с материками нет намеренно: нарисовать береговые линии от руки
        значило бы поставить их наугад, а карта, где Каспий не на месте, хуже
        честной сетки координат. Точки стоят по тем же координатам, по которым
        система считает скорость перемещения между операциями.
      </p>

      <div className="table-scroll">
        <svg
          viewBox={`0 0 ${BOX.width} ${BOX.height}`}
          className="anomaly-map"
          role="img"
          aria-label={t('map.title')}
        >
          <rect x={0} y={0} width={BOX.width} height={BOX.height} className="map-bg" />

          {meridians.map(({ longitude, x }) => (
            <g key={`m${longitude}`}>
              <line x1={x} y1={0} x2={x} y2={BOX.height} className="map-grid" />
              <text x={x + 3} y={BOX.height - 5} className="map-axis">
                {longitude}°
              </text>
            </g>
          ))}
          {parallels.map(({ latitude, y }) => (
            <g key={`p${latitude}`}>
              <line x1={0} y1={y} x2={BOX.width} y2={y} className="map-grid" />
              <text x={4} y={y - 4} className="map-axis">
                {latitude}°
              </text>
            </g>
          ))}

          {countries.map((country) => {
            const { x, y } = project(country.latitude, country.longitude, BOX)
            const r = radius(country.rows, maxRows)
            const { dx, anchor } = labelAnchor(x, BOX)
            return (
              <g
                key={country.country}
                onMouseEnter={() => setHovered(country)}
                onMouseLeave={() => setHovered(null)}
                className="map-point"
              >
                <circle
                  cx={x}
                  cy={y}
                  r={r}
                  className={`map-dot ${tone(country.fraud_share)}${
                    country.high_risk ? ' high-risk' : ''
                  }`}
                />
                <text x={x + dx} y={y + 4} textAnchor={anchor} className="map-label">
                  {country.country}
                </text>
              </g>
            )
          })}
        </svg>
      </div>

      <div className="map-legend">
        <span>
          <i className="map-dot low" /> {t('map.lowFraud')}
        </span>
        <span>
          <i className="map-dot medium" /> {t('map.someFraud')}
        </span>
        <span>
          <i className="map-dot high" /> {t('map.mostlyFraud')}
        </span>
        <span>
          <i className="map-dot low high-risk" /> {t('map.highRiskCountry')}
        </span>
      </div>

      {shown && (
        <div className="tiles">
          <Readout country={shown} hovered={hovered !== null} />
        </div>
      )}
    </section>
  )
}

/**
 * Что показывать, пока курсор никуда не наведён.
 *
 * Пустая панель заставляла бы искать, куда навести. Показывается страна
 * с самой высокой долей фрода среди заметных по объёму — то есть ровно
 * то, ради чего аналитик открыл карту.
 */
function mostSuspicious(countries: CountryStat[]): CountryStat | null {
  const notable = countries.filter((item) => item.rows >= 20)
  const pool = notable.length > 0 ? notable : countries
  return pool.reduce<CountryStat | null>(
    (worst, item) => (worst === null || item.fraud_share > worst.fraud_share ? item : worst),
    null,
  )
}

function Readout({ country, hovered }: { country: CountryStat; hovered: boolean }) {
  const { t } = useLanguage()
  const { formatCount } = useFormat()
  const share = (value: number) => `${(value * 100).toFixed(1)} %`

  return (
    <>
      <div className="tile">
        <span className="tile-label">{hovered ? t('map.hovered') : t('map.worst')}</span>
        <strong className="tile-value">{country.country}</strong>
        <span className="tile-note">
          {country.high_risk ? t('map.highRiskCountry') : t('map.ordinaryCountry')}
        </span>
      </div>
      <div className="tile">
        <span className="tile-label">{t('map.operations')}</span>
        <strong className="tile-value">{formatCount(country.rows)}</strong>
      </div>
      <div className="tile">
        <span className="tile-label">{t('map.fraudShare')}</span>
        <strong className="tile-value">{share(country.fraud_share)}</strong>
        <span className="tile-note">{formatCount(country.fraud_rows)}</span>
      </div>
      <div className="tile">
        <span className="tile-label">{t('map.flaggedShare')}</span>
        <strong className="tile-value">{share(country.flagged_share)}</strong>
        <span className="tile-note">{formatCount(country.flagged)}</span>
      </div>
    </>
  )
}
