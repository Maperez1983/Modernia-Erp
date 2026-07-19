#!/usr/bin/env node
'use strict';

const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const {StringDecoder} = require('node:string_decoder');
const {spawn, spawnSync} = require('child_process');
const {ensureSwClearedUrl} = require('./lighthouse-url.cjs');
const {
  captureProcFdListing: captureChromeCleanFdListing,
  runChromeFdInheritanceCase,
} = require('./chrome-clean-launcher.cjs');

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

function resolveSchemaSqlPath(tempDir) {
  const localSchemaPath = path.join(process.cwd(), 'schema.sql');
  if (fs.existsSync(localSchemaPath)) {
    return localSchemaPath;
  }

  const findSchemaCommit = () => {
    const revListResult = spawnSync('git', ['rev-list', '--all', '--', 'schema.sql'], {
      cwd: process.cwd(),
      env: process.env,
      encoding: 'utf8',
      timeout: 120000,
      killSignal: 'SIGKILL',
    });
    if (revListResult.status !== 0) {
      return null;
    }
    const commits = String(revListResult.stdout || '')
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    for (const commit of commits) {
      const showResult = spawnSync('git', ['show', `${commit}:schema.sql`], {
        cwd: process.cwd(),
        env: process.env,
        encoding: 'utf8',
        timeout: 120000,
        killSignal: 'SIGKILL',
      });
      if (showResult.status === 0 && String(showResult.stdout || '').trim()) {
        return {
          commit,
          content: String(showResult.stdout || ''),
        };
      }
    }
    return null;
  };

  let schemaSource = findSchemaCommit();
  if (!schemaSource) {
    const shallowProbe = spawnSync('git', ['rev-parse', '--is-shallow-repository'], {
      cwd: process.cwd(),
      env: process.env,
      encoding: 'utf8',
      timeout: 30000,
      killSignal: 'SIGKILL',
    });
    const isShallow = shallowProbe.status === 0 && String(shallowProbe.stdout || '').trim() === 'true';
    if (isShallow) {
      const fetchAttempts = [
        ['fetch', '--unshallow', '--tags', 'origin'],
        ['fetch', '--deepen=2000', '--tags', 'origin'],
      ];
      for (const args of fetchAttempts) {
        const fetchResult = spawnSync('git', args, {
          cwd: process.cwd(),
          env: process.env,
          encoding: 'utf8',
          timeout: 180000,
          killSignal: 'SIGKILL',
        });
        if (fetchResult.status === 0) {
          schemaSource = findSchemaCommit();
          if (schemaSource) {
            break;
          }
        }
      }
    }
  }

  if (!schemaSource) {
    return null;
  }

  const schemaPath = path.join(tempDir, 'schema.sql');
  fs.writeFileSync(schemaPath, schemaSource.content, 'utf8');
  console.log(`[lighthouse] schema.sql recuperado desde git (${schemaSource.commit}).`);
  return schemaPath;
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
  const schemaSourcePath = resolveSchemaSqlPath(path.dirname(dbPath));
  if (!schemaSourcePath) {
    console.warn(
      '[lighthouse] No se pudo recuperar schema.sql desde el árbol actual ni desde git; se continúa sin bootstrap SQLite temporal.'
    );
    return;
  }

  const applySchemaCode = `
import sys
from web.schema_support import apply_schema_file
from web.server import open_sqlite_conn
db_path = sys.argv[1]
schema_path = sys.argv[2]
conn = open_sqlite_conn(db_path, with_row_factory=True)
try:
    applied = apply_schema_file(conn, schema_path)
    conn.commit()
    print("applied" if applied else "missing")
finally:
    conn.close()
`;
  const applyResult = runPythonCode(applySchemaCode, [dbPath, schemaSourcePath], env);
  if (applyResult.status !== 0) {
    const applyOutput = `${String(applyResult.stdout || '')}\n${String(applyResult.stderr || '')}`.trim();
    throw new Error(
      [
        'No se pudo aplicar el esquema real de SQLite para Lighthouse.',
        applyOutput ? `Salida: ${applyOutput}` : 'Salida vacía.',
      ].join('\n')
    );
  }

  const ensureCode = `
import sys
from web.server import ensure_tables
db_path = sys.argv[1]
ensure_tables(db_path)
print("ok")
`;
  const ensureResult = runPythonCode(ensureCode, [dbPath], env);
  if (ensureResult.status !== 0) {
    const output = `${String(ensureResult.stdout || '')}\n${String(ensureResult.stderr || '')}`.trim();
    throw new Error(
      [
        'No se pudo completar el bootstrap SQLite de Lighthouse con el esquema real.',
        output ? `Salida: ${output}` : 'Salida vacía.',
      ].join('\n')
    );
  }
  console.log('[lighthouse] SQLite bootstrap completado con el esquema real.');
}

function tailText(text, maxLines = 80) {
  const lines = String(text || '')
    .replace(/\r\n/g, '\n')
    .split('\n')
    .filter((line, index, arr) => !(index === arr.length - 1 && line === ''));
  return lines.slice(Math.max(0, lines.length - maxLines)).join('\n');
}

function readDiagnosticFileText(filePath) {
  try {
    return String(fs.readFileSync(filePath, 'utf8') || '');
  } catch {
    return '';
  }
}

function createSanitizedConsoleLineWriter(writeFn) {
  const decoder = new StringDecoder('utf8');
  let buffer = '';
  let closed = false;
  let decoderFinished = false;

  const emit = (line, newline = '') => {
    try {
      writeFn(`${sanitizeDiagnosticText(line)}${newline}`);
    } catch {}
  };

  const drainBufferedLines = () => {
    let newlineIndex = buffer.indexOf('\n');
    while (newlineIndex !== -1) {
      const hasCarriageReturn = newlineIndex > 0 && buffer.charCodeAt(newlineIndex - 1) === 13;
      const line = buffer.slice(0, hasCarriageReturn ? newlineIndex - 1 : newlineIndex);
      const newline = hasCarriageReturn ? '\r\n' : '\n';
      emit(line, newline);
      buffer = buffer.slice(newlineIndex + 1);
      newlineIndex = buffer.indexOf('\n');
    }
  };

  const appendDecodedText = (text) => {
    if (!text) return;
    buffer += text;
    drainBufferedLines();
  };

  const decodeChunk = (chunk) => {
    if (typeof chunk === 'string') {
      return chunk;
    }
    if (Buffer.isBuffer(chunk) || ArrayBuffer.isView(chunk)) {
      return decoder.write(chunk);
    }
    return String(chunk ?? '');
  };

  return {
    write(chunk) {
      if (closed) return;
      appendDecodedText(decodeChunk(chunk));
    },
    flush() {
      if (closed) return;
      drainBufferedLines();
    },
    finish() {
      if (closed) return;
      if (!decoderFinished) {
        appendDecodedText(decoder.end());
        decoderFinished = true;
      }
      drainBufferedLines();
      if (buffer) {
        emit(buffer);
        buffer = '';
      }
      closed = true;
    },
  };
}

function removeStreamListener(stream, eventName, handler) {
  if (!stream) return;
  if (typeof stream.off === 'function') {
    stream.off(eventName, handler);
    return;
  }
  if (typeof stream.removeListener === 'function') {
    stream.removeListener(eventName, handler);
  }
}

function attachSanitizedConsoleStream(stream, writeFn) {
  const writer = createSanitizedConsoleLineWriter(writeFn);
  let ended = false;
  let settled = false;
  let resolveDone;
  const done = new Promise((resolve) => {
    resolveDone = resolve;
  });

  function onData(chunk) {
    writer.write(chunk);
  }

  function cleanup() {
    removeStreamListener(stream, 'data', onData);
    removeStreamListener(stream, 'end', onEnd);
    removeStreamListener(stream, 'close', onClose);
  }

  function settle(reason) {
    if (settled) return reason;
    settled = true;
    writer.finish();
    cleanup();
    resolveDone(reason);
    return reason;
  }

  function onEnd() {
    ended = true;
    settle('end');
  }

  function onClose() {
    settle(ended ? 'close-after-end' : 'close');
  }

  if (stream && typeof stream.on === 'function') {
    stream.on('data', onData);
    stream.once('end', onEnd);
    stream.once('close', onClose);
  }

  return {
    done,
    finish(reason = 'forced') {
      return settle(reason);
    },
    flushPending() {
      writer.flush();
    },
    isDone() {
      return settled;
    },
    hasEnded() {
      return ended;
    },
  };
}

function createBufferedLineCollector(onLine) {
  const decoder = new StringDecoder('utf8');
  let buffer = '';
  let closed = false;

  const emit = (line) => {
    try {
      onLine(line);
    } catch {}
  };

  const drain = () => {
    let newlineIndex = buffer.indexOf('\n');
    while (newlineIndex !== -1) {
      const line = buffer.slice(0, newlineIndex).replace(/\r$/, '');
      emit(line);
      buffer = buffer.slice(newlineIndex + 1);
      newlineIndex = buffer.indexOf('\n');
    }
  };

  return {
    write(chunk) {
      if (closed) return;
      const text = typeof chunk === 'string' ? chunk : decoder.write(chunk);
      if (!text) return;
      buffer += text;
      drain();
    },
    finish() {
      if (closed) return;
      const tail = decoder.end();
      if (tail) {
        buffer += tail;
      }
      drain();
      if (buffer) {
        emit(buffer);
        buffer = '';
      }
      closed = true;
    },
  };
}

