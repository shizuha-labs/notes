// The standalone login route belongs to the configured application mount.
export function loginRedirect(loginUrl, basePath, currentPath) {
  if (loginUrl) {
    return `${loginUrl}?continue=${encodeURIComponent(currentPath || '/notes/')}`
  }
  return `${(basePath || '/').replace(/\/?$/, '/')}login`
}
