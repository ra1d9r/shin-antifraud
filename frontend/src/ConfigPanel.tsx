/**
 * Настройка на работающей системе (брифинг §4.5, §5.C).
 *
 * ## Зачем форма, если есть API
 *
 * Эндпоинты `POST /config/*` существовали и раньше, но добраться до них
 * мог только тот, кто откроет Swagger и соберёт запрос руками. Брифинг
 * §4.5 требует возможности «корректировать веса рисков», а не наличия
 * адреса, по которому это теоретически делается: человек, смотрящий
 * на дашборд, должен увидеть, что настройка есть, и что она работает.
 *
 * ## Три формы, а не одна
 *
 * Пороги Risk Engine, веса политик и бизнес-метрика меняются разными
 * запросами и дают разные последствия. Пороги и политики решают судьбу
 * операции — после их смены обнуляется тень и стареет аналитика.
 * Веса метрики не меняют ни одного решения: они переводят уже принятые
 * решения в деньги, и от них двигается только кривая компромисса.
 *
 * Свести их в одну кнопку «сохранить» значило бы скрыть эту разницу —
 * и человек, поправивший цену проверки, ждал бы, что изменятся вердикты.
 *
 * ## Что показывается после применения
 *
 * Последствия приходят с backend и перечисляются как есть. Выводить их
 * здесь («раз меняли пороги, значит тень сброшена») запрещено ТЗ §11 и
 * разошлось бы с правдой в первый же день, когда backend решит иначе.
 *
 * ## Почему пароль спрашивается, а не хранится
 *
 * Значение `CONFIG_ADMIN_TOKEN` живёт в памяти вкладки и не попадает
 * ни в `localStorage`, ни в адресную строку. Это пароль от адреса,
 * которым отключается блокировка любого мошенничества; сохранённый
 * в браузере, он пережил бы и вкладку, и того, кто его вводил.
 */

import { useCallback, useState } from 'react'

import {
  errorText,
  fetchCostWeights,
  fetchPolicies,
  fetchThresholds,
  updateCostWeights,
  updatePolicies,
  updateThresholds,
} from './api'
import { useLanguage } from './LanguageContext'
import type { Substitutions, TranslationKey } from './i18n'
import { useFormat } from './useFormat'
import PanelError from './PanelError'
import { usePanelData } from './usePanelData'
import type { CostState, PolicyState, ThresholdsState } from './types'

/** Черновик формы: значения полей как их набрали, строками. */
type Draft = Record<string, string>

/**
 * Что из черновика реально изменилось против действующего.
 *
 * Строками, а не числами, черновик держится намеренно: поле `type=number`
 * во время набора бывает пустым, и хранение числа заставляло бы выбирать
 * между «пустое поле = ноль» и «поле нельзя очистить». Оба варианта
 * человеку мешают.
 *
 * Отправляются только изменённые величины: backend оставляет незаданное
 * как есть, и переслать заодно остальные пять значило бы напрашиваться
 * на опечатку в той политике, которую трогать не собирались.
 */
function changedNumbers(draft: Draft, current: Record<string, number>): Record<string, number> {
  const changed: Record<string, number> = {}
  for (const [name, text] of Object.entries(draft)) {
    if (text.trim() === '') continue
    const value = Number(text)
    if (!Number.isFinite(value)) continue
    if (value !== current[name]) changed[name] = value
  }
  return changed
}

/** Черновик из действующих значений: числа становятся строками полей. */
function draftFrom(current: Record<string, number>): Draft {
  const draft: Draft = {}
  for (const [name, value] of Object.entries(current)) draft[name] = String(value)
  return draft
}

/** Одно числовое поле формы. */
function NumberField({
  label,
  value,
  onChange,
  disabled,
  step,
  min,
  max,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  disabled: boolean
  step?: string
  min?: number
  max?: number
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input
        type="number"
        value={value}
        step={step}
        min={min}
        max={max}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  )
}

/** Строка «зачем меняли» — она уходит в журнал правок. */
function ReasonField({
  value,
  onChange,
  disabled,
}: {
  value: string
  onChange: (value: string) => void
  disabled: boolean
}) {
  const { t } = useLanguage()

  return (
    <label className="field config-wide">
      <span>{t('config.reason')}</span>
      <input
        type="text"
        maxLength={300}
        value={value}
        disabled={disabled}
        placeholder={t('config.reasonPlaceholder')}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  )
}

