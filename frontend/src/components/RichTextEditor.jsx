import { useMemo } from 'react'
import {
  BaseEditor,
  createNotesExtensions,
} from '@shizuha/editor'
import { attachmentsApi } from '../services/api'

/**
 * Rich text editor for Notes using the shared editor package
 */
export default function RichTextEditor({
  content,
  onChange,
  onBlur,
  placeholder = 'Start writing...',
  editable = true,
  className,
  noteId,
  onEnsureSaved,
  onAttachmentUploaded,
}) {
  // Create extensions with the Notes preset
  const extensions = useMemo(
    () => createNotesExtensions({ placeholder }),
    [placeholder]
  )

  // Handler for uploading images
  const handleImageUpload = async (file) => {
    let currentNoteId = noteId
    if (!currentNoteId && onEnsureSaved) {
      currentNoteId = await onEnsureSaved()
    }
    if (!currentNoteId) throw new Error('Note must be saved first')
    const response = await attachmentsApi.upload(currentNoteId, file)
    // Return the file URL for the editor to insert
    return response.data.file_url || response.data.file
  }

  // Handler for uploading attachments
  const handleAttachmentUpload = async (file) => {
    let currentNoteId = noteId
    if (!currentNoteId && onEnsureSaved) {
      currentNoteId = await onEnsureSaved()
    }
    if (!currentNoteId) throw new Error('Note must be saved first')
    await attachmentsApi.upload(currentNoteId, file)
    // Attachments are added to the list, not inserted into editor
  }

  return (
    <BaseEditor
      content={content}
      onChange={onChange}
      onBlur={onBlur}
      editable={editable}
      className={className}
      extensions={extensions}
      toolbarPreset="notes"
      showToolbar={editable}
      entityId={noteId}
      entityLabel="note"
      onImageUpload={handleImageUpload}
      onAttachmentUpload={handleAttachmentUpload}
      onAttachmentUploaded={onAttachmentUploaded}
      onEnsureSaved={onEnsureSaved}
      minHeight="280px"
      contentClassName="[&_.ProseMirror]:min-h-[280px]"
    />
  )
}
