import test from 'node:test'
import assert from 'node:assert/strict'
import { attachmentRequestPath } from '../../src/components/authenticatedAttachmentImage.js'
const id = '11111111-1111-4111-8111-111111111111'
const origin = 'https://notes.example.invalid'
test('credentials are restricted to the configured same-origin exact attachment route', () => {
  assert.equal(attachmentRequestPath(`/api/attachments/${id}/file/`, '/api', origin), `/attachments/${id}/file/`)
  assert.equal(attachmentRequestPath(`${origin}/notes/api/attachments/${id}/file/`, '/notes/api', origin), `/attachments/${id}/file/`)
  for (const path of [
    `https://foreign.example.invalid/api/attachments/${id}/file/`,
    `https://user:password@notes.example.invalid/api/attachments/${id}/file/`,
    `/api/attachments/${id}/file/?signature=not-a-real-signature`,
    `/api/attachments/${id}/file/#fragment`,
    `/api/attachments/${id}/`, '/api/notes/', '/api/attachments/not-an-id/file/',
  ]) assert.equal(attachmentRequestPath(path, '/api', origin), null)
  for (const base of ['https://foreign.example.invalid/api', `${origin}/api?other=true`, `${origin}/api#other`, 'https://user:password@notes.example.invalid/api']) {
    assert.equal(attachmentRequestPath(`/api/attachments/${id}/file/`, base, origin), null)
  }
})
