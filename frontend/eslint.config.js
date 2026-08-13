import js from '@eslint/js'
import tseslintPlugin from '@typescript-eslint/eslint-plugin'
import tseslintParser from '@typescript-eslint/parser'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import globals from 'globals'

export default [
  { ignores: ['dist'] },
  js.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      sourceType: 'module',
      globals: { ...globals.browser, ...globals.node },
      parser: tseslintParser,
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      '@typescript-eslint': tseslintPlugin,
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...tseslintPlugin.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      // TypeScript-only constructs (e.g. `React.MouseEvent<...>` used purely as a type) read
      // as undefined globals to this JS-only rule; tsc already catches genuinely undefined
      // identifiers, so typescript-eslint's own docs recommend disabling the base rule for TS.
      'no-undef': 'off',
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      // New in eslint-plugin-react-hooks v7's recommended set (wasn't enforced under the old
      // v4 setup this project previously had). Downgraded to a warning rather than silently
      // rewriting ~25 existing setState-in-effect call sites across the app as an unrelated
      // side effect of a dependency security bump - each would need its own real behavioral
      // review, not a mechanical fix.
      'react-hooks/set-state-in-effect': 'warn',
    },
  },
]
