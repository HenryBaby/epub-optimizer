/* Run through tests/ui/run.sh. No HTTP server or live service is used. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '../..');
const artifacts = process.env.UI_ARTIFACT_DIR || '/artifacts';
fs.mkdirSync(artifacts, { recursive: true });
const origin = 'http://optimizer.test';
const template = fs.readFileSync(path.join(root, 'src/epub_optimizer/templates/index.html'), 'utf8')
  .replace(/\{\{\s*app_version\s*\}\}/g, 'ui-fixture')
  .replace(/\{\{\s*max_upload_mb\s*\}\}/g, '100');
assert(!template.includes('{{'), 'Render all template placeholders before serving');
const clone = value => JSON.parse(JSON.stringify(value));
const libraries = [
  { id: 1, name: 'Fiction', paths: ['/books/fiction'], watch: true },
  { id: 2, name: 'Reference', paths: ['/books/reference'], watch: false },
];
const scope = {
  plan_id: 'preview-1', epub_count: 2, files: 4, bytes: 4096,
  mappings: [{ library_id: 1, remote_path: '/books/fiction', local_path: '/libraries/fiction-draft' },
    { library_id: 2, remote_path: '/books/reference', local_path: '/libraries/reference' }],
};
const completed = {
  id: 'run-1', status: 'completed', created_at: 1730000000,
  message: 'Finished. Library watching remains paused.',
  results: [{ path: '/libraries/fiction-draft/Novel.epub', status: 'optimized' },
    { path: '/libraries/reference/Broken.epub', status: 'failed', message: 'Invalid archive; inspect source EPUB.' }],
};
const snapshot = { snapshot_id: 'backup-1', status: 'verified', created_at: 1730000000, plan: scope };
const automation = {
  config: { enabled: false, append_suffix: true, poll_seconds: 10, stable_seconds: 15,
    archive_retention_days: 30, failed_retention_days: 30 },
  paths: { watch_dir: '/watch', output_dir: '/output', failed_dir: '/failed', unprocessed_dir: '/unprocessed' },
  pipeline: { watch: { count: 0, bytes: 0 }, output: { count: 0, bytes: 0 },
    failed: { count: 0, bytes: 0 }, archive: { count: 0, bytes: 0 },
    last_scan_at: null, next_scan_at: null, seconds_until_next_scan: null },
  current_job: null, history: [], last_scan_at: null, running: false,
};

function fixture() {
  return {
    state: { connected: false, base_url: null, libraries: [], mappings: [], active_job: null,
      job: null, history: [], snapshots: [], watcher_maintenance: null },
    posts: [], reads: 0, unexpected: [], partial: false, failStatus: false,
    receipt(partial = false) {
      return { session_id: 'watch-session-1', base_url: 'http://grimmory.test:6060',
        status: partial ? 'partial' : 'paused', libraries: [
          { library_id: 1, name: 'Fiction', original_watch: true, status: 'paused' },
          { library_id: 2, name: 'Reference', original_watch: false,
            status: partial ? 'failed' : 'already_disabled',
            error: partial ? 'Permission denied. Grant manage-library permission, then retry.' : null },
        ] };
    },
    action(action, payload) {
      this.posts.push({ action, payload });
      switch (action) {
        case 'connect':
          this.state.connected = true;
          this.state.base_url = payload.base_url;
          this.state.libraries = clone(libraries);
          break;
        case 'pause-watching':
          assert.deepEqual(payload.library_ids, [1, 2]);
          this.state.watcher_maintenance = this.receipt(this.partial);
          this.state.libraries.forEach(library => {
            const item = this.state.watcher_maintenance.libraries.find(item => item.library_id === library.id);
            if (item.status === 'paused' || item.status === 'already_disabled') library.watch = false;
          });
          break;
        case 'preview':
          assert.deepEqual(payload.mappings, scope.mappings);
          return scope;
        case 'start':
          assert.deepEqual(payload, { plan_id: 'preview-1', maintenance_confirmed: true });
          this.state.job = { ...clone(completed), status: 'running', results: [completed.results[1]] };
          this.state.active_job = 'run-1';
          break;
        case 'cancel':
          this.state.job = { ...clone(completed), status: 'cancelled' };
          this.state.active_job = null;
          break;
        case 'resume-watching':
          assert.deepEqual(payload, { session_id: 'watch-session-1' });
          assert(this.state.connected);
          assert.equal(this.state.base_url, this.state.watcher_maintenance.base_url);
          this.state.watcher_maintenance.status = 'resumed';
          this.state.watcher_maintenance.libraries.forEach(library => {
            library.status = 'restored';
            const current = this.state.libraries.find(item => item.id === library.library_id);
            if (current) current.watch = library.original_watch;
          });
          break;
        case 'restore':
          assert.deepEqual(payload, { snapshot_id: 'backup-1', maintenance_confirmed: true });
          this.state.job = { id: 'restore-1', status: 'restoring', results: [] };
          this.state.active_job = 'restore-1';
          break;
        default: throw new Error(`Unexpected action: ${action}`);
      }
      return this.state;
    },
  };
}

async function setup(browser, mock, options = {}) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 },
    colorScheme: 'light', serviceWorkers: 'block', ...options });
  const errors = [];
  context.on('page', page => {
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => {
      if (message.type() !== 'error') return;
      // Chromium logs the intentionally injected HTTP failure as a resource error.
      if (mock.failStatus && message.location().url === `${origin}/grimmory` &&
          /Failed to load resource.*503/.test(message.text())) return;
      errors.push(message.text());
    });
  });
  await context.route('**/*', async route => {
    const req = route.request();
    const url = new URL(req.url());
    const json = value => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(value) });
    if (url.origin !== origin) {
      mock.unexpected.push(`${req.method()} ${url.href}`);
      return route.abort('blockedbyclient');
    }
    if (req.method() === 'GET' && url.pathname === '/') {
      return route.fulfill({ status: 200, contentType: 'text/html', body: template });
    }
    if (req.method() === 'GET' && /^\/static\/(app\.js|styles\.css|favicon\.png)$/.test(url.pathname)) {
      const type = url.pathname.endsWith('.js') ? 'text/javascript' : url.pathname.endsWith('.css') ? 'text/css' : 'image/png';
      return route.fulfill({ status: 200, contentType: type,
        body: fs.readFileSync(path.join(root, 'src/epub_optimizer', url.pathname)) });
    }
    if (req.method() === 'GET' && url.pathname === '/automation') return json(automation);
    if (req.method() === 'GET' && url.pathname === '/grimmory') {
      mock.reads++;
      if (mock.failStatus) return route.fulfill({ status: 503, contentType: 'application/json',
        body: JSON.stringify({ detail: 'Status unavailable. Check connection and refresh to retry.' }) });
      return json(mock.state);
    }
    if (req.method() === 'POST' && url.pathname.startsWith('/grimmory/')) {
      try { return await json(mock.action(url.pathname.split('/').at(-1), req.postDataJSON())); }
      catch (error) {
        errors.push(error.stack);
        return route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: error.message }) });
      }
    }
    mock.unexpected.push(`${req.method()} ${url.href}`);
    return route.abort('blockedbyclient');
  });
  const page = await context.newPage();
  page.setDefaultTimeout(7000);
  await page.goto(origin);
  await page.locator('[data-tab="grimmory"]').click();
  await page.locator('#grimmory-pill').filter({ hasText: /Disconnected|Connected|Maintenance/ }).waitFor();
  return { context, page, errors, mock };
}

