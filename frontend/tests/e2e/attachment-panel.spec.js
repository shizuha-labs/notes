import { test, expect } from '@playwright/test'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'
import http from 'node:http'
import { fileURLToPath } from 'node:url'

const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP4z8AARAwQCgAf7gP9i18U1AAAAABJRU5ErkJggg==', 'base64')
const ID = '11111111-1111-4111-8111-111111111111'
const FILE = `/api/attachments/${ID}/file/`
let server, origin, requests, mode, held, external, foreign, externalRequests, refreshes

test.beforeAll(async () => {
  external = http.createServer((req, res) => {
    externalRequests.push({ authorization: !!req.headers.authorization, organization: !!req.headers['x-organization-id'] })
    res.setHeader('Content-Type', 'image/png'); res.end(PNG)
  })
  await new Promise(resolve => external.listen(0, '127.0.0.1', resolve))
  foreign = `http://127.0.0.1:${external.address().port}/public.png`
  server = await createServer({ configFile: false, root: fileURLToPath(new URL('../../', import.meta.url)), plugins: [react(), {
    name: 'actual-note-editor-attachment-panel',
    configureServer(vite) {
      vite.middlewares.use(async (req, res, next) => {
        if (req.url === '/panel.html') {
          res.setHeader('Content-Type', 'text/html'); res.end(await vite.transformIndexHtml(req.url, '<div id="root"></div><script type="module" src="/@id/__x00__panel-fixture"></script>')); return
        }
        if (req.url === '/api/auth/user/' || req.url === '/admin/api/organizations/') {
          res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(req.url.startsWith('/admin') ? [{ id: 'tenant-a' }] : { id: 1, username: 'disposable-user' })); return
        }
        if (req.url === '/api/auth/token/refresh/') { refreshes++; res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({access:'disposable-refreshed-token'})); return }
        if (req.url === FILE) {
          const authorized = req.headers.authorization === (mode === 'refresh' ? 'Bearer disposable-refreshed-token' : 'Bearer disposable-panel-token') && req.headers['x-organization-id'] === 'tenant-a'
          requests.push({ authorized, authorization: !!req.headers.authorization, organization: !!req.headers['x-organization-id'] })
          const reply = () => {
            if (mode === 'redirect') { res.writeHead(302, { Location: foreign }); res.end(); return }
            res.statusCode = authorized && mode !== 'denied' ? 200 : 401
            res.setHeader('Content-Type', res.statusCode === 200 ? (mode === 'html' ? 'text/html' : 'image/png') : 'application/json')
            res.end(res.statusCode === 200 ? (mode === 'html' ? '<script>localStorage.setItem("unsafe-preview","executed")</script>' : PNG) : '{}')
          }
          if (mode === 'held') held.push(reply); else reply()
          return
        }
        if (req.url?.startsWith('/api/')) {
          res.setHeader('Content-Type', 'application/json')
          if (req.url.startsWith('/api/notes/')) res.end(JSON.stringify({ id: ID, title: 'Owned panel fixture', notebook: ID, tags: [], version: 1, content_json: { type: 'doc', content: [{ type: 'paragraph' }] }, updated_at: '2026-01-01T00:00:00Z' }))
          else if (req.url.startsWith('/api/attachments/')) res.end(JSON.stringify([{ id: ID, original_filename: 'owned-2px.png', mime_type: 'image/png', file_type: 'image', file_size: PNG.length, file_url: mode === 'foreign' ? foreign : FILE }]))
          else res.end('[]')
          return
        }
        next()
      })
    },
    resolveId(id) { if (id === '\0panel-fixture') return id },
    load(id) {
      if (id !== '\0panel-fixture') return
      return `import '/src/index.css';import React from'react';import{createRoot}from'react-dom/client';import{MemoryRouter,Routes,Route}from'react-router-dom';import{QueryClient,QueryClientProvider}from'@tanstack/react-query';import NoteEditor from'/src/pages/NoteEditor.jsx';import AuthContext,{AuthProvider,useAuth} from'/src/contexts/AuthContext.jsx';import WorkspaceContext from'/src/contexts/WorkspaceContext.jsx';
      const root=createRoot(document.getElementById('root')),client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});localStorage.setItem('shizuha_access_token','disposable-panel-token');window.created=[];window.revoked=[];const create=URL.createObjectURL.bind(URL),revoke=URL.revokeObjectURL.bind(URL);URL.createObjectURL=b=>{const u=create(b);window.created.push(u);return u};URL.revokeObjectURL=u=>{window.revoked.push(u);revoke(u)};
      window.show=(tenant='tenant-a',user=1)=>{localStorage.setItem('shizuha_organization_id',tenant);root.render(React.createElement(AuthContext.Provider,{value:{user:{id:user},organization:{id:tenant}}},React.createElement(WorkspaceContext.Provider,{value:{notebooks:[{id:'${ID}',name:'Owned notebook'}],defaultNotebook:{id:'${ID}'},tags:[]}},React.createElement(QueryClientProvider,{client},React.createElement(MemoryRouter,{initialEntries:['/notes/${ID}']},React.createElement(Routes,null,React.createElement(Route,{path:'/notes/:id',element:React.createElement(NoteEditor)})))))))};window.mountRealAuth=()=>{localStorage.setItem('shizuha_user',JSON.stringify({id:1}));localStorage.setItem('shizuha_refresh_token','disposable-refresh-token');function Child(){const auth=useAuth();window.realAuthReady=auth.isAuthenticated&&!auth.isLoading;return window.realAuthReady?React.createElement(WorkspaceContext.Provider,{value:{notebooks:[{id:'${ID}',name:'Owned notebook'}],defaultNotebook:{id:'${ID}'},tags:[]}},React.createElement(QueryClientProvider,{client},React.createElement(MemoryRouter,{initialEntries:['/notes/${ID}']},React.createElement(Routes,null,React.createElement(Route,{path:'/notes/:id',element:React.createElement(NoteEditor)}))))):null}root.render(React.createElement(AuthProvider,null,React.createElement(Child)))};window.unmount=()=>root.unmount();window.show();`
    },
  }], server: { host: '127.0.0.1', port: 0 } })
  await server.listen(); origin = server.resolvedUrls.local[0].replace(/\/$/, '')
})
test.afterAll(async () => { await server.close(); await new Promise(resolve => external.close(resolve)) })
test.beforeEach(async ({ page }) => { requests = []; held = []; externalRequests = []; refreshes = 0; mode = 'ready'; await page.goto(`${origin}/panel.html`); await expect(page.getByText('Attachments (1)')).toBeVisible() })

