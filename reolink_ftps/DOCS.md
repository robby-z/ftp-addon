# Reolink FTPS Server

This Home Assistant App provides a small, authenticated vsftpd service for Reolink camera uploads. It supports explicit FTPS (`AUTH TLS`), passive data connections, multiple chrooted users, storage-mount safeguards, free-space protection, and optional retention.

## Before the first start

1. Expose the dedicated recording storage to Home Assistant as `/media/<anchor>` or `/share/<anchor>`. This App does not mount, format, partition, or discover disks.
2. Confirm that the anchor already exists. For the default, `/media/ReolinkSSD` must exist before the App starts.
3. Configure at least one user with a strong password.
4. Set `pasv_address` to the stable Home Assistant LAN IPv4 address or a hostname that resolves to it from the camera VLAN.
5. Keep external passive ports mapped one-to-one as `30000` through `30019`.
6. Start the App and inspect its log before configuring cameras.

The App intentionally refuses to start with an empty user list, blank PASV address, missing anchor, unsafe path, missing required marker, or invalid TLS material.

## Configuration example

```yaml
storage:
  root: media
  directory: ReolinkSSD/reolink
  minimum_free_space_gb: 20
  stop_uploads_below_free_space: true
  require_marker_file: true
  initialize_marker_file: false
  marker_file: .reolink-storage
users:
  - username: camera_front
    password: change-this-in-the-ui
    directory: front
    read_only: false
  - username: camera_garden
    password: use-a-different-password
    directory: garden
    read_only: false
  - username: viewer
    password: another-strong-password
    directory: front
    read_only: true
tls:
  require_tls: true
  allow_plain_ftp: false
  certificate: ""
  private_key: ""
pasv_address: 192.168.1.10
max_clients: 20
max_per_ip: 5
idle_session_timeout: 600
data_connection_timeout: 300
delay_failed_login: 2
retention_days: 0
log_level: info
```

Passwords are masked by the Home Assistant `password` schema. They are necessarily available to the App at startup to provision container-local accounts, but are never logged. Use one account and a unique password per camera.

## Storage safety

`storage.directory` is always relative and must contain at least two components. Its first component is the **storage anchor** and must already exist; the remaining components are the App directory and may be created. Thus `ReolinkSSD/reolink` means:

- mapped root: `/media`
- pre-existing anchor: `/media/ReolinkSSD`
- creatable recording root: `/media/ReolinkSSD/reolink`

The App rejects absolute paths, `..`, backslashes, control characters, unsafe components, symlinks anywhere in managed directory chains, and canonical paths outside the chosen root. It performs a temporary write/fsync/delete test on both anchor and recording root. If `/media/ReolinkSSD` is absent, it will **not** create it:

> Configured recording storage /media/ReolinkSSD is unavailable. Refusing to start to prevent recordings from being written to the Home Assistant system disk.

For extra protection, enable `initialize_marker_file` for one successful start while the real storage is mounted. This creates `.reolink-storage` in the validated existing anchor. Then disable initialization and enable `require_marker_file`. A later mount failure or wrong volume will stop startup if the marker is absent.

Free space is measured with `statvfs`/filesystem usage on the canonical recording root—not on `/data` or an unrelated filesystem. Every 30 seconds, the supervisor compares it with `minimum_free_space_gb`. With `stop_uploads_below_free_space`, it stops vsftpd completely below the threshold and automatically restarts it after recovery. Stopping the service also temporarily prevents downloads, but reliably blocks uploads to nested existing directories; open transfers are terminated rather than allowed to fill the disk.

## Dedicated SSD architecture

```text
Reolink Cameras
      |
      | Explicit FTPS: TCP 21 + 30000-30019
      v
Reolink FTPS Server App
      |
      v
/media/ReolinkSSD/reolink
      |
      v
Dedicated 1 TB M.2 SSD

Home Assistant OS + Core + Supervisor + Apps + database
      |
      v
Existing 128 GB system SSD
```

Do **not** use **Move data disk** for this design: that moves Home Assistant's general data partition, not only camera recordings. Network storage can be added at **Settings → System → Storage → Add network storage**, with **Usage: Media**. Home Assistant OS does not offer the same simple UI for mounting every arbitrary second local disk as a media-only volume; a separate, trusted disk-mounting App or another supported storage architecture may be needed. Mounting remains outside this unprivileged App.

The App maps only `/media` and `/share` read/write, `/ssl` read-only, and its automatic persistent `/data`. It has no device access, host filesystem, Docker socket, Supervisor API role, `full_access`, host networking, or privileged mode. Protection Mode stays enabled.

The App uses Home Assistant's supported Debian Trixie base because Alpine's vsftpd login child is unreliable with FTPS on some current amd64 container kernels. vsftpd's own legacy seccomp sandbox and nested network namespace are disabled for container-kernel compatibility. The App already has a container network namespace; the container runtime's seccomp policy remains active, as do the AppArmor profile, per-user chroot, dropped login shells, mapped-storage boundaries, and Home Assistant Protection Mode.

