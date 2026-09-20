/**
 * Дашборд аналитика (брифинг §5.A и чек-лист §11).
 *
 * Показывает то, чего не видно по одной транзакции: сколько фрода система
 * ловит на всём потоке, скольких добросовестных клиентов при этом задевает
 * и во что это обходится. Данные приходят готовыми из `/analytics/overview` —
 * ни одна величина здесь не считается заново, иначе цифры на экране начали
 * бы расходиться с теми, что печатает `evaluate_risk_engine.py`.
 *
 * Единственное исключение — выборка точки кривой по положению ползунка:
 * это не расчёт, а поиск уже посчитанного значения в массиве.
 */

import { useMemo, useState } from 'react'
import type { MouseEvent } from 'react'

import DriftPanel from './DriftPanel'
import { readoutX, thresholdAtPointer } from './chart'
import { formatCount as formatNumber, formatMoney } from './format'
import FeedbackPanel from './FeedbackPanel'
import GraphPanel from './GraphPanel'
import ShadowPanel from './ShadowPanel'
import Tile from './Tile'
import type { AnalyticsOverview, CurvePoint, ModelInfo } from './types'

const DECISION_CLASS: Record<string, string> = {
  APPROVE: 'approve',
  CHALLENGE: 'challenge',
  BLOCK: 'block',
}

function formatShare(value: number): string {
  // Доля от нулевого знаменателя — не ошибка данных, а вырожденный датасет:
  // например, выборка без единого фрода. Backend такие места закрывает
  // `max(1, ...)`, здесь показываем прочерк вместо «NaN %».
  if (!Number.isFinite(value)) return '—'
  return `${(value * 100).toFixed(1)} %`
}