test('actual NoteEditor thumbnail loads protected bytes with authenticated tenant authority', async ({ page }) => {
  const thumbnail = page.locator('img[alt="owned-2px.png"]')
  await expect.poll(() => thumbnail.evaluate(image => image.naturalWidth)).toBe(2)
  await page.screenshot({ path: '/tmp/notes-attachment-panel-fixed.png', fullPage: true })
  expect(requests.length).toBeGreaterThan(0); expect(requests.every(r => r.authorized)).toBe(true)
})

test('actual NoteEditor Open displays the protected image through a fresh authorized request', async ({ page }) => {
  const before = requests.length
  const opened = page.context().waitForEvent('page')
  await page.getByTitle('Open in new tab').click()
  const popup = await opened
  await expect.poll(async () => popup.locator('img').count()).toBe(1)
  await expect.poll(() => popup.locator('img').evaluate(image => image.naturalWidth)).toBe(2)
  expect(requests.slice(before).some(r => r.authorized)).toBe(true)
  await popup.close()
})

test('actual NoteEditor Download transfers the exact private file after fresh authorization', async ({ page }) => {
  const before = requests.length
  const transfer = page.waitForEvent('download')
  await page.getByTitle('Download', { exact: true }).click()
  const download = await transfer
  expect(await download.failure()).toBeNull()
  const stream = await download.createReadStream(); const chunks = []
  for await (const chunk of stream) chunks.push(chunk)
  expect(Buffer.concat(chunks)).toEqual(PNG)
  expect(download.suggestedFilename()).toBe('owned-2px.png')
  expect(requests.slice(before).some(r => r.authorized)).toBe(true)
})


test('revoked access is checked afresh for both actions without reusing the thumbnail authority', async ({ page }) => {
  await expect.poll(() => page.locator('img[alt="owned-2px.png"]').evaluate(i => i.naturalWidth)).toBe(2)
  mode = 'denied'
  const before = requests.length
  const opened = page.context().waitForEvent('page')
  await page.getByTitle('Open in new tab').click()
  const popup = await opened
  await expect.poll(() => popup.isClosed()).toBe(true)
  await page.getByTitle('Download', { exact: true }).click()
  await expect(page.getByRole('button', { name: 'Download: unavailable', exact: true })).toBeVisible()
  expect(requests.length - before).toBe(2)
  expect(requests.every(r => r.authorization && r.organization)).toBe(true)
})

test('redirected private reads refuse without sending Notes credentials to another origin', async ({ page }) => {
  mode = 'redirect'
  await page.reload()
  await expect(page.getByText('Attachments (1)')).toBeVisible()
  const opened = page.context().waitForEvent('page')
  await page.getByTitle('Open in new tab').click()
  const popup = await opened
  await expect.poll(() => popup.isClosed()).toBe(true)
  expect(externalRequests).toEqual([])
  expect(await page.locator('img[alt="owned-2px.png"]').getAttribute('src')).toBeNull()
})

