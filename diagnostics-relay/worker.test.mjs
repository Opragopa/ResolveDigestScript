import test from 'node:test';
import assert from 'node:assert/strict';
import worker from './worker.mjs';

const data = { id: 'a'.repeat(64), stage: 'Download', details: 'Timeout @someone ```' };
const request = body => new Request('https://relay.test/report', {
  method: 'POST', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' },
});
const environment = () => ({ GITHUB_TOKEN: 'test-secret',
  REPORTS: { get: async () => null, put: async () => {} },
  REPORT_LIMIT: { limit: async () => ({ success: true }) },
});

test('refuses an unconfigured service', async () => {
  assert.equal((await worker.fetch(request(data), {})).status, 503);
});

test('rejects invalid reports and oversized request bodies', async () => {
  assert.equal((await worker.fetch(request({ details: 'bad' }), environment())).status, 400);
  assert.equal((await worker.fetch(request({ ...data, details: 'x'.repeat(65000) }), environment())).status, 413);
});

test('rate limits requests before contacting GitHub', async () => {
  const env = environment();
  env.REPORT_LIMIT.limit = async () => ({ success: false });
  assert.equal((await worker.fetch(request(data), env)).status, 429);
});

test('returns an already created issue without calling GitHub', async () => {
  const env = environment();
  env.REPORTS.get = async () => 'https://github.com/Opragopa/ResolveDigestScript/issues/42';
  const response = await worker.fetch(request(data), env);
  assert.equal(response.status, 200);
  assert.equal((await response.json()).issue_url, 'https://github.com/Opragopa/ResolveDigestScript/issues/42');
});

test('creates an issue in the fixed repository and saves its id', async () => {
  const originalFetch = globalThis.fetch;
  const env = environment();
  let saved;
  env.REPORTS.put = async (...args) => { saved = args; };
  globalThis.fetch = async (url, options) => {
    assert.equal(url, 'https://api.github.com/repos/Opragopa/ResolveDigestScript/issues');
    assert.equal(options.headers.Authorization, 'Bearer test-secret');
    const body = JSON.parse(options.body);
    assert.ok(body.body.includes('＠someone'));
    assert.ok(body.body.includes('` ` `'));
    return Response.json({ html_url: 'https://github.com/Opragopa/ResolveDigestScript/issues/42' });
  };
  try {
    const response = await worker.fetch(request(data), env);
    assert.equal(response.status, 201);
    assert.equal(saved[0], data.id);
    assert.equal(saved[1], 'https://github.com/Opragopa/ResolveDigestScript/issues/42');
  } finally { globalThis.fetch = originalFetch; }
});
