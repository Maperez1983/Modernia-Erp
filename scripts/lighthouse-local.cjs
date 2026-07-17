#!/usr/bin/env node
'use strict';

const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const {spawn, spawnSync} = require('child_process');

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once('error', reject);
    server.listen({host: '127.0.0.1', port: 0}, () => {
      const address = server.address();
      const port = address && typeof address === 'object' ? address.port : 0;
      server.close((err) => {
        if (err) {
          reject(err);
          return;
        }
        resolve(Number(port || 0));
      });
    });
  });
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
    if (!url.searchParams.has('swcleared')) {
      url.searchParams.set('swcleared', '1');
    }
    return url.toString();
  } catch {
    return fallback;
  }
}

function ensureFile(filePath) {
  fs.mkdirSync(path.dirname(filePath), {recursive: true});
  fs.writeFileSync(filePath, '');
}

function runPythonCode(code, args, env) {
  return spawnSync('python', ['-c', code, ...args], {
    encoding: 'utf8',
    cwd: process.cwd(),
    env,
  });
}

function bootstrapSqliteSchema(dbPath, env) {
  const ensureCode = `
import sys
from web.server import ensure_tables
db_path = sys.argv[1]
ensure_tables(db_path)
print("ok")
`;
  const createTableCode = `
import sqlite3
import sys
db_path = sys.argv[1]
table_name = sys.argv[2]
conn = sqlite3.connect(db_path)
try:
    conn.execute(
        f'''
        CREATE TABLE IF NOT EXISTS "{table_name}" (
          id TEXT PRIMARY KEY,
          nombre TEXT,
          activo INTEGER,
          created_at TEXT,
          updated_at TEXT,
          workspace_id TEXT,
          empresa_id TEXT,
          cliente_id TEXT,
          servicio TEXT,
          slug TEXT,
          estado TEXT,
          plan TEXT,
          descripcion TEXT,
          logo_url TEXT
        )
        '''
    )
    conn.commit()
finally:
    conn.close()
print(table_name)
`;
  for (let attempt = 1; attempt <= 120; attempt += 1) {
    const ensureResult = runPythonCode(ensureCode, [dbPath], env);
    if (ensureResult.status === 0) {
      console.log(`[lighthouse] SQLite bootstrap completado en ${attempt} intentos.`);
      return;
    }
    const output = `${String(ensureResult.stdout || '')}\n${String(ensureResult.stderr || '')}`.trim();
    const missingMatch = output.match(/no such table: (?:main\.)?([A-Za-z_][A-Za-z0-9_]*)/i);
    if (!missingMatch) {
      throw new Error(
        [
          'No se pudo preparar la SQLite temporal para Lighthouse.',
          output ? `Salida: ${output}` : 'Salida vacía.',
        ].join('\n')
      );
    }
    const tableName = missingMatch[1];
    const createResult = runPythonCode(createTableCode, [dbPath, tableName], env);
    if (createResult.status !== 0) {
      const createOutput = `${String(createResult.stdout || '')}\n${String(createResult.stderr || '')}`.trim();
      throw new Error(
        [
          `No se pudo crear la tabla placeholder "${tableName}" para Lighthouse.`,
          createOutput ? `Salida: ${createOutput}` : 'Salida vacía.',
        ].join('\n')
      );
    }
    console.log(`[lighthouse] SQLite bootstrap: creada tabla ${tableName}`);
  }
  throw new Error('No se pudo completar el bootstrap SQLite de Lighthouse tras 120 intentos.');
}

function tailText(text, maxLines = 80) {
  const lines = String(text || '')
    .replace(/\r\n/g, '\n')
    .split('\n')
    .filter((line, index, arr) => !(index === arr.length - 1 && line === ''));
  return lines.slice(Math.max(0, lines.length - maxLines)).join('\n');
}

