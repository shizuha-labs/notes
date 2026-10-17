// Preserve server totals: a page's length is not the number of accessible rows.
export function collectionPage(data) {
  if (Array.isArray(data)) return { results: data, count: data.length }
  return { results: data?.results || [], count: data?.count ?? null }
}

export async function dashboardNotes(notesApi, searchApi, kind) {
  // CRUD lists support notebook/status only. Boolean filters belong to the
  // authorized Search endpoint, which returns its own filtered total.
  const response = kind === 'recent'
    ? await notesApi.list({ page_size: 10 })
    : await searchApi.search('', { [kind]: true, page_size: 10 })
  return collectionPage(response.data)
}