/**
 * Какая из трёх форм применяла правку.
 *
 * Нужно потому, что итог живёт снаружи форм и должен вернуться туда же,
 * откуда пришёл: иначе «кривая пересчитана» появлялось бы под порогами.
 */
type FormName = 'thresholds' | 'policies' | 'cost'

/** Одна строка итога: ключ словаря, а не готовый текст. */
interface AppliedNote {
  key: TranslationKey
  values?: Substitutions
}

/**
 * Итог применения: что изменилось и что из-за этого сброшено.
 *
 * Хранится ключами перевода, а не строками. Строка сложилась бы один раз,
 * в момент применения, и осталась бы на языке, выбранном тогда: после
 * переключения на английский итог продолжал бы говорить по-русски.
 * Та же причина, по которой `usePanelData` держит причину отказа,
 * а не её текст.
 */
interface ApplyReport {
  form: FormName
  notes: AppliedNote[]
  /** Аналитика наверху страницы посчитана на прежних порогах. */
  reload: boolean
}

/**
 * Строка итога под формой.
 *
 * Живёт снаружи форм намеренно. Формы перемонтируются после каждого
 * применения — так черновик становится тем, что подтвердил сервер, —
 * и сообщение, лежи оно внутри, исчезало бы в тот же миг, когда
 * появилось. Ровно это и происходило: правка применялась, а человек
 * видел только то, что поле перестало быть изменённым.
 */
function Applied({ report }: { report: ApplyReport }) {
  const { t } = useLanguage()

  return (
    <p className="config-applied">
      <strong>{t('config.applied')}.</strong>
      {report.notes.length > 0
        ? ` ${report.notes.map((note) => t(note.key, note.values)).join(' · ')}.`
        : null}
      {report.reload ? ` ${t('config.reloadHint')}.` : null}
    </p>
  )
}

export default function ConfigPanel({ onApplied }: { onApplied: () => void }) {
  const [token, setToken] = useState('')
  const [version, setVersion] = useState(0)
  const [report, setReport] = useState<ApplyReport | null>(null)

  return (
    <ConfigForms
      key={version}
      token={token}
      report={report}
      onToken={setToken}
      onApplied={(next) => {
        setReport(next)
        setVersion((previous) => previous + 1)
        onApplied()
      }}
    />
  )
}

function ConfigForms({
  token,
  report,
  onToken,
  onApplied,
}: {
  token: string
  report: ApplyReport | null
  onToken: (value: string) => void
  onApplied: (report: ApplyReport) => void
}) {
  const { t, language } = useLanguage()
  const { formatDateTime } = useFormat()

  const load = useCallback(
    () => Promise.all([fetchThresholds(), fetchPolicies(language), fetchCostWeights()]),
    [language],
  )

  const { data, failure } = usePanelData(load)

  if (failure !== null) {
    return <PanelError title={t('config.title')} reason={errorText(failure.cause, t)} />
  }
  if (data === null) return null

  const [thresholds, policies, cost] = data

  // Признак один на все три эндпоинта: он означает, задан ли на сервере
  // `CONFIG_ADMIN_TOKEN` вообще.
  const writable = thresholds.writable

  return (
    <section className="panel">
      <h2>{t('config.title')}</h2>
      <p className="hint">
        Брифинг §4.5 требует возможности корректировать веса рисков, §5.C —
        настраиваемой бизнес-метрики. Всё, что меняется здесь, применяется
        без перезапуска и действует на следующую же операцию. Правки живут
        в памяти: перезапуск возвращает значения из <code>.env</code>, поэтому
        неудачную настройку отменяет рестарт, а не поиск того, кто её сделал.
      </p>

      {!writable && (
        <p className="hint always-visible config-locked">
          <strong className="warn-text">{t('config.locked')}.</strong> {t('config.lockedWhy')}
        </p>
      )}

      {writable && (
        <label className="field config-wide">
          <span>{t('config.token')}</span>
          <input
            type="password"
            autoComplete="off"
            value={token}
            onChange={(event) => onToken(event.target.value)}
          />
          <small className="muted">{t('config.tokenHint')}</small>
        </label>
      )}

      <ThresholdForm
        state={thresholds}
        token={token}
        writable={writable}
        report={report?.form === 'thresholds' ? report : null}
        onApplied={onApplied}
      />

      <PolicyForm
        state={policies}
        token={token}
        writable={writable}
        report={report?.form === 'policies' ? report : null}
        onApplied={onApplied}
      />

      <CostForm
        state={cost}
        token={token}
        writable={writable}
        report={report?.form === 'cost' ? report : null}
        onApplied={onApplied}
      />

      <p className="hint">
        Журнал правок порогов:{' '}
        {thresholds.history.length === 0
          ? 'пока пусто'
          : thresholds.history
              .slice(0, 3)
              .map(
                (item) =>
                  `${formatDateTime(item.at)} — ${item.approve_max}/${item.challenge_max}/${item.critical_min}` +
                  (item.reason ? ` (${item.reason})` : ''),
              )
              .join('; ')}
        .
      </p>
    </section>
  )
}

