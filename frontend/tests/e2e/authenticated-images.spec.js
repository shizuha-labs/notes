import { test, expect } from '@playwright/test'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'
import http from 'node:http'
import { fileURLToPath } from 'node:url'

const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP4z8AARAwQCgAf7gP9i18U1AAAAABJRU5ErkJggg==', 'base64')
const PATH = '/api/attachments/11111111-1111-4111-8111-111111111111/file/'
let server, external, origin, foreign, requests, externalRequests, held, mode, refreshes

test.beforeAll(async () => {
  external = http.createServer((req, res) => {
    externalRequests.push({ authorization: !!req.headers.authorization, organization: !!req.headers['x-organization-id'] })
    res.setHeader('Content-Type', 'image/png'); res.end(PNG)
  })
  await new Promise(resolve => external.listen(0, '127.0.0.1', resolve))
  foreign = `http://127.0.0.1:${external.address().port}/image.png`
  server = await createServer({
    configFile: false,
    root: fileURLToPath(new URL('../../', import.meta.url)),
    plugins: [react(), {
      name: 'owned-attachment-auth-fixture',
      configureServer(vite) {
        vite.middlewares.use(async (req, res, next) => {
          if (req.url === '/image-fixture.html') {
            res.setHeader('Content-Type', 'text/html')
            res.end(await vite.transformIndexHtml(req.url, '<div id="root"></div><script type="module" src="/@id/__x00__image-fixture"></script>'))
            return
          }
          if (req.url === '/api/auth/user/' || req.url === '/admin/api/organizations/') {
            res.setHeader('Content-Type', 'application/json')
            res.end(JSON.stringify(req.url.startsWith('/admin') ? [{ id: 'tenant-a' }] : { id: 1, username: 'disposable-user' })); return
          }
          if (req.url === '/api/auth/token/refresh/') {
            refreshes++; res.setHeader('Content-Type', 'application/json')
            res.end(JSON.stringify({ access: 'disposable-refreshed-token' })); return
          }
          if (req.url !== PATH) return next()
          const authorized = req.headers.authorization === (mode === 'refresh' ? 'Bearer disposable-refreshed-token' : 'Bearer disposable-token') && req.headers['x-organization-id'] === 'tenant-a'
          requests.push({ authorization: !!req.headers.authorization, organization: !!req.headers['x-organization-id'], authorized })
          const reply = () => {
            if (mode === 'redirect') { res.writeHead(302, { Location: foreign }); res.end(); return }
            res.statusCode = authorized && mode !== 'denied' ? 200 : 401
            res.setHeader('Content-Type', res.statusCode === 200 ? 'image/png' : 'application/json')
            res.end(res.statusCode === 200 ? PNG : '{}')
          }
          if (mode === 'held') held.push(reply); else reply()
        })
      },
      resolveId(id) { if (id === '\0image-fixture') return id },
      load(id) {
        if (id !== '\0image-fixture') return
        return `import '/src/index.css';import React from 'react';import{createRoot}from'react-dom/client';import Editor from'/src/components/RichTextEditor.jsx';import AuthContext,{AuthProvider,useAuth} from'/src/contexts/AuthContext.jsx';import api from'/src/services/api.js';
        const root=createRoot(document.getElementById('root'));
        localStorage.setItem('shizuha_access_token','disposable-token');localStorage.setItem('shizuha_organization_id','tenant-a');
        window.revoked=[];const revoke=URL.revokeObjectURL.bind(URL);URL.revokeObjectURL=u=>{window.revoked.push(u);revoke(u)};
        window.show=(src,tenant='tenant-a',userId=1)=>{localStorage.setItem('shizuha_organization_id',tenant);root.render(React.createElement(AuthContext.Provider,{value:{user:{id:userId},organization:{id:tenant}}},React.createElement(Editor,{content:{type:'doc',content:[{type:'paragraph',content:[{type:'image',attrs:{src}}]}]},onChange:data=>window.saved=data.json})));};
        window.mountRealAuth=()=>{localStorage.setItem('shizuha_user',JSON.stringify({id:1}));localStorage.setItem('shizuha_refresh_token','disposable-refresh-token');function Child(){const auth=useAuth();window.realAuthReady=auth.isAuthenticated&&!auth.isLoading;return window.realAuthReady?React.createElement(Editor,{content:{type:'doc',content:[{type:'paragraph',content:[{type:'image',attrs:{src:'${PATH}'}}]}]}}):null}root.render(React.createElement(AuthProvider,null,React.createElement(Child)))};
        window.unmount=()=>root.unmount();window.apiProof=()=>api.get('${PATH.replace('/api', '')}',{responseType:'blob'}).then(r=>r.data.size);`
      },
    }],
    server: { host: '127.0.0.1', port: 0 },
  })
  await server.listen()
  origin = server.resolvedUrls.local[0].replace(/\/$/, '')
})
test.afterAll(async () => { await server.close(); await new Promise(resolve => external.close(resolve)) })
test.beforeEach(async ({ page }) => {
  requests = []; externalRequests = []; held = []; mode = 'ready'; refreshes = 0
  page.on('pageerror', error => console.log('fixture page error:', error.message))
  page.on('console', message => { if (message.type() === 'error') console.log('fixture console error:', message.text()) })
  await page.goto(`${origin}/image-fixture.html`)
  await page.waitForFunction(() => !!window.show)
})

async function show(page, src = PATH, tenant = 'tenant-a') {
  await page.evaluate(({ src, tenant }) => window.show(src, tenant), { src, tenant })
}

