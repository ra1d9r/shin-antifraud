/**
 * Панель, которая не смогла загрузиться, говорит об этом.
 *
 * Раньше такая панель просто исчезала. Для человека, впервые открывшего
 * дашборд, исчезнувшая панель и несделанная панель выглядят одинаково —
 * а это разные вещи, и вторая гораздо хуже первой.
 *
 * Занимает одну строку: место панели обозначено, работе не мешает,
 * причина названа словами backend — он знает точнее, артефакт ли
 * не выгружен, модель ли не загружена или дело в сети.
 */

import { useLanguage } from './LanguageContext'

export default function PanelError({ title, reason }: { title: string; reason: string }) {
  const { t } = useLanguage()

  return (
    <section className="panel panel-unavailable">
      <h2>{title}</h2>
      <p className="hint always-visible">
        <strong className="warn-text">{t('error.panelUnavailable')}.</strong>
        {/* Причины может не быть: тогда обрываем фразу, а не вешаем пустоту. */}
        {reason === '' ? null : ` ${reason}`}
      </p>
    </section>
  )
}
