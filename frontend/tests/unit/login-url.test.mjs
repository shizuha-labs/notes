import assert from 'node:assert/strict'
import test from 'node:test'
import { loginRedirect } from '../../src/utils/loginUrl.js'

test('mounted standalone Notes keeps anonymous callers inside its own login route', () => {
  assert.equal(loginRedirect(undefined, '/notes/', '/notes/notes/123'), '/notes/login')
  assert.equal(loginRedirect(undefined, '/notes', '/notes/'), '/notes/login')
  assert.equal(loginRedirect(undefined, '/', '/'), '/login')
})

test('an explicit identity login retains the original application destination', () => {
  assert.equal(loginRedirect('/id/login', '/notes/', '/notes/notes/123'),
    '/id/login?continue=%2Fnotes%2Fnotes%2F123')
})