## TLS

Leave both certificate fields blank to generate an RSA-3072, SHA-256 self-signed certificate under persistent `/data/tls`. It is reused on every restart. Cameras may need to accept or tolerate a self-signed server certificate.

To use Home Assistant certificate files, set relative names below `/ssl`, usually `fullchain.pem` and `privkey.pem`. Absolute paths and traversal are rejected. The certificate is parsed and its public key is compared with the private key before vsftpd starts.

TLS is required by default for both login and data. Plain FTP is available only by setting `tls.require_tls: false` and `tls.allow_plain_ftp: true`; startup displays a prominent warning. Plain FTP exposes credentials and recordings and should only be used for old firmware on a trusted isolated LAN. There is no silent downgrade, implicit FTPS, SFTP, SSH, port 990, or port 22.

## Passive networking

The internal passive range is fixed at TCP `30000-30019` and all twenty ports are declared to Home Assistant. Do not remap those external ports to different numbers. The external control port may be changed in the App Network panel if the same port is entered in Reolink.

`pasv_address` is mandatory because vsftpd otherwise may advertise its private container address. Prefer a DHCP reservation or static LAN address. A hostname is accepted only if it resolves to IPv4 at startup; vsftpd then resolves it for PASV replies.

For a camera VLAN, permit only:

```text
camera VLAN -> Home Assistant IP -> TCP control port + TCP 30000-30019
```

Do not expose FTP/FTPS directly to the public Internet. Use a VPN for remote access and do not forward passive ports to WAN.

## Reolink setup

Current Reolink guidance uses these typical settings:

- **Server:** Home Assistant LAN IP or hostname only; no `ftp://`, `ftps://`, port, or path
- **Port:** `21` (or the external control port selected in Home Assistant)
- **Username/password:** the camera-specific App account
- **Transport Mode:** `Auto` or `PASV`
- **FTPs Only:** enabled
- **Remote directory:** normally blank, because the user is already chrooted into its configured directory

The server permits directory creation, upload, rename, overwrite, and delete for write accounts. Some Reolink NVR/Home Hub models do not support overwrite; this is a camera capability rather than a server error.

## Isolation and retention

Container users have persistent UIDs stored under `/data`, `/sbin/nologin`, a shared non-world-writable group, and a vsftpd kernel chroot rooted at the configured user directory. They do not exist on the HAOS host. Per-user vsftpd configuration disables all writes for read-only users. Two users may intentionally share a directory (for example, a camera writer and viewer), but no account can browse the recording root or another chroot.

`retention_days: 0` disables deletion. A positive value checks hourly and removes only regular files older than the cutoff beneath the already validated recording root. Directory symlinks are not followed; symlinks, directories, the anchor, TLS data, and App data are never deleted. Removed file count and estimated bytes are logged.

Recordings remain outside `/data` and are not copied into App backups. Camera archives may be hundreds of gigabytes and generally should not be included in normal Home Assistant backups. This App makes no claim that it globally excludes arbitrary `/media` or `/share` content from Home Assistant backup policies.

## Troubleshooting

- **App refuses startup / anchor unavailable:** mount or expose the dedicated storage first; never create the missing anchor merely to silence the check. Verify the optional marker.
- **Reolink test fails:** confirm server is only an IP/hostname, port and credentials match, **FTPs Only** is on, and the user is writable.
- **FTPS handshake / wrong certificate:** update camera firmware, verify the certificate pair and hostname, or test the persistent self-signed mode. Do not enable plain FTP unless isolation is acceptable.
- **PASV failure / 0-byte files:** set `pasv_address` to the camera-reachable HA address and allow every passive port. Across VLANs, inspect firewall rules and FTP helpers that rewrite TLS-blind traffic.
- **Permission denied / mkdir / rename failure:** make sure `read_only` is false, storage is writable, and free-space safety has not stopped the service.
- **Connected but no files:** leave the camera remote directory blank, inspect its upload schedule/file-type selection, and look inside that user's configured directory.
- **Insufficient disk space:** free space or raise/lower the threshold only after checking the correct filesystem. The service resumes automatically.
- **Works on one VLAN only:** allow the narrow camera-VLAN-to-HA control and passive range; cameras do not need broader Home Assistant access.
- **Old firmware has no FTPS:** update firmware first. As a last resort, explicitly opt into plain FTP on an isolated LAN.

## Development

Run unit tests with `python3 -m unittest discover -s tests -v`. Build locally with BuildKit:

```bash
docker build --platform linux/amd64 -t reolink-ftps:test reolink_ftps
```

The release workflow uses the current Home Assistant builder actions to publish per-architecture `amd64`/`aarch64` images and a generic multi-architecture manifest.
