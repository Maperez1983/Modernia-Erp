'use strict';

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

module.exports = {
  ensureSwClearedUrl,
};
