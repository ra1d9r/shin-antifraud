// Линтер фронтенда.
//
// `tsc --noEmit` уже ловит ошибки типов, поэтому здесь важно другое:
// правила react-hooks. Забытая зависимость в useEffect или useCallback —
// это не стилистика, а состояние, которое перестанет обновляться,
// и TypeScript о нём ничего не скажет.

import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', 'node_modules'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
    },
  },
)
