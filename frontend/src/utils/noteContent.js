/**
 * NTS-47: TipTap / @shizuha/editor only renders non-empty JSONContent objects.
 * Many notes (API creates, imports) store plain content_text with content_json={}.
 * Build a minimal TipTap doc so the editor shows the body instead of a blank pane.
 */
export function resolveNoteEditorContent(note) {
  if (!note) {
    return { type: 'doc', content: [{ type: 'paragraph' }] }
  }
  const json = note.content_json
  if (json && typeof json === 'object' && Object.keys(json).length > 0) {
    return json
  }
  const text = note.content_text || ''
  if (!text) {
    return { type: 'doc', content: [{ type: 'paragraph' }] }
  }
  return {
    type: 'doc',
    content: [{
      type: 'paragraph',
      content: [{ type: 'text', text }],
    }],
  }
}