async function text(page, selector, pattern) {
  await page.waitForFunction(({ selector, source }) => new RegExp(source).test(document.querySelector(selector)?.textContent || ''),
    { selector, source: pattern.source });
}
async function noOverflow(page) {
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'No horizontal page overflow');
}
async function connect(page) {
  const details = page.locator('#grimmory-connection');
  if (!(await details.evaluate(node => node.open))) await details.locator('summary').click();
  await page.getByLabel('Grimmory URL', { exact: true }).fill('http://grimmory.test:6060');
  await page.getByLabel('Username', { exact: true }).fill('fixture-admin');
  await page.getByLabel('Password', { exact: true }).fill('fixture-only-password');
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  await page.locator('#grimmory-mappings input[type="checkbox"]').first().waitFor();
  assert.equal(await page.locator('#grimmory-password').inputValue(), '', 'Password is cleared');
}
async function selectFolders(page) {
  const rows = page.locator('#grimmory-mappings .grimmory-mapping');
  await rows.nth(0).getByRole('checkbox').check();
  await rows.nth(1).getByRole('checkbox').check();
  await rows.nth(0).getByRole('textbox').fill('/libraries/fiction-draft');
  await rows.nth(1).getByRole('textbox').fill('/libraries/reference');
}
async function finish(session) {
  assert.deepEqual(session.errors, [], 'No browser console or unhandled JavaScript errors');
  assert.deepEqual(session.mock.unexpected, [], 'All requests stay inside the fixture allowlist');
  await session.context.close();
}