function curlStatus(url, timeoutSeconds, options = {}) {
  const captureBody = Boolean(options.captureBody);
  const method = String(options.method || 'GET').trim().toUpperCase();
  const result = spawnSync(
    'curl',
    [
      '--silent',
      '--show-error',
      '--max-time',
      String(timeoutSeconds),
      ...(method === 'HEAD' ? ['--head'] : method !== 'GET' ? ['--request', method] : []),
      ...(captureBody
        ? [
            '--output',
            '-',
            '--write-out',
            '\n%{http_code}',
            url,
          ]
        : [
            '--output',
            '/dev/null',
            '--write-out',
            '%{http_code}',
            url,
          ]),
    ],
    {encoding: 'utf8'}
  );

  const rawStdout = String(result.stdout || '');
  const stdout = rawStdout.trim();
  let body = '';
  let code = 0;
  if (captureBody) {
    const separator = rawStdout.lastIndexOf('\n');
    if (separator >= 0) {
      body = rawStdout.slice(0, separator).trim();
      code = Number.parseInt(rawStdout.slice(separator + 1).trim(), 10);
    } else {
      body = rawStdout.trim();
    }
  } else {
    code = Number.parseInt(stdout, 10);
  }
  return {
    url,
    code: Number.isFinite(code) ? code : 0,
    stdout,
    body,
    stderr: String(result.stderr || '').trim(),
    status: typeof result.status === 'number' ? result.status : null,
    signal: result.signal || null,
    error: result.error ? result.error.message : '',
  };
}

function parseHeaderBlocks(headersText) {
  const normalized = String(headersText || '').replace(/\r\n/g, '\n').trim();
  if (!normalized) return [];
  const lines = normalized.split('\n');
  const blocks = [];
  let current = [];
  for (const line of lines) {
    if (!line) {
      if (current.length) {
        blocks.push(current);
        current = [];
      }
      continue;
    }
    if (/^HTTP\/\d(?:\.\d)?\s+\d+/.test(line)) {
      if (current.length) {
        blocks.push(current);
      }
      current = [line];
      continue;
    }
    current.push(line);
  }
  if (current.length) {
    blocks.push(current);
  }
  return blocks.map((block) => {
    const statusLine = block[0] || '';
    const headers = [];
    const headerMap = {};
    for (const line of block.slice(1)) {
      const idx = line.indexOf(':');
      if (idx <= 0) continue;
      const key = line.slice(0, idx).trim();
      const value = line.slice(idx + 1).trim();
      headers.push({key, value});
      const lower = key.toLowerCase();
      if (!Object.prototype.hasOwnProperty.call(headerMap, lower)) {
        headerMap[lower] = value;
      }
    }
    return {statusLine, headers, headerMap};
  });
}

function printHeaderBlocks(url, blocks) {
  if (!blocks.length) {
    console.log(`[lighthouse][diag] ${url} response headers: none captured`);
    return;
  }
  blocks.forEach((block, index) => {
    const label = index === blocks.length - 1 ? 'final' : `redirect-${index + 1}`;
    console.log(`[lighthouse][diag] ${label} response: ${block.statusLine}`);
    block.headers.forEach(({key, value}) => {
      console.log(`[lighthouse][diag]   ${key}: ${value}`);
    });
  });
}

