const globals = require("globals");

const targetFiles = [
  "web/app.js",
  "web/app-auth.js",
  "web/app-routing.js",
  "web/app_shared.js",
  "web/ui-foundation.js",
];

const baseRules = {
  "no-undef": "error",
  "no-redeclare": "error",
  "no-dupe-keys": "error",
  "no-dupe-args": "error",
  "no-unreachable": "error",
  "no-constant-condition": ["error", { checkLoops: false }],
  "valid-typeof": "error",
  "use-isnan": "error",
  "no-self-assign": "error",
  "no-import-assign": "error",
  "no-ex-assign": "error",
  "no-func-assign": "error",
  "no-unused-vars": [
    "warn",
    {
      args: "after-used",
      argsIgnorePattern: "^_",
      caughtErrors: "all",
      caughtErrorsIgnorePattern: "^_",
      varsIgnorePattern: "^_",
      ignoreRestSiblings: true,
    },
  ],
  "no-useless-catch": "warn",
  "no-useless-escape": "warn",
  eqeqeq: "warn",
  curly: "warn",
  "no-console": ["warn", { allow: ["warn", "error"] }],
};

module.exports = [
  {
    ignores: [
      "**/node_modules/**",
      "**/htmlcov/**",
      "**/playwright-report/**",
      "**/test-results/**",
      "**/coverage/**",
      "**/generated/**",
      "**/*.generated.js",
      "**/*_generated.js",
      "**/*.min.js",
      "assets/**",
    ],
  },
  {
    files: targetFiles,
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "script",
      globals: {
        ...globals.browser,
      },
    },
    rules: baseRules,
  },
  {
    files: ["web/sw.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "script",
      globals: {
        ...globals.browser,
        ...globals.serviceworker,
      },
    },
    rules: baseRules,
  },
  {
    files: ["eslint.config.js", "**/*.config.js", "scripts/**/*.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "commonjs",
      globals: {
        ...globals.node,
      },
    },
    rules: {
      ...baseRules,
      "no-console": "off",
    },
  },
];
