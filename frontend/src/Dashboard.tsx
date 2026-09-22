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

import AdaptivePanel from './AdaptivePanel'
import DriftPanel from './DriftPanel'
import { readoutX, thresholdAtPointer } from './chart'
import { fetchCostWeights } from './api'
import { formatMeasuredShare } from './feedback'
import { useLanguage } from './LanguageContext'
import type { Translator } from './i18n'
import { useFormat } from './useFormat'
import { usePanelData } from './usePanelData'
import FeedbackPanel from './FeedbackPanel'
import GraphPanel from './GraphPanel'
import MapPanel from './MapPanel'
import ShadowPanel from './ShadowPanel'
import StreamPanel from './StreamPanel'
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

/**
 * Приписка «а без политик было бы столько» к обязательным метрикам §5.A.
 *
 * Сами по себе «спасённый бюджет» и «процент ложных срабатываний» не
 * показывают, чья это заслуга и чья цена: политики поверх модели двигают
 * обе, причём в разные стороны. Без сравнения FPR 2.1 % читается как
 * неточность модели, хотя у неё самой он 0.1 %.
 *
 * При выключенных политиках приписки нет: числа совпали бы, и строка
 * повторяла бы саму себя.
 */
function withoutRules(data: AnalyticsOverview, value: number, label: string): string {
  if (!data.rules_enabled) return ''
  return ` · ${label} ${formatShare(value)}`
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
  const { t } = useLanguage()
  const { formatCount: formatNumber, formatMoney, formatDateTime } = useFormat()
  // Ползунок стартует с текущего порога системы: сравнивать удобнее,
  // когда точка отсчёта — то, что работает прямо сейчас.
  const [threshold, setThreshold] = useState(data.thresholds.approve_max)
  // Счётчик прогонов: меняется — панели наблюдения перечитывают состояние.
  const [streamRuns, setStreamRuns] = useState(0)

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
          <h2>{t('error.staleAnalytics')}</h2>
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
        <h2>{t('dash.flow')}</h2>
        <div className="tiles">
          <Tile label={t('dash.total')} value={formatNumber(data.rows)} />
          <Tile
            label={t('dash.fraudRows')}
            value={formatNumber(data.fraud_rows)}
            note={formatShare(data.fraud_rate)}
          />
          <Tile
            label={t('dash.fraudStopped')}
            value={formatShare(data.fraud_stopped_share)}
            note={
              `${formatNumber(data.fraud_stopped)} ${t('dash.ofAtRisk')} ${formatNumber(data.fraud_rows)}` +
              withoutRules(data, data.fraud_stopped_share_without_rules, t('dash.withoutPolicies'))
            }
            tone="good"
          />
          <Tile
            label={t('dash.fraudSaved')}
            value={formatMoney(data.fraud_loss_prevented)}
            note={`${t('dash.ofAtRisk')} ${formatMoney(data.fraud_loss_exposure)} ${t('dash.atRisk')}`}
            tone="good"
          />
          <Tile
            label={t('dash.fraudMissed')}
            value={formatNumber(data.fraud_missed)}
            note={`${t('dash.approvedFor')} ${formatMoney(data.fraud_loss_incurred)}`}
            tone={data.fraud_missed > 0 ? 'bad' : 'good'}
          />
          <Tile
            label={t('dash.fpr')}
            value={formatShare(data.friction_share)}
            note={
              `${formatNumber(data.friction)} ${t('dash.botheredInVain')}` +
              withoutRules(data, data.friction_share_without_rules, t('dash.withoutPolicies'))
            }
            tone="warn"
          />
          <Tile
            label={t('dash.turnover')}
            value={formatMoney(data.total_amount)}
            note={t('dash.allTransactions')}
          />
        </div>
        <p className="hint">
          <strong>Спасённый бюджет</strong> — деньги фрода, которые не ушли: сумма
          операций, остановленных блокировкой или отправленных на проверку, по той же
          формуле, по которой считается стоимость на кривой ниже. Проверка считается
          остановкой: это допущение модели стоимости, а не факт — клиент может
          подтвердить операцию, и тогда фрод пройдёт.
        </p>
        <p className="hint">
          <strong>Трение</strong> и есть ложные срабатывания: добросовестные клиенты,
          которых система задержала. Здесь это видно в процентах, а в деньгах — на кривой
          ниже, потому что стоимость проверки и стоимость блокировки разные.
        </p>
        <p className="hint">
          Аналитика выгружена {formatDateTime(data.generated_at)}. Считается
          по датасету с известной разметкой — поэтому здесь, в отличие от `/stats`, виден
          пропущенный фрод.
        </p>
      </section>

      <section className="panel">
        <h2>{t('dash.tradeOff')}</h2>
        <p className="hint">
          Один рычаг: всё, что выше порога, уходит на проверку. Слева система почти никого
          не трогает и пропускает фрод, справа ловит всё и мешает живым клиентам. Ищем дно
          суммарной кривой.
        </p>

        <CostMetricLine />

        {/* Два графика в одной панели: у них общая ось порога, и смотреть
            их порознь бессмысленно. Но раньше их разделяли восемь пикселей
            и ничего больше — читались они как один график с пятью линиями.
            Теперь у каждого своя подпись и своя рамка. */}
        <figure className="chart-block">
          <figcaption className="chart-caption">{t('curve.costTitle')}</figcaption>
          <TradeOffChart
            curve={data.curve}
            selected={threshold}
            currentThreshold={data.thresholds.approve_max}
            optimalThreshold={data.optimal_threshold}
          />
        </figure>

        <figure className="chart-block">
          <figcaption className="chart-caption">{t('curve.qualityTitle')}</figcaption>
          <QualityChart
            curve={data.curve}
            selected={threshold}
            currentThreshold={data.thresholds.approve_max}
            optimalThreshold={data.optimal_threshold}
          />
        </figure>

        <div className="slider">
          <label>
            <span>
              {t('dash.threshold')}: {threshold}
            </span>
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
              {t('dash.current')} ({data.thresholds.approve_max})
            </button>
            <button type="button" className="chip" onClick={() => setThreshold(data.optimal_threshold)}>
              {t('cost.cheapest', { score: data.optimal_threshold })}
            </button>
          </div>
        </div>

        <div className="tiles">
          <Tile
            label={t('curve.fraudMissed')}
            value={formatNumber(point.fraud_missed)}
            tone="bad"
          />
          <Tile
            label={t('curve.frictionHit')}
            value={formatNumber(point.friction)}
            tone="warn"
          />
          <Tile label={t('curve.fraudLoss')} value={formatMoney(point.fraud_loss)} />
          <Tile label={t('curve.checksCost')} value={formatMoney(point.friction_cost)} />
          <Tile
            label={t('curve.total')}
            value={formatMoney(point.total_cost)}
            note={costNote(point, current, formatMoney, t)}
            tone={point.total_cost <= current.total_cost ? 'good' : 'bad'}
          />
          <Tile
            label={t('curve.precision')}
            value={formatMeasuredShare(point.precision, t)}
            note={t('curve.precisionNote')}
          />
          <Tile
            label={t('curve.recall')}
            value={formatMeasuredShare(point.recall, t)}
            note={t('curve.recallNote')}
          />
        </div>

        <p className="hint">
          Точность и потери лежат в одной точке намеренно: это и есть компромисс,
          который требует кейс. Ведите ползунок влево — точность падает, потому что
          под проверку попадает всё больше честных клиентов; вправо — падает полнота,
          потому что фрод начинает проходить. Дешевле всего не там, где точность
          выше, и в этом вся сложность.
        </p>
      </section>

      <section className="panel">
        <h2>{t('dash.decisions')}</h2>
        <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>{t('common.decision')}</th>
              <th>{t('common.legit')}</th>
              <th>{t('common.fraud')}</th>
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
          <h2>{t('rules.title')}</h2>
          <p className="hint">
            Предельный вклад — что политика меняет <strong>сверх</strong> решения модели.
            Срабатывание на транзакции, которую модель и так остановила, пользы не приносит,
            а трение у честного клиента добавляет всегда.
          </p>
          {/* Числа подставляются в готовые формулировки, а падеж
              существительного от числа не зависит: «+1 901 побеспокоенных
              клиентов» согласуется неверно, а вести таблицу склонений
              ради двух строк не стоит. */}
          <p className="hint">
            Весь слой целиком: пойманного фрода{' '}
            <strong>+{formatNumber(data.rules_gained_fraud)}</strong>, побеспокоено честных
            клиентов <strong>+{formatNumber(data.rules_added_friction)}</strong>. Это
            разница по решениям целиком — сумма по столбцам таблицы получилась бы больше,
            потому что на одной операции срабатывает сразу несколько политик.
          </p>
          <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>{t('rules.policy')}</th>
                <th>{t('rules.minScore')}</th>
                <th>{t('rules.precision')}</th>
                <th>{t('rules.gained')}</th>
                <th>{t('rules.friction')}</th>
                <th>{t('rules.pricePerFraud')}</th>
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
                      ? t('rules.noUse')
                      : `${Math.round(rule.checks_per_fraud)} ${t('rules.checks')}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>

          <div className="tiles">
            <Tile label={t('rules.costPure')} value={formatMoney(data.cost_without_rules)} />
            <Tile label={t('rules.costWith')} value={formatMoney(data.cost_with_rules)} />
            <Tile
              label={data.rules_cost_delta < 0 ? t('rules.payOff') : t('rules.costMore')}
              value={`${data.rules_cost_delta > 0 ? '+' : ''}${formatMoney(data.rules_cost_delta)}`}
              tone={data.rules_cost_delta < 0 ? 'good' : 'bad'}
              note={t('dashboard.raisedByRules', { count: formatNumber(data.raised_by_rules) })}
            />
          </div>
        </section>
      )}

      <MapPanel data={data} />

      <AdaptivePanel />

      <StreamPanel onFinished={() => setStreamRuns((runs) => runs + 1)} />

      {/* Ключ, а не проп обновления: панели забирают своё состояние при
          монтировании, и после прогона показывали бы картину, снятую
          до него. Смена ключа перемонтирует их — без правки каждой. */}
      <FeedbackPanel key={`feedback-${streamRuns}`} />

      <GraphPanel key={`graph-${streamRuns}`} />

      <ShadowPanel key={`shadow-${streamRuns}`} />

      <DriftPanel key={`drift-${streamRuns}`} />

      {!model?.loaded && modelError && (
        <section className="panel alert">
          <h2>{t('error.modelInfo')}</h2>
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
          <h2>{t('model.title')}</h2>
          <div className="tiles">
            <Tile label={t('model.algorithm')} value={model.algorithm ?? '—'} note={model.calibration_method ?? ''} />
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

/**
 * Точность и полнота по тому же порогу.
 *
 * Отдельным графиком, а не второй осью на денежном: деньги измеряются
 * сотнями тысяч, метрики — долями единицы, и общая ось сделала бы одну
 * из двух пар линий плоской. Вторая ось справа читается неоднозначно —
 * по линии не видно, к какой шкале она относится.
 *
 * Ось порога общая с графиком выше, засечки те же. Вместе они и есть
 * «индикация компромисса между точностью и потерями бизнеса» из
 * брифинга §5.A: слева точность низкая, а потери малы; справа наоборот.
 */
function QualityChart({
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
  const { t } = useLanguage()
  const width = 720
  const height = 150
  const padding = { top: 14, right: 16, bottom: 26, left: 56 }

  const x = (threshold: number) =>
    padding.left + (threshold / 100) * (width - padding.left - padding.right)
  const y = (share: number) =>
    height - padding.bottom - share * (height - padding.top - padding.bottom)

  // Точки без значения пропускаются, а не рисуются нулём: на пороге 100
  // система никого не помечает, и точность там не ноль, а неизвестна.
  const line = (pick: (point: CurvePoint) => number | null) =>
    curve
      .filter((point) => pick(point) !== null)
      .map((point) => `${x(point.threshold).toFixed(1)},${y(pick(point) as number).toFixed(1)}`)
      .join(' ')

  const marks = [
    { at: currentThreshold, color: 'var(--accent)' },
    { at: optimalThreshold, color: 'var(--approve)' },
    { at: selected, color: 'var(--text)' },
  ]

  // Наведение работает так же, как на графике стоимости. Раньше его
  // здесь не было, и два соседних графика вели себя по-разному: на одном
  // числа под курсором есть, на другом нет — это читается как поломка,
  // а не как решение.
  const [hovered, setHovered] = useState<number | null>(null)

  const track = (event: MouseEvent<SVGRectElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    setHovered(thresholdAtPointer(event.clientX - box.left, box.width))
  }

  const point = hovered === null ? null : (curve.find((item) => item.threshold === hovered) ?? null)

  return (
    <svg
      className="chart"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={t('curve.qualityLabel')}
    >
      {[0, 0.25, 0.5, 0.75, 1].map((share) => (
        <g key={share}>
          <line
            x1={padding.left}
            x2={width - padding.right}
            y1={y(share)}
            y2={y(share)}
            className="chart-grid"
          />
          <text x={padding.left - 8} y={y(share) + 4} className="chart-tick" textAnchor="end">
            {`${share * 100} %`}
          </text>
        </g>
      ))}

      {[0, 25, 50, 75, 100].map((tick) => (
        <text key={tick} x={x(tick)} y={height - 8} className="chart-tick" textAnchor="middle">
          {tick}
        </text>
      ))}

      {marks.map((mark, index) => (
        <line
          key={index}
          x1={x(mark.at)}
          x2={x(mark.at)}
          y1={padding.top}
          y2={height - padding.bottom}
          stroke={mark.color}
          strokeDasharray="4 4"
          strokeWidth={1}
        />
      ))}

      <polyline className="chart-line precision" points={line((point) => point.precision)} />
      <polyline className="chart-line recall" points={line((point) => point.recall)} />

      <g className="chart-legend">
        <text x={padding.left + 8} y={padding.top + 12} className="legend precision">
          — {t('quality.precisionLegend')}
        </text>
        <text x={padding.left + 190} y={padding.top + 12} className="legend recall">
          — {t('quality.recallLegend')}
        </text>
      </g>

      {point && <QualityReadout point={point} x={x(point.threshold)} width={width} height={height} />}

      {/* Прозрачная накладка ловит мышь по всей площади — как у графика
          стоимости. Попадать курсором в ломаную толщиной в полтора
          пикселя одинаково мучительно на обоих. */}
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
 * Точность и полнота под курсором.
 *
 * Отдельная от `Readout` компонента: там деньги и три строки расходов,
 * здесь две доли и другая высота графика. Сводить их в одну значило бы
 * получить пяток условий вместо двух коротких функций.
 *
 * `—` вместо числа не прячется: на высоких порогах система не помечает
 * никого, и точность там не ноль, а неизвестна.
 */
function QualityReadout({
  point,
  x,
  width,
  height,
}: {
  point: CurvePoint
  x: number
  width: number
  height: number
}) {
  const { t } = useLanguage()
  const boxWidth = 150
  const boxHeight = 56
  const boxX = readoutX(x, boxWidth, width)

  return (
    <g className="chart-readout" pointerEvents="none">
      <line x1={x} x2={x} y1={10} y2={height - 26} className="readout-rule" />
      <rect x={boxX} y={12} width={boxWidth} height={boxHeight} rx={5} className="readout-box" />
      <text x={boxX + 10} y={28} className="readout-title">
        {t('cost.atThreshold', { score: point.threshold })}
      </text>
      <text x={boxX + 10} y={44} className="readout-row precision">
        {t('quality.precisionShort', { value: formatMeasuredShare(point.precision, t) })}
      </text>
      <text x={boxX + 10} y={58} className="readout-row recall">
        {t('quality.recallShort', { value: formatMeasuredShare(point.recall, t) })}
      </text>
    </g>
  )
}

function costNote(
  point: CurvePoint,
  current: CurvePoint,
  formatMoney: (value: number) => string,
  t: Translator,
): string {
  const delta = point.total_cost - current.total_cost
  if (Math.round(delta) === 0) return t('cost.sameAsNow')
  return delta < 0
    ? t('cost.cheaperBy', { amount: formatMoney(-delta) })
    : t('cost.dearerBy', { amount: formatMoney(delta) })
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

/**
 * Чем система меряет свои ошибки (брифинг §5.C).
 *
 * Кривая выше нарисована в деньгах, но откуда они берутся, до сих пор
 * нигде не говорилось. Строка называет метрику словами и помечает,
 * если её правили на работающей системе: тогда числа на графике
 * посчитаны не тем, что лежит в `.env`, и об этом надо знать.
 *
 * Читается без пароля — знать метрику полезно всем, кто смотрит
 * на оптимум. Менять её можно только с `X-Admin-Token`.
 */
function CostMetricLine() {
  const { t } = useLanguage()
  const { formatMoney } = useFormat()
  const { data: cost } = usePanelData(fetchCostWeights)

  if (cost === null) return null

  return (
    <p className="hint always-visible metric-line">
      <strong>{t('cost.metric')}:</strong>{' '}
      {t('cost.missedFraud', {
        ratio: cost.fraud_loss_ratio.toFixed(2),
        fixed: formatMoney(cost.fraud_fixed),
      })}
      {'; '}
      {t('cost.extraCheck', { amount: formatMoney(cost.false_challenge) })}
      {cost.overridden && <span className="warn-text"> · {t('cost.tunedAt')}</span>}
    </p>
  )
}

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
  const { t } = useLanguage()
  const { formatMoney } = useFormat()
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
    { at: currentThreshold, color: 'var(--accent)', label: t('cost.markNow') },
    { at: optimalThreshold, color: 'var(--approve)', label: t('cost.markOptimum') },
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
    <svg className="chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t('curve.chartLabel')}>
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
          — {t('cost.fraudLoss')}
        </text>
        <text x={padding.left + 160} y={padding.top + 12} className="legend friction">
          — {t('cost.checkCost')}
        </text>
        <text x={padding.left + 330} y={padding.top + 12} className="legend total">
          — {t('cost.total')}
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
  const { t } = useLanguage()
  const { formatMoney } = useFormat()
  const rows: [string, string, string][] = [
    [t('cost.fraudLoss'), formatMoney(point.fraud_loss), 'fraud'],
    [t('cost.checkCost'), formatMoney(point.friction_cost), 'friction'],
    [t('cost.total'), formatMoney(point.total_cost), 'total'],
  ]

  // Метрики идут отдельным блоком под деньгами: у них своя шкала,
  // и точки на линиях к ним не относятся.
  const metrics = [
    t('quality.precisionShort', { value: formatMeasuredShare(point.precision, t) }),
    t('quality.recallShort', { value: formatMeasuredShare(point.recall, t) }),
  ]

  const boxWidth = 186
  // Две строки метрик плюс разделитель: коробка растёт, иначе они
  // вылезли бы за подложку и легли поверх линий графика.
  const boxHeight = 74 + metrics.length * 14 + 6
  const boxX = readoutX(x, boxWidth, width)

  return (
    <g className="chart-readout" pointerEvents="none">
      <line x1={x} x2={x} y1={16} y2={y(0)} className="readout-rule" />
      {rows.map(([, , tone], index) => (
        <circle key={tone} cx={x} cy={y([point.fraud_loss, point.friction_cost, point.total_cost][index])} r={3} className={`readout-dot ${tone}`} />
      ))}

      <rect x={boxX} y={20} width={boxWidth} height={boxHeight} rx={5} className="readout-box" />
      <text x={boxX + 10} y={36} className="readout-title">
        {t('cost.atThreshold', { score: point.threshold })}
      </text>
      {rows.map(([label, value, tone], index) => (
        <text key={label} x={boxX + 10} y={51 + index * 14} className={`readout-row ${tone}`}>
          {label}: {value}
        </text>
      ))}
      <line
        x1={boxX + 10}
        x2={boxX + boxWidth - 10}
        y1={51 + rows.length * 14 - 4}
        y2={51 + rows.length * 14 - 4}
        className="chart-grid"
      />
      {metrics.map((line, index) => (
        <text
          key={line}
          x={boxX + 10}
          y={51 + (rows.length + index) * 14 + 6}
          className="readout-row muted-row"
        >
          {line}
        </text>
      ))}
    </g>
  )
}