function runCurlDiagnostic(url, timeoutSeconds, tempDir) {
  const diagnosticDir = path.join(tempDir, 'diagnostics');
  fs.mkdirSync(diagnosticDir, {recursive: true});
  const bodyPath = path.join(diagnosticDir, 'audit-body.html');
  const headersPath = path.join(diagnosticDir, 'audit-headers.txt');
  const result = spawnSync(
    'curl',
    [
      '--silent',
      '--show-error',
      '--location',
      '--max-redirs',
      '10',
      '--max-time',
      String(timeoutSeconds),
      '--dump-header',
      headersPath,
      '--output',
      bodyPath,
      '--write-out',
      '%{http_code}\t%{url_effective}\t%{content_type}\t%{size_download}\t%{redirect_url}',
      url,
    ],
    {encoding: 'utf8'}
  );

  const rawStdout = String(result.stdout || '').replace(/\r\n/g, '\n').trim();
  const writeOutParts = rawStdout ? rawStdout.split('\t') : [];
  const code = Number(writeOutParts[0] || 0);
  const effectiveUrl = String(writeOutParts[1] || '').trim();
  const contentType = String(writeOutParts[2] || '').trim();
  const sizeDownload = Number(writeOutParts[3] || 0);
  const redirectUrl = String(writeOutParts[4] || '').trim();
  const headersText = fs.existsSync(headersPath) ? fs.readFileSync(headersPath, 'utf8') : '';
  const bodySize = fs.existsSync(bodyPath) ? fs.statSync(bodyPath).size : 0;
  return {
    url,
    code: Number.isFinite(code) ? code : 0,
    effectiveUrl: effectiveUrl || url,
    contentType: contentType || '',
    sizeDownload: Number.isFinite(sizeDownload) ? sizeDownload : bodySize,
    redirectUrl: redirectUrl || '',
    headersText,
    bodyPath,
    bodySize,
    stderr: String(result.stderr || '').trim(),
    status: typeof result.status === 'number' ? result.status : null,
    signal: result.signal || null,
    error: result.error ? result.error.message : '',
  };
}

async function runBrowserDiagnostic(url, chromePath, tempDir) {
  let puppeteer = null;
  try {
    puppeteer = require('puppeteer-core');
  } catch (error) {
    console.log(
      `[lighthouse][diag] puppeteer-core no disponible, se omite la comprobacion del navegador: ${error?.message || error}`
    );
    return null;
  }
  if (!chromePath) {
    console.log('[lighthouse][diag] Chrome no encontrado, se omite la comprobacion del navegador.');
    return null;
  }

  const flags = [
    '--no-sandbox',
    '--disable-crashpad-for-testing',
    '--disable-dev-shm-usage',
    '--disable-background-networking',
    '--disable-breakpad',
    '--disable-client-side-phishing-detection',
    '--disable-component-update',
    '--disable-default-apps',
    '--disable-extensions',
    '--disable-popup-blocking',
    '--disable-renderer-backgrounding',
    '--mute-audio',
    '--disable-gpu',
  ];

  let browser;
  try {
    browser = await puppeteer.launch({
      executablePath: chromePath,
      headless: true,
      args: flags,
    });
  } catch (error) {
    console.log(`[lighthouse][diag] puppeteer.launch error: ${error?.stack || error?.message || error}`);
    return null;
  }

  try {
    const page = await browser.newPage();
    const initialUrl = url;
    page.on('requestfailed', (request) => {
      const failure = request.failure() || {};
      console.log(
        `[lighthouse][diag] requestfailed ${request.resourceType()} ${request.method()} ${request.url()} ${failure.errorText || failure.error_text || 'requestfailed'}`
      );
    });
    page.on('response', (response) => {
      const request = response.request();
      if (request.resourceType() === 'document' || response.status() >= 300) {
        const headers = response.headers ? response.headers() : {};
        const location = headers.location || headers.Location || '';
        console.log(
          `[lighthouse][diag] response ${response.status()} ${request.resourceType()} ${request.method()} ${request.url()}${location ? ` location=${location}` : ''}`
        );
      }
    });
    page.on('pageerror', (error) => {
      console.log(`[lighthouse][diag] pageerror ${error?.stack || error?.message || error}`);
    });
    page.on('framenavigated', (frame) => {
      if (frame === page.mainFrame()) {
        console.log(`[lighthouse][diag] framenavigated ${frame.url()}`);
      }
    });
    page.on('console', (message) => {
      const type = String(message.type() || '').trim();
      if (!type || type === 'debug' || type === 'log') return;
      console.log(`[lighthouse][diag] console ${type} ${message.text()}`);
    });

    let navigationResponse = null;
    try {
      navigationResponse = await page.goto(url, {waitUntil: 'domcontentloaded', timeout: 30000});
      if (navigationResponse) {
        console.log(
          `[lighthouse][diag] page.goto -> ${navigationResponse.status()} ${navigationResponse.url()}`
        );
      } else {
        console.log('[lighthouse][diag] page.goto -> sin respuesta');
      }
    } catch (error) {
      console.log(`[lighthouse][diag] page.goto error: ${error?.stack || error?.message || error}`);
    }

    await new Promise((resolve) => setTimeout(resolve, 4000));
    const finalUrl = page.url();
    console.log(`[lighthouse][diag] final URL ${finalUrl}`);
    if (finalUrl !== initialUrl && finalUrl.includes('swcleared=1') && !initialUrl.includes('swcleared=1')) {
      console.log(
        '[lighthouse][diag] auto-navigation detected: the shell rewrites / to add swcleared=1 in web/index.html:12124-12130'
      );
    }
    return {initialUrl, finalUrl, navigationResponse: navigationResponse ? navigationResponse.url() : ''};
  } catch (error) {
    console.log(`[lighthouse][diag] browser diagnostic error: ${error?.stack || error?.message || error}`);
    return null;
  } finally {
    if (browser) {
      try {
        await browser.close();
      } catch (error) {
        console.log(`[lighthouse][diag] browser.close error: ${error?.stack || error?.message || error}`);
      }
    }
  }
}