/** Общие свойства трёх форм. */
interface FormProps<T> {
  state: T
  token: string
  writable: boolean
  /** Итог последнего применения этой формы — или null, применяли другую. */
  report: ApplyReport | null
  onApplied: (report: ApplyReport) => void
}

function ThresholdForm({ state, token, writable, report, onApplied }: FormProps<ThresholdsState>) {
  const { t } = useLanguage()
  const { formatDateTime } = useFormat()

  const current = {
    approve_max: state.approve_max,
    challenge_max: state.challenge_max,
    critical_min: state.critical_min,
  }

  const [draft, setDraft] = useState<Draft>({
    approve_max: String(state.approve_max),
    challenge_max: String(state.challenge_max),
    critical_min: String(state.critical_min),
  })
  const [rulesEnabled, setRulesEnabled] = useState(state.rules_enabled)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function set(name: string, value: string) {
    setDraft((previous) => ({ ...previous, [name]: value }))
  }

  async function apply() {
    setBusy(true)
    setError(null)
    try {
      const applied = await updateThresholds(
        {
          // Пороги отправляются все четыре: они проверяются на возрастание
          // друг относительно друга, и «менять только изменённое» здесь
          // означало бы проверять новое значение против старого соседа.
          approve_max: Number(draft.approve_max),
          challenge_max: Number(draft.challenge_max),
          critical_min: Number(draft.critical_min),
          rules_enabled: rulesEnabled,
          ...(reason.trim() ? { reason: reason.trim() } : {}),
        },
        token,
      )
      const notes: AppliedNote[] = []
      if (applied.shadow_reset) notes.push({ key: 'config.shadowReset' })
      if (applied.analytics_marked_stale) notes.push({ key: 'config.analyticsStale' })
      if (applied.drift_kept) notes.push({ key: 'config.driftKept' })
      onApplied({ form: 'thresholds', notes, reload: applied.analytics_marked_stale })
    } catch (cause) {
      setError(errorText(cause, t))
    } finally {
      setBusy(false)
    }
  }

  const untouched =
    Object.keys(changedNumbers(draft, current)).length === 0 &&
    rulesEnabled === state.rules_enabled

  return (
    <div className="config-block">
      <h3>{t('config.thresholds')}</h3>
      <p className="hint">
        Один рычаг на три зоны: всё до первого порога проходит само, между
        первым и вторым уходит на подтверждение владельца, выше второго
        блокируется. Пороги обязаны возрастать — проверяет это backend, и
        отказ приходит с разбором по полям.
      </p>

      <div className="grid">
        <NumberField
          label={t('config.approveMax')}
          value={draft.approve_max}
          onChange={(value) => set('approve_max', value)}
          disabled={!writable || busy}
          min={0}
          max={100}
        />
        <NumberField
          label={t('config.challengeMax')}
          value={draft.challenge_max}
          onChange={(value) => set('challenge_max', value)}
          disabled={!writable || busy}
          min={0}
          max={100}
        />
        <NumberField
          label={t('config.criticalMin')}
          value={draft.critical_min}
          onChange={(value) => set('critical_min', value)}
          disabled={!writable || busy}
          min={0}
          max={100}
        />
      </div>

      <label className="checkbox">
        <input
          type="checkbox"
          checked={rulesEnabled}
          disabled={!writable || busy}
          onChange={(event) => setRulesEnabled(event.target.checked)}
        />
        <span>{t('config.rulesEnabled')}</span>
      </label>

      <div className="grid">
        <ReasonField value={reason} onChange={setReason} disabled={!writable || busy} />
      </div>

      <div className="actions">
        <button type="button" className="primary" disabled={!writable || busy || untouched} onClick={() => void apply()}>
          {busy ? t('config.applying') : t('config.apply')}
        </button>
        <span className="muted">
          {state.overridden ? t('config.overridden') : t('config.fromEnv')}
          {state.changed_at ? ` · ${t('config.changedAt')}: ${formatDateTime(state.changed_at)}` : ''}
        </span>
      </div>

      {/* Подсказка исчезает, как только появился итог: «ничего не изменено»
          рядом с «применено» противоречило бы само себе. */}
      {writable && untouched && report === null && (
        <p className="muted">{t('config.nothingToChange')}</p>
      )}
      {error && <p className="warn-text">{error}</p>}
      {report && <Applied report={report} />}
    </div>
  )
}

