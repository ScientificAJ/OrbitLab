import js from '@eslint/js';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: ['dist/**', 'playwright-report/**', 'test-results/**', 'node_modules/**', '*.tsbuildinfo'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}', 'e2e/**/*.ts', 'playwright.config.ts', 'vite.config.ts'],
    languageOptions: {
      globals: {
        document: 'readonly',
        window: 'readonly',
        KeyboardEvent: 'readonly',
        MouseEvent: 'readonly',
        Blob: 'readonly',
        URL: 'readonly',
        HTMLAnchorElement: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
        console: 'readonly',
        process: 'readonly',
      },
    },
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
);