async function runPreLhciDiagnostics({auditUrl, tempDir, chromePath}) {
  console.log(`[lighthouse][diag] GET audit url: ${auditUrl}`);
  const curlResult = runCurlDiagnostic(auditUrl, 15, tempDir);
  const blocks = parseHeaderBlocks(curlResult.headersText);
  const finalBlock = blocks.length ? blocks[blocks.length - 1] : null;
  const contentType = finalBlock?.headerMap?.['content-type'] || curlResult.contentType || 'n/a';
  const contentLength = finalBlock?.headerMap?.['content-length'] || curlResult.bodySize || curlResult.sizeDownload || 'n/a';
  console.log(
    `[lighthouse][diag] curl status=${curlResult.code || curlResult.status || 0} final=${curlResult.effectiveUrl} content-type=${contentType} content-length=${contentLength}`
  );
  if (curlResult.redirectUrl) {
    console.log(`[lighthouse][diag] redirect-url: ${curlResult.redirectUrl}`);
  }
  printHeaderBlocks(auditUrl, blocks);
  console.log(`[lighthouse][diag] body saved to ${curlResult.bodyPath}`);
  await runBrowserDiagnostic(auditUrl, chromePath, tempDir);
}

function describeStatus(result) {
  if (!result) return 'sin respuesta';
  if (result.code === 200) return 'HTTP 200';
  if (result.code > 0) return `HTTP ${result.code}`;
  if (result.error) return `curl error: ${result.error}`;
  if (result.status !== null && result.status !== 0) {
    const suffix = result.stderr ? `: ${result.stderr}` : '';
    return `curl exit ${result.status}${suffix}`;
  }
  return 'HTTP 000';
}

function isHeadUnsupported(result) {
  return Boolean(result && (result.code === 405 || result.code === 501));
}

