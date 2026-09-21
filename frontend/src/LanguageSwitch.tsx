/**
 * Переключатель языка и заметка про русские пояснения.
 *
 * Языки подписаны на самих себе — «Рус», «Қаз», «Eng». Подписывать их
 * на текущем языке интерфейса значит требовать от человека сначала
 * понять этот язык, а он как раз и ищет, как его сменить.
 */

import { LANGUAGES, LANGUAGE_NAMES } from './i18n'
import { useLanguage } from './LanguageContext'

export default function LanguageSwitch() {
  const { language, setLanguage } = useLanguage()

  return (
    <div className="tabs" role="group" aria-label="Language">
      {LANGUAGES.map((code) => (
        <button
          key={code}
          type="button"
          className={code === language ? 'tab active' : 'tab'}
          onClick={() => setLanguage(code)}
          aria-pressed={code === language}
          lang={code}
        >
          {LANGUAGE_NAMES[code]}
        </button>
      ))}
    </div>
  )
}

/**
 * Заметка о том, что подробные пояснения остались русскими.
 *
 * Показывается только в казахском и английском режимах, где это правда.
 * Сказать прямо лучше, чем показать полторы тысячи слов машинного
 * перевода технической прозы или молча спрятать половину интерфейса.
 *
 * Сами пояснения убираются правилом CSS по `data-lang` на корне —
 * одно правило вместо полусотни правок по компонентам, — а этот
 * переключатель их возвращает.
 */
export function CommentaryNote() {
  const { language, t } = useLanguage()

  if (language === 'ru') return null

  return (
    <section className="panel commentary-note">
      <p className="hint always-visible">
        {t('app.commentaryNote')}{' '}
        <label className="checkbox inline-checkbox">
          <input
            type="checkbox"
            onChange={(event) => {
              document.documentElement.dataset.commentary = event.target.checked ? 'on' : 'off'
            }}
          />
          <span>{t('app.commentary')}</span>
        </label>
      </p>
    </section>
  )
}