test('real editor renders authenticated bytes and retains canonical document identity', async ({ page }, testInfo) => {
  expect(await page.evaluate(() => window.apiProof())).toBe(PNG.length)
  await show(page)
  const image = page.locator(`.ProseMirror img[data-canonical-src="${PATH}"]`)
  await expect.poll(() => image.evaluate(el => el.naturalWidth)).toBe(2)
  await expect(image).toHaveAttribute('src', /^blob:/)
  expect(requests.length).toBeGreaterThan(0)
  expect(requests.every(request => request.authorized)).toBe(true)
  await page.locator('.ProseMirror').press('End')
  await page.locator('.ProseMirror').press('a')
  await expect.poll(() => page.evaluate(() => JSON.stringify(window.saved))).toContain(PATH)
  expect(await page.evaluate(() => JSON.stringify(window.saved))).not.toContain('blob:')
  await page.screenshot({ path: testInfo.outputPath('authenticated-editor.png') })
})

test('foreign images load natively without Notes credentials', async ({ page }) => {
  await show(page, foreign)
  await expect.poll(() => page.locator('.ProseMirror img[src]').evaluate(el => el.naturalWidth)).toBe(2)
  expect(requests).toEqual([])
  expect(externalRequests).toEqual([{ authorization: false, organization: false }])
})

test('server redirects never forward credentials to another origin', async ({ page }) => {
  mode = 'redirect'
  await show(page)
  await expect.poll(() => requests.length).toBeGreaterThan(0)
  await page.waitForTimeout(100)
  expect(externalRequests).toEqual([])
  expect(await page.locator('[data-canonical-src]').getAttribute('src')).toBeNull()
})

test('revoked authority stays refused without unsigned fallback', async ({ page }) => {
  mode = 'denied'; await show(page)
  await expect.poll(() => requests.length).toBeGreaterThan(0)
  await page.waitForTimeout(100)
  expect(requests.every(request => request.authorization && request.organization)).toBe(true)
  expect(await page.locator('[data-canonical-src]').getAttribute('src')).toBeNull()
})

test('tenant switch rejects stale response and revokes displayed object URLs', async ({ page }) => {
  await show(page)
  await expect.poll(() => page.locator('[data-canonical-src]').evaluate(el => el.naturalWidth)).toBe(2)
  await show(page, PATH, 'tenant-b')
  await expect.poll(() => page.evaluate(() => window.revoked.length)).toBeGreaterThan(0)
  await expect.poll(() => requests.some(request => !request.authorized)).toBe(true)
  expect(await page.locator('[data-canonical-src]').getAttribute('src')).toBeNull()
})

test('unmount releases existing Blob URLs', async ({ page }) => {
  await show(page)
  await expect.poll(() => page.locator('[data-canonical-src]').evaluate(el => el.naturalWidth)).toBe(2)
  await page.evaluate(() => window.unmount())
  expect(await page.evaluate(() => window.revoked.length)).toBeGreaterThan(0)
})

test('late response from prior tenant cannot become visible', async ({ page }) => {
  mode = 'held'; await show(page)
  await expect.poll(() => held.length).toBeGreaterThan(0)
  await show(page, PATH, 'tenant-b')
  await expect.poll(() => held.length).toBeGreaterThan(1)
  mode = 'ready'; held.splice(0).forEach(reply => reply())
  await page.waitForTimeout(100)
  expect(await page.locator('[data-canonical-src]').getAttribute('src')).toBeNull()
})


test('unmount refuses a late pending response without creating an object URL', async ({ page }) => {
  mode = 'held'; await show(page)
  await expect.poll(() => held.length).toBeGreaterThan(0)
  await page.evaluate(() => {
    window.created = 0
    const create = URL.createObjectURL.bind(URL)
    URL.createObjectURL = blob => { window.created++; return create(blob) }
    window.unmount()
  })
  mode = 'ready'; held.splice(0).forEach(reply => reply())
  await page.waitForTimeout(100)
  expect(await page.evaluate(() => window.created)).toBe(0)
  await expect(page.locator('.ProseMirror')).toHaveCount(0)
})


test('actual AuthProvider refresh retries the attachment for the same principal and tenant', async ({ page }) => {
  mode = 'refresh'
  await page.evaluate(() => window.mountRealAuth())
  await expect.poll(() => page.evaluate(() => window.realAuthReady)).toBe(true)
  await expect.poll(() => refreshes).toBe(1)
  await expect.poll(() => page.locator('[data-canonical-src]').evaluate(el => el.naturalWidth)).toBe(2)
  expect(requests.some(request => !request.authorized)).toBe(true)
  expect(requests.some(request => request.authorized)).toBe(true)
  expect(requests.every(request => request.authorization && request.organization)).toBe(true)
})


test('a different principal cannot display the previous principal pending response', async ({ page }) => {
  mode = 'held'; await show(page)
  await expect.poll(() => held.length).toBeGreaterThan(0)
  await page.evaluate(path => window.show(path, 'tenant-a', 2), PATH)
  await expect.poll(() => held.length).toBeGreaterThan(1)
  held.shift()()
  await page.waitForTimeout(100)
  expect(await page.locator('[data-canonical-src]').getAttribute('src')).toBeNull()
  mode = 'ready'; held.splice(0).forEach(reply => reply())
  await expect.poll(() => page.locator('[data-canonical-src]').evaluate(el => el.naturalWidth)).toBe(2)
})

test('logout during a pending response cannot display attachment bytes', async ({ page }) => {
  mode = 'held'; await show(page)
  await expect.poll(() => held.length).toBeGreaterThan(0)
  await page.evaluate(() => localStorage.removeItem('shizuha_access_token'))
  mode = 'ready'; held.splice(0).forEach(reply => reply())
  await page.waitForTimeout(100)
  expect(await page.locator('[data-canonical-src]').getAttribute('src')).toBeNull()
})
