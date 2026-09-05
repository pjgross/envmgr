module.exports = {
  root: true,
  env: { browser: true, es2020: true, node: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
    'prettier',
  ],
  ignorePatterns: [
    'dist',
    'node_modules',
    'coverage',
    'playwright-report',
    'test-results',
    'e2e',
    '.eslintrc.cjs',
  ],
  parser: '@typescript-eslint/parser',
  plugins: ['react-refresh'],
  rules: {
    'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    '@typescript-eslint/no-unused-vars': [
      'warn',
      { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
    ],
    // Every grid renders through components/DataTable.tsx, which adds saved
    // column visibility, an entity-specific empty state, and the server-mode
    // guards (no client-side filter or export over one windowed page). A raw
    // DataGrid gets none of it and diverges silently. Types are unrestricted —
    // only the component binding is.
    'no-restricted-imports': [
      'error',
      {
        paths: [
          {
            name: '@mui/x-data-grid',
            importNames: ['DataGrid'],
            message:
              'Import DataTable from components/DataTable instead — it wraps DataGrid with saved column visibility, empty states and the server-mode guards.',
          },
        ],
      },
    ],
  },
  overrides: [
    {
      // The one file allowed to import DataGrid: the wrapper the rule exists
      // to funnel everything through.
      files: ['src/components/DataTable.tsx'],
      rules: { 'no-restricted-imports': 'off' },
    },
  ],
};