function attachRawLogCapture(child, logStream) {
  let logStreamClosed = false;
  let stdoutCapturing = false;
  let stderrCapturing = false;

  function onStdoutLogData(chunk) {
    if (!stdoutCapturing || logStreamClosed) return;
    logStream.write(chunk);
  }

  function onStderrLogData(chunk) {
    if (!stderrCapturing || logStreamClosed) return;
    logStream.write(chunk);
  }

  function stopStdoutCapture() {
    if (!stdoutCapturing) return;
    stdoutCapturing = false;
    removeStreamListener(child?.stdout, 'data', onStdoutLogData);
    removeStreamListener(child?.stdout, 'end', stopStdoutCapture);
    removeStreamListener(child?.stdout, 'close', stopStdoutCapture);
  }

  function stopStderrCapture() {
    if (!stderrCapturing) return;
    stderrCapturing = false;
    removeStreamListener(child?.stderr, 'data', onStderrLogData);
    removeStreamListener(child?.stderr, 'end', stopStderrCapture);
    removeStreamListener(child?.stderr, 'close', stopStderrCapture);
  }

  if (child?.stdout && typeof child.stdout.on === 'function') {
    stdoutCapturing = true;
    child.stdout.on('data', onStdoutLogData);
    child.stdout.once('end', stopStdoutCapture);
    child.stdout.once('close', stopStdoutCapture);
  }

  if (child?.stderr && typeof child.stderr.on === 'function') {
    stderrCapturing = true;
    child.stderr.on('data', onStderrLogData);
    child.stderr.once('end', stopStderrCapture);
    child.stderr.once('close', stopStderrCapture);
  }

  const stop = () => {
    stopStdoutCapture();
    stopStderrCapture();
  };

  const closeLog = () => {
    if (logStreamClosed) return Promise.resolve();
    logStreamClosed = true;
    stop();
    return new Promise((resolve, reject) => {
      try {
        logStream.end(resolve);
      } catch (error) {
        reject(error);
      }
    });
  };

  return {
    stop,
    closeLog,
    isClosed() {
      return logStreamClosed;
    },
    isStdoutCapturing() {
      return stdoutCapturing;
    },
    isStderrCapturing() {
      return stderrCapturing;
    },
  };
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

function createNavigationDiagnosticRecorder(tempDir) {
  const diagnosticPath = path.join(tempDir, 'navigation-diagnostic.log');
  fs.mkdirSync(path.dirname(diagnosticPath), {recursive: true});
  try {
    fs.writeFileSync(diagnosticPath, '');
  } catch {}

  let seq = 0;
  const startedAt = Date.now();

  const record = (event, data = {}) => {
    const sanitizedData = sanitizeDiagnosticValue(data);
    const entry = {
      seq: ++seq,
      ts: new Date().toISOString(),
      elapsedMs: Date.now() - startedAt,
      event,
      ...sanitizedData,
    };
    try {
      fs.appendFileSync(diagnosticPath, `${JSON.stringify(entry)}\n`);
    } catch (error) {
      console.log(
        `[lighthouse][diag] no se pudo escribir ${diagnosticPath}: ${error?.stack || error?.message || error}`
      );
    }
    return entry;
  };

  return {diagnosticPath, record};
}

const DIAGNOSTIC_REDACTED_VALUE = 'REDACTED';
const DIAGNOSTIC_SENSITIVE_PARAM_NAMES = new Set([
  'accesstoken',
  'apikey',
  'authtoken',
  'auth',
  'authorization',
  'bearertoken',
  'clientid',
  'clientsecret',
  'code',
  'cookie',
  'csrftoken',
  'idtoken',
  'jwt',
  'jwttoken',
  'oauthtoken',
  'key',
  'pass',
  'passwd',
  'password',
  'privatekey',
  'publickey',
  'refreshtoken',
  'secret',
  'session',
  'sessionid',
  'sessiontoken',
  'signedurl',
  'sig',
  'signature',
  'state',
  'token',
  'xsrftoken',
]);
const DIAGNOSTIC_OMIT_KEYS = new Set(['body', 'bodypath', 'headers', 'headerspath', 'headerstext', 'responseblocks']);

function normalizeDiagnosticParamName(name) {
  return String(name || '')
    .trim()
    .replace(/[_-]+/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .toLowerCase()
    .replace(/\s+/g, ' ');
}

function isSensitiveDiagnosticParamName(name) {
  const collapsed = normalizeDiagnosticParamName(name).replace(/\s+/g, '');
  if (!collapsed || collapsed === 'swcleared') {
    return false;
  }
  return DIAGNOSTIC_SENSITIVE_PARAM_NAMES.has(collapsed);
}

function redactSensitiveDiagnosticQueryParams(text) {
  return String(text || '').replace(/(^|[^A-Za-z0-9._-])([A-Za-z0-9._-]+)=([^\s&#"'`<>]+)/g, (match, prefix, key, value) => {
    if (!isSensitiveDiagnosticParamName(key)) {
      return match;
    }
    return `${prefix}${key}=${DIAGNOSTIC_REDACTED_VALUE}`;
  });
}

function sanitizeDiagnosticText(value) {
  let text = String(value || '');
  if (!text) return '';
  text = text.replace(/\b(authorization|proxy-authorization|cookie|set-cookie)\s*:\s*[^\r\n]+/gi, (match) => {
    const idx = match.indexOf(':');
    return `${match.slice(0, idx + 1)} ${DIAGNOSTIC_REDACTED_VALUE}`;
  });
  text = text.replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, `Bearer ${DIAGNOSTIC_REDACTED_VALUE}`);
  text = text.replace(/https?:\/\/[^\s"'<>`]+/gi, (match) => sanitizeDiagnosticUrl(match));
  text = redactSensitiveDiagnosticQueryParams(text);
  return text;
}

function sanitizeDiagnosticUrl(rawUrl) {
  const candidate = String(rawUrl || '').trim();
  if (!candidate) return '';
  try {
    const url = new URL(candidate);
    url.username = '';
    url.password = '';
    const searchKeys = Array.from(url.searchParams.keys());
    for (const key of searchKeys) {
      if (isSensitiveDiagnosticParamName(key)) {
        url.searchParams.set(key, DIAGNOSTIC_REDACTED_VALUE);
      }
    }
    const hash = String(url.hash || '').replace(/^#/, '');
    if (hash && hash.includes('=')) {
      const hashParams = new URLSearchParams(hash);
      const hashKeys = Array.from(hashParams.keys());
      for (const key of hashKeys) {
        if (isSensitiveDiagnosticParamName(key)) {
          hashParams.set(key, DIAGNOSTIC_REDACTED_VALUE);
        }
      }
      const sanitizedHash = hashParams.toString();
      url.hash = sanitizedHash ? `#${sanitizedHash}` : '';
    }
    return url.toString();
  } catch {
    return sanitizeDiagnosticText(candidate);
  }
}

function sanitizeDiagnosticValue(value, key = '') {
  if (value === null || value === undefined) {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeDiagnosticValue(item, key));
  }
  if (typeof value === 'object') {
    const out = {};
    for (const [childKey, childValue] of Object.entries(value)) {
      const childKeyLower = String(childKey || '').toLowerCase();
      if (DIAGNOSTIC_OMIT_KEYS.has(childKeyLower)) {
        continue;
      }
      out[childKey] = sanitizeDiagnosticValue(childValue, childKey);
    }
    return out;
  }
  if (typeof value === 'string') {
    const lowerKey = String(key || '').toLowerCase();
    if (
      lowerKey.includes('url') ||
      lowerKey === 'location' ||
      lowerKey === 'targeturl' ||
      lowerKey === 'redirecturl' ||
      lowerKey === 'frameurl'
    ) {
      return sanitizeDiagnosticUrl(value);
    }
    return sanitizeDiagnosticText(value);
  }
  return value;
}

const DIAGNOSTIC_PROXY_ENV_KEYS = [
  'ALL_PROXY',
  'HTTPS_PROXY',
  'HTTP_PROXY',
  'NO_PROXY',
  'all_proxy',
  'https_proxy',
  'http_proxy',
  'no_proxy',
];

function normalizeDiagnosticProxyValue(rawValue) {
  const value = String(rawValue || '').trim();
  if (!value) return '';

  const candidate = /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(value) ? value : `http://${value}`;
  try {
    const url = new URL(candidate);
    url.username = '';
    url.password = '';
    url.search = '';
    url.hash = '';
    return `${url.protocol}//${url.host}`;
  } catch {
    return sanitizeDiagnosticText(value);
  }
}

function collectDiagnosticEnvironmentSummary(env = process.env) {
  const proxyEnv = {};
  for (const key of DIAGNOSTIC_PROXY_ENV_KEYS) {
    const rawValue = env ? env[key] : undefined;
    proxyEnv[key] = {
      defined: rawValue !== undefined && rawValue !== null && String(rawValue).trim() !== '',
      value:
        String(key).toLowerCase().includes('no_proxy')
          ? sanitizeDiagnosticText(rawValue)
          : normalizeDiagnosticProxyValue(rawValue),
    };
  }

  return {
    platform: process.platform,
    arch: process.arch,
    nodeVersion: process.version,
    proxyEnv,
  };
}

function invertDiagnosticMap(map) {
  const out = new Map();
  if (!map || typeof map !== 'object') return out;
  for (const [key, value] of Object.entries(map)) {
    if (typeof value === 'number' || typeof value === 'string') {
      out.set(value, key);
    }
  }
  return out;
}

function getDiagnosticNetLogEventName(constants, event) {
  const eventType = event && Object.prototype.hasOwnProperty.call(event, 'type') ? event.type : null;
  const candidates = [
    constants?.logEventTypes,
    constants?.eventTypes,
    constants?.logEventType,
  ].filter(Boolean);
  for (const candidate of candidates) {
    const reverse = invertDiagnosticMap(candidate);
    if (reverse.has(eventType)) {
      return reverse.get(eventType);
    }
  }
  return String(eventType ?? '');
}

function getDiagnosticNetLogSourceName(constants, source) {
  const sourceType = source && Object.prototype.hasOwnProperty.call(source, 'type') ? source.type : null;
  const candidates = [
    constants?.logSourceType,
    constants?.sourceType,
    constants?.sourceTypes,
  ].filter(Boolean);
  for (const candidate of candidates) {
    const reverse = invertDiagnosticMap(candidate);
    if (reverse.has(sourceType)) {
      return reverse.get(sourceType);
    }
  }
  return String(sourceType ?? '');
}

function sanitizeDiagnosticNetLogValue(value) {
  return sanitizeDiagnosticValue(value);
}

function sanitizeDiagnosticNetLogEvent(constants, event, auditUrl) {
  const eventName = getDiagnosticNetLogEventName(constants, event);
  const sourceType = getDiagnosticNetLogSourceName(constants, event?.source || {});
  const params = sanitizeDiagnosticNetLogValue(event?.params || {});
  return {
    time: event?.time || 0,
    type: eventName,
    sourceType,
    phase: event?.phase ?? null,
    source: sanitizeDiagnosticNetLogValue(event?.source || {}),
    params,
    matchesAuditUrl:
      auditUrl && JSON.stringify({eventName, sourceType, params}).includes(sanitizeDiagnosticUrl(auditUrl)),
  };
}

function summarizeDiagnosticNetLog(parsedNetLog, auditUrl, meta = {}) {
  const constants = parsedNetLog?.constants || {};
  const events = Array.isArray(parsedNetLog?.events) ? parsedNetLog.events : [];
  const highlights = [];
  const categories = {
    proxyResolution: [],
    dnsResolution: [],
    socketEvents: [],
    urlRequestEvents: [],
    abortEvents: [],
  };
  let lastRelevantEvent = null;

  for (const event of events) {
    const entry = sanitizeDiagnosticNetLogEvent(constants, event, auditUrl);
    const typeName = String(entry.type || '').toUpperCase();
    const paramsText = JSON.stringify(entry.params || {});
    const interesting =
      entry.matchesAuditUrl ||
      /URL_REQUEST|HOST_RESOLVER|DNS|PROXY|SOCKET|TCP_CONNECT|CONNECT|CANCEL|ABORT|ERR_|REQUEST/i.test(typeName) ||
      /net[_-]?error|error|reason|address|proxy|host|url/i.test(paramsText);
    if (!interesting) {
      continue;
    }

    const compact = {
      time: entry.time,
      type: entry.type,
      sourceType: entry.sourceType,
      phase: entry.phase,
      params: entry.params,
    };
    highlights.push(compact);
    lastRelevantEvent = compact;

    if (/PROXY/i.test(typeName) || /proxy/i.test(paramsText)) {
      categories.proxyResolution.push(compact);
    }
    if (/HOST_RESOLVER|DNS/i.test(typeName) || /dns|resolved|host/i.test(paramsText)) {
      categories.dnsResolution.push(compact);
    }
    if (/SOCKET|TCP_CONNECT|CONNECT/i.test(typeName) || /socket|address|port/i.test(paramsText)) {
      categories.socketEvents.push(compact);
    }
    if (/URL_REQUEST|REQUEST/i.test(typeName) || entry.matchesAuditUrl) {
      categories.urlRequestEvents.push(compact);
    }
    if (/CANCEL|ABORT|ERR_/i.test(typeName) || /net[_-]?error|error/i.test(paramsText)) {
      categories.abortEvents.push(compact);
      lastRelevantEvent = compact;
    }
  }

  return {
    ...meta,
    auditUrl: sanitizeDiagnosticUrl(auditUrl),
    eventCount: events.length,
    highlights: highlights.slice(0, 100),
    lastRelevantEvent,
    ...categories,
  };
}

function createNetLogSummaryArtifacts(tempDir) {
  const jsonPath = path.join(tempDir, 'lighthouse-netlog-summary.json');
  const logPath = path.join(tempDir, 'lighthouse-netlog-summary.log');
  fs.mkdirSync(path.dirname(jsonPath), {recursive: true});
  try {
    fs.writeFileSync(jsonPath, '');
  } catch {}
  try {
    fs.writeFileSync(logPath, '');
  } catch {}

  const createdAt = new Date().toISOString();
  const summary = {
    generatedAt: createdAt,
    jsonPath,
    logPath,
    entries: [],
    exitCode: 0,
  };
  const recorder = createJsonlArtifactRecorder(logPath);

  const writeSummary = () => {
    try {
      fs.writeFileSync(jsonPath, `${JSON.stringify(summary, null, 2)}\n`);
    } catch (error) {
      console.log(
        `[lighthouse][diag] no se pudo escribir ${jsonPath}: ${error?.stack || error?.message || error}`
      );
    }
  };

  writeSummary();

  const recordEntry = (event, data = {}) => {
    const entry = recorder.record(event, data);
    summary.entries.push(entry);
    summary.exitCode = summary.exitCode || Number(data?.exitCode || 0) || 0;
    writeSummary();
    return entry;
  };

  return {
    jsonPath,
    logPath,
    summary,
    recordEntry,
    writeSummary,
  };
}

function recordDiagnosticFileBootstrap(filePath) {
  if (!filePath) return;
  try {
    fs.mkdirSync(path.dirname(filePath), {recursive: true});
    fs.writeFileSync(filePath, '');
  } catch {}
}

function readDiagnosticJsonlEntries(filePath) {
  try {
    if (!filePath || !fs.existsSync(filePath)) {
      return [];
    }
    const text = String(fs.readFileSync(filePath, 'utf8') || '');
    if (!text.trim()) {
      return [];
    }
    return text
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        try {
          return JSON.parse(line);
        } catch (error) {
          return {
            event: 'parse-error',
            message: sanitizeDiagnosticText(error?.message || String(error || 'Invalid JSONL line')),
            raw: sanitizeDiagnosticText(line.slice(0, 2000)),
          };
        }
      });
  } catch {
    return [];
  }
}

function summarizeDiagnosticServerObservations(entries, targetUrl = '') {
  const sanitizedTargetUrl = sanitizeDiagnosticUrl(targetUrl);
  const matchingEntries = Array.isArray(entries) ? entries.filter(Boolean) : [];
  const lastEntry = matchingEntries.length ? matchingEntries[matchingEntries.length - 1] : null;
  const counts = matchingEntries.reduce(
    (acc, entry) => {
      const event = String(entry?.event || '').toLowerCase();
      if (event === 'tcp-accept') acc.tcpAccept += 1;
      if (event === 'request-start') acc.requestStart += 1;
      if (event === 'request-finish') acc.requestFinish += 1;
      if (event === 'request-error') acc.requestError += 1;
      if (event === 'send-response') acc.sendResponse += 1;
      if (event === 'end-headers') acc.endHeaders += 1;
      if (event === 'socket-close') acc.socketClose += 1;
      if (event === 'error') acc.error += 1;
      return acc;
    },
    {
      tcpAccept: 0,
      requestStart: 0,
      requestFinish: 0,
      requestError: 0,
      sendResponse: 0,
      endHeaders: 0,
      socketClose: 0,
      error: 0,
    }
  );
  return {
    targetUrl: sanitizedTargetUrl,
    eventCount: matchingEntries.length,
    counts,
    serverReceived: counts.requestStart > 0 || counts.sendResponse > 0 || counts.endHeaders > 0,
    lastEvent: lastEntry ? sanitizeDiagnosticValue(lastEntry) : null,
    events: matchingEntries.slice(-100).map((entry) => sanitizeDiagnosticValue(entry)),
  };
}

function readDiagnosticNetLog(filePath, auditUrl, meta = {}) {
  const result = {
    path: filePath,
    exists: Boolean(filePath && fs.existsSync(filePath)),
    size: 0,
    error: '',
    summary: null,
    rawPreview: '',
  };
  if (!result.exists) {
    result.error = 'missing';
    return result;
  }
  try {
    const text = String(fs.readFileSync(filePath, 'utf8') || '');
    result.size = Buffer.byteLength(text, 'utf8');
    if (!text.trim()) {
      result.error = 'empty';
      return result;
    }
    const parsed = JSON.parse(text);
    result.summary = summarizeDiagnosticNetLog(parsed, auditUrl, meta);
    return result;
  } catch (error) {
    try {
      const text = String(fs.readFileSync(filePath, 'utf8') || '');
      result.size = Buffer.byteLength(text, 'utf8');
      result.rawPreview = sanitizeDiagnosticText(text.slice(0, 2000));
    } catch {}
    result.error = sanitizeDiagnosticText(error?.message || String(error || 'Unknown netlog error'));
    return result;
  }
}

function extractCurlConnectionSummary(stderr) {
  const lines = String(stderr || '')
    .replace(/\r\n/g, '\n')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
  const connectedLine = lines.find((line) => /\* Connected to /i.test(line)) || '';
  const proxyLine =
    lines.find((line) => /\* Uses proxy env variable /i.test(line)) ||
    lines.find((line) => /\* proxy /i.test(line)) ||
    '';
  const matched = connectedLine.match(/\* Connected to ([^\s(]+) \(([^)]+)\) port (\d+)/i);
  return {
    connectedLine: sanitizeDiagnosticText(connectedLine),
    proxyLine: sanitizeDiagnosticText(proxyLine),
    remoteName: matched ? matched[1] : '',
    remoteAddress: matched ? matched[2] : '',
    remotePort: matched ? Number(matched[3]) || null : null,
    usesProxy: /proxy/i.test(proxyLine),
  };
}

function runVerboseCurlProbe(url, timeoutSeconds, options = {}) {
  const start = Date.now();
  const args = [
    '--silent',
    '--show-error',
    '--verbose',
    '--max-time',
    String(timeoutSeconds),
    ...(options.noproxy ? ['--noproxy', '*'] : []),
    '--output',
    '/dev/null',
    '--write-out',
    '\n%{http_code}',
    url,
  ];
  const result = spawnSync('curl', args, {encoding: 'utf8'});
  const rawStdout = String(result.stdout || '');
  const rawStderr = String(result.stderr || '');
  const stdout = sanitizeDiagnosticText(rawStdout.trim());
  const stderr = sanitizeDiagnosticText(rawStderr.trim());
  const connection = extractCurlConnectionSummary(rawStderr);
  let httpCode = 0;
  const separator = rawStdout.lastIndexOf('\n');
  if (separator >= 0) {
    httpCode = Number.parseInt(rawStdout.slice(separator + 1).trim(), 10);
  }
  return {
    url: sanitizeDiagnosticUrl(url),
    noproxy: Boolean(options.noproxy),
    stdout,
    stderr,
    connectedLine: connection.connectedLine,
    proxyLine: connection.proxyLine,
    remoteName: connection.remoteName,
    remoteAddress: connection.remoteAddress,
    remotePort: connection.remotePort,
    usesProxy: connection.usesProxy,
    httpCode: Number.isFinite(httpCode) ? httpCode : 0,
    status: typeof result.status === 'number' ? result.status : null,
    signal: result.signal || null,
    error: sanitizeDiagnosticText(result.error ? result.error.message : ''),
    durationMs: Date.now() - start,
  };
}

async function runNodeHttpProbe(url, timeoutMs = 10000) {
  const startedAt = Date.now();
  const target = new URL(url);
  const transport = target.protocol === 'https:' ? require('node:https') : require('node:http');
  return await new Promise((resolve) => {
    const request = transport.request(
      target,
      {
        method: 'GET',
      },
      (response) => {
        const chunks = [];
        const remoteAddress = response.socket ? response.socket.remoteAddress || '' : '';
        const remotePort = response.socket ? response.socket.remotePort || null : null;
        const localAddress = response.socket ? response.socket.localAddress || '' : '';
        const localPort = response.socket ? response.socket.localPort || null : null;
        response.on('data', (chunk) => chunks.push(chunk));
        response.on('end', () => {
        resolve({
          url: sanitizeDiagnosticUrl(url),
          statusCode: response.statusCode || 0,
          headers: sanitizeDiagnosticValue(response.headers || {}),
          remoteAddress,
            remotePort,
            localAddress,
            localPort,
            bytes: Buffer.concat(chunks).length,
            durationMs: Date.now() - startedAt,
            error: '',
          });
        });
      }
    );
    request.on('error', (error) => {
      resolve({
        url: sanitizeDiagnosticUrl(url),
        statusCode: 0,
        headers: {},
        remoteAddress: '',
        remotePort: null,
        localAddress: '',
        localPort: null,
        bytes: 0,
        durationMs: Date.now() - startedAt,
        error: sanitizeDiagnosticText(error?.message || String(error || 'Unknown node http error')),
      });
    });
    request.setTimeout(timeoutMs, () => {
      request.destroy(new Error(`timeout after ${timeoutMs}ms`));
    });
    request.end();
  });
}

function captureBrowserStderr(browser, filePath) {
  if (!filePath) return null;
  const browserProcess = browser && typeof browser.process === 'function' ? browser.process() : null;
  const stderr = browserProcess && browserProcess.stderr ? browserProcess.stderr : null;
  if (!stderr || typeof stderr.on !== 'function') {
    return null;
  }
  recordDiagnosticFileBootstrap(filePath);
  return attachSanitizedConsoleStream(stderr, (text) => {
    try {
      fs.appendFileSync(filePath, text);
    } catch {}
  });
}

function describeRedirectChain(request) {
  try {
    return (request.redirectChain ? request.redirectChain() : []).map((redirectRequest) => {
      const response = redirectRequest.response ? redirectRequest.response() : null;
      const headers = response && response.headers ? response.headers() : {};
      return {
        url: redirectRequest.url(),
        method: redirectRequest.method(),
        resourceType: redirectRequest.resourceType(),
        navigationRequest: Boolean(redirectRequest.isNavigationRequest && redirectRequest.isNavigationRequest()),
        responseStatus: response ? response.status() : null,
        responseUrl: response ? response.url() : '',
        location: headers.location || headers.Location || '',
      };
    });
  } catch {
    return [];
  }
}

function describeRequestEvent(request) {
  let frameUrl = '';
  try {
    frameUrl = request.frame ? request.frame().url() : '';
  } catch {}
  return {
    url: request.url(),
    method: request.method(),
    resourceType: request.resourceType(),
    navigationRequest: Boolean(request.isNavigationRequest && request.isNavigationRequest()),
    frameUrl,
    redirectChain: describeRedirectChain(request),
  };
}

function describeResponseEvent(response) {
  const request = response.request();
  const headers = response.headers ? response.headers() : {};
  let frameUrl = '';
  try {
    frameUrl = request.frame ? request.frame().url() : '';
  } catch {}
  return {
    url: response.url(),
    status: response.status(),
    resourceType: request.resourceType(),
    navigationRequest: Boolean(request.isNavigationRequest && request.isNavigationRequest()),
    fromCache: Boolean(response.fromCache && response.fromCache()),
    contentType: headers['content-type'] || headers['Content-Type'] || '',
    contentLength: headers['content-length'] || headers['Content-Length'] || '',
    location: headers.location || headers.Location || '',
    frameUrl,
    redirectChain: describeRedirectChain(request),
  };
}

function describeRequestFailureEvent(request) {
  const failure = request.failure ? request.failure() || {} : {};
  const event = describeRequestEvent(request);
  return {
    ...event,
    errorText: failure.errorText || failure.error_text || 'requestfailed',
  };
}

function runCurlDiagnostic(url, timeoutSeconds, recorder) {
  recorder?.record('curl-start', {
    method: 'GET',
    url,
    timeoutSeconds,
  });
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
      '--output',
      '/dev/null',
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
  const summary = {
    method: 'GET',
    url: sanitizeDiagnosticUrl(url),
    code: Number.isFinite(code) ? code : 0,
    effectiveUrl: sanitizeDiagnosticUrl(effectiveUrl || url),
    contentType: contentType || '',
    contentLength: Number.isFinite(sizeDownload) ? sizeDownload : 0,
    redirectUrl: sanitizeDiagnosticUrl(redirectUrl || ''),
    stderr: sanitizeDiagnosticText(String(result.stderr || '').trim()),
    status: typeof result.status === 'number' ? result.status : null,
    signal: result.signal || null,
    error: sanitizeDiagnosticText(result.error ? result.error.message : ''),
  };
  recorder?.record('curl-summary', summary);
  return summary;
}

async function runBrowserDiagnostic(url, chromePath, tempDir, recorder, options = {}) {
  let puppeteer = null;
  try {
    puppeteer = require('puppeteer-core');
  } catch (error) {
    const message = sanitizeDiagnosticText(error?.message || String(error || 'Unknown require error'));
    console.warn(
      `[lighthouse][diag] puppeteer-core no disponible, se omite la comprobacion del navegador: ${message}`
    );
    recorder?.record('browser-warning', {
      phase: 'require',
      message,
    });
    return null;
  }
  if (!chromePath) {
    console.log('[lighthouse][diag] Chrome no encontrado, se omite la comprobacion del navegador.');
    return null;
  }

  const flags = Array.isArray(options.flags) && options.flags.length ? options.flags : getDiagnosticChromeFlags();
  const netLogPath = options.netLogPath ? path.resolve(options.netLogPath) : '';
  const chromeStderrPath = options.chromeStderrPath ? path.resolve(options.chromeStderrPath) : '';
  if (netLogPath) {
    recordDiagnosticFileBootstrap(netLogPath);
  }
  if (chromeStderrPath) {
    recordDiagnosticFileBootstrap(chromeStderrPath);
  }
  const launchFlags = [
    ...flags,
    ...(netLogPath ? [`--log-net-log=${netLogPath}`, '--net-log-capture-mode=Everything'] : []),
  ];
  const profileDir = options.profileDir ? path.resolve(options.profileDir) : '';
  const captureLifecycleEvents = Boolean(options.includeLifecycleEvents);
  const startedAt = Date.now();
  let chromeStderrBridge = null;

  recorder?.record('browser-start', {
    url,
    flags: launchFlags,
    profileDir,
    executablePath: chromePath,
    netLogPath,
    chromeStderrPath,
  });

  let browser;
  try {
    browser = await puppeteer.launch({
      executablePath: chromePath,
      headless: true,
      args: launchFlags,
      ...(profileDir ? {userDataDir: profileDir} : {}),
    });
  } catch (error) {
    console.log(`[lighthouse][diag] puppeteer.launch error: ${error?.stack || error?.message || error}`);
    recorder?.record('browser-error', {
      phase: 'launch',
      message: error?.message || String(error || 'Unknown error'),
      stack: error?.stack || '',
    });
    return null;
  }

  try {
    chromeStderrBridge = captureBrowserStderr(browser, chromeStderrPath);
    const page = await browser.newPage();
    const initialUrl = url;
    const sanitizedInitialUrl = sanitizeDiagnosticUrl(initialUrl);
    const browserProcess = browser.process ? browser.process() : null;
    const browserPid = browserProcess && typeof browserProcess.pid === 'number' ? browserProcess.pid : null;
    let browserVersion = '';
    try {
      browserVersion = sanitizeDiagnosticText(await browser.version());
    } catch {}
    const getPageUrl = () => {
      try {
        return page.url();
      } catch {
        return '';
      }
    };
    let mainNavigationRequestEntry = null;
    let mainNavigationResponseEntry = null;
    let mainNavigationFailureEntry = null;
    let lifecycleEvents = [];
    browser.on('targetchanged', (target) => {
      const entry = sanitizeDiagnosticValue({
        targetType: target.type(),
        targetUrl: target.url(),
      });
      recorder?.record('targetchanged', entry);
    });
    if (captureLifecycleEvents) {
      browser.on('disconnected', () => {
        const entry = recorder?.record('browser-disconnected', {
          phase: 'browser',
          url: sanitizeDiagnosticUrl(getPageUrl()),
          browserPid,
        });
        lifecycleEvents.push(entry);
      });
      page.on('domcontentloaded', () => {
        const entry = recorder?.record('domcontentloaded', {
          url: sanitizeDiagnosticUrl(getPageUrl()),
          isMainFrame: true,
        });
        lifecycleEvents.push(entry);
      });
      page.on('load', () => {
        const entry = recorder?.record('load', {
          url: sanitizeDiagnosticUrl(getPageUrl()),
          isMainFrame: true,
        });
        lifecycleEvents.push(entry);
      });
      page.on('close', () => {
        const entry = recorder?.record('close', {
          phase: 'page',
          url: sanitizeDiagnosticUrl(getPageUrl()),
          browserPid,
        });
        lifecycleEvents.push(entry);
      });
      page.on('error', (error) => {
        const entry = recorder?.record('crash', {
          message: error?.message || String(error || 'Unknown page crash'),
          stack: error?.stack || '',
          url: sanitizeDiagnosticUrl(getPageUrl()),
          browserPid,
        });
        lifecycleEvents.push(entry);
      });
    }
    page.on('request', (request) => {
      const entry = sanitizeDiagnosticValue(describeRequestEvent(request));
      recorder?.record('request', entry);
      if (entry.navigationRequest && entry.resourceType === 'document') {
        mainNavigationRequestEntry = entry;
      }
      if (entry.navigationRequest && entry.resourceType === 'document') {
        console.log(
          `[lighthouse][diag] request ${entry.method} ${entry.resourceType} ${entry.url} nav=${entry.navigationRequest} frame=${entry.frameUrl || '-'}`
        );
      }
    });
    page.on('response', (response) => {
      const entry = sanitizeDiagnosticValue(describeResponseEvent(response));
      recorder?.record('response', entry);
      if (entry.navigationRequest && entry.resourceType === 'document') {
        mainNavigationResponseEntry = entry;
      }
      if (entry.navigationRequest || entry.resourceType === 'document' || entry.status >= 300) {
        console.log(
          `[lighthouse][diag] response ${entry.status} ${entry.resourceType} ${entry.url}${entry.location ? ` location=${entry.location}` : ''}`
        );
      }
    });
    page.on('requestfailed', (request) => {
      const entry = sanitizeDiagnosticValue(describeRequestFailureEvent(request));
      recorder?.record('requestfailed', entry);
      if (entry.navigationRequest && entry.resourceType === 'document') {
        mainNavigationFailureEntry = entry;
      }
      console.log(
        `[lighthouse][diag] requestfailed ${entry.resourceType} ${entry.method} ${entry.url} nav=${entry.navigationRequest} error=${entry.errorText}`
      );
    });
    page.on('framenavigated', (frame) => {
      const isMainFrame = frame === page.mainFrame();
      const entry = sanitizeDiagnosticValue({
        url: frame.url(),
        name: frame.name ? frame.name() : '',
        isMainFrame,
      });
      recorder?.record('framenavigated', entry);
      if (isMainFrame) {
        console.log(`[lighthouse][diag] framenavigated ${sanitizeDiagnosticUrl(frame.url())}`);
      }
    });
    page.on('console', (message) => {
      const type = String(message.type() || '').trim();
      if (!type || type === 'debug' || type === 'log') return;
      const entry = sanitizeDiagnosticValue({
        type,
        text: message.text(),
      });
      recorder?.record('console', entry);
      console.log(`[lighthouse][diag] console ${entry.type} ${entry.text}`);
    });
    page.on('pageerror', (error) => {
      const entry = sanitizeDiagnosticValue({
        message: error?.message || String(error || 'Unknown pageerror'),
        stack: error?.stack || '',
      });
      recorder?.record('pageerror', entry);
      console.log(`[lighthouse][diag] pageerror ${entry.stack || entry.message}`);
    });

    let navigationResponse = null;
    let navigationError = null;
    try {
      navigationResponse = await page.goto(url, {waitUntil: 'domcontentloaded', timeout: 30000});
      if (navigationResponse) {
        console.log(
          `[lighthouse][diag] page.goto -> ${navigationResponse.status()} ${sanitizeDiagnosticUrl(navigationResponse.url())}`
        );
        recorder?.record('goto-response', {
          status: navigationResponse.status(),
          url: navigationResponse.url(),
        });
      } else {
        console.log('[lighthouse][diag] page.goto -> sin respuesta');
        recorder?.record('goto-response', {
          status: null,
          url: '',
        });
      }
    } catch (error) {
      navigationError = error;
      const entry = sanitizeDiagnosticValue({
        message: error?.message || String(error || 'Unknown goto error'),
        stack: error?.stack || '',
      });
      recorder?.record('goto-error', entry);
      console.log(`[lighthouse][diag] page.goto error: ${entry.stack || entry.message}`);
    }

    let inspection = null;
    if (typeof options.inspectBrowser === 'function') {
      try {
        inspection = await options.inspectBrowser({
          phase: options.inspectPhase || 'browser-diagnostic',
          browser,
          browserPid,
          browserVersion,
          browserPath: chromePath,
          launcherPath: chromePath,
          url,
          profileDir,
          flags: launchFlags,
          tempDir,
        });
      } catch (error) {
        const entry = sanitizeDiagnosticValue({
          phase: 'inspect',
          message: error?.message || String(error || 'Unknown browser inspect error'),
          stack: error?.stack || '',
        });
        recorder?.record('browser-error', entry);
        console.log(`[lighthouse][diag] browser inspect error: ${entry.stack || entry.message}`);
      }
    }

    await new Promise((resolve) => setTimeout(resolve, 4000));
    const finalUrl = page.url();
    const sanitizedFinalUrl = sanitizeDiagnosticUrl(finalUrl);
    console.log(`[lighthouse][diag] final URL ${sanitizedFinalUrl}`);
    const navRequestSummary = mainNavigationResponseEntry || (navigationResponse
      ? {
          status: navigationResponse.status(),
          url: sanitizeDiagnosticUrl(navigationResponse.url()),
          resourceType: 'document',
          navigationRequest: true,
          fromCache: Boolean(navigationResponse.fromCache && navigationResponse.fromCache()),
          contentType: '',
          contentLength: '',
          location: '',
          frameUrl: '',
          redirectChain: [],
        }
      : null);
    const summary = {
      initialUrl: sanitizedInitialUrl,
      finalUrl: sanitizedFinalUrl,
      status: navRequestSummary ? navRequestSummary.status : null,
      navigationResponseUrl: navRequestSummary ? navRequestSummary.url : '',
      redirectChain: mainNavigationRequestEntry ? mainNavigationRequestEntry.redirectChain : [],
      mainRequest: mainNavigationRequestEntry,
      mainResponse: mainNavigationResponseEntry,
      mainFailure: mainNavigationFailureEntry || null,
      failureErrorText: sanitizeDiagnosticText(
        mainNavigationFailureEntry?.errorText || navigationError?.message || ''
      ),
      browserPid,
      browserVersion,
      profileDir,
      flags: launchFlags,
      netLogPath,
      chromeStderrPath,
      launchDurationMs: Date.now() - startedAt,
      lifecycleEvents: lifecycleEvents.filter(Boolean),
      inspection: inspection ? sanitizeDiagnosticValue(inspection) : null,
    };
    recorder?.record('browser-summary', summary);
    if (
      sanitizedFinalUrl !== sanitizedInitialUrl &&
      sanitizedFinalUrl.includes('swcleared=1') &&
      !sanitizedInitialUrl.includes('swcleared=1')
    ) {
      console.log(
        '[lighthouse][diag] auto-navigation detected: the shell rewrites / to add swcleared=1 in web/index.html:12124-12130'
      );
    }
    return {
      initialUrl: sanitizedInitialUrl,
      finalUrl: sanitizedFinalUrl,
      navigationResponse: navigationResponse ? sanitizeDiagnosticUrl(navigationResponse.url()) : '',
      browserPid,
      browserVersion,
      profileDir,
      flags: launchFlags,
      netLogPath,
      chromeStderrPath,
      launchDurationMs: Date.now() - startedAt,
      exitCode: mainNavigationFailureEntry || navigationError ? 1 : 0,
    };
  } catch (error) {
    const entry = sanitizeDiagnosticValue({
      phase: 'runtime',
      message: error?.message || String(error || 'Unknown browser diagnostic error'),
      stack: error?.stack || '',
    });
    recorder?.record('browser-error', entry);
    console.log(`[lighthouse][diag] browser diagnostic error: ${entry.stack || entry.message}`);
    return null;
  } finally {
    if (browser) {
      try {
        await browser.close();
      } catch (error) {
        const entry = sanitizeDiagnosticValue({
          phase: 'close',
          message: error?.message || String(error || 'Unknown browser close error'),
          stack: error?.stack || '',
        });
        recorder?.record('browser-error', entry);
        console.log(`[lighthouse][diag] browser.close error: ${entry.stack || entry.message}`);
      }
    }
    try {
      if (chromeStderrBridge) {
        chromeStderrBridge.finish('browser-close');
        await chromeStderrBridge.done;
      }
    } catch {}
  }
}

async function runPreLhciDiagnostics({auditUrl, tempDir, chromePath}) {
  const recorder = createNavigationDiagnosticRecorder(tempDir);
  recorder.record('diagnostic-start', {
    auditUrl,
  });
  console.log(`[lighthouse][diag] navigation diagnostics written to ${recorder.diagnosticPath}`);
  console.log(`[lighthouse][diag] GET audit url: ${sanitizeDiagnosticUrl(auditUrl)}`);
  const curlResult = runCurlDiagnostic(auditUrl, 15, recorder);
  console.log(
    `[lighthouse][diag] curl status=${curlResult.code || curlResult.status || 0} final=${curlResult.effectiveUrl} content-type=${curlResult.contentType || 'n/a'} content-length=${curlResult.contentLength ?? 'n/a'}`
  );
  if (curlResult.redirectUrl) {
    console.log(`[lighthouse][diag] redirect-url: ${curlResult.redirectUrl}`);
  }
  await runBrowserDiagnostic(auditUrl, chromePath, tempDir, recorder);
  recorder.record('diagnostic-complete', {
    auditUrl,
    curlStatus: curlResult.code,
    finalUrl: curlResult.effectiveUrl,
  });
}

function getDiagnosticChromeFlags() {
  return [
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
}

function buildChromeLaunchFlags(extraFlags = [], options = {}) {
  const resolvedExtraFlags = Array.isArray(extraFlags)
    ? extraFlags.map((flag) => String(flag)).filter((flag) => flag.trim())
    : [];
  return [
    ...(options.includeNoSandbox === false ? [] : ['--no-sandbox']),
    ...getDiagnosticChromeFlags().filter((flag) => flag !== '--no-sandbox'),
    '--headless=new',
    '--remote-debugging-port=0',
    ...resolvedExtraFlags,
  ];
}

function isTruthyEnvFlag(value) {
  return String(value || '').trim() === '1';
}

function isDiagnosticMatrixEnabled() {
  return isTruthyEnvFlag(process.env.LHCI_DIAGNOSTIC_MATRIX);
}

function isBrowserMatrixDiagnosticEnabled() {
  return isTruthyEnvFlag(process.env.LHCI_BROWSER_MATRIX_DIAGNOSTIC);
}

function isFdInheritanceDiagnosticEnabled() {
  return isTruthyEnvFlag(process.env.LHCI_FD_INHERITANCE_DIAGNOSTIC);
}

function buildDiagnosticMatrixCases(auditUrl) {
  const rootUrl = new URL(auditUrl);
  rootUrl.searchParams.delete('swcleared');

  const probeUrl = new URL('/kiosk', auditUrl);
  probeUrl.searchParams.delete('swcleared');

  return [
    {
      id: 'A',
      label: 'app-root-without-swcleared',
      url: rootUrl.toString(),
    },
    {
      id: 'B',
      label: 'app-root-with-swcleared',
      url: ensureSwClearedUrl(auditUrl, 0),
    },
    {
      id: 'C',
      label: 'probe-without-swcleared',
      url: probeUrl.toString(),
    },
    {
      id: 'D',
      label: 'probe-with-swcleared',
      url: ensureSwClearedUrl(probeUrl.toString(), 0),
    },
  ];
}

function buildFdInheritanceMatrixVariants(chromePath) {
  const resolvePath = (value) => sanitizeDiagnosticText(String(value || '').trim());
  return [
    {
      id: 'F1',
      label: 'main-pipes',
      launcherKind: 'direct',
      stdioMode: 'pipe',
      closeInheritedPipeFds: false,
      executablePath: resolvePath(chromePath),
    },
    {
      id: 'F2',
      label: 'main-ignore',
      launcherKind: 'direct',
      stdioMode: 'ignore',
      closeInheritedPipeFds: false,
      executablePath: resolvePath(chromePath),
    },
    {
      id: 'F3',
      label: 'main-inherit',
      launcherKind: 'direct',
      stdioMode: 'inherit',
      closeInheritedPipeFds: false,
      executablePath: resolvePath(chromePath),
    },
    {
      id: 'F4',
      label: 'auxiliary-clean',
      launcherKind: 'auxiliary',
      stdioMode: 'pipe',
      closeInheritedPipeFds: false,
      executablePath: resolvePath(chromePath),
    },
    {
      id: 'F5',
      label: 'auxiliary-scrubbed',
      launcherKind: 'auxiliary',
      launcherTransport: 'python',
      stdioMode: 'pipe',
      closeInheritedPipeFds: true,
      scrubInheritedFds: true,
      sandboxMode: 'no-sandbox',
      extraFlags: [],
      includeNoSandbox: true,
      executablePath: resolvePath(chromePath),
    },
    {
      id: 'F6',
      label: 'auxiliary-scrubbed-network-service-in-process',
      launcherKind: 'auxiliary',
      launcherTransport: 'python',
      stdioMode: 'pipe',
      closeInheritedPipeFds: true,
      scrubInheritedFds: true,
      sandboxMode: 'no-sandbox',
      extraFlags: ['--enable-features=NetworkService,NetworkServiceInProcess'],
      includeNoSandbox: true,
      executablePath: resolvePath(chromePath),
    },
    {
      id: 'F7',
      label: 'auxiliary-scrubbed-sandbox-enabled',
      launcherKind: 'auxiliary',
      launcherTransport: 'python',
      stdioMode: 'pipe',
      closeInheritedPipeFds: true,
      executablePath: resolvePath(chromePath),
      scrubInheritedFds: true,
      sandboxMode: 'sandbox-enabled',
      extraFlags: [],
      includeNoSandbox: false,
    },
  ];
}

function buildFdInheritanceMatrixArtifacts(tempDir, variantId) {
  const caseDir = path.join(tempDir, 'fd-inheritance-matrix', variantId);
  return {
    caseDir,
    resultPath: path.join(caseDir, 'result.json'),
    parentFdsBeforePath: path.join(caseDir, 'parent-fds-before.json'),
    parentFdsAfterPath: path.join(caseDir, 'parent-fds-after.json'),
    launcherStderrPath: path.join(caseDir, 'launcher-stderr.log'),
    launcherStdoutPath: path.join(caseDir, 'launcher-stdout.log'),
    launcherResultPath: path.join(caseDir, 'launcher-result.json'),
  };
}

function buildBrowserMatrixVariants(chromePath, env = process.env) {
  const resolvePath = (value) => sanitizeDiagnosticText(String(value || '').trim());
  return [
    {
      id: 'V1',
      label: 'playwright-chromium-current',
      source: 'current-playwright-chromium',
      executablePath: resolvePath(chromePath),
      captureStrace: true,
    },
    {
      id: 'V2',
      label: 'runner-google-chrome-stable',
      source: 'runner-google-chrome-stable',
      executablePath: resolvePath(
        env.LHCI_BROWSER_MATRIX_V2_PATH ||
          env.GOOGLE_CHROME_PATH ||
          env.GOOGLE_CHROME_STABLE_PATH ||
          env.CHROME_PATH
      ),
      captureStrace: true,
    },
    {
      id: 'V3',
      label: 'playwright-chromium-previous',
      source: 'playwright-1.54.0-chromium',
      executablePath: resolvePath(env.LHCI_BROWSER_MATRIX_V3_PATH),
      captureStrace: false,
    },
    {
      id: 'V4',
      label: 'official-browser-alt',
      source: 'official-browser-alternative',
      executablePath: resolvePath(env.LHCI_BROWSER_MATRIX_V4_PATH),
      captureStrace: false,
    },
  ];
}

function buildBrowserMatrixArtifacts(tempDir, variantId) {
  const caseDir = path.join(tempDir, 'browser-matrix-linux', variantId);
  return {
    caseDir,
    prelaunchSnapshotPath: path.join(caseDir, 'prelaunch-snapshot.json'),
    runtimeSnapshotPath: path.join(caseDir, 'runtime-snapshot.json'),
    directStraceDir: path.join(caseDir, 'direct-strace'),
    lighthouseStraceDir: path.join(caseDir, 'lighthouse-strace'),
    directLauncherPath: path.join(caseDir, 'direct-launcher.cjs'),
    lighthouseLauncherPath: path.join(caseDir, 'lighthouse-launcher.cjs'),
    browserNetLogPath: path.join(caseDir, 'browser-netlog.json'),
    browserChromeStderrPath: path.join(caseDir, 'browser-stderr.log'),
    directProfileDir: path.join(caseDir, 'direct-profile'),
    directNetLogPath: path.join(caseDir, 'direct-netlog.json'),
    directChromeStderrPath: path.join(caseDir, 'direct-chrome-stderr.log'),
    lighthouseProfileDir: path.join(caseDir, 'lighthouse-profile'),
    lighthouseNetLogPath: path.join(caseDir, 'lighthouse-netlog.json'),
    lighthouseChromeStderrPath: path.join(caseDir, 'lighthouse-chrome-stderr.log'),
    directSnapshotPath: path.join(caseDir, 'direct-snapshot.json'),
    lighthouseSnapshotPath: path.join(caseDir, 'lighthouse-snapshot.json'),
    straceSummaryPath: path.join(caseDir, 'strace-summary.json'),
  };
}

function extractFdInheritanceCaseLog(logText, variantId) {
  const text = String(logText || '');
  if (!text) {
    return '';
  }
  const startMarker = `[lighthouse][fd-matrix] ${variantId} start`;
  const endMarker = `[lighthouse][fd-matrix] ${variantId} complete`;
  const startIndex = text.indexOf(startMarker);
  if (startIndex === -1) {
    return text;
  }
  const endIndex = text.indexOf(endMarker, startIndex);
  if (endIndex === -1) {
    return text.slice(startIndex);
  }
  return text.slice(startIndex, endIndex + endMarker.length);
}

async function runChromeFdInheritanceCaseViaPythonLauncher(config, deps = {}) {
  const spawnImpl = deps.spawn || spawn;
  const puppeteerImpl = deps.puppeteer || require('puppeteer-core');
  const fsImpl = deps.fs || fs;
  const processImpl = deps.process || process;
  const pythonExecutable = sanitizeDiagnosticText(
    String(
      deps.pythonExecutable ||
        process.env.LHCI_FD_INHERITANCE_PYTHON ||
        process.env.PYTHON ||
        'python'
    ).trim() || 'python'
  );
  const wrapperScriptPath = path.join(process.cwd(), 'scripts', 'chrome_clean_launcher.py');
  const variant = {
    id: config.variantId || config.id || 'F?',
    label: config.label || config.variantLabel || '',
    stdioMode: config.stdioMode || 'pipe',
    launcherKind: config.launcherKind || 'auxiliary',
    launcherTransport: config.launcherTransport || 'python',
    closeInheritedPipeFds: Boolean(config.closeInheritedPipeFds),
    scrubInheritedFds: Boolean(config.scrubInheritedFds),
    sandboxMode: config.sandboxMode || (config.includeNoSandbox === false ? 'sandbox-enabled' : 'no-sandbox'),
    extraFlags: Array.isArray(config.extraFlags) ? config.extraFlags : [],
    includeNoSandbox: config.includeNoSandbox !== false,
  };
  const auditUrl = sanitizeDiagnosticUrl(config.auditUrl || '');
  const chromePath = sanitizeDiagnosticText(config.chromePath || '');
  const tempDir = path.resolve(config.tempDir || fsImpl.mkdtempSync(path.join(os.tmpdir(), 'lhci-fd-')));
  const caseDir = path.resolve(config.caseDir || path.join(tempDir, 'fd-inheritance-matrix', variant.id));
  fsImpl.mkdirSync(caseDir, {recursive: true});
  const profileDir = path.resolve(config.profileDir || path.join(caseDir, 'profile'));
  fsImpl.mkdirSync(profileDir, {recursive: true});
  const extraFlags = Array.isArray(config.extraFlags) ? config.extraFlags : [];
  const launchFlags = Array.isArray(config.launchFlags) && config.launchFlags.length
    ? config.launchFlags.map((flag) => String(flag))
    : buildChromeLaunchFlags(extraFlags);
  const scrubInheritedFds = variant.scrubInheritedFds;
  const helperConfig = {
    ...config,
    variantId: variant.id,
    label: variant.label,
    stdioMode: variant.stdioMode,
    launcherKind: variant.launcherKind,
    launcherTransport: variant.launcherTransport,
    closeInheritedPipeFds: false,
    scrubInheritedFds,
    auditUrl,
    chromePath,
    tempDir,
    caseDir,
    profileDir,
    launchFlags,
    completionTimeoutMs:
      Number(
        config.wrapperTimeoutMs ||
          Number(config.navigationTimeoutMs || 30000) + Number(config.closeTimeoutMs || 10000) + 15000
      ),
    completionGraceMs: Number(config.wrapperGraceMs || 5000),
  };
  const helperArgs = [wrapperScriptPath, `--config-json=${JSON.stringify(helperConfig)}`];
  if (scrubInheritedFds) {
    helperArgs.push('--scrub-inherited-fds');
  }

  const helperProcess = spawnImpl(
    pythonExecutable,
    helperArgs,
    {
      cwd: processImpl.cwd(),
      env: processImpl.env,
      stdio: ['pipe', 'pipe', 'pipe'],
      shell: false,
    }
  );

  if (!helperProcess || typeof helperProcess.pid !== 'number') {
    throw new Error('No se pudo lanzar el helper Python para la matriz de herencia de FDs.');
  }

  const helperStdoutLines = [];
  const helperStderrLines = [];
  let helperLaunchRecord = null;
  let helperCompleteRecord = null;
  let helperError = null;
  let helperTerminationScheduled = false;
  let helperCloseCommandSent = false;

  const scheduleHelperTermination = (reason, graceMs = 5000) => {
    if (helperTerminationScheduled) {
      return;
    }
    helperTerminationScheduled = true;
    console.log(`[lighthouse][fd-matrix] ${variant.id} helper timeout: ${reason}; sending SIGTERM.`);
    try {
      helperProcess.kill('SIGTERM');
    } catch {}
    const killTimer = setTimeout(() => {
      if (helperProcess.exitCode === null && helperProcess.signalCode === null) {
        console.log(`[lighthouse][fd-matrix] ${variant.id} helper timeout: escalating to SIGKILL.`);
        try {
          helperProcess.kill('SIGKILL');
        } catch {}
      }
    }, graceMs);
    if (killTimer && typeof killTimer.unref === 'function') {
      killTimer.unref();
    }
  };

  const stdoutCollector = createBufferedLineCollector((line) => {
    if (!line) return;
    helperStdoutLines.push(line);
    try {
      const parsed = JSON.parse(line);
      if (parsed && (parsed.phase === 'launch_info' || parsed.phase === 'launch') && !helperLaunchRecord) {
        helperLaunchRecord = parsed;
      } else if (parsed && (parsed.phase === 'complete_info' || parsed.phase === 'complete')) {
        helperCompleteRecord = parsed;
      } else if (parsed && parsed.phase === 'error' && !helperError) {
        helperError = new Error(parsed.message || 'Python launcher error');
      }
    } catch {}
  });
  const stderrWriter = createSanitizedConsoleLineWriter((line) => {
    helperStderrLines.push(line);
    if (processImpl.stderr && typeof processImpl.stderr.write === 'function') {
      processImpl.stderr.write(line);
    }
  });

  if (helperProcess.stdout && typeof helperProcess.stdout.on === 'function') {
    helperProcess.stdout.on('data', (chunk) => stdoutCollector.write(chunk));
    helperProcess.stdout.once('end', () => stdoutCollector.finish());
    helperProcess.stdout.once('close', () => stdoutCollector.finish());
  }
  if (helperProcess.stderr && typeof helperProcess.stderr.on === 'function') {
    helperProcess.stderr.on('data', (chunk) => stderrWriter.write(chunk));
    helperProcess.stderr.once('end', () => stderrWriter.finish());
    helperProcess.stderr.once('close', () => stderrWriter.finish());
  }

  const helperClosePromise = new Promise((resolve, reject) => {
    helperProcess.once('close', (status, signal) => {
      resolve({status, signal});
    });
    helperProcess.once('error', (error) => {
      helperError = error;
      reject(error);
    });
  });

  const helperLaunchPromise = new Promise((resolve, reject) => {
    const startedAt = Date.now();
    const timeoutMs = Number(config.devtoolsTimeoutMs || 30000) + 60000;
    const timer = setInterval(() => {
      if (helperLaunchRecord) {
        clearInterval(timer);
        resolve(helperLaunchRecord);
        return;
      }
      if (helperError) {
        clearInterval(timer);
        reject(helperError);
        return;
      }
      if (Date.now() - startedAt > timeoutMs) {
        clearInterval(timer);
        scheduleHelperTermination('launch timeout');
        reject(
          new Error(
            `El helper Python no publicó DevToolsActivePort dentro de ${Math.round(timeoutMs / 1000)}s.`
          )
        );
      }
    }, 100);
  });

  const helperCompletePromise = new Promise((resolve, reject) => {
    const startedAt = Date.now();
    const timeoutMs = Number(config.closeTimeoutMs || 10000) + 60000;
    const timer = setInterval(() => {
      if (helperCompleteRecord) {
        clearInterval(timer);
        resolve(helperCompleteRecord);
        return;
      }
      if (helperError) {
        clearInterval(timer);
        reject(helperError);
        return;
      }
      if (Date.now() - startedAt > timeoutMs) {
        clearInterval(timer);
        scheduleHelperTermination('completion timeout');
        reject(
          new Error(`El helper Python no publicó el resultado completo dentro de ${Math.round(timeoutMs / 1000)}s.`)
        );
      }
    }, 100);
  });

  const launchRecord = await helperLaunchPromise;
  if (!launchRecord || !launchRecord.browserWSEndpoint || !launchRecord.chromePid) {
    throw new Error('El helper Python no devolvió un endpoint DevTools o PID válidos.');
  }

  const navigationEvents = [];

  let navigationResponse = null;
  let gotoError = null;
  let browserClosed = false;
  let browser = null;
  let browserVersion = '';
  let browserConnectError = null;
  let page = null;
  let processTableBeforeClose = null;
  let processTableAfterClose = null;
  let networkServicePid = null;
  let networkServiceFds = null;
  let chromeFdsBeforeClose = null;
  let chromeFdsAfterClose = null;

  try {
    const connectTimeoutMs = Number(config.devtoolsTimeoutMs || 30000) + 15000;
    const connectStartedAt = Date.now();
    let connectAttemptError = null;
    while (!browser && Date.now() - connectStartedAt < connectTimeoutMs) {
      try {
        browser = await puppeteerImpl.connect({
          browserWSEndpoint: launchRecord.browserWSEndpoint,
        });
      } catch (error) {
        connectAttemptError = error;
        await sleep(250);
      }
    }
    if (!browser) {
      browserConnectError = connectAttemptError || new Error('No se pudo conectar al navegador.');
      navigationEvents.push(
        sanitizeDiagnosticValue({
          event: 'browser-connect-error',
          message: browserConnectError?.message || String(browserConnectError || 'Unknown browser connect error'),
        })
      );
    } else {
      browserVersion = sanitizeDiagnosticText(await browser.version());
      page = await browser.newPage();
      page.on('request', (request) => {
        navigationEvents.push(
          sanitizeDiagnosticValue({
            event: 'request',
            url: request.url(),
            method: request.method(),
            resourceType: request.resourceType(),
            navigationRequest: request.isNavigationRequest(),
          })
        );
      });
      page.on('response', (response) => {
        navigationEvents.push(
          sanitizeDiagnosticValue({
            event: 'response',
            url: response.url(),
            status: response.status(),
            fromCache: response.fromCache(),
          })
        );
      });
      page.on('requestfailed', (request) => {
        const failure = request.failure ? request.failure() : null;
        navigationEvents.push(
          sanitizeDiagnosticValue({
            event: 'requestfailed',
            url: request.url(),
            method: request.method(),
            resourceType: request.resourceType(),
            errorText: failure?.errorText || '',
          })
        );
      });
      page.on('framenavigated', (frame) => {
        navigationEvents.push(
          sanitizeDiagnosticValue({
            event: 'framenavigated',
            url: frame.url(),
          })
        );
      });
      page.on('load', () => {
        navigationEvents.push({event: 'load'});
      });
      page.on('domcontentloaded', () => {
        navigationEvents.push({event: 'domcontentloaded'});
      });
      page.on('pageerror', (error) => {
        navigationEvents.push(
          sanitizeDiagnosticValue({
            event: 'pageerror',
            message: error?.message || String(error || 'Unknown pageerror'),
          })
        );
      });
      page.on('console', (message) => {
        navigationEvents.push(
          sanitizeDiagnosticValue({
            event: 'console',
            type: message.type(),
            text: message.text(),
          })
        );
      });
    }

    try {
      if (page) {
        navigationResponse = await page.goto(auditUrl, {
          waitUntil: 'load',
          timeout: Number(config.navigationTimeoutMs || 30000),
        });
      } else if (browserConnectError) {
        gotoError = browserConnectError;
      }
    } catch (error) {
      gotoError = error;
    }

    processTableBeforeClose = captureProcessTable();
    networkServicePid = findNetworkServicePid(processTableBeforeClose.rows, launchRecord.chromePid);
    networkServiceFds = captureChromeCleanFdListing(networkServicePid, fsImpl, processImpl);
    chromeFdsBeforeClose = captureChromeCleanFdListing(launchRecord.chromePid, fsImpl, processImpl);

    if (browser) {
      try {
        await browser.close();
        browserClosed = true;
      } catch (error) {
        navigationEvents.push(
          sanitizeDiagnosticValue({
            event: 'browser-close-error',
            message: error?.message || String(error || 'Unknown browser close error'),
          })
        );
      }
    } else {
      navigationEvents.push({event: 'browser-close-skipped', reason: 'browser-not-connected'});
    }

    if (!helperCloseCommandSent && helperProcess.stdin && typeof helperProcess.stdin.write === 'function') {
      helperCloseCommandSent = true;
      try {
        helperProcess.stdin.write(`${JSON.stringify({command: 'close'})}\n`);
        if (typeof helperProcess.stdin.end === 'function') {
          helperProcess.stdin.end();
        }
      } catch (error) {
        navigationEvents.push(
          sanitizeDiagnosticValue({
            event: 'helper-close-command-error',
            message: error?.message || String(error || 'Unknown helper close command error'),
          })
        );
      }
    }

    let helperCloseInfo = {status: null, signal: null};
    try {
      helperCloseInfo = await helperClosePromise;
    } catch (error) {
      helperError = helperError || error;
    }
    let helperCompleteInfo = null;
    try {
      helperCompleteInfo = await helperCompletePromise;
    } catch (error) {
      helperError = helperError || error;
    }
    const helperCompleteSnapshot = helperCompleteInfo || {
      chromeExitCode: null,
      chromeExitSignal: null,
      chromeTimedOut: true,
      chromeStdoutText: '',
      chromeStderrText: '',
    };
    processTableAfterClose = captureProcessTable();
    if (!networkServicePid) {
      networkServicePid = findNetworkServicePid(processTableAfterClose.rows, launchRecord.chromePid);
    }
    if (networkServicePid) {
      networkServiceFds = captureChromeCleanFdListing(networkServicePid, fsImpl, processImpl);
    }
    chromeFdsAfterClose = captureChromeCleanFdListing(launchRecord.chromePid, fsImpl, processImpl);

    const requestEvent = navigationEvents.find((entry) => entry.event === 'request');
    const responseEvent = navigationEvents.find((entry) => entry.event === 'response');
    const failedEvent = navigationEvents.find((entry) => entry.event === 'requestfailed');
    const frameNavigated = navigationEvents.find((entry) => entry.event === 'framenavigated');
    const loadEvent = navigationEvents.find((entry) => entry.event === 'load');
    const domContentLoadedEvent = navigationEvents.find((entry) => entry.event === 'domcontentloaded');

    const chromeStdoutText = sanitizeDiagnosticText(helperCompleteSnapshot.chromeStdoutText || '');
    const chromeStderrText = sanitizeDiagnosticText(helperCompleteSnapshot.chromeStderrText || '');
    const requestFailedErrorText = failedEvent ? String(failedEvent.errorText || '') : '';
    const navigationStatus = responseEvent ? Number(responseEvent.status || 0) : null;
    const summary = {
      variantId: variant.id,
      label: variant.label,
      launcherKind: variant.launcherKind,
      launcherTransport: variant.launcherTransport,
      stdioMode: variant.stdioMode,
      closeInheritedPipeFds: variant.closeInheritedPipeFds,
      sandboxMode: variant.sandboxMode || (variant.includeNoSandbox === false ? 'sandbox-enabled' : 'no-sandbox'),
      extraFlags: Array.isArray(variant.extraFlags) ? variant.extraFlags : [],
      includeNoSandbox: variant.includeNoSandbox !== false,
      auditUrl,
      chromePath,
      helperPid: launchRecord.pythonPid || helperProcess.pid,
      chromePid: launchRecord.chromePid,
      browserVersion,
      browserWSEndpoint: launchRecord.browserWSEndpoint,
      navigationTimeoutMs: Number(config.navigationTimeoutMs || 30000),
      closeTimeoutMs: Number(config.closeTimeoutMs || 10000),
      devtoolsTimeoutMs: Number(config.devtoolsTimeoutMs || 30000),
      launchFlags,
      scrubInheritedFds,
      navigation: {
        requestedUrl: sanitizeDiagnosticUrl(auditUrl),
        finalUrl: sanitizeDiagnosticUrl(navigationResponse?.url() || auditUrl),
        status: navigationStatus,
        requestFailedErrorText: sanitizeDiagnosticText(requestFailedErrorText),
        gotoError: gotoError
          ? {
              name: gotoError?.name || 'Error',
              message: sanitizeDiagnosticText(gotoError?.message || String(gotoError || 'Unknown goto error')),
            }
          : null,
        events: navigationEvents,
        requestEvent,
        responseEvent,
        requestfailedEvent: failedEvent || null,
        frameNavigatedEvent: frameNavigated || null,
        domContentLoadedEvent: domContentLoadedEvent || null,
        loadEvent: loadEvent || null,
        browserClosed,
        exitInfo: {
          code: helperCompleteSnapshot.chromeExitCode,
          signal: helperCompleteSnapshot.chromeExitSignal || null,
          timeout: Boolean(helperCompleteSnapshot.chromeTimedOut),
        },
      },
      helperFdsBefore: launchRecord.pythonFdsBefore,
      helperFdsBeforeScrub: launchRecord.pythonFdsBeforeScrub,
      helperFdsAfterScrub: launchRecord.pythonFdsAfterScrub,
      helperFdsAfter: launchRecord.pythonFdsAfterLaunch,
      chromeFdsAfterLaunch: launchRecord.chromeFdsAfterLaunch,
      chromeFdsBeforeClose,
      chromeFdsAfterClose,
      networkServicePid,
      networkServiceFds,
      processTableBeforeClose,
      processTableAfterClose,
      chromeStdoutText,
      chromeStderrText,
      fd142InHelper:
        hasFdTarget(launchRecord.pythonFdsBefore, 142, /pipe:/i) ||
        hasFdTarget(launchRecord.pythonFdsAfterLaunch, 142, /pipe:/i),
      fd145InHelper:
        hasFdTarget(launchRecord.pythonFdsBefore, 145, /pipe:/i) ||
        hasFdTarget(launchRecord.pythonFdsAfterLaunch, 145, /pipe:/i),
      fd142InChrome:
        hasFdTarget(chromeFdsBeforeClose, 142, /pipe:/i) || hasFdTarget(chromeFdsAfterClose, 142, /pipe:/i),
      fd145InChrome:
        hasFdTarget(chromeFdsBeforeClose, 145, /pipe:/i) || hasFdTarget(chromeFdsAfterClose, 145, /pipe:/i),
      fd142InNetworkService: hasFdTarget(networkServiceFds, 142, /pipe:/i),
      fd145InNetworkService: hasFdTarget(networkServiceFds, 145, /pipe:/i),
      helperProcess: {
        status: helperCloseInfo.status,
        signal: helperCloseInfo.signal || null,
        stdoutText: sanitizeDiagnosticText(helperStdoutLines.join('\n')),
        stderrText: sanitizeDiagnosticText(helperStderrLines.join('')),
      },
      chromeCloseTimedOut: Boolean(helperCompleteSnapshot.chromeTimedOut),
    };

    summary.httpStatus = navigationStatus;
    summary.errAborted =
      /ERR_ABORTED/i.test(requestFailedErrorText) ||
      /ERR_ABORTED/i.test(String(gotoError?.message || '')) ||
      /ERR_ABORTED/i.test(chromeStderrText);
    summary.fdViolation = /FD ownership violation/i.test(chromeStderrText);
    summary.networkServiceRestart = /Network service crashed or was terminated/i.test(chromeStderrText);
    if (browserConnectError) {
      summary.browserConnectError = {
        name: browserConnectError?.name || 'Error',
        message: sanitizeDiagnosticText(
          browserConnectError?.message || String(browserConnectError || 'Unknown browser connect error')
        ),
      };
    }
    summary.exitCode =
      summary.errAborted ||
      summary.fdViolation ||
      Boolean(browserConnectError) ||
      Boolean(gotoError) ||
      !navigationResponse ||
      Boolean(helperCompleteSnapshot.chromeTimedOut) ||
      Boolean(helperCloseInfo.status && helperCloseInfo.status !== 0) ||
      Boolean(helperCloseInfo.signal)
        ? 1
        : 0;
    summary.signal = helperCompleteSnapshot.chromeExitSignal || null;
    summary.chromeExitCode = typeof helperCompleteSnapshot.chromeExitCode === 'number' ? helperCompleteSnapshot.chromeExitCode : null;
    summary.chromeExitSignal = helperCompleteSnapshot.chromeExitSignal || null;
    summary.navigation.loadSeen = Boolean(loadEvent);
    summary.navigation.domContentLoadedSeen = Boolean(domContentLoadedEvent);
    summary.navigation.responseSeen = Boolean(responseEvent);
    summary.navigation.requestFailedSeen = Boolean(failedEvent);
    summary.navigation.frameNavigatedSeen = Boolean(frameNavigated);
    summary.navigation.stdoutText = chromeStdoutText;
    summary.navigation.stderrText = chromeStderrText;
    summary.navigation.networkServicePid = networkServicePid;
    summary.navigation.chromePid = launchRecord.chromePid;
    summary.navigation.helperPid = launchRecord.pythonPid || helperProcess.pid;
    summary.navigation.launcherKind = variant.launcherKind;
    summary.navigation.launcherTransport = variant.launcherTransport;
    summary.navigation.stdioMode = variant.stdioMode;
    summary.navigation.closeInheritedPipeFds = variant.closeInheritedPipeFds;
    summary.navigation.scrubInheritedFds = scrubInheritedFds;
    summary.navigation.sandboxMode = variant.sandboxMode || (variant.includeNoSandbox === false ? 'sandbox-enabled' : 'no-sandbox');
    summary.navigation.extraFlags = Array.isArray(variant.extraFlags) ? variant.extraFlags : [];
    summary.navigation.includeNoSandbox = variant.includeNoSandbox !== false;
    summary.navigation.closeActions = [];
    summary.navigation.helperFdsBefore = launchRecord.pythonFdsBefore;
    summary.navigation.helperFdsBeforeScrub = launchRecord.pythonFdsBeforeScrub;
    summary.navigation.helperFdsAfterScrub = launchRecord.pythonFdsAfterScrub;
    summary.navigation.helperFdsAfter = launchRecord.pythonFdsAfterLaunch;
    summary.navigation.chromeFdsAfterLaunch = launchRecord.chromeFdsAfterLaunch;
    summary.navigation.chromeFdsBeforeClose = chromeFdsBeforeClose;
    summary.navigation.chromeFdsAfterClose = chromeFdsAfterClose;
    summary.navigation.networkServiceFds = networkServiceFds;
    summary.navigation.processTableBeforeClose = processTableBeforeClose;
    summary.navigation.processTableAfterClose = processTableAfterClose;
    summary.navigation.browserVersion = browserVersion;
    summary.navigation.browserWSEndpoint = launchRecord.browserWSEndpoint;
    summary.navigation.chromeStdoutText = chromeStdoutText;
    summary.navigation.chromeStderrText = chromeStderrText;
    summary.navigation.fd142InHelper = summary.fd142InHelper;
    summary.navigation.fd145InHelper = summary.fd145InHelper;
    summary.navigation.fd142InChrome = summary.fd142InChrome;
    summary.navigation.fd145InChrome = summary.fd145InChrome;
    summary.navigation.fd142InNetworkService = summary.fd142InNetworkService;
    summary.navigation.fd145InNetworkService = summary.fd145InNetworkService;

    return sanitizeDiagnosticValue(summary);
  } finally {
    if (browser && !browserClosed) {
      try {
        await browser.close();
      } catch {}
    }
  }
}

async function runFdInheritanceMatrixDiagnostic({auditUrl, tempDir, chromePath}) {
  const logPath = path.join(tempDir, 'fd-inheritance-matrix.log');
  const jsonPath = path.join(tempDir, 'fd-inheritance-matrix.json');
  const helperScriptPath = path.join(process.cwd(), 'scripts', 'chrome-clean-launcher.cjs');
  const pythonHelperScriptPath = path.join(process.cwd(), 'scripts', 'chrome_clean_launcher.py');
  const variants = buildFdInheritanceMatrixVariants(chromePath);
  const matrix = {
    generatedAt: new Date().toISOString(),
    auditUrl: sanitizeDiagnosticUrl(auditUrl),
    chromePath: sanitizeDiagnosticText(chromePath || ''),
    environment: collectDiagnosticEnvironmentSummary(),
    variants: variants.map((variant) => ({
      id: variant.id,
      label: variant.label,
      launcherKind: variant.launcherKind,
      launcherTransport: variant.launcherTransport || 'node',
      stdioMode: variant.stdioMode,
      closeInheritedPipeFds: variant.closeInheritedPipeFds,
      scrubInheritedFds:
        ['F5', 'F6', 'F7'].includes(variant.id) && isTruthyEnvFlag(process.env.LHCI_FD_INHERITANCE_SCRUB),
      sandboxMode: variant.sandboxMode || (variant.includeNoSandbox === false ? 'sandbox-enabled' : 'no-sandbox'),
      extraFlags: Array.isArray(variant.extraFlags) ? variant.extraFlags : [],
      includeNoSandbox: variant.includeNoSandbox !== false,
      executablePath: variant.executablePath,
    })),
    cases: [],
    exitCode: 0,
    logPath,
    jsonPath,
  };

  const writeSummary = () => {
    try {
      fs.writeFileSync(jsonPath, `${JSON.stringify(matrix, null, 2)}\n`);
    } catch (error) {
      console.log(
        `[lighthouse][diag] no se pudo escribir ${jsonPath}: ${error?.stack || error?.message || error}`
      );
    }
  };

  try {
    fs.writeFileSync(logPath, '', 'utf8');
  } catch {}
  console.log('[lighthouse] FD inheritance diagnostic enabled.');
  console.log(`[lighthouse][diag] FD matrix log: ${logPath}`);
  console.log(`[lighthouse][diag] FD matrix json: ${jsonPath}`);
  console.log(`[lighthouse][diag] Chrome helper (node): ${helperScriptPath}`);
  console.log(`[lighthouse][diag] Chrome helper (python): ${pythonHelperScriptPath}`);
  writeSummary();

  for (const variant of variants) {
    const artifacts = buildFdInheritanceMatrixArtifacts(tempDir, variant.id);
    fs.mkdirSync(artifacts.caseDir, {recursive: true});
    fs.mkdirSync(path.dirname(artifacts.launcherResultPath), {recursive: true});

    const caseConfig = {
      variantId: variant.id,
      label: variant.label,
      launcherKind: variant.launcherKind,
      stdioMode: variant.stdioMode,
      closeInheritedPipeFds: variant.closeInheritedPipeFds,
      scrubInheritedFds:
        ['F5', 'F6', 'F7'].includes(variant.id) && isTruthyEnvFlag(process.env.LHCI_FD_INHERITANCE_SCRUB),
      sandboxMode: variant.sandboxMode || (variant.includeNoSandbox === false ? 'sandbox-enabled' : 'no-sandbox'),
      extraFlags: Array.isArray(variant.extraFlags) ? variant.extraFlags : [],
      includeNoSandbox: variant.includeNoSandbox !== false,
      auditUrl,
      chromePath: variant.executablePath,
      tempDir,
      caseDir: artifacts.caseDir,
      profileDir: path.join(artifacts.caseDir, 'profile'),
      launchFlags: buildChromeLaunchFlags(
        variant.extraFlags || [],
        {includeNoSandbox: variant.includeNoSandbox !== false}
      ),
      navigationTimeoutMs: 30000,
      devtoolsTimeoutMs: 30000,
      closeTimeoutMs: 10000,
    };

    console.log(
      `[lighthouse][fd-matrix] ${variant.id} start launcher=${variant.launcherKind} stdio=${variant.stdioMode} scrub=${caseConfig.scrubInheritedFds ? '1' : '0'} net=${variant.extraFlags && variant.extraFlags.includes('--enable-features=NetworkService,NetworkServiceInProcess') ? 'in-process' : 'out-of-process'} sandbox=${variant.includeNoSandbox === false ? 'enabled' : 'disabled'}`
    );
    const parentFdsBefore = captureChromeCleanFdListing(process.pid);
    let helperStdout = '';
    let helperStderr = '';
    let helperStatus = 0;
    let helperSignal = null;
    let caseResult = null;

    if (variant.launcherTransport === 'python') {
      caseResult = await runChromeFdInheritanceCaseViaPythonLauncher(caseConfig);
      helperStdout = String(caseResult?.helperProcess?.stdoutText || '');
      helperStderr = String(caseResult?.helperProcess?.stderrText || '');
      helperStatus = Number(caseResult?.helperProcess?.status || 0);
      helperSignal = caseResult?.helperProcess?.signal || null;
    } else if (variant.launcherKind === 'auxiliary') {
      const helperArgs = ['--config-json=' + JSON.stringify(caseConfig)];
      const helperResult = spawnSync(process.execPath, [helperScriptPath, ...helperArgs], {
        cwd: process.cwd(),
        env: process.env,
        encoding: 'utf8',
        timeout: 600000,
        killSignal: 'SIGKILL',
        maxBuffer: 20 * 1024 * 1024,
      });
      helperStdout = String(helperResult.stdout || '');
      helperStderr = String(helperResult.stderr || '');
      helperStatus = helperResult.status;
      helperSignal = helperResult.signal;
      try {
        caseResult = helperStdout ? JSON.parse(helperStdout) : null;
      } catch (error) {
        caseResult = {
          variantId: variant.id,
          error: sanitizeDiagnosticText(error?.message || String(error || 'No se pudo parsear JSON del auxiliar.')),
          rawStdout: sanitizeDiagnosticText(helperStdout),
        };
      }
    } else {
      caseResult = await runChromeFdInheritanceCase(caseConfig);
    }

    const parentFdsAfter = captureChromeCleanFdListing(process.pid);
    if (variant.stdioMode === 'inherit') {
      await sleep(100);
    }
    const sanitizedCaseResult = sanitizeDiagnosticValue(caseResult || {});
    const inheritedConsoleLogText =
      variant.stdioMode === 'inherit' ? readDiagnosticFileText(logPath) : '';
    if (inheritedConsoleLogText) {
      const extractedLogText = extractFdInheritanceCaseLog(inheritedConsoleLogText, variant.id);
      helperStderr = helperStderr ? `${helperStderr}\n${extractedLogText}` : extractedLogText;
      sanitizedCaseResult.chromeStderrText = sanitizeDiagnosticText(
        `${sanitizedCaseResult.chromeStderrText || ''}\n${extractedLogText}`.trim()
      );
      sanitizedCaseResult.navigation = sanitizedCaseResult.navigation || {};
      sanitizedCaseResult.navigation.stderrText = sanitizeDiagnosticText(
        `${sanitizedCaseResult.navigation.stderrText || ''}\n${extractedLogText}`.trim()
      );
    }
    sanitizedCaseResult.parentFdsBefore = sanitizeDiagnosticValue(parentFdsBefore);
    sanitizedCaseResult.parentFdsAfter = sanitizeDiagnosticValue(parentFdsAfter);
    sanitizedCaseResult.helperProcess = {
      status: helperStatus,
      signal: helperSignal || null,
      stdoutText: sanitizeDiagnosticText(helperStdout),
      stderrText: sanitizeDiagnosticText(helperStderr),
    };
    sanitizedCaseResult.launcher = {
      kind: variant.launcherKind,
      stdioMode: variant.stdioMode,
      closeInheritedPipeFds: variant.closeInheritedPipeFds,
    };
    sanitizedCaseResult.variantId = variant.id;
    sanitizedCaseResult.label = variant.label;
    sanitizedCaseResult.auditUrl = sanitizeDiagnosticUrl(auditUrl);
    sanitizedCaseResult.chromePath = sanitizeDiagnosticText(variant.executablePath);
    sanitizedCaseResult.fd142InParent = Boolean(
      parentFdsBefore.entries?.some((entry) => Number(entry.fd) === 142 && /pipe:/i.test(String(entry.target || ''))) ||
        parentFdsAfter.entries?.some((entry) => Number(entry.fd) === 142 && /pipe:/i.test(String(entry.target || '')))
    );
    sanitizedCaseResult.fd145InParent = Boolean(
      parentFdsBefore.entries?.some((entry) => Number(entry.fd) === 145 && /pipe:/i.test(String(entry.target || ''))) ||
        parentFdsAfter.entries?.some((entry) => Number(entry.fd) === 145 && /pipe:/i.test(String(entry.target || '')))
    );

    const caseJsonPath = path.join(artifacts.caseDir, 'case.json');
    const launcherResultPath = artifacts.launcherResultPath;
    try {
      fs.writeFileSync(caseJsonPath, `${JSON.stringify(sanitizedCaseResult, null, 2)}\n`);
      fs.writeFileSync(launcherResultPath, `${JSON.stringify(sanitizedCaseResult, null, 2)}\n`);
      fs.writeFileSync(artifacts.parentFdsBeforePath, `${JSON.stringify(parentFdsBefore, null, 2)}\n`);
      fs.writeFileSync(artifacts.parentFdsAfterPath, `${JSON.stringify(parentFdsAfter, null, 2)}\n`);
      if (helperStdout) {
        fs.writeFileSync(artifacts.launcherStdoutPath, sanitizeDiagnosticText(helperStdout));
      }
      if (helperStderr) {
        fs.writeFileSync(artifacts.launcherStderrPath, sanitizeDiagnosticText(helperStderr));
      }
    } catch (error) {
      console.log(
        `[lighthouse][fd-matrix] ${variant.id} no se pudieron escribir artifacts: ${error?.stack || error?.message || error}`
      );
    }

    matrix.cases.push(sanitizedCaseResult);
    if (
      sanitizedCaseResult.exitCode !== 0 ||
      helperStatus !== 0 ||
      helperSignal ||
      sanitizedCaseResult.helperProcess?.status !== 0
    ) {
      matrix.exitCode = 1;
    }
    console.log(
      `[lighthouse][fd-matrix] ${variant.id} complete exit=${sanitizedCaseResult.exitCode ?? 0} helper=${helperStatus ?? 0}${helperSignal ? ` signal=${helperSignal}` : ''}`
    );
    writeSummary();
  }

  console.log(`[lighthouse] FD inheritance diagnostic completed with exit code ${matrix.exitCode}.`);
  writeSummary();
  return matrix;
}

function runDiagnosticCommand(command, args, env = process.env) {
  const result = spawnSync(command, args, {
    cwd: process.cwd(),
    env,
    encoding: 'utf8',
    timeout: 30000,
    killSignal: 'SIGKILL',
  });
  return {
    command,
    args: [...args],
    status: result.status,
    signal: result.signal,
    stdout: sanitizeDiagnosticText(result.stdout || ''),
    stderr: sanitizeDiagnosticText(result.stderr || ''),
    error: sanitizeDiagnosticText(result.error ? result.error.message || String(result.error) : ''),
  };
}

function captureProcFdListing(pid) {
  const targetPid = Number(pid || 0);
  const snapshot = {
    pid: targetPid || null,
    available: false,
    count: 0,
    entries: [],
    error: '',
  };
  if (!targetPid || process.platform !== 'linux' || !fs.existsSync('/proc')) {
    snapshot.error = targetPid ? 'procfs unavailable' : 'missing pid';
    return snapshot;
  }
  const fdDir = path.join('/proc', String(targetPid), 'fd');
  try {
    const entries = fs
      .readdirSync(fdDir)
      .sort((left, right) => Number(left) - Number(right))
      .map((fdName) => {
        const fdPath = path.join(fdDir, fdName);
        let target = '';
        try {
          target = fs.readlinkSync(fdPath);
        } catch (error) {
          target = `ERROR: ${error?.message || String(error || 'Unknown fd error')}`;
        }
        return {
          fd: Number(fdName),
          target: sanitizeDiagnosticText(target),
        };
      });
    snapshot.available = true;
    snapshot.count = entries.length;
    snapshot.entries = entries;
  } catch (error) {
    snapshot.error = sanitizeDiagnosticText(error?.message || String(error || 'Unknown fd listing error'));
  }
  return snapshot;
}

function hasFdTarget(snapshot, fdNumber, matcher) {
  if (!snapshot || !Array.isArray(snapshot.entries)) {
    return false;
  }
  const entry = snapshot.entries.find((item) => Number(item.fd) === Number(fdNumber));
  if (!entry) {
    return false;
  }
  if (!matcher) {
    return true;
  }
  return matcher.test(String(entry.target || ''));
}

function parseProcessTableRows(stdout) {
  return String(stdout || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const match = line.match(/^(\d+)\s+(\d+)\s+(.*)$/);
      if (!match) {
        return null;
      }
      return {
        pid: Number(match[1]),
        ppid: Number(match[2]),
        command: sanitizeDiagnosticText(match[3] || ''),
      };
    })
    .filter(Boolean);
}

function captureProcessTable() {
  const result = runDiagnosticCommand('ps', ['-A', '-o', 'pid=', '-o', 'ppid=', '-o', 'command=']);
  const rows = result.status === 0 ? parseProcessTableRows(result.stdout) : [];
  return {
    ...result,
    available: result.status === 0,
    rows,
  };
}

function collectDescendantProcessRows(rows, rootPid) {
  const targetPid = Number(rootPid || 0);
  if (!targetPid || !Array.isArray(rows) || !rows.length) {
    return [];
  }
  const childrenByPid = new Map();
  for (const row of rows) {
    if (!childrenByPid.has(row.ppid)) {
      childrenByPid.set(row.ppid, []);
    }
    childrenByPid.get(row.ppid).push(row);
  }
  const seen = new Set();
  const queue = [targetPid];
  const descendants = [];
  while (queue.length) {
    const parentPid = queue.shift();
    const children = childrenByPid.get(parentPid) || [];
    for (const child of children) {
      if (seen.has(child.pid)) {
        continue;
      }
      seen.add(child.pid);
      descendants.push(child);
      queue.push(child.pid);
    }
  }
  return descendants;
}

function findNetworkServicePid(rows, browserPid) {
  const descendants = collectDescendantProcessRows(rows, browserPid);
  for (const row of descendants) {
    const command = String(row.command || '');
    if (
      /NetworkService/i.test(command) ||
      /network\.mojom\.NetworkService/i.test(command) ||
      /--type=utility/i.test(command) ||
      /network service/i.test(command)
    ) {
      return row.pid;
    }
  }
  return null;
}

function captureUlimitSnapshot() {
  const result = runDiagnosticCommand('sh', ['-lc', 'ulimit -n']);
  return {
    ...result,
    value: result.status === 0 ? String(result.stdout || '').trim() : '',
  };
}

function createBrowserMatrixLauncherScript({scriptPath, browserPath, stracePrefix}) {
  const source = `#!/usr/bin/env node
'use strict';
const {spawn} = require('child_process');
const browserPath = ${JSON.stringify(browserPath)};
const stracePrefix = ${JSON.stringify(stracePrefix)};
const traceArgs = [
  '-ff',
  '-e',
  'trace=clone,fork,vfork,execve,dup,dup2,dup3,close,fcntl,pipe,pipe2,socket,socketpair',
  '-o',
  stracePrefix,
  browserPath,
  ...process.argv.slice(2),
];
const child = spawn('strace', traceArgs, {
  stdio: 'inherit',
});
child.once('error', (error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
child.once('exit', (code, signal) => {
  process.exit(typeof code === 'number' ? code : signal ? 1 : 0);
});
`;
  fs.mkdirSync(path.dirname(scriptPath), {recursive: true});
  fs.writeFileSync(scriptPath, source, 'utf8');
  try {
    fs.chmodSync(scriptPath, 0o755);
  } catch {}
  return scriptPath;
}

function captureBrowserMatrixSnapshot({
  phase,
  variant,
  browserPid,
  browserVersion,
  browserPath,
  launcherPath,
  tempDir,
  caseDir,
  recorder,
}) {
  const processTable = captureProcessTable();
  const networkServicePid = findNetworkServicePid(processTable.rows, browserPid);
  const snapshot = {
    phase,
    variantId: variant.id,
    label: variant.label,
    source: variant.source,
    browserPid: browserPid || null,
    browserVersion: sanitizeDiagnosticText(browserVersion || ''),
    browserPath: sanitizeDiagnosticText(browserPath || ''),
    launcherPath: sanitizeDiagnosticText(launcherPath || ''),
    nodePid: process.pid,
    tempDir: sanitizeDiagnosticText(tempDir || ''),
    caseDir: sanitizeDiagnosticText(caseDir || ''),
    nodeUlimit: captureUlimitSnapshot(),
    nodeFds: captureProcFdListing(process.pid),
    browserFds: captureProcFdListing(browserPid),
    processTable: {
      ...processTable,
      descendants: collectDescendantProcessRows(processTable.rows, browserPid),
      networkServicePid,
    },
    networkServicePid,
    networkServiceFds: captureProcFdListing(networkServicePid),
  };
  const jsonPath = path.join(caseDir, `${phase}-snapshot.json`);
  const logPath = path.join(caseDir, `${phase}-snapshot.log`);
  try {
    fs.mkdirSync(caseDir, {recursive: true});
    fs.writeFileSync(jsonPath, `${JSON.stringify(snapshot, null, 2)}\n`);
    fs.writeFileSync(
      logPath,
      [
        `[browser-matrix][${variant.id}][${phase}] browserPid=${snapshot.browserPid || 'n/a'}`,
        `[browser-matrix][${variant.id}][${phase}] networkServicePid=${snapshot.networkServicePid || 'n/a'}`,
        `[browser-matrix][${variant.id}][${phase}] nodeFds=${snapshot.nodeFds.count || 0}`,
        `[browser-matrix][${variant.id}][${phase}] browserFds=${snapshot.browserFds.count || 0}`,
        `[browser-matrix][${variant.id}][${phase}] networkServiceFds=${snapshot.networkServiceFds.count || 0}`,
        `[browser-matrix][${variant.id}][${phase}] ulimit=${snapshot.nodeUlimit.value || 'n/a'}`,
      ].join('\n') + '\n',
      'utf8'
    );
  } catch (error) {
    recorder?.record('browser-matrix-snapshot-write-error', {
      phase,
      variantId: variant.id,
      message: sanitizeDiagnosticText(error?.message || String(error || 'Unknown snapshot error')),
    });
  }
  recorder?.record('browser-matrix-snapshot', {
    phase,
    variantId: variant.id,
    jsonPath,
    logPath,
    browserPid: snapshot.browserPid,
    networkServicePid: snapshot.networkServicePid,
    nodeFds: snapshot.nodeFds.count,
    browserFds: snapshot.browserFds.count,
    networkServiceFds: snapshot.networkServiceFds.count,
    ulimit: snapshot.nodeUlimit.value,
  });
  return {
    ...snapshot,
    jsonPath,
    logPath,
  };
}

function summarizeBrowserMatrixStrace(caseDir, variantId) {
  const straceDir = path.join(caseDir, 'strace');
  const summaryPath = path.join(caseDir, 'strace-summary.json');
  const summary = {
    available: false,
    variantId,
    straceDir,
    files: [],
    firstSuspiciousLine: null,
    fdOwnershipViolation: false,
    networkServiceRestart: false,
    error: '',
  };
  try {
    const entries = fs.existsSync(straceDir) ? fs.readdirSync(straceDir).sort() : [];
    summary.files = entries.map((name) => path.join(straceDir, name));
    for (const filePath of summary.files) {
      const text = sanitizeDiagnosticText(fs.readFileSync(filePath, 'utf8'));
      const lines = text.split(/\r?\n/);
      for (let index = 0; index < lines.length; index += 1) {
        const line = lines[index];
        if (!line) continue;
        const suspicious =
          /dup2|dup3|close|fcntl|FD_CLOEXEC|execve|pipe2|socketpair/i.test(line) ||
          /FD ownership violation/i.test(line) ||
          /Network service crashed or was terminated/i.test(line);
        if (!suspicious) continue;
        summary.available = true;
        summary.firstSuspiciousLine = {
          filePath,
          lineNumber: index + 1,
          text: line,
        };
        summary.fdOwnershipViolation = /FD ownership violation/i.test(line);
        summary.networkServiceRestart = /Network service crashed or was terminated/i.test(line);
        break;
      }
      if (summary.firstSuspiciousLine) break;
    }
    if (summary.files.length) {
      summary.available = true;
    }
    fs.writeFileSync(summaryPath, `${JSON.stringify(summary, null, 2)}\n`);
  } catch (error) {
    summary.error = sanitizeDiagnosticText(error?.message || String(error || 'Unknown strace summary error'));
    try {
      fs.writeFileSync(summaryPath, `${JSON.stringify(summary, null, 2)}\n`);
    } catch {}
  }
  return {
    ...summary,
    summaryPath,
  };
}

function buildDiagnosticCaseArtifacts(tempDir, caseId) {
  const caseDir = path.join(tempDir, 'lighthouse-diagnostic-matrix', caseId);
  return {
    caseDir,
    directProfileDir: path.join(caseDir, 'direct-profile'),
    lighthouseProfileDir: path.join(caseDir, 'lighthouse-profile'),
    directNetLogPath: path.join(caseDir, 'lighthouse-netlog-direct.json'),
    lighthouseNetLogPath: path.join(caseDir, 'lighthouse-netlog.json'),
    directChromeStderrPath: path.join(caseDir, 'chrome-stderr-direct.log'),
    lighthouseChromeStderrPath: path.join(caseDir, 'chrome-stderr.log'),
  };
}

function buildDiagnosticServerBootstrapSource() {
  return String.raw`import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

sys.path.insert(0, os.getcwd())

OBSERVATION_PATH = Path(os.environ.get("LHCI_SERVER_OBSERVATION_PATH", ""))
if OBSERVATION_PATH:
    OBSERVATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        OBSERVATION_PATH.write_text("", encoding="utf-8")
    except Exception:
        pass

STARTED_AT = time.time()
SEQ = 0
SENSITIVE_NAMES = {
    "accesstoken",
    "apikey",
    "authtoken",
    "auth",
    "authorization",
    "bearertoken",
    "clientid",
    "clientsecret",
    "code",
    "cookie",
    "csrftoken",
    "idtoken",
    "jwt",
    "jwttoken",
    "oauthtoken",
    "key",
    "pass",
    "passwd",
    "password",
    "privatekey",
    "publickey",
    "refreshtoken",
    "secret",
    "session",
    "sessionid",
    "sessiontoken",
    "signedurl",
    "sig",
    "signature",
    "state",
    "token",
    "xsrftoken",
}


def normalize_name(name):
    text = str(name or "").strip()
    if not text:
        return ""
    text = re.sub(r"[_-]+", " ", text)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return re.sub(r"\s+", " ", text).lower().replace(" ", "")


def redact_query(query):
    if not query:
        return ""
    pairs = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        if normalize_name(key) == "swcleared":
            pairs.append((key, value))
        elif normalize_name(key) in SENSITIVE_NAMES:
            pairs.append((key, "REDACTED"))
        else:
            pairs.append((key, value))
    return urlencode(pairs, doseq=True)


def sanitize_url(value):
    text = str(value or "").strip()
    if not text:
        return ""
    absolute = "://" in text
    candidate = text if absolute else f"http://diagnostic.invalid{text}"
    try:
        split = urlsplit(candidate)
        netloc = split.netloc
        if "@" in netloc:
            netloc = netloc.split("@", 1)[1]
        query = redact_query(split.query)
        fragment = split.fragment
        if fragment and "=" in fragment:
            fragment = redact_query(fragment)
        sanitized = urlunsplit((split.scheme, netloc, split.path, query, fragment))
        if absolute:
            return sanitized
        prefix = "http://diagnostic.invalid"
        if sanitized.startswith(prefix):
            return sanitized[len(prefix):]
        return sanitized
    except Exception:
        return text


def record(event, **data):
    global SEQ
    SEQ += 1
    entry = {
        "seq": SEQ,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime()) + f"{int((time.time() % 1) * 1000):03d}Z",
        "elapsedMs": int((time.time() - STARTED_AT) * 1000),
        "event": event,
        **data,
    }
    if OBSERVATION_PATH:
        try:
            with OBSERVATION_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\\n")
        except Exception:
            pass
    return entry


import web.server as server_module

original_get_request = server_module.ThreadingHTTPServer.get_request
original_send_response = server_module.Handler.send_response
original_end_headers = server_module.Handler.end_headers
original_finish = server_module.Handler.finish
original_log_error = server_module.Handler.log_error
original_do_get = server_module.Handler.do_GET
original_do_head = server_module.Handler.do_HEAD


def get_request(self):
    request, client_address = original_get_request(self)
    record(
        "tcp-accept",
        remoteAddress=client_address[0] if client_address else "",
        remotePort=client_address[1] if client_address else None,
        localAddress=self.server_address[0] if self.server_address else "",
        localPort=self.server_address[1] if self.server_address else None,
    )
    return request, client_address


def send_response(self, code, message=None):
    self._lhci_diag_status = code
    record(
        "send-response",
        method=getattr(self, "command", ""),
        path=sanitize_url(getattr(self, "path", "")),
        status=code,
    )
    return original_send_response(self, code, message)


def end_headers(self):
    record(
        "end-headers",
        method=getattr(self, "command", ""),
        path=sanitize_url(getattr(self, "path", "")),
    )
    return original_end_headers(self)


def finish(self):
    record(
        "socket-close",
        method=getattr(self, "command", ""),
        path=sanitize_url(getattr(self, "path", "")),
        status=getattr(self, "_lhci_diag_status", None),
    )
    return original_finish(self)


def log_error(self, format, *args):
    message = format % args if args else format
    record(
        "error",
        method=getattr(self, "command", ""),
        path=sanitize_url(getattr(self, "path", "")),
        message=sanitize_url(message),
    )
    return original_log_error(self, format, *args)


def wrap_request(original, method_name):
    def wrapped(self, *args, **kwargs):
        record(
            "request-start",
            method=method_name,
            path=sanitize_url(getattr(self, "path", "")),
            remoteAddress=self.client_address[0] if getattr(self, "client_address", None) else "",
            remotePort=self.client_address[1] if getattr(self, "client_address", None) else None,
        )
        try:
            result = original(self, *args, **kwargs)
            record(
                "request-finish",
                method=method_name,
                path=sanitize_url(getattr(self, "path", "")),
                status=getattr(self, "_lhci_diag_status", None),
            )
            return result
        except Exception as exc:
            record(
                "request-error",
                method=method_name,
                path=sanitize_url(getattr(self, "path", "")),
                error=sanitize_url(f"{type(exc).__name__}: {exc}"),
            )
            raise

    return wrapped


server_module.ThreadingHTTPServer.get_request = get_request
server_module.Handler.send_response = send_response
server_module.Handler.end_headers = end_headers
server_module.Handler.finish = finish
server_module.Handler.log_error = log_error
server_module.Handler.do_GET = wrap_request(original_do_get, "GET")
server_module.Handler.do_HEAD = wrap_request(original_do_head, "HEAD")

server_module.main()
`;
}

function createJsonlArtifactRecorder(filePath) {
  fs.mkdirSync(path.dirname(filePath), {recursive: true});
  try {
    fs.writeFileSync(filePath, '');
  } catch {}

  let seq = 0;
  const startedAt = Date.now();

  const record = (event, data = {}) => {
    const sanitizedData = sanitizeDiagnosticValue(data);
    const entry = {
      seq: ++seq,
      ts: new Date().toISOString(),
      elapsedMs: Date.now() - startedAt,
      event,
      ...sanitizedData,
    };
    try {
      fs.appendFileSync(filePath, `${JSON.stringify(entry)}\n`);
    } catch (error) {
      console.log(
        `[lighthouse][diag] no se pudo escribir ${filePath}: ${error?.stack || error?.message || error}`
      );
    }
    return entry;
  };

  return {
    filePath,
    record,
    startedAt,
  };
}

async function runLighthouseMatrixAudit({
  url,
  chromePath,
  userDataDir,
  flags,
  recorder,
  netLogPath = '',
  chromeStderrPath = '',
  inspectBrowser = null,
  inspectPhase = '',
}) {
  let puppeteer = null;
  try {
    puppeteer = require('puppeteer-core');
  } catch (error) {
    const summary = {
      url: sanitizeDiagnosticUrl(url),
      pid: null,
      port: null,
      userDataDir,
      chromePath,
      flags: [...flags, '--headless=new'],
      durationMs: 0,
      error: sanitizeDiagnosticText(error?.message || String(error || 'Unknown require error')),
      exitCode: 1,
    };
    recorder?.record('lighthouse-error', {
      phase: 'require',
      ...summary,
    });
    return summary;
  }
  const lighthouseModule = require('lighthouse');
  const lighthouse = lighthouseModule.default || lighthouseModule;
  const defaultConfig = lighthouseModule.defaultConfig || undefined;
  const startedAt = Date.now();
  const launchFlags = [
    ...flags,
    '--headless=new',
    ...(netLogPath ? [`--log-net-log=${netLogPath}`, '--net-log-capture-mode=Everything'] : []),
  ];
  let browser = null;
  let port = null;
  let browserVersion = '';
  let chromeStderrBridge = null;
  if (netLogPath) {
    recordDiagnosticFileBootstrap(netLogPath);
  }
  if (chromeStderrPath) {
    recordDiagnosticFileBootstrap(chromeStderrPath);
  }
  try {
    browser = await puppeteer.launch({
      executablePath: chromePath,
      headless: true,
      args: launchFlags,
      userDataDir,
    });
    const wsEndpoint = typeof browser.wsEndpoint === 'function' ? browser.wsEndpoint() : '';
    try {
      port = Number(new URL(wsEndpoint).port) || null;
    } catch {
      port = null;
    }
    if (!port) {
      throw new Error('No se pudo derivar el puerto DevTools de Puppeteer para Lighthouse.');
    }
    try {
      chromeStderrBridge = captureBrowserStderr(browser, chromeStderrPath);
    } catch {}
  } catch (error) {
    const summary = {
      url: sanitizeDiagnosticUrl(url),
      pid: null,
      port,
      userDataDir,
      chromePath,
      flags: launchFlags,
      durationMs: Date.now() - startedAt,
      browserVersion,
      netLogPath,
      chromeStderrPath,
      error: sanitizeDiagnosticText(error?.message || String(error || 'Unknown chrome launch error')),
      exitCode: 1,
    };
    recorder?.record('lighthouse-error', {
      phase: 'launch',
      ...summary,
    });
    if (browser) {
      try {
        await browser.close();
      } catch {}
    }
    return summary;
  }
  recorder?.record('lighthouse-launch', {
    url: sanitizeDiagnosticUrl(url),
    pid: browser?.process ? (browser.process() ? browser.process().pid || null : null) : null,
    port,
    userDataDir,
    chromePath,
    flags: launchFlags,
    netLogPath,
    chromeStderrPath,
  });

  try {
    try {
      browserVersion = sanitizeDiagnosticText(await browser.version());
    } catch {}
    const inspectionPromise =
      typeof inspectBrowser === 'function'
        ? Promise.resolve()
            .then(() =>
              inspectBrowser({
                phase: inspectPhase || 'lighthouse-matrix',
                browser,
                browserPid: browser?.process ? (browser.process() ? browser.process().pid || null : null) : null,
                browserVersion,
                browserPath: chromePath,
                launcherPath: chromePath,
                userDataDir,
                url,
                flags: launchFlags,
                netLogPath,
                chromeStderrPath,
              })
            )
            .catch((error) => {
              recorder?.record('lighthouse-error', {
                phase: 'inspect',
                url: sanitizeDiagnosticUrl(url),
                userDataDir,
                chromePath,
                error: sanitizeDiagnosticText(error?.message || String(error || 'Unknown lighthouse inspect error')),
              });
              return null;
            })
        : Promise.resolve(null);
    const runnerResult = await lighthouse(
      url,
      {
        port,
        logLevel: 'error',
        output: 'json',
      },
      defaultConfig
    );
    const inspection = await inspectionPromise;
    const runtimeError = runnerResult?.lhr?.runtimeError || null;
    const summary = {
      url: sanitizeDiagnosticUrl(url),
      pid: browser?.process ? (browser.process() ? browser.process().pid || null : null) : null,
      port,
      userDataDir,
      chromePath,
      flags: launchFlags,
      durationMs: Date.now() - startedAt,
      browserVersion: browserVersion || String(runnerResult?.lhr?.userAgent || ''),
      requestedUrl: sanitizeDiagnosticUrl(runnerResult?.lhr?.requestedUrl || url || ''),
      finalUrl: sanitizeDiagnosticUrl(runnerResult?.lhr?.finalUrl || ''),
      finalDisplayedUrl: sanitizeDiagnosticUrl(runnerResult?.lhr?.finalDisplayedUrl || ''),
      runtimeError: runtimeError
        ? {
            code: runtimeError.code || '',
            message: runtimeError.message || '',
          }
        : null,
      exitCode: runtimeError ? 1 : 0,
      inspection: inspection ? sanitizeDiagnosticValue(inspection) : null,
    };
    recorder?.record('lighthouse-summary', summary);
    return summary;
  } catch (error) {
    const summary = {
      url: sanitizeDiagnosticUrl(url),
      pid: browser?.process ? (browser.process() ? browser.process().pid || null : null) : null,
      port,
      userDataDir,
      chromePath,
      flags: launchFlags,
      durationMs: Date.now() - startedAt,
      browserVersion,
      netLogPath,
      chromeStderrPath,
      error: sanitizeDiagnosticText(error?.message || String(error || 'Unknown lighthouse error')),
      exitCode: 1,
    };
    recorder?.record('lighthouse-error', summary);
    return summary;
  } finally {
    try {
      await browser?.close();
    } catch (error) {
      recorder?.record('lighthouse-error', {
        url: sanitizeDiagnosticUrl(url),
        userDataDir,
        chromePath,
        error: sanitizeDiagnosticText(error?.message || String(error || 'Unknown chrome close error')),
      });
    }
    try {
      if (chromeStderrBridge) {
        chromeStderrBridge.finish('browser-close');
        await chromeStderrBridge.done;
      }
    } catch {}
  }
}

async function runDiagnosticMatrix({auditUrl, tempDir, chromePath}) {
  const logPath = path.join(tempDir, 'lighthouse-diagnostic-matrix.log');
  const jsonPath = path.join(tempDir, 'lighthouse-diagnostic-matrix.json');
  const recorder = createJsonlArtifactRecorder(logPath);
  const netLogArtifacts = createNetLogSummaryArtifacts(tempDir);
  const serverObservationPath = path.join(tempDir, 'lighthouse-server-observations.jsonl');
  let serverObservationCursor = 0;
  const readNewServerObservations = () => {
    const entries = readDiagnosticJsonlEntries(serverObservationPath);
    const nextEntries = entries.slice(serverObservationCursor);
    serverObservationCursor = entries.length;
    return nextEntries;
  };
  const matrix = {
    generatedAt: new Date().toISOString(),
    auditUrl: sanitizeDiagnosticUrl(auditUrl),
    chromePath: sanitizeDiagnosticText(chromePath || ''),
    environment: collectDiagnosticEnvironmentSummary(),
    cases: [],
    probes: [],
    exitCode: 0,
    logPath,
    jsonPath,
    serverObservationPath,
    netLogSummary: netLogArtifacts.summary,
  };
  const cases = buildDiagnosticMatrixCases(auditUrl);
  const baseFlags = getDiagnosticChromeFlags();

  const writeSummary = () => {
    try {
      fs.writeFileSync(jsonPath, `${JSON.stringify(matrix, null, 2)}\n`);
    } catch (error) {
      console.log(
        `[lighthouse][diag] no se pudo escribir ${jsonPath}: ${error?.stack || error?.message || error}`
      );
    }
  };

  recorder.record('matrix-start', {
    auditUrl,
    chromePath,
    environment: matrix.environment,
    serverObservationPath,
    netLogSummary: {
      jsonPath: netLogArtifacts.jsonPath,
      logPath: netLogArtifacts.logPath,
    },
    cases: cases.map((item) => ({id: item.id, label: item.label, url: item.url})),
  });
  writeSummary();

  for (const matrixCase of cases) {
    const caseObservationEntries = [];
    const readCaseObservations = () => {
      const entries = readNewServerObservations();
      caseObservationEntries.push(...entries);
      return entries;
    };
    const artifacts = buildDiagnosticCaseArtifacts(tempDir, matrixCase.id);
    fs.mkdirSync(artifacts.caseDir, {recursive: true});
    fs.mkdirSync(artifacts.directProfileDir, {recursive: true});
    fs.mkdirSync(artifacts.lighthouseProfileDir, {recursive: true});

    const caseSummary = {
      id: matrixCase.id,
      label: matrixCase.label,
      url: sanitizeDiagnosticUrl(matrixCase.url),
      profiles: {
        direct: artifacts.directProfileDir,
        lighthouse: artifacts.lighthouseProfileDir,
      },
      artifacts: {
        caseDir: artifacts.caseDir,
        directNetLogPath: artifacts.directNetLogPath,
        lighthouseNetLogPath: artifacts.lighthouseNetLogPath,
        directChromeStderrPath: artifacts.directChromeStderrPath,
        lighthouseChromeStderrPath: artifacts.lighthouseChromeStderrPath,
      },
      probes: {},
      directNavigation: null,
      lighthouse: null,
      serverObservations: null,
      exitCode: 0,
    };

    recorder.record('case-start', {
      id: matrixCase.id,
      label: matrixCase.label,
      url: matrixCase.url,
      profiles: caseSummary.profiles,
      artifacts: caseSummary.artifacts,
    });

    const curlDefault = runVerboseCurlProbe(matrixCase.url, 10, {noproxy: false});
    const curlDefaultObservations = summarizeDiagnosticServerObservations(readCaseObservations(), matrixCase.url);
    const curlNoProxy = runVerboseCurlProbe(matrixCase.url, 10, {noproxy: true});
    const curlNoProxyObservations = summarizeDiagnosticServerObservations(readCaseObservations(), matrixCase.url);
    const nodeHttpProbe = await runNodeHttpProbe(matrixCase.url, 10000);
    const nodeHttpObservations = summarizeDiagnosticServerObservations(readCaseObservations(), matrixCase.url);
    caseSummary.probes = {
      curl: {
        default: {
          ...curlDefault,
          serverObservations: curlDefaultObservations,
        },
        noProxy: {
          ...curlNoProxy,
          serverObservations: curlNoProxyObservations,
        },
      },
      nodeHttp: {
        ...nodeHttpProbe,
        serverObservations: nodeHttpObservations,
      },
    };
    matrix.probes.push({
      id: matrixCase.id,
      url: caseSummary.url,
      curl: caseSummary.probes.curl,
      nodeHttp: caseSummary.probes.nodeHttp,
    });

    const directStartedAt = Date.now();
    const directResult = await runBrowserDiagnostic(
      matrixCase.url,
      chromePath,
      tempDir,
      {
        record: (event, data) =>
          recorder.record(`case-${matrixCase.id}-direct-${event}`, data),
        diagnosticPath: path.join(artifacts.caseDir, 'navigation-diagnostic.log'),
      },
      {
        profileDir: artifacts.directProfileDir,
        flags: baseFlags,
        waitMs: 4000,
        includeLifecycleEvents: true,
        netLogPath: artifacts.directNetLogPath,
        chromeStderrPath: artifacts.directChromeStderrPath,
      }
    );
    const directServerObservations = summarizeDiagnosticServerObservations(readCaseObservations(), matrixCase.url);
    caseSummary.directNavigation = directResult
      ? {
          ...directResult,
          durationMs: Date.now() - directStartedAt,
          exitCode: directResult.exitCode || 0,
          netLog: readDiagnosticNetLog(artifacts.directNetLogPath, matrixCase.url, {
            caseId: matrixCase.id,
            kind: 'direct-navigation',
          }),
          serverObservations: directServerObservations,
        }
      : {
          exitCode: 1,
          durationMs: Date.now() - directStartedAt,
          error: 'direct navigation failed',
          netLog: readDiagnosticNetLog(artifacts.directNetLogPath, matrixCase.url, {
            caseId: matrixCase.id,
            kind: 'direct-navigation',
          }),
          serverObservations: directServerObservations,
        };
    netLogArtifacts.recordEntry('case-netlog-summary', {
      caseId: matrixCase.id,
      kind: 'direct-navigation',
      path: artifacts.directNetLogPath,
      chromeStderrPath: artifacts.directChromeStderrPath,
      ...caseSummary.directNavigation.netLog,
    });
    if (caseSummary.directNavigation.exitCode !== 0) {
      matrix.exitCode = 1;
    }

    const lighthouseResult = await runLighthouseMatrixAudit({
      url: matrixCase.url,
      chromePath,
      userDataDir: artifacts.lighthouseProfileDir,
      flags: baseFlags,
      recorder: {
        record: (event, data) => recorder.record(`case-${matrixCase.id}-lighthouse-${event}`, data),
      },
      netLogPath: artifacts.lighthouseNetLogPath,
      chromeStderrPath: artifacts.lighthouseChromeStderrPath,
    });
    const lighthouseServerObservations = summarizeDiagnosticServerObservations(readCaseObservations(), matrixCase.url);
    caseSummary.lighthouse = lighthouseResult;
    caseSummary.lighthouse.netLog = readDiagnosticNetLog(artifacts.lighthouseNetLogPath, matrixCase.url, {
      caseId: matrixCase.id,
      kind: 'lighthouse-run',
    });
    caseSummary.lighthouse.serverObservations = lighthouseServerObservations;
    netLogArtifacts.recordEntry('case-netlog-summary', {
      caseId: matrixCase.id,
      kind: 'lighthouse-run',
      path: artifacts.lighthouseNetLogPath,
      chromeStderrPath: artifacts.lighthouseChromeStderrPath,
      ...caseSummary.lighthouse.netLog,
    });
    if ((lighthouseResult && lighthouseResult.exitCode) || !lighthouseResult || lighthouseResult.error) {
      matrix.exitCode = 1;
      if (caseSummary.lighthouse && typeof caseSummary.lighthouse.exitCode !== 'number') {
        caseSummary.lighthouse.exitCode = 1;
      }
    }

    caseSummary.exitCode =
      Number(caseSummary.directNavigation?.exitCode || 0) ||
      Number(caseSummary.lighthouse?.exitCode || 0) ||
      0;
    caseSummary.serverObservations = summarizeDiagnosticServerObservations(caseObservationEntries, matrixCase.url);
    if (caseSummary.exitCode !== 0) {
      matrix.exitCode = 1;
    }

    matrix.cases.push(caseSummary);
    recorder.record('case-complete', {
      id: matrixCase.id,
      label: matrixCase.label,
      exitCode: caseSummary.exitCode,
    });
    writeSummary();
  }

  recorder.record('matrix-complete', {
    exitCode: matrix.exitCode,
    cases: matrix.cases.length,
  });
  netLogArtifacts.recordEntry('matrix-complete', {
    exitCode: matrix.exitCode,
    cases: matrix.cases.length,
  });
  writeSummary();
  return matrix;
}

async function runBrowserMatrixDiagnostic({auditUrl, tempDir, chromePath}) {
  const logPath = path.join(tempDir, 'browser-matrix-linux.log');
  const jsonPath = path.join(tempDir, 'browser-matrix-linux.json');
  const recorder = createJsonlArtifactRecorder(logPath);
  const baseFlags = getDiagnosticChromeFlags();
  const variants = buildBrowserMatrixVariants(chromePath);
  const matrix = {
    generatedAt: new Date().toISOString(),
    auditUrl: sanitizeDiagnosticUrl(auditUrl),
    chromePath: sanitizeDiagnosticText(chromePath || ''),
    environment: collectDiagnosticEnvironmentSummary(),
    variants: variants.map((variant) => ({
      id: variant.id,
      label: variant.label,
      source: variant.source,
      executablePath: variant.executablePath,
      captureStrace: variant.captureStrace,
    })),
    cases: [],
    exitCode: 0,
    logPath,
    jsonPath,
  };

  const writeSummary = () => {
    try {
      fs.writeFileSync(jsonPath, `${JSON.stringify(matrix, null, 2)}\n`);
    } catch (error) {
      console.log(
        `[lighthouse][diag] no se pudo escribir ${jsonPath}: ${error?.stack || error?.message || error}`
      );
    }
  };

  recorder.record('browser-matrix-start', {
    auditUrl,
    chromePath,
    environment: matrix.environment,
    variants: variants.map((variant) => ({
      id: variant.id,
      label: variant.label,
      source: variant.source,
      executablePath: variant.executablePath,
      captureStrace: variant.captureStrace,
    })),
  });
  writeSummary();

  for (const variant of variants) {
    const artifacts = buildBrowserMatrixArtifacts(tempDir, variant.id);
    fs.mkdirSync(artifacts.caseDir, {recursive: true});
    fs.mkdirSync(artifacts.directProfileDir, {recursive: true});
    fs.mkdirSync(artifacts.lighthouseProfileDir, {recursive: true});
    fs.mkdirSync(artifacts.directStraceDir, {recursive: true});
    fs.mkdirSync(artifacts.lighthouseStraceDir, {recursive: true});

    let directChromePath = variant.executablePath;
    let lighthouseChromePath = variant.executablePath;
    if (variant.captureStrace && variant.executablePath) {
      directChromePath = createBrowserMatrixLauncherScript({
        scriptPath: artifacts.directLauncherPath,
        browserPath: variant.executablePath,
        stracePrefix: path.join(artifacts.directStraceDir, 'trace'),
      });
      lighthouseChromePath = createBrowserMatrixLauncherScript({
        scriptPath: artifacts.lighthouseLauncherPath,
        browserPath: variant.executablePath,
        stracePrefix: path.join(artifacts.lighthouseStraceDir, 'trace'),
      });
    }

    const caseSummary = {
      id: variant.id,
      label: variant.label,
      source: variant.source,
      browserPath: variant.executablePath,
      directChromePath,
      lighthouseChromePath,
      captureStrace: variant.captureStrace,
      profiles: {
        direct: artifacts.directProfileDir,
        lighthouse: artifacts.lighthouseProfileDir,
      },
      artifacts: {
        caseDir: artifacts.caseDir,
        prelaunchSnapshotPath: artifacts.prelaunchSnapshotPath,
        runtimeSnapshotPath: artifacts.runtimeSnapshotPath,
        directSnapshotPath: artifacts.directSnapshotPath,
        lighthouseSnapshotPath: artifacts.lighthouseSnapshotPath,
        directNetLogPath: artifacts.directNetLogPath,
        lighthouseNetLogPath: artifacts.lighthouseNetLogPath,
        directChromeStderrPath: artifacts.directChromeStderrPath,
        lighthouseChromeStderrPath: artifacts.lighthouseChromeStderrPath,
        straceSummaryPath: artifacts.straceSummaryPath,
      },
      prelaunchSnapshot: null,
      runtimeSnapshot: null,
      directNavigation: null,
      lighthouse: null,
      straceSummary: null,
      exitCode: 0,
    };

    recorder.record('browser-matrix-case-start', {
      id: variant.id,
      label: variant.label,
      source: variant.source,
      browserPath: variant.executablePath,
      captureStrace: variant.captureStrace,
      profiles: caseSummary.profiles,
      artifacts: caseSummary.artifacts,
    });

    caseSummary.prelaunchSnapshot = captureBrowserMatrixSnapshot({
      phase: 'prelaunch',
      variant,
      browserPid: null,
      browserVersion: '',
      browserPath: variant.executablePath,
      launcherPath: directChromePath,
      tempDir,
      caseDir: artifacts.caseDir,
      recorder,
    });

    const directStartedAt = Date.now();
    const directResult = await runBrowserDiagnostic(
      auditUrl,
      directChromePath,
      tempDir,
      {
        record: (event, data) =>
          recorder.record(`browser-matrix-${variant.id}-direct-${event}`, data),
        diagnosticPath: path.join(artifacts.caseDir, 'direct-navigation-diagnostic.log'),
      },
      {
        profileDir: artifacts.directProfileDir,
        flags: baseFlags,
        waitMs: 4000,
        includeLifecycleEvents: true,
        netLogPath: artifacts.directNetLogPath,
        chromeStderrPath: artifacts.directChromeStderrPath,
        inspectPhase: 'direct-navigation',
        inspectBrowser: async ({
          browser,
          browserPid,
          browserVersion,
          browserPath,
          launcherPath,
          flags,
          tempDir: inspectTempDir,
        }) => {
          await sleep(250);
          return captureBrowserMatrixSnapshot({
            phase: 'direct',
            variant,
            browserPid,
            browserVersion,
            browserPath,
            launcherPath,
            tempDir: inspectTempDir,
            caseDir: artifacts.caseDir,
            recorder,
          });
        },
      }
    );
    caseSummary.directNavigation = directResult
      ? {
          ...directResult,
          durationMs: Date.now() - directStartedAt,
          exitCode: directResult.exitCode || 0,
          netLog: readDiagnosticNetLog(artifacts.directNetLogPath, auditUrl, {
            variantId: variant.id,
            kind: 'direct-navigation',
          }),
        }
      : {
          exitCode: 1,
          durationMs: Date.now() - directStartedAt,
          error: 'direct navigation failed',
          netLog: readDiagnosticNetLog(artifacts.directNetLogPath, auditUrl, {
            variantId: variant.id,
            kind: 'direct-navigation',
          }),
        };
    if (caseSummary.directNavigation.exitCode !== 0) {
      matrix.exitCode = 1;
    }

    const lighthouseStartedAt = Date.now();
    const lighthouseResult = await runLighthouseMatrixAudit({
      url: auditUrl,
      chromePath: lighthouseChromePath,
      userDataDir: artifacts.lighthouseProfileDir,
      flags: baseFlags,
      recorder: {
        record: (event, data) =>
          recorder.record(`browser-matrix-${variant.id}-lighthouse-${event}`, data),
      },
      netLogPath: artifacts.lighthouseNetLogPath,
      chromeStderrPath: artifacts.lighthouseChromeStderrPath,
      inspectPhase: 'lighthouse-navigation',
      inspectBrowser: async ({
        browser,
        browserPid,
        browserVersion,
        browserPath,
        launcherPath,
        userDataDir,
        flags,
        netLogPath,
        chromeStderrPath,
      }) => {
        await sleep(750);
        return captureBrowserMatrixSnapshot({
          phase: 'lighthouse',
          variant,
          browserPid,
          browserVersion,
          browserPath,
          launcherPath,
          tempDir,
          caseDir: artifacts.caseDir,
          recorder,
        });
      },
    });
    caseSummary.lighthouse = lighthouseResult
      ? {
          ...lighthouseResult,
          durationMs: Date.now() - lighthouseStartedAt,
          exitCode: lighthouseResult.exitCode || 0,
          netLog: readDiagnosticNetLog(artifacts.lighthouseNetLogPath, auditUrl, {
            variantId: variant.id,
            kind: 'lighthouse-run',
          }),
        }
      : {
          exitCode: 1,
          durationMs: Date.now() - lighthouseStartedAt,
          error: 'lighthouse run failed',
          netLog: readDiagnosticNetLog(artifacts.lighthouseNetLogPath, auditUrl, {
            variantId: variant.id,
            kind: 'lighthouse-run',
          }),
        };
    if ((lighthouseResult && lighthouseResult.exitCode) || !lighthouseResult || lighthouseResult.error) {
      matrix.exitCode = 1;
      if (caseSummary.lighthouse && typeof caseSummary.lighthouse.exitCode !== 'number') {
        caseSummary.lighthouse.exitCode = 1;
      }
    }

    caseSummary.runtimeSnapshot = caseSummary.lighthouse?.inspection || caseSummary.directNavigation?.inspection || null;
    caseSummary.directNavigation.stderrFlags = {
      fdOwnershipViolation: /FD ownership violation/i.test(readDiagnosticFileText(artifacts.directChromeStderrPath)),
      networkServiceRestart: /Network service crashed or was terminated/i.test(
        readDiagnosticFileText(artifacts.directChromeStderrPath)
      ),
      errAborted: /ERR_ABORTED/i.test(
        String(caseSummary.directNavigation.failureErrorText || '') + String(caseSummary.lighthouse?.runtimeError?.message || '')
      ),
    };
    caseSummary.lighthouse.stderrFlags = {
      fdOwnershipViolation: /FD ownership violation/i.test(readDiagnosticFileText(artifacts.lighthouseChromeStderrPath)),
      networkServiceRestart: /Network service crashed or was terminated/i.test(
        readDiagnosticFileText(artifacts.lighthouseChromeStderrPath)
      ),
      errAborted: /ERR_ABORTED/i.test(
        String(caseSummary.lighthouse?.runtimeError?.message || '') + String(caseSummary.directNavigation?.failureErrorText || '')
      ),
    };

    caseSummary.straceSummary = summarizeBrowserMatrixStrace(artifacts.caseDir, variant.id);
    if (caseSummary.straceSummary.firstSuspiciousLine) {
      recorder.record('browser-matrix-strace-summary', {
        variantId: variant.id,
        ...caseSummary.straceSummary,
      });
    }

    caseSummary.exitCode =
      Number(caseSummary.directNavigation?.exitCode || 0) ||
      Number(caseSummary.lighthouse?.exitCode || 0) ||
      0;
    if (caseSummary.exitCode !== 0) {
      matrix.exitCode = 1;
    }

    matrix.cases.push(caseSummary);
    recorder.record('browser-matrix-case-complete', {
      id: variant.id,
      label: variant.label,
      exitCode: caseSummary.exitCode,
    });
    writeSummary();
  }

  recorder.record('browser-matrix-complete', {
    exitCode: matrix.exitCode,
    cases: matrix.cases.length,
  });
  writeSummary();
  return matrix;
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

function isReachableHttpStatus(code) {
  return Number.isInteger(code) && code >= 200 && code < 400;
}

function probeAuditUrlReachability(auditUrl, curlTimeoutSeconds) {
  const headResult = curlStatus(auditUrl, curlTimeoutSeconds, {method: 'HEAD'});
  if (isReachableHttpStatus(headResult.code)) {
    return {
      method: 'HEAD',
      headResult,
      result: headResult,
      headUnsupported: false,
      fallbackUsed: false,
    };
  }
  return {
    method: 'GET',
    headResult,
    result: curlStatus(auditUrl, curlTimeoutSeconds, {method: 'GET'}),
    headUnsupported: isHeadUnsupported(headResult),
    fallbackUsed: true,
  };
}

function spawnServer({port, tempDir, dbPath, ocrDbPath, serverLogPath, diagnosticMode = false, serverObservationPath = ''}) {
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

  if (diagnosticMode) {
    const bootstrapPath = path.join(tempDir, 'lighthouse-server-bootstrap.py');
    try {
      fs.writeFileSync(bootstrapPath, buildDiagnosticServerBootstrapSource(), 'utf8');
    } catch (error) {
      throw new Error(
        [
          'No se pudo preparar el bootstrap diagnóstico del servidor para Lighthouse.',
          error?.message || String(error || 'Unknown bootstrap error'),
        ].join(' ')
      );
    }
    env.LHCI_SERVER_OBSERVATION_PATH = serverObservationPath || path.join(tempDir, 'lighthouse-server-observations.jsonl');
    const child = spawn(
      'python',
      ['-u', bootstrapPath, '--host', '127.0.0.1', '--port', String(port), '--db', dbPath, '--ocr-db', ocrDbPath, '--ocr-workers', '1'],
      {
        cwd: process.cwd(),
        env,
        stdio: ['ignore', 'pipe', 'pipe'],
      }
    );
    const logStream = fs.createWriteStream(serverLogPath, {flags: 'a'});
    const rawLogCapture = attachRawLogCapture(child, logStream);
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    const writeStdout = process.stdout.write.bind(process.stdout);
    const writeStderr = process.stderr.write.bind(process.stderr);
    const stdoutConsole = attachSanitizedConsoleStream(child.stdout, writeStdout);
    const stderrConsole = attachSanitizedConsoleStream(child.stderr, writeStderr);
    const consoleClosed = Promise.all([stdoutConsole.done, stderrConsole.done]);
    const forceConsoleClose = () => {
      stdoutConsole.finish('forced');
      stderrConsole.finish('forced');
    };

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
      consoleClosed,
      forceConsoleClose,
      stopRawLogCapture: rawLogCapture.stop,
      closeLog: rawLogCapture.closeLog,
      diagnosticMode: true,
      diagnosticServerObservationPath: env.LHCI_SERVER_OBSERVATION_PATH,
    };
  }

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
  const rawLogCapture = attachRawLogCapture(child, logStream);
  child.stdout.setEncoding('utf8');
  child.stderr.setEncoding('utf8');
  const writeStdout = process.stdout.write.bind(process.stdout);
  const writeStderr = process.stderr.write.bind(process.stderr);
  const stdoutConsole = attachSanitizedConsoleStream(child.stdout, writeStdout);
  const stderrConsole = attachSanitizedConsoleStream(child.stderr, writeStderr);
  const consoleClosed = Promise.all([stdoutConsole.done, stderrConsole.done]);
  const forceConsoleClose = () => {
    stdoutConsole.finish('forced');
    stderrConsole.finish('forced');
  };

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
    consoleClosed,
    forceConsoleClose,
    stopRawLogCapture: rawLogCapture.stop,
    closeLog: rawLogCapture.closeLog,
    diagnosticMode: false,
    diagnosticServerObservationPath: serverObservationPath || '',
  };
}

async function stopServer(server, opts = {}) {
  if (!server || !server.child) return;
  const child = server.child;
  const wait = typeof sleep === 'function'
    ? sleep
    : (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const graceMs = Math.max(500, Number(opts.graceMs || 5000) || 5000);
  const consoleGraceMs = Math.max(500, Number(opts.consoleGraceMs || graceMs) || graceMs);
  const killSignal = opts.signal || 'SIGTERM';
  if (child.exitCode === null && child.signalCode === null) {
    try {
      child.kill(killSignal);
    } catch {}

    const settled = await Promise.race([
      server.exited.then(() => true),
      wait(graceMs).then(() => false),
    ]);
    if (!settled && child.exitCode === null && child.signalCode === null) {
      try {
        child.kill('SIGKILL');
      } catch {}
      await Promise.race([server.exited.then(() => true), wait(2000)]);
    }
  }

  try {
    const consoleClosed = server.consoleClosed || Promise.resolve();
    const consoleSettled = await Promise.race([
      consoleClosed.then(() => true),
      wait(consoleGraceMs).then(() => false),
    ]);
    if (!consoleSettled) {
      try {
        server.stopRawLogCapture?.();
      } catch {}
      try {
        server.forceConsoleClose?.();
      } catch {}
      await Promise.race([
        consoleClosed.then(() => true),
        wait(2000).then(() => false),
      ]);
    }
  } catch {}
  try {
    server.stopRawLogCapture?.();
  } catch {}
  try {
    await server.closeLog?.();
  } catch {}
}

async function waitForServer({
  auditUrl,
  healthUrl,
  server,
  timeoutMs,
  curlTimeoutSeconds,
  mode = 'local',
}) {
  const startedAt = Date.now();
  let attempt = 0;
  let lastHealth = null;
  let lastAudit = null;
  const isExternalMode = mode === 'external';
  let auditProbeMethod = 'HEAD';

  while ((Date.now() - startedAt) < timeoutMs) {
    if (server?.child && (server.child.exitCode !== null || server.child.signalCode !== null)) {
      break;
    }

    attempt += 1;
    let auditDetail = 'pendiente';

    if (isExternalMode) {
      lastHealth = null;
      const auditProbe = probeAuditUrlReachability(auditUrl, curlTimeoutSeconds);
      auditProbeMethod = auditProbe.method;
      lastAudit = auditProbe.result;
      if (isReachableHttpStatus(auditProbe.headResult?.code)) {
        auditDetail = `HEAD ${describeStatus(auditProbe.headResult)}`;
      } else if (auditProbe.headUnsupported) {
        auditDetail = `HEAD no soportado (${describeStatus(auditProbe.headResult)}), GET ${describeStatus(auditProbe.result)}`;
      } else {
        auditDetail = `HEAD ${describeStatus(auditProbe.headResult)}, GET ${describeStatus(auditProbe.result)}`;
      }
    } else {
      lastHealth = curlStatus(healthUrl, curlTimeoutSeconds, {captureBody: true});
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
    }

    const elapsedMs = Date.now() - startedAt;
    const remainingMs = Math.max(0, timeoutMs - elapsedMs);
    const elapsedLabel = Math.ceil(elapsedMs / 1000);
    const remainingLabel = Math.ceil(remainingMs / 1000);
    const healthDetail = lastHealth?.body ? ` (${lastHealth.body.slice(0, 120)})` : '';

    if (isExternalMode) {
      console.log(
        `[lighthouse] readiness attempt ${attempt} [external]: url=${auditDetail} elapsed=${elapsedLabel}s remaining=${remainingLabel}s`
      );
      if (isReachableHttpStatus(lastAudit?.code)) {
        return {
          attempt,
          elapsedMs,
          lastHealth,
          lastAudit,
          readinessMode: 'external',
          auditProbeMethod,
        };
      }
    } else {
      console.log(
        `[lighthouse] readiness attempt ${attempt} [local]: health=${describeStatus(lastHealth)}${healthDetail} url=${auditDetail} elapsed=${elapsedLabel}s remaining=${remainingLabel}s`
      );

      if (lastHealth.code === 200 && lastAudit?.code === 200) {
        return {attempt, elapsedMs, lastHealth, lastAudit, readinessMode: 'local'};
      }

      if (lastHealth.code === 200 && isHeadUnsupported(lastAudit)) {
        console.log(
          '[lighthouse] La ruta auditada no soporta HEAD; se confiará en /api/health y Lighthouse hará la primera carga real.'
        );
        return {attempt, elapsedMs, lastHealth, lastAudit, readinessMode: 'local', auditHeadUnsupported: true};
      }
    }

    if (server?.child && (server.child.exitCode !== null || server.child.signalCode !== null)) {
      break;
    }

    const delayMs = Math.min(5000, 1000 + attempt * 500);
    await sleep(delayMs);
  }

  const failure = new Error(
    [
      isExternalMode
        ? `El destino externo no respondió con un estado HTTP válido dentro de ${Math.round(timeoutMs / 1000)}s.`
        : `La aplicación no devolvió HTTP 200 dentro de ${Math.round(timeoutMs / 1000)}s.`,
      ...(isExternalMode ? [] : [`Health check: ${describeStatus(lastHealth)}`]),
      `URL auditada: ${describeStatus(lastAudit)}`,
    ].join('\n')
  );
  failure.lastHealth = lastHealth;
  failure.lastAudit = lastAudit;
  throw failure;
}

function runCommand(command, args, env, options = {}) {
  const captureOutput = Boolean(options.captureOutput);
  const buildCommandError = (code, signal) => {
    const error = new Error(
      `${command} ${args.join(' ')} terminó con código ${typeof code === 'number' ? code : 1}${signal ? ` (signal ${signal})` : ''}`
    );
    error.code = code;
    error.signal = signal;
    return error;
  };

  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: process.cwd(),
      env,
      stdio: captureOutput ? ['ignore', 'pipe', 'pipe'] : 'inherit',
    });

    if (!captureOutput) {
      child.once('error', reject);
      child.once('exit', (code, signal) => {
        if (code === 0) {
          resolve({code, signal});
          return;
        }
        reject(buildCommandError(code, signal));
      });
      return;
    }

    const stdoutConsole = child.stdout
      ? attachSanitizedConsoleStream(child.stdout, process.stdout.write.bind(process.stdout))
      : null;
    const stderrConsole = child.stderr
      ? attachSanitizedConsoleStream(child.stderr, process.stderr.write.bind(process.stderr))
      : null;
    const consoleClosed = Promise.all([
      stdoutConsole ? stdoutConsole.done : Promise.resolve(),
      stderrConsole ? stderrConsole.done : Promise.resolve(),
    ]);

    let settled = false;

    const cleanup = () => {
      child.removeListener('error', onError);
      child.removeListener('close', onClose);
    };

    const settleResolve = (value) => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve(value);
    };

    const settleReject = (error) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    };

    function onError(error) {
      if (stdoutConsole) {
        stdoutConsole.finish('error');
      }
      if (stderrConsole) {
        stderrConsole.finish('error');
      }
      settleReject(error);
    }

    function onClose(code, signal) {
      consoleClosed.then(
        () => {
          if (code === 0) {
            settleResolve({code, signal});
            return;
          }
          settleReject(buildCommandError(code, signal));
        },
        (error) => settleReject(error)
      );
    }

    child.once('error', onError);
    child.once('close', onClose);
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
  const chromePath = resolveChromePath();
  const diagnosticsEnabled = String(process.env.LHCI_DIAGNOSTIC || '').trim() === '1';
  const matrixEnabled = isDiagnosticMatrixEnabled();
  const fdInheritanceMatrixEnabled = isFdInheritanceDiagnosticEnabled();
  const browserMatrixEnabled = isBrowserMatrixDiagnosticEnabled();
  const localOrigin = new URL(`http://127.0.0.1:${port}/`).origin;
  const auditOrigin = new URL(auditUrl).origin;
  const useExternalBaseUrl = Boolean(String(process.env.LHCI_BASE_URL || '').trim()) && auditOrigin !== localOrigin;
  const healthUrl = useExternalBaseUrl ? null : `http://127.0.0.1:${port}/api/health`;
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
  if (!useExternalBaseUrl) {
    bootstrapSqliteSchema(dbPath, sharedDbEnv);
  } else {
    console.log('[lighthouse] LHCI_BASE_URL externo detectado; se omite el servidor local y el bootstrap SQLite temporal.');
  }
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
  const sanitizedRawAuditUrl = sanitizeDiagnosticUrl(rawAuditUrl);
  const sanitizedAuditUrl = sanitizeDiagnosticUrl(auditUrl);
  console.log(`Lighthouse temp dir: ${tempDir}`);
  console.log(`Lighthouse server log: ${path.join(tempDir, 'lighthouse-server.log')}`);
  if (String(sanitizedRawAuditUrl).trim() !== String(sanitizedAuditUrl).trim()) {
    console.log(`[lighthouse] audit URL normalized: ${sanitizedRawAuditUrl} -> ${sanitizedAuditUrl}`);
  }
  console.log(`Lighthouse base URL: ${sanitizedAuditUrl}`);

  const server = useExternalBaseUrl
    ? null
    : spawnServer({
        port,
        tempDir,
        dbPath,
        ocrDbPath,
        serverLogPath: path.join(tempDir, 'lighthouse-server.log'),
        diagnosticMode: matrixEnabled || browserMatrixEnabled,
        serverObservationPath: path.join(tempDir, 'lighthouse-server-observations.jsonl'),
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
    if (server) {
      await server.started;
    }

    const ready = await waitForServer({
      auditUrl,
      healthUrl,
      server,
      timeoutMs: 300000,
      curlTimeoutSeconds: 5,
      mode: useExternalBaseUrl ? 'external' : 'local',
    });

    console.log(
      useExternalBaseUrl
        ? `[lighthouse] destino externo listo tras ${Math.ceil(ready.elapsedMs / 1000)}s y ${ready.attempt} comprobaciones.`
        : `[lighthouse] servidor listo tras ${Math.ceil(ready.elapsedMs / 1000)}s y ${ready.attempt} comprobaciones.`
    );

    if (fdInheritanceMatrixEnabled) {
      console.log('[lighthouse] FD inheritance matrix diagnostic enabled.');
      const matrix = await runFdInheritanceMatrixDiagnostic({auditUrl, tempDir, chromePath});
      console.log(`[lighthouse] FD inheritance matrix completed with exit code ${matrix.exitCode}.`);
      if (matrix.exitCode !== 0) {
        throw new Error(`FD inheritance matrix diagnostic failed with exit code ${matrix.exitCode}`);
      }
      return;
    }

    if (browserMatrixEnabled) {
      console.log('[lighthouse] Browser matrix diagnostic enabled.');
      const matrix = await runBrowserMatrixDiagnostic({auditUrl, tempDir, chromePath});
      console.log(`[lighthouse] Browser matrix diagnostic completed with exit code ${matrix.exitCode}.`);
      if (matrix.exitCode !== 0) {
        throw new Error(`Browser matrix diagnostic failed with exit code ${matrix.exitCode}`);
      }
      return;
    }

    if (matrixEnabled) {
      console.log('[lighthouse] Lighthouse diagnostic matrix enabled.');
      const matrix = await runDiagnosticMatrix({auditUrl, tempDir, chromePath});
      console.log(
        `[lighthouse] Lighthouse diagnostic matrix completed with exit code ${matrix.exitCode}.`
      );
      if (matrix.exitCode !== 0) {
        throw new Error(`Lighthouse diagnostic matrix failed with exit code ${matrix.exitCode}`);
      }
      return;
    }

    if (diagnosticsEnabled) {
      console.log('[lighthouse] Pre-LHCI diagnostics enabled.');
      await runPreLhciDiagnostics({auditUrl, tempDir, chromePath});
      console.log('[lighthouse] Pre-LHCI diagnostics completed.');
    }

    await runCommand('npx', ['--no-install', 'lhci', 'autorun'], baseEnv, {captureOutput: true});
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
      const sanitizedTail = sanitizeDiagnosticText(tail);
      console.error('--- Server log tail ---');
      console.error(sanitizedTail);
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
