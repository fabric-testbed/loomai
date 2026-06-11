import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';

const browserGlobals = {
  AbortController: 'readonly',
  alert: 'readonly',
  Blob: 'readonly',
  clearInterval: 'readonly',
  clearTimeout: 'readonly',
  confirm: 'readonly',
  console: 'readonly',
  CustomEvent: 'readonly',
  document: 'readonly',
  EventSource: 'readonly',
  fetch: 'readonly',
  File: 'readonly',
  FileList: 'readonly',
  FormData: 'readonly',
  Headers: 'readonly',
  HTMLElement: 'readonly',
  HTMLButtonElement: 'readonly',
  HTMLDivElement: 'readonly',
  HTMLInputElement: 'readonly',
  HTMLSelectElement: 'readonly',
  HTMLTextAreaElement: 'readonly',
  KeyboardEvent: 'readonly',
  localStorage: 'readonly',
  MouseEvent: 'readonly',
  navigator: 'readonly',
  prompt: 'readonly',
  process: 'readonly',
  React: 'readonly',
  requestAnimationFrame: 'readonly',
  Response: 'readonly',
  sessionStorage: 'readonly',
  setInterval: 'readonly',
  setTimeout: 'readonly',
  TextDecoder: 'readonly',
  URL: 'readonly',
  URLSearchParams: 'readonly',
  WebSocket: 'readonly',
  window: 'readonly',
};

export default tseslint.config(
  {
    ignores: [
      '.next/**',
      '.next-*/*',
      '.next-*/**',
      'dist/**',
      'e2e/playwright-report/**',
      'e2e/test-results/**',
      'node_modules/**',
      'next-env.d.ts',
      'out/**',
      'tsconfig.tsbuildinfo',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{cjs,js,jsx,mjs,ts,tsx}'],
    languageOptions: {
      ecmaVersion: 'latest',
      globals: browserGlobals,
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
      sourceType: 'module',
    },
    plugins: {
      'react-hooks': reactHooks,
    },
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-expressions': 'warn',
      '@typescript-eslint/no-unused-vars': ['warn', {
        argsIgnorePattern: '^_',
        caughtErrorsIgnorePattern: '^_',
        varsIgnorePattern: '^_',
      }],
      'no-constant-binary-expression': 'warn',
      'no-empty': ['warn', { allowEmptyCatch: true }],
      'no-undef': 'off',
      'no-useless-assignment': 'warn',
      'react-hooks/exhaustive-deps': 'warn',
      'react-hooks/rules-of-hooks': 'error',
    },
  },
  {
    files: ['e2e/**/*.ts', 'vitest.config.ts'],
    languageOptions: {
      globals: {
        ...browserGlobals,
        Buffer: 'readonly',
        process: 'readonly',
      },
    },
  },
);
