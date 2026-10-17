import assert from 'node:assert/strict'
import http from 'node:http'
import test from 'node:test'
import axios from 'axios'
import { collectionPage, dashboardNotes } from '../../src/utils/dashboardData.js'

test('dashboard consumes actual filtered HTTP routes and paginated server totals', async () => {
  const requests = []
  const server = http.createServer((request, response) => {
    const url = new URL(request.url, 'http://localhost')
    requests.push(url)
    response.setHeader('Content-Type', 'application/json')
    if (url.pathname === '/notes/') {
      // Match the CRUD API: unrelated boolean parameters do not filter it.
      response.end(JSON.stringify({ count: 807, results: [{ id: 'ordinary', is_pinned: false }] }))
    } else if (url.pathname === '/search/' && url.searchParams.get('pinned') === 'true') {
      response.end(JSON.stringify({ count: 0, results: [] }))
    } else if (url.pathname === '/search/' && url.searchParams.get('favorite') === 'true') {
      response.end(JSON.stringify({ count: 23, results: [{ id: 'favorite', is_favorite: true }] }))
    } else {
      response.statusCode = 400
      response.end('{"error":"unsupported query"}')
    }
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  try {
    const client = axios.create({ baseURL: `http://127.0.0.1:${server.address().port}`, proxy: false })
    const notes = { list: params => client.get('/notes/', { params }) }
    const search = { search: (q, params) => client.get('/search/', { params: { q, ...params } }) }
    const recent = await dashboardNotes(notes, search, 'recent')
    assert.equal(recent.count, 807)
    assert.equal(recent.results.length, 1)
    const pinned = await dashboardNotes(notes, search, 'pinned')
    assert.deepEqual(pinned, { count: 0, results: [] })
    const favorite = await dashboardNotes(notes, search, 'favorite')
    assert.equal(favorite.count, 23)
    assert.equal(favorite.results[0].is_favorite, true)
    assert.deepEqual(requests.map(url => url.pathname), ['/notes/', '/search/', '/search/'])
  } finally {
    await new Promise(resolve => server.close(resolve))
  }
})

test('notebook totals remain distinct from the loaded page and missing totals remain unknown', () => {
  assert.equal(collectionPage({ count: 64, results: [{ id: 'one' }] }).count, 64)
  assert.equal(collectionPage({ results: [{ id: 'one' }] }).count, null)
  assert.deepEqual(collectionPage([]), { count: 0, results: [] })
})
