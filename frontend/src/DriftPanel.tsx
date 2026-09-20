/**
 * Панель сдвига распределения на дашборде.
 *
 * Соседние панели отвечают на вопрос «правильно ли система решает».
 * Эта — на другой: «похож ли вход на то, что модель видела при обучении».
 * Дрейф ломает систему молча, поэтому смотреть на него нужно отдельно
 * от качества: метрики могут выглядеть прежними ещё долго после того,
 * как данные уехали.
 *
 * Панель самостоятельна и молчит об ошибках по тем же причинам, что
 * и `FeedbackPanel`: данные живые, вкладка размонтируется при
 * переключении, а сообщение о недоступном наблюдении поверх честно
 * загрузившейся аналитики выглядело бы как общая поломка.
 */

import { useEffect, useMemo, useState } from 'react'

import Tile from './Tile'
import { fetchDrift } from './api'
import { formatCount } from './format'
import {
  DRIFT_STATUS_LABEL,
  driftHeadline,
  driftTone,
  formatBinShare,
  formatPsi,
} from './drift'
import type { DriftReport, FeatureDrift } from './types'

export default function DriftPanel() {
  const [report, setReport] = useState<DriftReport | null>(null)
  const [selected, setSelected] = useState<string>('')

  useEffect(() => {
    let cancelled = false

    fetchDrift()
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

  // По умолчанию раскрыт самый разошедшийся: он уже первый в списке,
  // и именно ради него панель открывают.
  const shown: FeatureDrift | undefined = useMemo(() => {
    if (report === null || report.features.length === 0) return undefined
    return report.features.find((item) => item.name === selected) ?? report.features[0]
  }, [report, selected])

  if (report === null) return null

  const measurable = report.features.filter((item) => item.status !== 'NOT_MEASURABLE')

  return (
    <section className="panel">
      <h2>Сдвиг распределения</h2>
      <p className="hint">
        Модель обучена на датасете и с тех пор не менялась. Когда входные данные
        перестают походить на обучающие, её оценки становятся недостоверными —
        и сама она об этом не сообщит: ответ по-прежнему будет числом от 0 до 100.
        Здесь видно, насколько живой поток разошёлся с тем, на чём система строилась.
      </p>

      <div className="tiles">
        <Tile
          label="Общая картина"
          value={DRIFT_STATUS_LABEL[report.status]}
          note="по самому разошедшемуся признаку"
          tone={driftTone(report.status)}
        />
        <Tile
          label="Наблюдений с запуска"
          value={formatCount(report.observed_rows)}
          note={report.enough_data ? undefined : `минимум ${report.min_observations}`}
        />
        <Tile
          label="Признаков за границей"
          value={report.enough_data ? `${report.drifted} из ${measurable.length}` : '—'}
          note={report.enough_data ? 'PSI ≥ 0.1' : 'пока не считаем'}
          tone={report.enough_data && report.drifted > 0 ? 'warn' : undefined}
        />
        <Tile
          label="Эталон снят по"
          value={formatCount(report.baseline_rows)}
          note="строкам датасета"
        />
      </div>

      <p className="hint">
        {driftHeadline(report.observed_rows, report.min_observations, report.enough_data)}.{' '}
        Мера — Population Stability Index: до 0.1 стабильно, 0.1–0.25 умеренный сдвиг,
        дальше существенный. Это отраслевая договорённость скоринга, а не выведенный
        из наших данных порог — повод посмотреть, а не приговор.
      </p>

      {report.invalid_values > 0 && (
        <p className="hint">
          <strong className="error-text">
            Нечисловых значений признаков: {report.invalid_values}. Так быть не должно —
            похоже на поломку в расчёте признаков.
          </strong>
        </p>
      )}

      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>Признак</th>
              <th>Что означает</th>
              <th>PSI</th>
              <th>Состояние</th>
            </tr>
          </thead>
          <tbody>
            {report.features.map((feature) => {
              const tone = driftTone(feature.status)
              return (
                <tr
                  key={feature.name}
                  className={feature.name === shown?.name ? 'row-selected' : undefined}
                  onClick={() => setSelected(feature.name)}
                >
                  <td>
                    <code>{feature.name}</code>
                  </td>
                  <td className="muted">{feature.description}</td>
                  <td>{formatPsi(feature.psi)}</td>
                  <td className={tone === 'bad' ? 'error-text' : tone === 'warn' ? 'warn-text' : ''}>
                    {DRIFT_STATUS_LABEL[feature.status]}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {shown && <Comparison feature={shown} />}
    </section>
  )
}

/**
 * Обучающее распределение против живого, корзина за корзиной.
 *
 * Само число PSI говорит «разошлось», но не говорит «как». Здесь видно
 * направление: ушёл ли поток в крупные суммы, в ночные часы или в новые
 * устройства. Без этого по одному числу нечего решать.
 */
function Comparison({ feature }: { feature: FeatureDrift }) {
  const peak = Math.max(...feature.expected, ...feature.observed, 0.0001)

  return (
    <>
      <h3>
        <code>{feature.name}</code> — как разложился поток
      </h3>
      <p className="hint">{feature.description}. Нажмите строку выше, чтобы посмотреть другой признак.</p>

      <div className="bins">
        {feature.labels.map((label, index) => {
          const expected = feature.expected[index] ?? 0
          const observed = feature.observed[index] ?? 0
          return (
            <div
              className="bin"
              key={label}
              // Подсказка на всю колонку, а не на каждый столбик:
              // сравнивают два числа, а не смотрят одно.
              title={
                `${label}
` +
                `обучающее: ${formatBinShare(expected)}
` +
                `сейчас: ${formatBinShare(observed)}`
              }
            >
              <div className="bin-bars">
                <span className="bin-bar expected" style={{ height: `${(expected / peak) * 100}%` }} />
                <span className="bin-bar observed" style={{ height: `${(observed / peak) * 100}%` }} />
              </div>
              <span className="bin-label">{label}</span>
              <span className="bin-share">{formatBinShare(observed)}</span>
            </div>
          )
        })}
      </div>

      <p className="hint">
        <span className="legend-swatch expected" /> обучающая выборка{'   '}
        <span className="legend-swatch observed" /> живой поток
      </p>
    </>
  )
}
