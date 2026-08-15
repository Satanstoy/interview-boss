import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'
import tsParser from '@typescript-eslint/parser'

export default [
  {
    ignores: ['dist/**', 'node_modules/**', 'coverage/**'],
  },
  js.configs.recommended,
  ...pluginVue.configs['flat/essential'],
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        // 101 个组件使用 <script setup lang="ts">；vue-eslint-parser 需要 TS
        // parser 才能解析这些 SFC 的脚本块，否则会整体报 parsing error 空转。
        parser: tsParser,
        extraFileExtensions: ['.vue'],
        sourceType: 'module',
      },
    },
  },
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
      // catch {} 表示显式忽略该错误（如 ctrl.abort()），保留空块。
      'no-empty': ['error', { allowEmptyCatch: true }],
      'vue/multi-word-component-names': 'off',
      'no-useless-escape': 'warn',
    },
  },
]
