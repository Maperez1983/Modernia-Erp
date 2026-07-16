#!/usr/bin/env node
'use strict';

const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const {spawnSync} = require('child_process');

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

function touchFile(filePath) {
  fs.mkdirSync(path.dirname(filePath), {recursive: true});
  fs.writeFileSync(filePath, '');
}

(async () => {
  const port = await getFreePort();
  if (!port) {
    throw new Error('No se pudo reservar un puerto libre para Lighthouse.');
  }

  const tempDir = process.env.LHCI_TMPDIR
    ? path.resolve(process.env.LHCI_TMPDIR)
    : fs.mkdtempSync(path.join(os.tmpdir(), 'lhci-'));
  const dbPath = path.join(tempDir, 'lighthouse.sqlite');
  const ocrDbPath = path.join(tempDir, 'ocr.sqlite');
  touchFile(dbPath);
  touchFile(ocrDbPath);

  const env = {
    ...process.env,
    LHCI_PORT: String(port),
    LHCI_BASE_URL: `http://127.0.0.1:${port}/?swcleared=1`,
    LHCI_DB_PATH: dbPath,
    LHCI_OCR_DB_PATH: ocrDbPath,
    LHCI_TMPDIR: tempDir,
    APP_HTTP_COMPRESSION: '1',
  };

  console.log(`Lighthouse temp dir: ${tempDir}`);
  console.log(`Lighthouse base URL: ${env.LHCI_BASE_URL}`);

  const result = spawnSync('npx', ['--no-install', 'lhci', 'autorun'], {
    cwd: process.cwd(),
    env,
    stdio: 'inherit',
  });

  if (result.error) {
    throw result.error;
  }
  process.exit(typeof result.status === 'number' ? result.status : 1);
})().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
