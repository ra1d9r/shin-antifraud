/**
 * Выбранный язык интерфейса и функция перевода.
 *
 * Контекст, а не проп через всё дерево: язык нужен почти каждому
 * компоненту, и протаскивать его руками через десять уровней значило бы
 * переписать сигнатуры ради одной строки.
 *
 * Язык выставляется и на `<html lang>`. Это не украшение: от него
 * зависят перенос слов, выбор шрифта и то, как читает страницу
 * экранный диктор.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { DEFAULT_LANGUAGE, rememberLanguage, storedLanguage, translate } from './i18n'
import type { Language, TranslationKey } from './i18n'

interface LanguageValue {
  language: Language
  setLanguage: (language: Language) => void
  t: (key: TranslationKey) => string
}

const LanguageContext = createContext<LanguageValue>({
  language: DEFAULT_LANGUAGE,
  setLanguage: () => {},
  t: (key) => translate(key, DEFAULT_LANGUAGE),
})

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(storedLanguage)

  useEffect(() => {
    document.documentElement.lang = language
    // Язык управляет и тем, показывать ли русские пояснения: правило
    // одно, в CSS, вместо двухсот тридцати правок по компонентам.
    document.documentElement.dataset.lang = language
  }, [language])

  const setLanguage = useCallback((next: Language) => {
    setLanguageState(next)
    rememberLanguage(next)
  }, [])

  const value = useMemo<LanguageValue>(
    () => ({
      language,
      setLanguage,
      t: (key: TranslationKey) => translate(key, language),
    }),
    [language, setLanguage],
  )

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
}

export function useLanguage(): LanguageValue {
  return useContext(LanguageContext)
}
