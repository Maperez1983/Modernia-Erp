'use strict';

const path = require('node:path');

describe('Lighthouse URL helpers', () => {
  const root = process.cwd();
  const lighthouseUrlPath = path.join(root, 'scripts', 'lighthouse-url.cjs');
  const lighthouseRcPath = path.join(root, 'lighthouserc.cjs');

  function clearModule(modulePath) {
    try {
      delete require.cache[require.resolve(modulePath)];
    } catch {}
  }

  afterEach(() => {
    delete process.env.LHCI_BASE_URL;
    delete process.env.LHCI_PORT;
    delete process.env.PORT;
    delete process.env.LHCI_MANAGED_SERVER;
    delete process.env.CHROME_PATH;
    delete process.env.LHCI_CHROME_PATH;
    clearModule(lighthouseUrlPath);
    clearModule(lighthouseRcPath);
  });

  it('forces swcleared=1 while preserving query params and hash', () => {
    const {ensureSwClearedUrl} = require(lighthouseUrlPath);
    const url = ensureSwClearedUrl('https://example.test/path?foo=1&swcleared=0#frag', 41765);
    expect(url).toBe('https://example.test/path?foo=1&swcleared=1#frag');
  });

  it('normalizes the collect URL in lighthouserc', () => {
    process.env.LHCI_BASE_URL = 'http://127.0.0.1:8080/path?foo=bar&swcleared=0#frag';
    process.env.LHCI_MANAGED_SERVER = '1';
    const rc = require(lighthouseRcPath);
    expect(rc.ci.collect.url).toEqual([
      'http://127.0.0.1:8080/path?foo=bar&swcleared=1#frag',
    ]);
  });
});