test('tenant switch aborts a pending Open and revokes the old thumbnail Blob', async ({ page }) => {
  await expect.poll(() => page.locator('img[alt="owned-2px.png"]').evaluate(i => i.naturalWidth)).toBe(2)
  const created = await page.evaluate(() => [...window.created])
  mode = 'held'
  const opened = page.context().waitForEvent('page')
  await page.getByTitle('Open in new tab').click()
  const popup = await opened
  await expect.poll(() => held.length).toBe(1)
  await page.evaluate(() => window.show('tenant-b'))
  await expect.poll(() => popup.isClosed()).toBe(true)
  mode = 'ready'; for (const reply of held.splice(0)) reply()
  await expect.poll(() => page.evaluate(urls => urls.every(u => window.revoked.includes(u)), created)).toBe(true)
  expect(await page.locator('img[alt="owned-2px.png"]').getAttribute('src')).toBeNull()
})

test('unmount aborts a pending Download without creating another Blob', async ({ page }) => {
  await expect.poll(() => page.locator('img[alt="owned-2px.png"]').evaluate(i => i.naturalWidth)).toBe(2)
  const created = await page.evaluate(() => [...window.created])
  mode = 'held'
  await page.getByTitle('Download', { exact: true }).click()
  await expect.poll(() => held.length).toBe(1)
  await page.evaluate(() => window.unmount())
  mode = 'ready'; for (const reply of held.splice(0)) reply()
  expect(await page.evaluate(() => window.created)).toEqual(created)
  expect(await page.evaluate(urls => urls.every(u => window.revoked.includes(u)), created)).toBe(true)
})

test('active HTML is downloaded rather than executed in a same-origin Blob tab', async ({ page }) => {
  mode = 'html'
  const opened = page.context().waitForEvent('page'), transfer = page.waitForEvent('download')
  await page.getByTitle('Open in new tab').click()
  const popup = await opened, download = await transfer
  expect(await download.failure()).toBeNull()
  await expect.poll(() => popup.isClosed()).toBe(true)
  expect(await page.evaluate(() => localStorage.getItem('unsafe-preview'))).toBeNull()
})

test('external attachments preserve native links without forwarding Notes credentials', async ({ page }) => {
  mode = 'foreign'; await page.reload()
  await expect.poll(() => page.locator('img[alt="owned-2px.png"]').evaluate(i => i.naturalWidth)).toBe(2)
  await expect(page.getByTitle('Open in new tab')).toHaveAttribute('href', foreign)
  await expect(page.getByTitle('Download', { exact: true })).toHaveAttribute('href', foreign)
  const opened = page.context().waitForEvent('page')
  await page.getByTitle('Open in new tab').click()
  const popup = await opened
  await expect.poll(() => popup.locator('img').count()).toBe(1)
  expect(externalRequests.length).toBeGreaterThan(0)
  expect(externalRequests.every(r => !r.authorization && !r.organization)).toBe(true)
  await popup.close()
})

for (const change of ['principal', 'logout']) {
  test(`${change} change rejects an already pending attachment action`, async ({ page }) => {
    await expect.poll(() => page.locator('img[alt="owned-2px.png"]').evaluate(i => i.naturalWidth)).toBe(2)
    const created = await page.evaluate(() => [...window.created])
    mode = 'held'
    const opened = page.context().waitForEvent('page')
    await page.getByTitle('Open in new tab').click()
    const popup = await opened
    await expect.poll(() => held.length).toBe(1)
    await page.evaluate(change => {
      if (change === 'logout') localStorage.removeItem('shizuha_access_token')
      else localStorage.setItem('shizuha_access_token', 'different-principal-token')
      window.show('tenant-a', change === 'logout' ? null : 2)
    }, change)
    await expect.poll(() => popup.isClosed()).toBe(true)
    mode = 'ready'; for (const reply of held.splice(0)) reply()
    expect(await page.evaluate(urls => urls.every(u => window.revoked.includes(u)), created)).toBe(true)
    expect(await page.locator('img[alt="owned-2px.png"]').getAttribute('src')).toBeNull()
  })
}

test('actual AuthProvider refresh preserves the panel response for the same principal and tenant', async ({ page }) => {
  mode = 'refresh'
  await page.evaluate(() => window.mountRealAuth())
  await expect.poll(() => page.evaluate(() => window.realAuthReady)).toBe(true)
  await expect.poll(() => refreshes).toBe(1)
  await expect.poll(() => page.locator('img[alt="owned-2px.png"]').evaluate(i => i.naturalWidth)).toBe(2)
  const opened = page.context().waitForEvent('page')
  await page.getByTitle('Open in new tab').click()
  const popup = await opened
  await expect.poll(() => popup.locator('img').count()).toBe(1)
  await expect.poll(() => popup.locator('img').evaluate(i => i.naturalWidth)).toBe(2)
  expect(requests.every(r => r.authorization && r.organization)).toBe(true)
  await popup.close()
})