function spawnServer({port, tempDir, dbPath, ocrDbPath, serverLogPath}) {
  const sharedEnv = {
    PYTHONUNBUFFERED: '1',
    APP_DB_BACKEND: 'sqlite',
    APP_SUPERADMIN_ENFORCE: '0',
    APP_WORKSPACE_MEMBERSHIP_ENFORCE: '0',
    APP_S3_SCOPE_ENFORCE: '0',
    WORKSPACE_TIME_SWEEP_ENABLED: '0',
    LEGAL_RADAR_AUTO_SCAN_ENABLED: '0',
    LEGAL_RADAR_AUTO_IMPORT_ENABLED: '0',
    APP_PERFORMANCE_LOGGING: '0',
    OCR_WORKERS: '1',
    UPLOADS_DIR: path.join(tempDir, 'uploads'),
    DB_PATH: dbPath,
    OCR_DB_PATH: ocrDbPath,
  };
  const env = {
    ...process.env,
    ...sharedEnv,
    LHCI_PORT: String(port),
    LHCI_BASE_URL: ensureSwClearedUrl(`http://127.0.0.1:${port}/`, port),
    LHCI_DB_PATH: dbPath,
    LHCI_OCR_DB_PATH: ocrDbPath,
    LHCI_TMPDIR: tempDir,
    APP_HTTP_COMPRESSION: '1',
  };

  const serverScript = path.join(process.cwd(), 'web', 'server.py');
  const child = spawn(
    'python',
    [serverScript, '--host', '127.0.0.1', '--port', String(port), '--db', dbPath, '--ocr-db', ocrDbPath, '--ocr-workers', '1'],
    {
      cwd: process.cwd(),
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
    }
  );

  const logStream = fs.createWriteStream(serverLogPath, {flags: 'a'});
  let logStreamClosed = false;
  child.stdout.setEncoding('utf8');
  child.stderr.setEncoding('utf8');
  child.stdout.on('data', (chunk) => {
    logStream.write(chunk);
    process.stdout.write(chunk);
  });
  child.stderr.on('data', (chunk) => {
    logStream.write(chunk);
    process.stderr.write(chunk);
  });

  const started = new Promise((resolve, reject) => {
    child.once('spawn', () => {
      resolve({pid: child.pid});
    });
    child.once('error', reject);
  });
  const exited = new Promise((resolve) => {
    child.once('exit', (code, signal) => {
      resolve({code, signal});
    });
  });

  return {
    child,
    env,
    started,
    exited,
    closeLog() {
      if (logStreamClosed) return Promise.resolve();
      logStreamClosed = true;
      return new Promise((resolve) => {
        logStream.end(resolve);
      });
    },
  };
}

async function stopServer(server, opts = {}) {
  if (!server || !server.child) return;
  const child = server.child;
  if (child.exitCode !== null || child.signalCode !== null) {
    try {
      await server.closeLog?.();
    } catch {}
    return;
  }

  const graceMs = Math.max(500, Number(opts.graceMs || 5000) || 5000);
  const killSignal = opts.signal || 'SIGTERM';
  try {
    child.kill(killSignal);
  } catch {}

  const settled = await Promise.race([
    server.exited.then(() => true),
    sleep(graceMs).then(() => false),
  ]);
  if (!settled && child.exitCode === null && child.signalCode === null) {
    try {
      child.kill('SIGKILL');
    } catch {}
    await Promise.race([server.exited.then(() => true), sleep(2000)]);
  }

  try {
    await server.closeLog?.();
  } catch {}
}

