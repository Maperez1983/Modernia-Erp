'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

function shellQuote(value) {
  return `'${String(value || '').replace(/'/g, `'\\''`)}'`;
}

function resolveChromePath() {
  const candidates = [
    process.env.CHROME_PATH,
    process.env.LHCI_CHROME_PATH,
    process.platform === 'darwin' ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : '',
  ].filter(Boolean);

  for (const candidate of candidates) {
    if (candidate && fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return undefined;
}

function ensureSwClearedUrl(rawUrl, fallbackPort) {
  const fallback = `http://127.0.0.1:${fallbackPort}/?swcleared=1`;
  const candidate = String(rawUrl || '').trim() || fallback;
  try {
    const url = new URL(candidate, fallback);
    url.searchParams.set('swcleared', '1');
    return url.toString();
  } catch {
    return fallback;
  }
}

const defaultPort = Number(process.env.LHCI_PORT || process.env.PORT || 41765);
const resolvedPort = Number.isFinite(defaultPort) && defaultPort > 0 ? defaultPort : 41765;
const tempDir = process.env.LHCI_TMPDIR || path.join(os.tmpdir(), 'lhci-crm-modernia');
const dbPath = process.env.LHCI_DB_PATH || path.join(tempDir, 'lighthouse.sqlite');
const ocrDbPath = process.env.LHCI_OCR_DB_PATH || path.join(tempDir, 'ocr.sqlite');
const uploadsDir = process.env.LHCI_UPLOADS_DIR || path.join(tempDir, 'uploads');
const baseUrl = ensureSwClearedUrl(process.env.LHCI_BASE_URL || `http://127.0.0.1:${resolvedPort}/`, resolvedPort);
const chromePath = resolveChromePath();
const managedServer = String(process.env.LHCI_MANAGED_SERVER || '').trim() === '1';

const startServerCommand = [
  'PYTHONUNBUFFERED=1',
  'APP_DB_BACKEND=sqlite',
  'APP_SUPERADMIN_ENFORCE=0',
  'APP_WORKSPACE_MEMBERSHIP_ENFORCE=0',
  'APP_S3_SCOPE_ENFORCE=0',
  'WORKSPACE_TIME_SWEEP_ENABLED=0',
  'LEGAL_RADAR_AUTO_SCAN_ENABLED=0',
  'LEGAL_RADAR_AUTO_IMPORT_ENABLED=0',
  'APP_PERFORMANCE_LOGGING=0',
  'OCR_WORKERS=1',
  `UPLOADS_DIR=${shellQuote(uploadsDir)}`,
  `DB_PATH=${shellQuote(dbPath)}`,
  `OCR_DB_PATH=${shellQuote(ocrDbPath)}`,
  `python web/server.py --host 127.0.0.1 --port ${resolvedPort} --db ${shellQuote(dbPath)} --ocr-db ${shellQuote(ocrDbPath)} --ocr-workers 1`,
].join(' ');

module.exports = {
  ci: {
    collect: {
      url: [baseUrl],
      numberOfRuns: 3,
      ...(managedServer
        ? {}
        : {
            startServerCommand,
            startServerReadyPattern: 'Servidor activo',
            startServerReadyTimeout: 120000,
          }),
      ...(chromePath ? {chromePath} : {}),
      settings: {
        chromeFlags: '--no-sandbox --disable-crashpad-for-testing --disable-dev-shm-usage --disable-background-networking --disable-breakpad --disable-client-side-phishing-detection --disable-component-update --disable-default-apps --disable-extensions --disable-popup-blocking --disable-renderer-backgrounding --mute-audio --disable-gpu',
      },
    },
    assert: {
      assertions: {
        'categories:performance': ['error', {minScore: 0.3}],
        'categories:accessibility': ['error', {minScore: 1}],
        'categories:best-practices': ['error', {minScore: 0.95}],
        'categories:seo': ['error', {minScore: 0.9}],
        'errors-in-console': ['error', {minScore: 1}],
        'meta-description': ['error', {minScore: 1}],
        redirects: ['error', {minScore: 1}],
        'bootup-time': ['warn', {}],
        'cumulative-layout-shift': ['warn', {}],
        'dom-size': ['warn', {}],
        'first-contentful-paint': ['warn', {}],
        'interactive': ['warn', {}],
        'largest-contentful-paint': ['warn', {}],
        'max-potential-fid': ['warn', {}],
        'offscreen-images': ['warn', {maxLength: 0}],
        'render-blocking-resources': ['warn', {maxLength: 0}],
        'server-response-time': ['warn', {}],
        'speed-index': ['warn', {}],
        'total-byte-weight': ['warn', {}],
        'unminified-css': ['warn', {maxLength: 0}],
        'unminified-javascript': ['warn', {maxLength: 0}],
        'unsized-images': ['warn', {}],
        'unused-css-rules': ['warn', {maxLength: 0}],
        'unused-javascript': ['warn', {maxLength: 0}],
        'uses-text-compression': ['warn', {maxLength: 0}],
        'valid-source-maps': ['warn', {}],
        'bf-cache': ['warn', {}],
      },
    },
    upload: {
      target: 'filesystem',
      outputDir: path.join(tempDir, 'lighthouse-results'),
    },
  },
};
