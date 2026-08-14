import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'

export default [
  {
    ignores: ['dist/**', 'node_modules/**', 'coverage/**'],
  },
  js.configs.recommended,
  ...pluginVue.configs['flat/essential'],
  {
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...globals.node,
        ...globals.es2022,
      },
    },
    rules: {
      // 阶段 A: 以 audit WARN 接入,只报告不拦截(对齐 CLAUDE.md「audit 第一阶段只报告不拦截」)。
      'no-unused-vars': 'warn',
      'vue/multi-word-component-names': 'off',
      'no-useless-escape': 'warn',
    },
  },
]
