/**
 * Переводчик для тестов.
 *
 * Модули, которые собирают фразы, принимают переводчик параметром —
 * так они остаются чистыми и не тянут за собой React. Тестам нужен
 * тот же переводчик, что и приложению, а не заглушка, возвращающая
 * ключ: заглушка пропустила бы забытую подстановку и разъехавшийся
 * порядок слов, то есть ровно те ошибки, ради которых подстановки
 * и заводились.
 *
 * В сборку не попадает: на него не ссылается ни один модуль
 * приложения, только тесты.
 */

import { translate } from './i18n'
import type { Language, Substitutions, TranslationKey, Translator } from './i18n'

/** Переводчик на заданном языке. По умолчанию — русский. */
export function translatorFor(language: Language = 'ru'): Translator {
  return (key: TranslationKey, values?: Substitutions) => translate(key, language, values)
}

/** Русский переводчик — им пользуется большинство тестов. */
export const ru = translatorFor('ru')
