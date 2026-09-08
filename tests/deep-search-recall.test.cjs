const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('cloudflare-worker/deep-search.js', 'utf8')
  .replace(/^import[\s\S]*?from "\.\/shared.js";\s*/, '')
  .replace(/export /g, '');
function harness(fetch) {
  const context = vm.createContext({ fetch, URLSearchParams, AbortSignal,
    cleanText: (v, n) => String(v || '').trim().slice(0, n) });
  vm.runInContext(source, context);
  return vm.runInContext('({sanitizePlan, retrieveNews, DEEP_SEARCH_LANGUAGE_CODES, buildEvidence})', context);
}
function plan(h) {
  return h.sanitizePlan({queries: Object.fromEntries(h.DEEP_SEARCH_LANGUAGE_CODES.map(language =>
    [language, {primary: `${language} Afghanistan opium cultivation`,
      secondary: `${language} Afghanistan heroin seizures`, broad: `${language} Afghanistan drugs`}]))}, 'Afghanistan drugs');
}
const rss = n => `<rss><channel>${Array.from({length:n}, (_, i) => `<item><title>Article ${i}</title><link>https://example.org/${i}</link></item>`).join('')}</channel></rss>`;
test('one English article triggers genuinely broader rescue in all 12 languages, within 36 requests', async () => {
  const calls = [];
  const h = harness(async url => { calls.push(new URL(url)); return new Response(rss(url.includes('en+') ? 1 : 0)); });
  const result = await h.retrieveNews(plan(h), 180);
  assert.equal(calls.length, 36);
  const rescues = result.waves.filter(w => w.query.variant === 'broad-rescue');
  assert.equal(rescues.length, 12);
  assert.ok(rescues.some(w => w.query.language === 'en'));
  assert.ok(rescues.every(w => w.query.query.endsWith('Afghanistan drugs')));
  assert.ok(calls.every(url => url.searchParams.get('q').endsWith('when:180d')));
});
test('three distinct URLs per language avoid unnecessary rescue', async () => {
  let calls = 0;
  const h = harness(async () => { calls++; return new Response(rss(3)); });
  await h.retrieveNews(plan(h), 30);
  assert.equal(calls, 24);
});
test('HTML errors with HTTP 200 are diagnosed as provider failures', async () => {
  const h = harness(async () => new Response('<html>Unavailable</html>'));
  const result = await h.retrieveNews(plan(h), 7);
  assert.equal(result.rows.length, 0);
  assert.ok(result.waves.every(w => !w.ok && w.error.includes('non-RSS')));
});
test('incomplete multilingual plans fail explicitly', () => {
  const h = harness();
  assert.throws(() => h.sanitizePlan({queries:{en:{primary:'Afghanistan opium', secondary:'Afghanistan heroin'}}}, ''), /broad queries/);
});
