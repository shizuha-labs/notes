// Persist the canonical attachment URL; only the local NodeView owns Blob URLs.
export function attachmentRequestPath(src, baseURL, origin) {
  try {
    const base = new URL(`${baseURL.replace(/\/$/, '')}/`, origin)
    const url = new URL(src, origin)
    if (base.origin !== origin || base.username || base.password || base.search || base.hash || url.origin !== origin || url.username || url.password || url.search || url.hash) return null
    const prefix = `${base.pathname}attachments/`
    if (!url.pathname.startsWith(prefix)) return null
    const suffix = url.pathname.slice(prefix.length)
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/file\/$/i.test(suffix)
      ? `/attachments/${suffix}` : null
  } catch { return null }
}

export function authenticatedAttachmentImage(extension, api, identity) {
  return extension.extend({
    addNodeView() {
      return ({ node }) => {
        const image = document.createElement('img')
        const src = node.attrs.src
        for (const name of ['alt', 'title', 'width', 'height']) {
          if (node.attrs[name] != null) image.setAttribute(name, node.attrs[name])
        }
        const path = attachmentRequestPath(src, api.defaults.baseURL, window.location.origin)
        const controller = new AbortController()
        let objectURL
        let destroyed = false
        if (!path) {
          image.src = src
        } else {
          image.dataset.canonicalSrc = src
          const requestedIdentity = identity()
          api.get(path, {
            responseType: 'blob', signal: controller.signal,
            adapter: 'fetch', fetchOptions: { redirect: 'error' },
          }).then(({ data }) => {
            if (destroyed || identity() !== requestedIdentity || !data.type.startsWith('image/')) return
            objectURL = URL.createObjectURL(data)
            image.src = objectURL
          }).catch(() => {
            // Refusal stays an unavailable image; never fall back to an unsigned request.
          })
        }
        return {
          dom: image,
          update: next => next.type === node.type &&
            ['src', 'alt', 'title', 'width', 'height'].every(name => next.attrs[name] === node.attrs[name]),
          destroy() {
            destroyed = true
            controller.abort()
            if (objectURL) URL.revokeObjectURL(objectURL)
          },
        }
      }
    },
  })
}
