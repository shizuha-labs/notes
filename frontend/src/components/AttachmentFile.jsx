import { useCallback, useContext, useEffect, useRef, useState } from 'react'
import AuthContext from '../contexts/AuthContext'
import api from '../services/api'
import { attachmentPreviewAllowed, attachmentRequestPath, requestAttachmentBlob } from './authenticatedAttachmentImage'

function useAttachmentFile(src) {
  const auth = useContext(AuthContext)
  const principal = useRef(null)
  principal.current = auth?.user?.id ?? null
  const identity = useCallback(() => JSON.stringify([
    principal.current, localStorage.getItem('shizuha_organization_id'),
    Boolean(localStorage.getItem('shizuha_access_token')),
  ]), [])
  const key = identity()
  const scope = useRef(null)
  const path = attachmentRequestPath(src, api.defaults.baseURL, window.location.origin)
  useEffect(() => {
    const current = { key, alive: true, controllers: new Set(), urls: new Set(), pendingWindows: new Set() }
    scope.current = current
    return () => {
      current.alive = false
      for (const controller of current.controllers) controller.abort()
      for (const url of current.urls) URL.revokeObjectURL(url)
      for (const popup of current.pendingWindows) popup.close()
    }
  }, [src, key])

  const read = useCallback(async (kind, popup) => {
    const current = scope.current
    if (!current?.alive || identity() !== current.key) throw new Error('Attachment identity changed')
    const requestedIdentity = identity()
    const controller = new AbortController()
    current.controllers.add(controller)
    if (popup) current.pendingWindows.add(popup)
    try {
      const { data } = await requestAttachmentBlob(api, src, controller.signal)
      if (!current.alive || scope.current !== current || identity() !== requestedIdentity) throw new Error('Attachment identity changed')
      if (kind === 'image' && !data.type.startsWith('image/')) throw new Error('Attachment is not an image')
      const preview = attachmentPreviewAllowed(data.type)
      const blob = kind === 'download' || (kind === 'open' && !preview)
        ? new Blob([data], { type: 'application/octet-stream' }) : data
      const url = URL.createObjectURL(blob)
      current.urls.add(url)
      return { url, identity: requestedIdentity, preview, scope: current }
    } finally {
      current.controllers.delete(controller)
    }
  }, [src, identity])
  return { path, key, read, scope, identity }
}

export function AttachmentThumbnail({ src, alt, className }) {
  const { path, key, read } = useAttachmentFile(src)
  const [loaded, setLoaded] = useState(null)
  useEffect(() => {
    if (!path) return
    let mounted = true
    read('image').then(value => { if (mounted) setLoaded(value) }).catch(() => {})
    return () => { mounted = false }
  }, [path, key, read])
  return <img src={path ? (loaded?.identity === key ? loaded.url : undefined) : src}
    data-canonical-src={path ? src : undefined} alt={alt} className={className} />
}

export function AttachmentLink({ src, filename, action, children, ...props }) {
  const file = useAttachmentFile(src)
  const [failedIdentity, setFailedIdentity] = useState(null)
  if (!file.path) return <a href={src} target={action === 'open' ? '_blank' : undefined}
    rel="noopener noreferrer" download={action === 'download' ? filename : undefined} {...props}>{children}</a>

  async function activate() {
    setFailedIdentity(null)
    // Allocate a tab during the real click, then sever its opener before awaiting bytes.
    const popup = action === 'open' ? window.open('about:blank', '_blank') : null
    if (popup) popup.opener = null
    try {
      const requestedIdentity = file.key
      const value = await file.read(action, popup)
      if (file.scope.current !== value.scope || !value.scope.alive || file.identity() !== requestedIdentity) throw new Error('Attachment identity changed')
      if (action === 'open' && value.preview) {
        if (!popup) throw new Error('Attachment window was blocked')
        popup.location.replace(value.url)
        file.scope.current.pendingWindows.delete(popup)
      } else {
        if (popup) { popup.close(); file.scope.current.pendingWindows.delete(popup) }
        const link = document.createElement('a')
        link.href = value.url; link.download = filename; link.rel = 'noopener noreferrer'
        document.body.append(link); link.click(); link.remove()
      }
    } catch {
      if (popup) popup.close()
      if (file.scope.current?.alive && file.identity() === file.key) setFailedIdentity(file.key)
    }
  }
  return <button type="button" onClick={activate} aria-label={failedIdentity === file.key ? `${props.title}: unavailable` : props.title}
    {...props}>{children}</button>
}
