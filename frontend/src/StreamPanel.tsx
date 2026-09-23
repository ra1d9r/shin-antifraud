/**
 * Прогон порождённого потока операций (брифинг §5.B).
 *
 * Брифинг §5.B требует «интерфейс или API для загрузки синтетического
 * датасета (100k строк) или симуляции потока транзакций». API есть
 * (`POST /predict/stream`), но без кнопки до него доберётся только тот,
 * кто откроет Swagger.
 *
 * А добраться нужно: наблюдение за дрейфом, теневая конфигурация
 * и история операций показывают что-либо только на потоке. На свежем
 * экземпляре системы эти панели пусты, и человек, открывший ссылку,
 * решит, что они не работают. Дрейфу вдобавок нужно двести наблюдений,
 * прежде чем он вообще что-то скажет.
 *
 * После прогона панели ниже перемонтируются ключом — иначе они показывали
 * бы состояние, снятое при загрузке страницы, то есть до прогона.
 */

import { useState } from 'react'

import { errorText, runStream } from './api'
import { useLanguage } from './LanguageContext'
import { useFormat } from './useFormat'
import Tile from './Tile'
import type { StreamSummary } from './types'

/** Размеры прогона. Триста — минимум, после которого дрейф оживает. */
const SIZES = [100, 300, 500] as const

export default function StreamPanel({ onFinished }: { onFinished: () => void }) {
  const { t } = useLanguage()
  const { formatCount } = useFormat()
  const [summary, setSummary] = useState<StreamSummary | null>(null)
  // Не булево «идёт прогон», а сколько именно операций гоним: при трёх
  // кнопках под общей подписью «Идёт прогон…» непонятно, какая нажата.
  const [running, setRunning] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function run(count: number) {
    setRunning(count)
    setError(null)
    try {
      const payload = await runStream(count)
      setSummary(payload)
      onFinished()
    } catch (cause) {
      setError(errorText(cause, t) || t('stream.failed'))
    } finally {
      setRunning(null)
    }
  }

  return (
    <section className="panel">
      <h2>{t('stream.title')}</h2>
      <p className="hint">
        Операции порождаются тем же генератором, на котором обучалась модель, и идут
        обычной цепочкой обработки. Разметка потока известна, поэтому сразу видно,
        сколько фрода система поймала и сколько пропустила — это проверка на живых
        данных, а не число из выгруженной аналитики.
      </p>
      <p className="hint">
        Наблюдение за дрейфом, теневая конфигурация и история операций наполняются
        именно здесь: без потока они пусты. Дрейфу нужно не меньше двухсот наблюдений.
      </p>

      <div className="scenario-buttons">
        {SIZES.map((size) => (
          <button
            key={size}
            type="button"
            disabled={running !== null}
            onClick={() => run(size)}
          >
            {running === size ? `${t('stream.running')} ${size}…` : `${t('stream.run')} ${size}`}
          </button>
        ))}
      </div>

      {running !== null && (
        <p className="hint">
          Каждая операция проходит полную цепочку, включая SHAP-объяснение. На бесплатном
          хостинге это занимает десятки секунд.
        </p>
      )}

      {error && <p className="warn-text">{error}</p>}

      {summary && running === null && (
        <>
          <div className="tiles">
            <Tile label={t('stream.processed')} value={formatCount(summary.processed)} />
            <Tile
              label={t('stream.fraudIn')}
              value={formatCount(summary.fraud_in_stream)}
              note={t('stream.ofProcessed', { total: formatCount(summary.processed) })}
            />
            <Tile
              label={t('stream.stopped')}
              value={formatCount(summary.fraud_stopped)}
              note={`${t('stream.missed')} ${formatCount(summary.fraud_missed)}`}
              tone={summary.fraud_missed === 0 ? 'good' : 'warn'}
            />
            <Tile
              label={t('stream.falsePositives')}
              value={formatCount(summary.false_positives)}
              note={t('feedback.botheredInVain')}
              tone={summary.false_positives > 0 ? 'warn' : 'good'}
            />
            <Tile
              label={t('stream.averageScore')}
              value={String(summary.average_risk_score)}
              note={t('stream.raisedByPolicies', { count: formatCount(summary.raised_by_rules) })}
            />
          </div>

          <p className="hint">
            Решения:{' '}
            {Object.entries(summary.decisions)
              .map(([decision, count]) => `${decision} ${formatCount(count)}`)
              .join(' · ')}
            . Выборка из {formatCount(summary.pool_rows)} операций, зерно {summary.seed} —
            с ним прогон повторяется. Заняло{' '}
            {(summary.processing_ms / 1000).toFixed(1)} с.
          </p>
        </>
      )}
    </section>
  )
}