const passed = [];
async function check(name, task) {
  await task();
  passed.push(name);
  process.stdout.write(`${JSON.stringify({ passed: name })}\n`);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    await check('manual maintenance workflow, preserved drafts, polling, history, scoped restore and explicit resume', async () => {
      const mock = fixture();
      const s = await setup(browser, mock);
      const { page } = s;
      await noOverflow(page);
      assert.equal(await page.locator('#source-picker').isVisible(), false);
      for (const tab of ['automation', 'optimizer', 'analyze', 'grimmory']) {
        await page.locator(`[data-tab="${tab}"]`).click();
        assert.equal(await page.locator('#source-picker').isVisible(), ['optimizer', 'analyze'].includes(tab),
          `The shared upload picker visibility follows the ${tab} workspace`);
      }
      await page.reload();
      await page.locator('#grimmory-url').waitFor();
      assert.equal(mock.posts.length, 0, 'Loading, reloading and navigating never POST');
      await page.screenshot({ path: path.join(artifacts, 'desktop-disconnected.png'), fullPage: true });
      await connect(page);
      await selectFolders(page);
      assert.deepEqual(mock.posts.map(item => item.action), ['connect'], 'Selection and mounted path edits are local drafts');
      const fills = await page.evaluate(() => Object.fromEntries(['preview', 'pause-watching', 'refresh'].map(name =>
        [name, getComputedStyle(document.querySelector(`#grimmory-${name}`)).backgroundColor])));
      assert.notEqual(fills.preview, fills['pause-watching'], 'Primary preview and secondary pause have distinct fills');
      assert.notEqual(fills.preview, fills.refresh, 'Refresh is a quiet action rather than another primary button');
      await page.screenshot({ path: path.join(artifacts, 'desktop-connected-light.png'), fullPage: true });
      await page.locator('#grimmory-pause-watching').click();
      await text(page, '#grimmory-watcher-maintenance', /already disabled/i);
      assert.equal(await page.locator('#grimmory-mappings input[type="text"]').first().inputValue(), '/libraries/fiction-draft');
      await page.screenshot({ path: path.join(artifacts, 'desktop-paused-light.png'), fullPage: true });
      await page.locator('#grimmory-preview').click();
      await page.locator('#grimmory-plan').waitFor();
      assert(await page.locator('#grimmory-start').isDisabled(), 'A preview never authorizes a write');
      await page.locator('#grimmory-maintenance').check();
      await page.locator('#grimmory-start').click();
      await text(page, '#grimmory-progress', /Optimizing/);
      assert(await page.locator('#grimmory-url').isDisabled(), 'Connection configuration is locked during a job');
      assert(await page.locator('#grimmory-mappings input').first().isDisabled(), 'Selected folder configuration is locked');
      assert(await page.locator('#grimmory-cancel').isEnabled(), 'Safe cancellation stays available');
      const results = page.locator('#grimmory-progress details');
      await results.locator('summary').click();
      const history = page.locator('#grimmory-past-activity');
      await history.locator('summary').click();
      await history.locator('summary').focus();
      const reads = mock.reads;
      mock.state.job.message = 'Polling update: review the source EPUB before retrying.';
      // Await a changed server fixture via the actual 1500ms timer, without a fixed sleep.
      await text(page, '#grimmory-progress', /Polling update/);
      assert(mock.reads > reads, 'Active work polls status');
      assert(await results.evaluate(node => node.open), 'Polling preserves expanded per-file errors');
      assert(await history.evaluate(node => node.open), 'Polling preserves expanded history');
      assert(await history.locator('summary').evaluate(node => node === document.activeElement), 'Polling preserves keyboard focus');
      assert.equal(await page.locator('#grimmory-mappings input[type="text"]').first().inputValue(), '/libraries/fiction-draft');
      assert(await page.locator('#grimmory-mappings input[type="checkbox"]').first().isChecked());
      await page.screenshot({ path: path.join(artifacts, 'desktop-active.png'), fullPage: true });
      mock.state.job = clone(completed);
      mock.state.active_job = null;
      mock.state.history = [clone(completed)];
      mock.state.snapshots = [clone(snapshot)];
      await page.locator('#grimmory-refresh').click();
      await text(page, '#grimmory-progress', /Completed/);
      assert.equal(mock.state.watcher_maintenance.status, 'paused');
      assert(!mock.posts.some(item => item.action === 'resume-watching'), 'Completion never automatically resumes watching');
      await page.screenshot({ path: path.join(artifacts, 'desktop-result.png'), fullPage: true });
      await page.locator('#grimmory-snapshots details').first().locator('summary').click();
      const restore = page.getByRole('button', { name: 'Restore this library-folder snapshot', exact: true });
      assert(await restore.isDisabled(), 'Restore requires a fresh maintenance acknowledgement');
      await page.locator('#grimmory-maintenance').check();
      let confirmation = '';
      page.once('dialog', async dialog => { confirmation = dialog.message(); await dialog.dismiss(); });
      await restore.click();
      assert.match(confirmation, /backup-1/);
      assert.match(confirmation, /replaced|replace/i);
      assert(!mock.posts.some(item => item.action === 'restore'), 'Dismissing confirmation never restores');
      page.once('dialog', dialog => dialog.accept());
      await restore.click();
      await text(page, '#grimmory-progress', /Restoring/);
      await page.locator('#grimmory-cancel').click();
      await text(page, '#grimmory-progress', /Cancelled/);
      await page.locator('#grimmory-resume-watching').click();
      await text(page, '#grimmory-watcher-maintenance', /restored/i);
      assert.equal(mock.state.watcher_maintenance.libraries[1].original_watch, false, 'Receipt retains originally disabled watching');
      assert.deepEqual(mock.posts.map(item => item.action), ['connect', 'pause-watching', 'preview', 'start', 'restore', 'cancel', 'resume-watching']);
      await noOverflow(page);
      await finish(s);
    });
    await check('preview-first keeps manual pause accessible and requires explicit re-preview', async () => {
      const mock = fixture();
      const s = await setup(browser, mock);
      await connect(s.page);
      await selectFolders(s.page);
      await s.page.locator('#grimmory-preview').click();
      await s.page.locator('#grimmory-plan').waitFor();
      assert.deepEqual(mock.posts.map(item => item.action), ['connect', 'preview'], 'Preview never pauses watching');
      const pause = s.page.locator('#grimmory-pause-watching');
      assert(await pause.isVisible(), 'Pause is available in the current review stage');
      assert(await pause.isEnabled());
      await pause.click();
      await text(s.page, '#grimmory-watcher-maintenance', /already disabled/i);
      await s.page.locator('#grimmory-preview').waitFor();
      assert.equal(await s.page.locator('#grimmory-plan').isVisible(), false, 'Pausing invalidates the previous preview');
      assert.deepEqual(mock.posts.map(item => item.action), ['connect', 'preview', 'pause-watching'], 'Pausing never implicitly previews');
      await s.page.locator('#grimmory-preview').click();
      await s.page.locator('#grimmory-plan').waitFor();
      assert.deepEqual(mock.posts.map(item => item.action), ['connect', 'preview', 'pause-watching', 'preview']);
      assert(await s.page.locator('#grimmory-start').isDisabled(), 'Fresh preview still requires maintenance acknowledgement');
      await finish(s);
    });
    await check('refresh failure remains a visible alert with connection settings collapsed', async () => {
      const mock = fixture();
      const s = await setup(browser, mock);
      await connect(s.page);
      const connection = s.page.locator('#grimmory-connection');
      assert.equal(await connection.evaluate(node => node.open), false);
      mock.failStatus = true;
      await s.page.getByRole('button', { name: 'Refresh status', exact: true }).click();
      const alert = s.page.getByRole('alert').filter({ hasText: 'Status unavailable. Check connection and refresh to retry.' });
      await alert.waitFor({ state: 'visible' });
      assert.equal(await connection.evaluate(node => node.open), false, 'Error is visible without reopening settings');
      assert.deepEqual(mock.posts.map(item => item.action), ['connect'], 'Refresh failures never trigger action POSTs');
      await finish(s);
    });
    await check('partial watching receipt survives disconnected reload and needs explicit same-instance reconnect and resume', async () => {
      const mock = fixture(); mock.partial = true;
      const s = await setup(browser, mock);
      await connect(s.page);
      await selectFolders(s.page);
      await s.page.locator('#grimmory-pause-watching').click();
      await text(s.page, '#grimmory-watcher-maintenance', /Permission denied/);
      mock.state.connected = false;
      mock.state.base_url = null;
      mock.state.libraries = [];
      const count = mock.posts.length;
      await s.page.reload();
      await text(s.page, '#grimmory-watcher-maintenance', /Reconnect to http:\/\/grimmory\.test:6060/);
      assert(await s.page.locator('#grimmory-resume-watching').isDisabled());
      assert.equal(mock.posts.length, count);
      await connect(s.page);
      assert.equal(mock.posts.length, count + 1, 'Reconnect alone never resumes');
      await s.page.locator('#grimmory-resume-watching').click();
      await text(s.page, '#grimmory-watcher-maintenance', /restored/i);
      await finish(s);
    });
    await check('dark mobile connected workspace has labelled keyboard controls and no horizontal overflow', async () => {
      const s = await setup(browser, fixture(), { viewport: { width: 390, height: 844 }, colorScheme: 'dark' });
      await connect(s.page);
      await selectFolders(s.page);
      await noOverflow(s.page);
      assert.equal(await s.page.locator('html').getAttribute('data-theme'), 'dark');
      const mounted = s.page.getByLabel('Mounted path', { exact: true }).first();
      await mounted.focus();
      await s.page.keyboard.press('Tab');
      assert(await s.page.evaluate(() => document.activeElement !== document.body), 'Tab moves focus to an interactive control');
      await s.page.screenshot({ path: path.join(artifacts, 'mobile-connected-dark.png'), fullPage: true });
      await finish(s);
    });
    fs.writeFileSync(path.join(artifacts, 'checks.json'), JSON.stringify({ status: 'passed', passed }, null, 2));
  } catch (error) {
    fs.writeFileSync(path.join(artifacts, 'checks.json'), JSON.stringify({ status: 'failed', passed, error: error.stack }, null, 2));
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