async function waitForServer({auditUrl, healthUrl, server, timeoutMs, curlTimeoutSeconds}) {
  const startedAt = Date.now();
  let attempt = 0;
  let lastHealth = null;
  let lastAudit = null;

  while ((Date.now() - startedAt) < timeoutMs) {
    if (server?.child && (server.child.exitCode !== null || server.child.signalCode !== null)) {
      break;
    }

    attempt += 1;
    lastHealth = curlStatus(healthUrl, curlTimeoutSeconds, {captureBody: true});
    let auditDetail = 'pendiente';
    const shouldProbeAudit = lastHealth.code === 200;
    if (shouldProbeAudit) {
      lastAudit = curlStatus(auditUrl, curlTimeoutSeconds, {method: 'HEAD'});
      if (isHeadUnsupported(lastAudit)) {
        auditDetail = 'HEAD no soportado';
      } else {
        auditDetail = describeStatus(lastAudit);
      }
    } else {
      lastAudit = null;
    }
    const elapsedMs = Date.now() - startedAt;
    const remainingMs = Math.max(0, timeoutMs - elapsedMs);
    const elapsedLabel = Math.ceil(elapsedMs / 1000);
    const remainingLabel = Math.ceil(remainingMs / 1000);
    const healthDetail = lastHealth?.body ? ` (${lastHealth.body.slice(0, 120)})` : '';
    console.log(
      `[lighthouse] readiness attempt ${attempt}: health=${describeStatus(lastHealth)}${healthDetail} url=${auditDetail} elapsed=${elapsedLabel}s remaining=${remainingLabel}s`
    );

    if (lastHealth.code === 200 && lastAudit?.code === 200) {
      return {attempt, elapsedMs, lastHealth, lastAudit};
    }

    if (lastHealth.code === 200 && isHeadUnsupported(lastAudit)) {
      console.log(
        '[lighthouse] La ruta auditada no soporta HEAD; se confiará en /api/health y Lighthouse hará la primera carga real.'
      );
      return {attempt, elapsedMs, lastHealth, lastAudit, auditHeadUnsupported: true};
    }

    if (server?.child && (server.child.exitCode !== null || server.child.signalCode !== null)) {
      break;
    }

    const delayMs = Math.min(5000, 1000 + attempt * 500);
    await sleep(delayMs);
  }

  const failure = new Error(
    [
      `La aplicación no devolvió HTTP 200 dentro de ${Math.round(timeoutMs / 1000)}s.`,
      `Health check: ${describeStatus(lastHealth)}`,
      `URL auditada: ${describeStatus(lastAudit)}`,
    ].join('\n')
  );
  failure.lastHealth = lastHealth;
  failure.lastAudit = lastAudit;
  throw failure;
}

function runCommand(command, args, env) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: process.cwd(),
      env,
      stdio: 'inherit',
    });

    child.once('error', reject);
    child.once('exit', (code, signal) => {
      if (code === 0) {
        resolve({code, signal});
        return;
      }
      const error = new Error(
        `${command} ${args.join(' ')} terminó con código ${typeof code === 'number' ? code : 1}${signal ? ` (signal ${signal})` : ''}`
      );
      error.code = code;
      error.signal = signal;
      reject(error);
    });
  });
}

