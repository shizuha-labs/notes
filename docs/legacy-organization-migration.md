# Restoring legacy workspace data

Fresh databases need no tenant mapping. Migration 0002 uses a workspace's existing
positive `organization_id` as authoritative. For historical workspaces without one,
set `NOTES_LEGACY_OWNER_ORGANIZATIONS` to a reviewed JSON object mapping positive
owner IDs (string keys) to positive organization IDs (integer values), for example
`{"17":51,"18":52}`. Resolve these identities against the installation's identity
and organization records before restoration; never infer a tenant from a default.

The complete workspace and content mapping is validated before any update.
Missing owners, conflicting organizations and orphaned content stop migration.
Keep restoration configuration outside the public source tree. Already-applied
migrations and production records are not rerun or rewritten by this source change.
