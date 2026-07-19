#!/usr/bin/env node
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const {spawn, spawnSync} = require('child_process');
const {StringDecoder} = require('node:string_decoder');
const puppeteer = require('puppeteer-core');

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

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

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
  return String(text || '').replace(
    /(^|[^A-Za-z0-9._-])([A-Za-z0-9._-]+)=([^\s&#"'`<>]+)/g,
    (match, prefix, key) => {
      if (!isSensitiveDiagnosticParamName(key)) {
        return match;
      }
      return `${prefix}${key}=${DIAGNOSTIC_REDACTED_VALUE}`;
    }
  );
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

function captureProcFdListing(pid, fsImpl = fs, processImpl = process) {
  const targetPid = Number(pid || 0);
  const snapshot = {
    pid: targetPid || null,
    available: false,
    count: 0,
    entries: [],
    error: '',
  };
  if (!targetPid || processImpl.platform !== 'linux' || !fsImpl.existsSync('/proc')) {
    snapshot.error = targetPid ? 'procfs unavailable' : 'missing pid';
    return snapshot;
  }
  const fdDir = path.join('/proc', String(targetPid), 'fd');
  try {
    const entries = fsImpl
      .readdirSync(fdDir)
      .sort((left, right) => Number(left) - Number(right))
      .map((fdName) => {
        const fdPath = path.join(fdDir, fdName);
        let target = '';
        try {
          target = fsImpl.readlinkSync(fdPath);
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
  const result = spawnSync('ps', ['-A', '-o', 'pid=', '-o', 'ppid=', '-o', 'command='], {
    cwd: process.cwd(),
    env: process.env,
    encoding: 'utf8',
    timeout: 30000,
    killSignal: 'SIGKILL',
  });
  const rows = result.status === 0 ? parseProcessTableRows(result.stdout) : [];
  return {
    command: 'ps',
    args: ['-A', '-o', 'pid=', '-o', 'ppid=', '-o', 'command='],
    status: result.status,
    signal: result.signal,
    stdout: sanitizeDiagnosticText(result.stdout || ''),
    stderr: sanitizeDiagnosticText(result.stderr || ''),
    error: sanitizeDiagnosticText(result.error ? result.error.message || String(result.error) : ''),
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

function buildChromeLaunchFlags(extraFlags = []) {
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
    '--headless=new',
    '--remote-debugging-port=0',
    ...extraFlags,
  ];
}

function readDevToolsActivePort(profileDir) {
  const filePath = path.join(profileDir, 'DevToolsActivePort');
  const text = String(fs.readFileSync(filePath, 'utf8') || '').trim();
  const [portLine = '', wsPathLine = ''] = text.split(/\r?\n/).filter(Boolean);
  const port = Number(portLine || 0) || 0;
  const wsPath = String(wsPathLine || '');
  if (!port || !wsPath) {
    throw new Error('DevToolsActivePort inválido.');
  }
  return {
    filePath,
    port,
    wsPath,
    wsEndpoint: `ws://127.0.0.1:${port}${wsPath}`,
  };
}

async function waitForDevToolsActivePort(profileDir, child, timeoutMs = 30000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (child.exitCode !== null || child.signalCode !== null) {
      throw new Error('Chrome terminó antes de publicar DevToolsActivePort.');
    }
    try {
      return readDevToolsActivePort(profileDir);
    } catch {
      await sleep(100);
    }
  }
  throw new Error(`DevToolsActivePort no apareció dentro de ${Math.round(timeoutMs / 1000)}s.`);
}

function snapshotFdsForPid(pid, fsImpl = fs, processImpl = process) {
  return captureProcFdListing(pid, fsImpl, processImpl);
}

function hasFdTarget(snapshot, fdNumber, matcher) {
  if (!snapshot || !Array.isArray(snapshot.entries)) return false;
  const entry = snapshot.entries.find((item) => Number(item.fd) === Number(fdNumber));
  if (!entry) return false;
  if (!matcher) return true;
  return matcher.test(String(entry.target || ''));
}

function closeInheritedPipeDescriptors({allowList = [0, 1, 2], fsImpl = fs, processImpl = process} = {}) {
  const before = snapshotFdsForPid(processImpl.pid, fsImpl, processImpl);
  const closed = [];
  const keep = new Set(allowList.map((fd) => Number(fd)));
  if (!before.available) {
    return {
      before,
      after: before,
      closed,
      error: before.error || 'fd snapshot unavailable',
    };
  }
  for (const entry of before.entries) {
    if (keep.has(entry.fd)) {
      continue;
    }
    if (!/^pipe:\[\d+\]$/.test(String(entry.target || ''))) {
      continue;
    }
    try {
      fsImpl.closeSync(entry.fd);
      closed.push({
        fd: entry.fd,
        target: entry.target,
        type: 'pipe',
        reason: 'inherited pipe from parent',
        closed: true,
      });
    } catch (error) {
      closed.push({
        fd: entry.fd,
        target: entry.target,
        type: 'pipe',
        reason: 'inherited pipe from parent',
        closed: false,
        error: sanitizeDiagnosticText(error?.message || String(error || 'Unknown close error')),
      });
    }
  }
  const after = snapshotFdsForPid(processImpl.pid, fsImpl, processImpl);
  return {
    before,
    after,
    closed,
  };
}

function normalizeChromiumStdio(stdioMode) {
  if (stdioMode === 'inherit') {
    return ['ignore', 'inherit', 'inherit'];
  }
  if (stdioMode === 'ignore') {
    return ['ignore', 'ignore', 'ignore'];
  }
  return ['ignore', 'pipe', 'pipe'];
}

function createCapturedLineWriter(onLine) {
  const decoder = new StringDecoder('utf8');
  let buffer = '';
  let closed = false;
  let decoderFinished = false;

  const emit = (line, newline = '') => {
    try {
      onLine(`${sanitizeDiagnosticText(line)}${newline}`);
    } catch {}
  };

  const drain = () => {
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
      if (!decoderFinished) {
        const tail = decoder.end();
        if (tail) {
          buffer += tail;
        }
        decoderFinished = true;
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

async function runChromeFdInheritanceCase(config, deps = {}) {
  const spawnImpl = deps.spawn || spawn;
  const puppeteerImpl = deps.puppeteer || puppeteer;
  const fsImpl = deps.fs || fs;
  const processImpl = deps.process || process;
  const variant = {
    id: config.variantId || config.id || 'F?',
    label: config.label || config.variantLabel || '',
    stdioMode: config.stdioMode || 'pipe',
    launcherKind: config.launcherKind || 'direct',
    closeInheritedPipeFds: Boolean(config.closeInheritedPipeFds),
  };
  const auditUrl = sanitizeDiagnosticUrl(config.auditUrl || '');
  const chromePath = sanitizeDiagnosticText(config.chromePath || '');
  const tempDir = path.resolve(config.tempDir || fsImpl.mkdtempSync(path.join(os.tmpdir(), 'lhci-fd-')));
  const caseDir = path.resolve(config.caseDir || path.join(tempDir, 'fd-inheritance-matrix', variant.id));
  fsImpl.mkdirSync(caseDir, {recursive: true});
  const profileDir = path.resolve(config.profileDir || path.join(caseDir, 'profile'));
  fsImpl.mkdirSync(profileDir, {recursive: true});
  const extraFlags = Array.isArray(config.extraFlags) ? config.extraFlags : [];
  const launchFlags = buildChromeLaunchFlags(extraFlags);
  const stdio = normalizeChromiumStdio(variant.stdioMode);

  const helperPid = processImpl.pid;
  const helperFdsBefore = snapshotFdsForPid(helperPid, fsImpl, processImpl);
  const scrubbedFds = variant.closeInheritedPipeFds
    ? closeInheritedPipeDescriptors({allowList: [0, 1, 2], fsImpl, processImpl})
    : {before: helperFdsBefore, after: helperFdsBefore, closed: []};
  const helperFdsAfter = variant.closeInheritedPipeFds ? scrubbedFds.after : helperFdsBefore;

  const navigationEvents = [];
  const chromeStdoutChunks = [];
  const chromeStderrChunks = [];
  const chromeStdoutForwarder = createCapturedLineWriter((line) => {
    chromeStdoutChunks.push(line);
    if (processImpl.stderr && typeof processImpl.stderr.write === 'function') {
      processImpl.stderr.write(line);
    }
  });
  const chromeStderrForwarder = createCapturedLineWriter((line) => {
    chromeStderrChunks.push(line);
    if (processImpl.stderr && typeof processImpl.stderr.write === 'function') {
      processImpl.stderr.write(line);
    }
  });

  const chromeArgs = [...launchFlags, `--user-data-dir=${profileDir}`];
  const child = spawnImpl(chromePath, chromeArgs, {
    cwd: processImpl.cwd(),
    env: processImpl.env,
    stdio,
    shell: false,
  });

  if (!child || typeof child.pid !== 'number') {
    throw new Error('No se pudo lanzar Chrome para la matriz de herencia de FDs.');
  }

  const chromePid = child.pid;
  const chromeClosePromise = new Promise((resolve) => {
    child.once('close', (code, signal) => {
      resolve({code, signal});
    });
  });

  if (child.stdout && typeof child.stdout.setEncoding === 'function') {
    child.stdout.setEncoding('utf8');
  }
  if (child.stderr && typeof child.stderr.setEncoding === 'function') {
    child.stderr.setEncoding('utf8');
  }

  if (child.stdout && typeof child.stdout.on === 'function' && variant.stdioMode === 'pipe') {
    child.stdout.on('data', (chunk) => {
      chromeStdoutForwarder.write(chunk);
    });
  }
  if (child.stderr && typeof child.stderr.on === 'function') {
    child.stderr.on('data', (chunk) => {
      chromeStderrForwarder.write(chunk);
    });
  }

  let browser = null;
  let browserVersion = '';
  let browserWSEndpoint = '';
  let chromeFdsBeforeClose = snapshotFdsForPid(chromePid, fsImpl, processImpl);
  let chromeFdsAfterClose = null;
  let navigationResponse = null;
  let gotoError = null;
  let browserClosed = false;
  let exitInfo = {code: null, signal: null};
  let networkServicePid = null;
  let networkServiceFds = null;
  let processTableBeforeClose = null;
  let processTableAfterClose = null;

  try {
    const devTools = await waitForDevToolsActivePort(profileDir, child, Number(config.devtoolsTimeoutMs || 30000));
    browserWSEndpoint = devTools.wsEndpoint;
    browser = await puppeteerImpl.connect({
      browserWSEndpoint,
    });
    browserVersion = sanitizeDiagnosticText(await browser.version());
    const page = await browser.newPage();
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

    try {
      navigationResponse = await page.goto(auditUrl, {
        waitUntil: 'load',
        timeout: Number(config.navigationTimeoutMs || 30000),
      });
    } catch (error) {
      gotoError = error;
    }

    processTableBeforeClose = captureProcessTable();
    networkServicePid = findNetworkServicePid(processTableBeforeClose.rows, chromePid);
    networkServiceFds = snapshotFdsForPid(networkServicePid, fsImpl, processImpl);
    chromeFdsBeforeClose = snapshotFdsForPid(chromePid, fsImpl, processImpl);

    try {
      if (browser) {
        await browser.close();
        browserClosed = true;
      }
    } catch (error) {
      navigationEvents.push(
        sanitizeDiagnosticValue({
          event: 'browser-close-error',
          message: error?.message || String(error || 'Unknown browser close error'),
        })
      );
    }

    exitInfo = await Promise.race([
      chromeClosePromise,
      sleep(Number(config.closeTimeoutMs || 10000)).then(() => ({code: null, signal: null, timeout: true})),
    ]);

    chromeStdoutForwarder.finish();
    chromeStderrForwarder.finish();

    chromeFdsAfterClose = snapshotFdsForPid(chromePid, fsImpl, processImpl);
    processTableAfterClose = captureProcessTable();
    if (!networkServicePid) {
      networkServicePid = findNetworkServicePid(processTableAfterClose.rows, chromePid);
    }
    if (networkServicePid) {
      networkServiceFds = snapshotFdsForPid(networkServicePid, fsImpl, processImpl);
    }
  } finally {
    if (browser && !browserClosed) {
      try {
        await browser.close();
      } catch {}
    }
  }

  const requestEvent = navigationEvents.find((entry) => entry.event === 'request');
  const responseEvent = navigationEvents.find((entry) => entry.event === 'response');
  const failedEvent = navigationEvents.find((entry) => entry.event === 'requestfailed');
  const frameNavigated = navigationEvents.find((entry) => entry.event === 'framenavigated');
  const loadEvent = navigationEvents.find((entry) => entry.event === 'load');
  const domContentLoadedEvent = navigationEvents.find((entry) => entry.event === 'domcontentloaded');

  const navigationStatus = responseEvent ? Number(responseEvent.status || 0) : null;
  const requestFailedErrorText = failedEvent ? String(failedEvent.errorText || '') : '';
  const stderrText = chromeStderrChunks.join('');
  const stdoutText = chromeStdoutChunks.join('');
  const summary = {
    variantId: variant.id,
    label: variant.label,
    launcherKind: variant.launcherKind,
    stdioMode: variant.stdioMode,
    closeInheritedPipeFds: variant.closeInheritedPipeFds,
    auditUrl,
    chromePath,
    helperPid,
    chromePid,
    browserVersion,
    browserWSEndpoint,
    navigationTimeoutMs: Number(config.navigationTimeoutMs || 30000),
    closeTimeoutMs: Number(config.closeTimeoutMs || 10000),
    devtoolsTimeoutMs: Number(config.devtoolsTimeoutMs || 30000),
    launchFlags,
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
      exitInfo,
    },
    helperFdsBefore,
    helperFdsAfter,
    chromeFdsBeforeClose,
    chromeFdsAfterClose,
    networkServicePid,
    networkServiceFds,
    processTableBeforeClose,
    processTableAfterClose,
    chromeStdoutText: sanitizeDiagnosticText(stdoutText),
    chromeStderrText: sanitizeDiagnosticText(stderrText),
    fd142InHelper: hasFdTarget(helperFdsBefore, 142, /pipe:/i) || hasFdTarget(helperFdsAfter, 142, /pipe:/i),
    fd145InHelper: hasFdTarget(helperFdsBefore, 145, /pipe:/i) || hasFdTarget(helperFdsAfter, 145, /pipe:/i),
    fd142InChrome:
      hasFdTarget(chromeFdsBeforeClose, 142, /pipe:/i) || hasFdTarget(chromeFdsAfterClose, 142, /pipe:/i),
    fd145InChrome:
      hasFdTarget(chromeFdsBeforeClose, 145, /pipe:/i) || hasFdTarget(chromeFdsAfterClose, 145, /pipe:/i),
    fd142InNetworkService: hasFdTarget(networkServiceFds, 142, /pipe:/i),
    fd145InNetworkService: hasFdTarget(networkServiceFds, 145, /pipe:/i),
  };
  summary.httpStatus = navigationStatus;
  summary.errAborted =
    /ERR_ABORTED/i.test(requestFailedErrorText) ||
    /ERR_ABORTED/i.test(String(gotoError?.message || '')) ||
    /ERR_ABORTED/i.test(stderrText);
  summary.fdViolation = /FD ownership violation/i.test(stderrText);
  summary.networkServiceRestart = /Network service crashed or was terminated/i.test(stderrText);
  summary.exitCode =
    summary.errAborted || summary.fdViolation || Boolean(gotoError) || !navigationResponse || Boolean(exitInfo.timeout)
      ? 1
      : 0;
  summary.signal = exitInfo.signal || null;
  summary.chromeExitCode = typeof exitInfo.code === 'number' ? exitInfo.code : null;
  summary.chromeExitSignal = exitInfo.signal || null;
  summary.chromeCloseTimedOut = Boolean(exitInfo.timeout);
  summary.navigation.loadSeen = Boolean(loadEvent);
  summary.navigation.domContentLoadedSeen = Boolean(domContentLoadedEvent);
  summary.navigation.responseSeen = Boolean(responseEvent);
  summary.navigation.requestFailedSeen = Boolean(failedEvent);
  summary.navigation.frameNavigatedSeen = Boolean(frameNavigated);
  summary.navigation.stdoutText = sanitizeDiagnosticText(stdoutText);
  summary.navigation.stderrText = sanitizeDiagnosticText(stderrText);
  summary.navigation.networkServicePid = networkServicePid;
  summary.navigation.chromePid = chromePid;
  summary.navigation.helperPid = helperPid;
  summary.navigation.launcherKind = variant.launcherKind;
  summary.navigation.stdioMode = variant.stdioMode;
  summary.navigation.closeInheritedPipeFds = variant.closeInheritedPipeFds;
  summary.navigation.closeActions = scrubbedFds.closed;
  summary.navigation.helperFdsBefore = helperFdsBefore;
  summary.navigation.helperFdsAfter = helperFdsAfter;
  summary.navigation.chromeFdsBeforeClose = chromeFdsBeforeClose;
  summary.navigation.chromeFdsAfterClose = chromeFdsAfterClose;
  summary.navigation.networkServiceFds = networkServiceFds;
  summary.navigation.processTableBeforeClose = processTableBeforeClose;
  summary.navigation.processTableAfterClose = processTableAfterClose;
  summary.navigation.browserVersion = browserVersion;
  summary.navigation.browserWSEndpoint = browserWSEndpoint;
  summary.navigation.chromeStdoutText = sanitizeDiagnosticText(stdoutText);
  summary.navigation.chromeStderrText = sanitizeDiagnosticText(stderrText);
  summary.navigation.fd142InHelper = summary.fd142InHelper;
  summary.navigation.fd145InHelper = summary.fd145InHelper;
  summary.navigation.fd142InChrome = summary.fd142InChrome;
  summary.navigation.fd145InChrome = summary.fd145InChrome;
  summary.navigation.fd142InNetworkService = summary.fd142InNetworkService;
  summary.navigation.fd145InNetworkService = summary.fd145InNetworkService;

  return sanitizeDiagnosticValue(summary);
}

async function main(argv = process.argv.slice(2), env = process.env) {
  const configArg = argv.find((arg) => arg.startsWith('--config-json='));
  const configFileArg = argv.find((arg) => arg.startsWith('--config-file='));
  let configText = '';
  if (configArg) {
    configText = configArg.slice('--config-json='.length);
  } else if (configFileArg) {
    configText = fs.readFileSync(configFileArg.slice('--config-file='.length), 'utf8');
  } else if (env.LHCI_FD_MATRIX_CONFIG) {
    configText = env.LHCI_FD_MATRIX_CONFIG;
  }
  if (!configText) {
    throw new Error('Falta la configuración JSON para chrome-clean-launcher.cjs.');
  }
  const config = JSON.parse(configText);
  const summary = await runChromeFdInheritanceCase(config);
  process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
  return summary;
}

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`${sanitizeDiagnosticText(error?.stack || error?.message || String(error || 'Unknown error'))}\n`);
    process.exit(1);
  });
}

module.exports = {
  captureProcessTable,
  captureProcFdListing,
  closeInheritedPipeDescriptors,
  collectDescendantProcessRows,
  findNetworkServicePid,
  createCapturedLineWriter,
  main,
  normalizeChromiumStdio,
  readDevToolsActivePort,
  runChromeFdInheritanceCase,
  sanitizeDiagnosticText,
  sanitizeDiagnosticUrl,
  sanitizeDiagnosticValue,
  waitForDevToolsActivePort,
};
