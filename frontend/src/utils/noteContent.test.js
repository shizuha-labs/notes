import { describe, it, expect } from 'vitest'
import { resolveNoteEditorContent } from './noteContent'

describe('NTS-47 resolveNoteEditorContent', () => {
  it('returns existing content_json when present', () => {
    const json = { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Hi' }] }] }
    expect(resolveNoteEditorContent({ content_json: json, content_text: 'Hi' })).toEqual(json)
  })

  it('synthesizes a doc from content_text when content_json is empty', () => {
    const out = resolveNoteEditorContent({ content_json: {}, content_text: 'Hello world' })
    expect(out).toEqual({
      type: 'doc',
      content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Hello world' }] }],
    })
  })

  it('returns empty paragraph doc when both empty', () => {
    expect(resolveNoteEditorContent({ content_json: {}, content_text: '' })).toEqual({
      type: 'doc',
      content: [{ type: 'paragraph' }],
    })
  })
})