export default function Dashboard({
  data,
  model,
  modelError,
}: {
  data: AnalyticsOverview
  model: ModelInfo | null
  modelError?: string
}) {
  // Ползунок стартует с текущего порога системы: сравнивать удобнее,
  // когда точка отсчёта — то, что работает прямо сейчас.
  const [threshold, setThreshold] = useState(data.thresholds.approve_max)

  const point = useMemo(
    () => data.curve.find((item) => item.threshold === threshold) ?? data.curve[0],
    [data.curve, threshold],
  )
  const current = useMemo(
    () =>
      data.curve.find((item) => item.threshold === data.thresholds.approve_max) ??
      data.curve[0],
    [data.curve, data.thresholds.approve_max],
  )

  return (
    <>
      {data.stale && (
        <section className="panel alert">
          <h2>Аналитика устарела</h2>
          <p>
            <strong>{data.stale_reason}</strong>
          </p>
          <p className="hint">
            Числа ниже посчитаны на другой модели и описывают прошлое состояние
            системы. Симулятор при этом работает на актуальной модели — значения
            на двух вкладках могут не сойтись.
          </p>
        </section>
      )}

      <section className="panel">
        <h2>Поток транзакций</h2>
        <div className="tiles">
          <Tile label="Всего транзакций" value={formatNumber(data.rows)} />
          <Tile
            label="Из них фрод"
            value={formatNumber(data.fraud_rows)}
            note={formatShare(data.fraud_rate)}
          />
          <Tile
            label="Фрод остановлен"
            value={formatShare(data.fraud_stopped_share)}
            note={`${formatNumber(data.fraud_stopped)} из ${formatNumber(data.fraud_rows)}`}
            tone="good"
          />
          <Tile
            label="Фрод пропущен"
            value={formatNumber(data.fraud_missed)}
            note="ушли с решением APPROVE"
            tone={data.fraud_missed > 0 ? 'bad' : 'good'}
          />
          <Tile
            label="Трение (False Positive Rate)"
            value={formatShare(data.friction_share)}
            note={`${formatNumber(data.friction)} честных клиентов побеспокоено`}
            tone="warn"
          />
          <Tile
            label="Оборот в выборке"
            value={formatMoney(data.total_amount)}
            note="сумма всех транзакций"
          />
        </div>
        <p className="hint">
          Аналитика выгружена {new Date(data.generated_at).toLocaleString('ru-RU')}. Считается
          по датасету с известной разметкой — поэтому здесь, в отличие от `/stats`, виден
          пропущенный фрод.
        </p>
      </section>

      <section className="panel">
        <h2>Fraud Loss против Customer Inconvenience</h2>
        <p className="hint">
          Один рычаг: всё, что выше порога, уходит на проверку. Слева система почти никого
          не трогает и пропускает фрод, справа ловит всё и мешает живым клиентам. Ищем дно
          суммарной кривой.
        </p>

        <TradeOffChart
          curve={data.curve}
          selected={threshold}
          currentThreshold={data.thresholds.approve_max}
          optimalThreshold={data.optimal_threshold}
        />

        <div className="slider">
          <label>
            <span>Порог чувствительности: {threshold}</span>
            <input
              type="range"
              min={0}
              max={100}
              step={1}
              value={threshold}
              onChange={(event) => setThreshold(Number(event.target.value))}
            />
          </label>
          <div className="slider-marks">
            <button type="button" className="chip" onClick={() => setThreshold(data.thresholds.approve_max)}>
              текущий ({data.thresholds.approve_max})
            </button>
            <button type="button" className="chip" onClick={() => setThreshold(data.optimal_threshold)}>
              дешевле всего ({data.optimal_threshold})
            </button>
          </div>
        </div>

        <div className="tiles">
          <Tile label="Пропущено фрода" value={formatNumber(point.fraud_missed)} tone="bad" />
          <Tile label="Задето честных" value={formatNumber(point.friction)} tone="warn" />
          <Tile label="Потери от фрода" value={formatMoney(point.fraud_loss)} />
          <Tile label="Стоимость проверок" value={formatMoney(point.friction_cost)} />
          <Tile
            label="Итого"
            value={formatMoney(point.total_cost)}
            note={costNote(point, current)}
            tone={point.total_cost <= current.total_cost ? 'good' : 'bad'}
          />
        </div>
      </section>

      <section className="panel">
        <h2>Решения системы</h2>
        <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>Решение</th>
              <th>Легальные</th>
              <th>Фрод</th>
            </tr>
          </thead>
          <tbody>
            {data.decisions.map((row) => (
              <tr key={row.decision}>
                <td>
                  <span className={`decision ${DECISION_CLASS[row.decision] ?? ''}`}>
                    {row.decision}
                  </span>
                </td>
                <td>
                  {formatNumber(row.legit)}{' '}
                  <span className="muted">({formatShare(row.legit / data.legit_rows)})</span>
                </td>
                <td>
                  {formatNumber(row.fraud)}{' '}
                  <span className="muted">({formatShare(row.fraud / data.fraud_rows)})</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </section>

      {data.rules.length > 0 && (
        <section className="panel">
          <h2>Политики поверх модели</h2>
          <p className="hint">
            Предельный вклад — что политика меняет <strong>сверх</strong> решения модели.
            Срабатывание на транзакции, которую модель и так остановила, пользы не приносит,
            а трение у честного клиента добавляет всегда.
          </p>
          <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>Политика</th>
                <th>Мин. балл</th>
                <th>Точность</th>
                <th>+ поймано</th>
                <th>+ трение</th>
                <th>Цена одного фрода</th>
              </tr>
            </thead>
            <tbody>
              {data.rules.map((rule) => (
                <tr key={rule.key}>
                  <td title={rule.title}>
                    <code>{rule.key}</code>
                  </td>
                  <td>{rule.min_score}</td>
                  <td>{formatShare(rule.precision)}</td>
                  <td>{rule.gained_fraud}</td>
                  <td>{rule.added_friction}</td>
                  <td className={rule.checks_per_fraud === null ? 'down-text' : ''}>
                    {rule.checks_per_fraud === null
                      ? 'ноль пользы'
                      : `${Math.round(rule.checks_per_fraud)} проверок`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>

          <div className="tiles">
            <Tile label="Стоимость: чистая модель" value={formatMoney(data.cost_without_rules)} />
            <Tile label="Стоимость: модель + политики" value={formatMoney(data.cost_with_rules)} />
            <Tile
              label={data.rules_cost_delta < 0 ? 'Политики окупаются' : 'Политики дороже, чем экономят'}
              value={`${data.rules_cost_delta > 0 ? '+' : ''}${formatMoney(data.rules_cost_delta)}`}
              tone={data.rules_cost_delta < 0 ? 'good' : 'bad'}
              note={`оценка поднята политиками у ${formatNumber(data.raised_by_rules)} операций`}
            />
          </div>
        </section>
      )}

      <FeedbackPanel />

      <GraphPanel />

      <ShadowPanel />

      <DriftPanel />

      {!model?.loaded && modelError && (
        <section className="panel alert">
          <h2>Сведения о модели не получены</h2>
          <p>
            <strong>{modelError}</strong>
          </p>
          <p className="hint">
            Метрики качества показать не удалось. Остальные числа на этой странице
            взяты из выгруженного отчёта и от этого запроса не зависят.
          </p>
        </section>
      )}

      {model?.loaded && (
        <section className="panel">
          <h2>Модель</h2>
          <div className="tiles">
            <Tile label="Алгоритм" value={model.algorithm ?? '—'} note={model.calibration_method ?? ''} />
            <Tile label="ROC-AUC" value={model.roc_auc?.toFixed(4) ?? '—'} />
            <Tile label="PR-AUC" value={model.pr_auc?.toFixed(4) ?? '—'} />
            <Tile label="Precision" value={model.precision?.toFixed(4) ?? '—'} />
            <Tile label="Recall" value={model.recall?.toFixed(4) ?? '—'} />
            <Tile label="F1" value={model.f1?.toFixed(4) ?? '—'} />
          </div>
          <p className="hint">
            Метрики на отложенной выборке при пороге 0.50. Признаков: {model.feature_count ?? '—'}.
          </p>
        </section>
      )}
    </>
  )
}

function costNote(point: CurvePoint, current: CurvePoint): string {
  const delta = point.total_cost - current.total_cost
  if (Math.round(delta) === 0) return 'как сейчас'
  return delta < 0
    ? `на ${formatMoney(-delta)} дешевле текущего`
    : `на ${formatMoney(delta)} дороже текущего`
}

/**
 * График компромисса.
 *
 * Рисуется вручную в SVG, без библиотеки графиков: три ломаных, три
 * засечки и подсказка под курсором не стоят двухсот килобайт зависимости,
 * а в бандле тестового интерфейса это заметная доля.
 *
 * Наведение показывает числа: по картинке видно форму, но решение
 * принимают по величинам, а снимать их с оси на глаз — гадание.
 * Клавиатурный путь к тем же числам уже есть — ползунок под графиком,
 * поэтому подсказка мышью ничего не запирает.
 */
function TradeOffChart({
  curve,
  selected,
  currentThreshold,
  optimalThreshold,
}: {
  curve: CurvePoint[]
  selected: number
  currentThreshold: number
  optimalThreshold: number
}) {
  const width = 720
  const height = 260
  const padding = { top: 16, right: 16, bottom: 28, left: 56 }

  const maxCost = Math.max(...curve.map((point) => point.total_cost), 1)

  const x = (threshold: number) =>
    padding.left + (threshold / 100) * (width - padding.left - padding.right)
  const y = (cost: number) =>
    height - padding.bottom - (cost / maxCost) * (height - padding.top - padding.bottom)

  const line = (pick: (point: CurvePoint) => number) =>
    curve.map((point) => `${x(point.threshold).toFixed(1)},${y(pick(point)).toFixed(1)}`).join(' ')

  const marks = [
    { at: currentThreshold, color: 'var(--accent)', label: 'сейчас' },
    { at: optimalThreshold, color: 'var(--approve)', label: 'оптимум' },
    { at: selected, color: 'var(--text)', label: '' },
  ]

  // Точка под курсором. null — курсор вне графика, и подсказки нет.
  const [hovered, setHovered] = useState<number | null>(null)

  const track = (event: MouseEvent<SVGRectElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    setHovered(thresholdAtPointer(event.clientX - box.left, box.width))
  }

  const point = hovered === null ? null : (curve.find((item) => item.threshold === hovered) ?? null)

  return (
    <svg className="chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Кривая компромисса">
      {[0, 0.25, 0.5, 0.75, 1].map((fraction) => (
        <g key={fraction}>
          <line
            x1={padding.left}
            x2={width - padding.right}
            y1={y(maxCost * fraction)}
            y2={y(maxCost * fraction)}
            className="chart-grid"
          />
          <text x={padding.left - 8} y={y(maxCost * fraction) + 4} className="chart-tick" textAnchor="end">
            {formatMoney(maxCost * fraction)}
          </text>
        </g>
      ))}

      {[0, 25, 50, 75, 100].map((tick) => (
        <text key={tick} x={x(tick)} y={height - 8} className="chart-tick" textAnchor="middle">
          {tick}
        </text>
      ))}

      {marks.map((mark) => (
        <line
          key={`${mark.label}-${mark.at}`}
          x1={x(mark.at)}
          x2={x(mark.at)}
          y1={padding.top}
          y2={height - padding.bottom}
          stroke={mark.color}
          strokeDasharray="4 4"
          strokeWidth={1}
        />
      ))}

      <polyline className="chart-line fraud" points={line((point) => point.fraud_loss)} />
      <polyline className="chart-line friction" points={line((point) => point.friction_cost)} />
      <polyline className="chart-line total" points={line((point) => point.total_cost)} />

      <g className="chart-legend">
        <text x={padding.left + 8} y={padding.top + 12} className="legend fraud">
          — потери от фрода
        </text>
        <text x={padding.left + 160} y={padding.top + 12} className="legend friction">
          — стоимость проверок
        </text>
        <text x={padding.left + 330} y={padding.top + 12} className="legend total">
          — итого
        </text>
      </g>

      {point && <Readout point={point} x={x(point.threshold)} y={y} width={width} />}

      {/* Прозрачная накладка ловит мышь по всей площади: попадать
          курсором в саму ломаную толщиной в полтора пикселя — мучение. */}
      <rect
        x={padding.left}
        y={padding.top}
        width={width - padding.left - padding.right}
        height={height - padding.top - padding.bottom}
        fill="transparent"
        onMouseMove={track}
        onMouseLeave={() => setHovered(null)}
      />
    </svg>
  )
}

/**
 * Числа под курсором.
 *
 * Подсказка переезжает на другую сторону засечки у правого края: иначе
 * на порогах под сотню она уходила бы за границу картинки.
 */
function Readout({
  point,
  x,
  y,
  width,
}: {
  point: CurvePoint
  x: number
  y: (cost: number) => number
  width: number
}) {
  const boxWidth = 186
  const boxHeight = 74
  const boxX = readoutX(x, boxWidth, width)

  const rows: [string, string, string][] = [
    ['потери от фрода', formatMoney(point.fraud_loss), 'fraud'],
    ['стоимость проверок', formatMoney(point.friction_cost), 'friction'],
    ['итого', formatMoney(point.total_cost), 'total'],
  ]

  return (
    <g className="chart-readout" pointerEvents="none">
      <line x1={x} x2={x} y1={16} y2={y(0)} className="readout-rule" />
      {rows.map(([, , tone], index) => (
        <circle key={tone} cx={x} cy={y([point.fraud_loss, point.friction_cost, point.total_cost][index])} r={3} className={`readout-dot ${tone}`} />
      ))}

      <rect x={boxX} y={20} width={boxWidth} height={boxHeight} rx={5} className="readout-box" />
      <text x={boxX + 10} y={36} className="readout-title">
        порог {point.threshold}
      </text>
      {rows.map(([label, value, tone], index) => (
        <text key={label} x={boxX + 10} y={51 + index * 14} className={`readout-row ${tone}`}>
          {label}: {value}
        </text>
      ))}
    </g>
  )
}