function PolicyForm({ state, token, writable, report, onApplied }: FormProps<PolicyState>) {
  const { t } = useLanguage()
  const { formatDateTime } = useFormat()

  /**
   * Действующие значения по именам полей настройки.
   *
   * Имя берётся из `config_field`, который прислал backend, а не
   * складывается из ключа: `velocity_burst` настраивается полем
   * `velocity_min_score`, и собранное имя backend отбросил бы молча.
   */
  const current: Record<string, number> = {
    velocity_txn_per_hour: state.velocity_txn_per_hour,
    new_account_amount_ratio: state.new_account_amount_ratio,
  }
  for (const policy of state.policies) current[policy.config_field] = policy.min_score

  const [draft, setDraft] = useState<Draft>(() => draftFrom(current))
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function set(name: string, value: string) {
    setDraft((previous) => ({ ...previous, [name]: value }))
  }

  const changed = changedNumbers(draft, current)

  async function apply() {
    setBusy(true)
    setError(null)
    try {
      const applied = await updatePolicies(
        { ...changed, ...(reason.trim() ? { reason: reason.trim() } : {}) },
        token,
      )
      const notes: AppliedNote[] = []
      if (applied.shadow_reset) notes.push({ key: 'config.shadowReset' })
      if (applied.analytics_marked_stale) notes.push({ key: 'config.analyticsStale' })
      onApplied({ form: 'policies', notes, reload: applied.analytics_marked_stale })
    } catch (cause) {
      setError(errorText(cause, t))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="config-block">
      <h3>{t('config.policies')}</h3>
      <p className="hint">
        Политика поднимает оценку до своего минимума и никогда не снижает.
        Поставить ноль — не «выключить проверку», а «пусть решает модель»:
        сработавшая политика с нулевым минимумом оценку не двигает.
        Выключить их все сразу можно флажком выше.
      </p>

      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>{t('config.policyColumn')}</th>
              <th>{t('config.minScore')}</th>
            </tr>
          </thead>
          <tbody>
            {state.policies.map((policy) => (
              <tr key={policy.key}>
                <td>
                  {policy.title}
                  <br />
                  <code className="muted">{policy.key}</code>
                </td>
                <td>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    value={draft[policy.config_field] ?? ''}
                    disabled={!writable || busy}
                    onChange={(event) => set(policy.config_field, event.target.value)}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid">
        <NumberField
          label={t('config.velocityPerHour')}
          value={draft.velocity_txn_per_hour ?? ''}
          onChange={(value) => set('velocity_txn_per_hour', value)}
          disabled={!writable || busy}
          min={1}
        />
        <NumberField
          label={t('config.amountRatio')}
          value={draft.new_account_amount_ratio ?? ''}
          onChange={(value) => set('new_account_amount_ratio', value)}
          disabled={!writable || busy}
          step="0.1"
          min={0}
        />
        <ReasonField value={reason} onChange={setReason} disabled={!writable || busy} />
      </div>

      <div className="actions">
        <button
          type="button"
          className="primary"
          disabled={!writable || busy || Object.keys(changed).length === 0}
          onClick={() => void apply()}
        >
          {busy ? t('config.applying') : t('config.apply')}
        </button>
        <span className="muted">
          {state.overridden ? t('config.overridden') : t('config.fromEnv')}
          {state.changed_at ? ` · ${t('config.changedAt')}: ${formatDateTime(state.changed_at)}` : ''}
        </span>
      </div>

      {error && <p className="warn-text">{error}</p>}
      {report && <Applied report={report} />}
    </div>
  )
}

function CostForm({ state, token, writable, report, onApplied }: FormProps<CostState>) {
  const { t } = useLanguage()
  const { formatDateTime } = useFormat()

  const current = {
    fraud_loss_ratio: state.fraud_loss_ratio,
    fraud_fixed: state.fraud_fixed,
    false_block: state.false_block,
    false_challenge: state.false_challenge,
  }

  const [draft, setDraft] = useState<Draft>(() => draftFrom(current))
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function set(name: string, value: string) {
    setDraft((previous) => ({ ...previous, [name]: value }))
  }

  const changed = changedNumbers(draft, current)

  async function apply() {
    setBusy(true)
    setError(null)
    try {
      const applied = await updateCostWeights(
        { ...changed, ...(reason.trim() ? { reason: reason.trim() } : {}) },
        token,
      )
      const notes: AppliedNote[] = [
        { key: applied.curve_recomputed ? 'config.curveRecomputed' : 'config.curveNotRecomputed' },
      ]
      if (
        applied.optimal_threshold_before !== null &&
        applied.optimal_threshold_after !== null &&
        applied.optimal_threshold_before !== applied.optimal_threshold_after
      ) {
        notes.push({
          key: 'config.optimumMoved',
          values: {
            before: applied.optimal_threshold_before,
            after: applied.optimal_threshold_after,
          },
        })
      }
      // Кривая пересчитана на месте, аналитика не устарела — перезагружать
      // страницу незачем, и предлагать это было бы лишним беспокойством.
      onApplied({ form: 'cost', notes, reload: false })
    } catch (cause) {
      setError(errorText(cause, t))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="config-block">
      <h3>{t('config.cost')}</h3>
      <p className="hint">
        Этими весами считается кривая компромисса и оптимальный порог на ней.
        Ни одно решение от них не меняется: они переводят уже принятые решения
        в деньги, а не участвуют в их принятии. Сделайте проверку дороже — и
        оптимум уедет вправо, к меньшему числу проверок.
      </p>

      <div className="grid">
        <NumberField
          label={t('config.fraudLossRatio')}
          value={draft.fraud_loss_ratio ?? ''}
          onChange={(value) => set('fraud_loss_ratio', value)}
          disabled={!writable || busy}
          step="0.05"
          min={0}
        />
        <NumberField
          label={t('config.fraudFixed')}
          value={draft.fraud_fixed ?? ''}
          onChange={(value) => set('fraud_fixed', value)}
          disabled={!writable || busy}
          step="100"
          min={0}
        />
        <NumberField
          label={t('config.falseBlock')}
          value={draft.false_block ?? ''}
          onChange={(value) => set('false_block', value)}
          disabled={!writable || busy}
          step="100"
          min={0}
        />
        <NumberField
          label={t('config.falseChallenge')}
          value={draft.false_challenge ?? ''}
          onChange={(value) => set('false_challenge', value)}
          disabled={!writable || busy}
          step="10"
          min={0}
        />
        <ReasonField value={reason} onChange={setReason} disabled={!writable || busy} />
      </div>

      <div className="actions">
        <button
          type="button"
          className="primary"
          disabled={!writable || busy || Object.keys(changed).length === 0}
          onClick={() => void apply()}
        >
          {busy ? t('config.applying') : t('config.apply')}
        </button>
        <span className="muted">
          {state.overridden ? t('config.overridden') : t('config.fromEnv')}
          {state.changed_at ? ` · ${t('config.changedAt')}: ${formatDateTime(state.changed_at)}` : ''}
        </span>
      </div>

      {!state.curve_recomputable && (
        <p className="muted">{t('config.curveNotRecomputed')}</p>
      )}
      {error && <p className="warn-text">{error}</p>}
      {report && <Applied report={report} />}
    </div>
  )
}