(async () => {
  const port = await getFreePort();
  if (!port) {
    throw new Error('No se pudo reservar un puerto libre para Lighthouse.');
  }

  const tempDir = process.env.LHCI_TMPDIR
    ? path.resolve(process.env.LHCI_TMPDIR)
    : fs.mkdtempSync(path.join(os.tmpdir(), 'lhci-'));
  fs.mkdirSync(tempDir, {recursive: true});

  const dbPath = path.join(tempDir, 'lighthouse.sqlite');
  const ocrDbPath = path.join(tempDir, 'ocr.sqlite');
  const uploadsDir = path.join(tempDir, 'uploads');
  ensureFile(dbPath);
  ensureFile(ocrDbPath);
  fs.mkdirSync(uploadsDir, {recursive: true});

  const rawAuditUrl = process.env.LHCI_BASE_URL || `http://127.0.0.1:${port}/`;
  const auditUrl = ensureSwClearedUrl(rawAuditUrl, port);
  const healthUrl = `http://127.0.0.1:${port}/api/health`;
  const chromePath = resolveChromePath();
  const diagnosticsEnabled = String(process.env.LHCI_DIAGNOSTIC || '').trim() === '1';
  const sharedDbEnv = {
    ...process.env,
    PYTHONUNBUFFERED: '1',
    APP_DB_BACKEND: 'sqlite',
    APP_SUPERADMIN_ENFORCE: '0',
    APP_WORKSPACE_MEMBERSHIP_ENFORCE: '0',
    APP_S3_SCOPE_ENFORCE: '0',
    WORKSPACE_TIME_SWEEP_ENABLED: '0',
    LEGAL_RADAR_AUTO_SCAN_ENABLED: '0',
    LEGAL_RADAR_AUTO_IMPORT_ENABLED: '0',
    APP_PERFORMANCE_LOGGING: '0',
    OCR_WORKERS: '1',
    UPLOADS_DIR: uploadsDir,
    DB_PATH: dbPath,
    OCR_DB_PATH: ocrDbPath,
  };
  bootstrapSqliteSchema(dbPath, sharedDbEnv);
  const baseEnv = {
    ...sharedDbEnv,
    LHCI_PORT: String(port),
    LHCI_BASE_URL: auditUrl,
    LHCI_DB_PATH: dbPath,
    LHCI_OCR_DB_PATH: ocrDbPath,
    LHCI_TMPDIR: tempDir,
    LHCI_MANAGED_SERVER: '1',
    APP_HTTP_COMPRESSION: '1',
  };
  console.log(`Lighthouse temp dir: ${tempDir}`);
  console.log(`Lighthouse server log: ${path.join(tempDir, 'lighthouse-server.log')}`);
  if (String(rawAuditUrl).trim() !== String(auditUrl).trim()) {
    console.log(`[lighthouse] audit URL normalized: ${rawAuditUrl} -> ${auditUrl}`);
  }
  console.log(`Lighthouse base URL: ${auditUrl}`);

  const server = spawnServer({
    port,
    tempDir,
    dbPath,
    ocrDbPath,
    serverLogPath: path.join(tempDir, 'lighthouse-server.log'),
  });

  let shuttingDown = false;
  const shutdown = async (exitCode, signal, error) => {
    if (shuttingDown) return;
    shuttingDown = true;
    try {
      await stopServer(server, {signal: signal || 'SIGTERM'});
    } catch (stopError) {
      if (stopError) {
        console.error(stopError.stack || stopError);
      }
    }
    if (error) {
      console.error(error.stack || error);
    }
    if (typeof exitCode === 'number') {
      process.exit(exitCode);
    }
    process.exit(1);
  };

  process.once('SIGINT', () => {
    void shutdown(130, 'SIGINT');
  });
  process.once('SIGTERM', () => {
    void shutdown(143, 'SIGTERM');
  });
  process.once('uncaughtException', (error) => {
    void shutdown(1, 'SIGTERM', error);
  });
  process.once('unhandledRejection', (reason) => {
    void shutdown(1, 'SIGTERM', reason instanceof Error ? reason : new Error(String(reason || 'Unhandled rejection')));
  });

  try {
    await server.started;

    const ready = await waitForServer({
      auditUrl,
      healthUrl,
      server,
      timeoutMs: 300000,
      curlTimeoutSeconds: 5,
    });

    console.log(
      `[lighthouse] servidor listo tras ${Math.ceil(ready.elapsedMs / 1000)}s y ${ready.attempt} comprobaciones.`
    );

    if (diagnosticsEnabled) {
      console.log('[lighthouse] Pre-LHCI diagnostics enabled.');
      await runPreLhciDiagnostics({auditUrl, tempDir, chromePath});
      console.log('[lighthouse] Pre-LHCI diagnostics completed.');
    }

    await runCommand('npx', ['--no-install', 'lhci', 'autorun'], baseEnv);
  } catch (error) {
    const tail = (() => {
      try {
        const logPath = path.join(tempDir, 'lighthouse-server.log');
        return tailText(fs.readFileSync(logPath, 'utf8'));
      } catch {
        return '';
      }
    })();
    if (tail) {
      console.error('--- Server log tail ---');
      console.error(tail);
      console.error('--- End server log tail ---');
    }

    const enhanced = error instanceof Error ? error : new Error(String(error || 'Error desconocido'));
    if (!enhanced.message.includes('Lighthouse')) {
      enhanced.message = `Lighthouse local falló: ${enhanced.message}`;
    }
    throw enhanced;
  } finally {
    await stopServer(server);
  }
})().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
