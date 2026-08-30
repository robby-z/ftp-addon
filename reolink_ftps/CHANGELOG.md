# Changelog

## 1.0.0

- Show live capacity, used space, free space, and disk utilization for the validated recording filesystem.
- Persist watched state in the SQLite metadata index, reset it when a recording is replaced, and add watched/unwatched filtering.
- Add quick age filters and safe bulk deletion for selected rows or all current filter results, with exclusions, count/size confirmation, and partial-failure reporting.
- Add deletion directly from the video viewer while retaining the existing confirmation and storage-safety checks.
- Redesign the recording table, filters, selection controls, and dialogs for phone-sized Home Assistant clients.

## 0.10.1

- Add a recursive recording table with newest-first ordering, camera and date filters, search, sortable columns, and pagination.
- Add explicit view, download, and confirmed delete actions for each indexed recording.
- Maintain a rebuildable SQLite metadata index under App `/data`; recordings remain on the configured media disk.
- Protect deletion with Ingress-only access, a per-start CSRF token, symlink/path confinement, and a write-settling delay.

## 0.10.0

- Add a Home Assistant Ingress recording browser with per-user tabs and safe directory navigation.
- Stream recordings with HTTP byte-range support for seeking and offer original-file downloads.
- Keep the browser read-only, Ingress-authenticated, and confined to each configured user directory.

## 0.9.1

- Treat an omitted per-user `read_only` checkbox as `false`, matching Home Assistant's form behavior.

## 0.9.0

- Initial production release.
- Explicit FTPS with persistent self-signed or Home Assistant `/ssl` certificates.
- Multiple isolated read/write and read-only users.
- Mandatory storage-anchor validation, optional marker file, and write health checks.
- Free-space service cutoff and symlink-safe file retention.
- Fixed passive range, configurable PASV address, AppArmor confinement, and protected-mode operation.
