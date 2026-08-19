# Reolink FTPS Server for Home Assistant

[![CI](https://github.com/robby-z/ftp-addon/actions/workflows/ci.yml/badge.svg)](https://github.com/robby-z/ftp-addon/actions/workflows/ci.yml)
[![Release](https://github.com/robby-z/ftp-addon/actions/workflows/release.yml/badge.svg)](https://github.com/robby-z/ftp-addon/actions/workflows/release.yml)

A production-oriented Home Assistant App that provides secure explicit FTPS for Reolink cameras using vsftpd. It is designed for continuous uploads to storage already exposed as `/media` or `/share`, especially a dedicated recording SSD that must remain separate from the Home Assistant system disk.

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Frobby-z%2Fftp-addon)

## Highlights

- Explicit FTPS (`AUTH TLS`) on TCP 21; no SFTP or implicit port 990
- Fixed passive range TCP 30000–30019 and camera-reachable PASV address
- Multiple camera-specific users, chroot isolation, and read-only viewer accounts
- TLS required by default; persistent self-signed or relative `/ssl` certificate pair
- Pre-existing storage-anchor requirement so a missing SSD cannot silently fall back to the system disk
- Optional marker file, filesystem write tests, and correct-filesystem free-space reporting
- Service cutoff below a configurable free-space threshold
- Optional symlink-safe retention limited to regular files inside the validated recording root
- AppArmor, Home Assistant Protection Mode, no host network, no devices, no APIs, no privilege escalation
- English and German Home Assistant configuration translations
- `amd64` and `aarch64` GHCR release images

## Architecture and storage separation

```text
Reolink Cameras
      |
      | Explicit FTPS: TCP 21 + passive TCP 30000-30019
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

Do not use Home Assistant's **Move data disk** feature for this layout; it moves Home Assistant's overall data partition. First expose the dedicated disk independently at an anchor such as `/media/ReolinkSSD`. Network storage can use **Settings → System → Storage → Add network storage → Usage: Media**. A second local SSD may require a separate trusted mount App or a different supported storage architecture. This FTPS App deliberately has no block-device or host-mount access.

`storage.directory: ReolinkSSD/reolink` is split into a required, pre-existing anchor (`/media/ReolinkSSD`) and a creatable child (`reolink`). Missing anchors, symlinks, absolute paths, traversal, unsafe components, or canonical escapes stop startup. The optional `.reolink-storage` marker adds protection against a wrong or absent volume.

## Install

Home Assistant OS users can use the button above, or:

1. Copy `https://github.com/robby-z/ftp-addon`.
2. Open **Settings → Apps → App store**.
3. Select the three-dots menu at top right, then **Repositories**.
4. Add the URL and select **Add**.
5. Select **Reolink FTPS Server**, then **Install**.

Before first start, expose and verify the storage anchor, add at least one user, set `pasv_address`, and keep passive external ports 30000–30019 mapped unchanged.

## Configuration

```yaml
storage:
  root: media
  directory: ReolinkSSD/reolink
  minimum_free_space_gb: 20
  stop_uploads_below_free_space: true
  require_marker_file: false
  initialize_marker_file: false
  marker_file: .reolink-storage
users:
  - username: camera_front
    password: use-a-unique-strong-password
    directory: front
    read_only: false
  - username: camera_garden
    password: use-another-unique-password
    directory: garden
    read_only: false
  - username: viewer
    password: use-a-third-password
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

There is currently no secure native Home Assistant selector for an arbitrary subdirectory of a mapped App folder. The UI therefore constrains `root` to `media|share`, masks passwords with the official `password` schema, and accepts a relative directory that the runtime validates again.

At low free space the App stops vsftpd entirely and resumes after recovery. This briefly blocks reads too, but reliably stops writes to existing nested camera directories. It never auto-deletes unless `retention_days` is positive.

The App uses Home Assistant's supported Debian Trixie base because Alpine's vsftpd login child is unreliable with FTPS on some current amd64 container kernels. vsftpd's internal legacy seccomp filter and its nested network namespace are disabled for container-kernel compatibility; the App already runs in its own container network namespace, and Docker seccomp, AppArmor, chroot isolation, and Home Assistant Protection Mode remain active.

## Reolink setup

- **Server:** Home Assistant LAN IP or DNS hostname—do not include `ftp://`, `ftps://`, a port, or a directory
- **Port:** `21`, unless you changed the external control port in Home Assistant
- **Username/password:** the camera-specific account
- **Transport Mode:** `Auto` or `PASV`
- **FTPs Only:** enabled
- **Remote directory:** blank; the account is already rooted in its own camera directory

Use one user per camera for separate credentials, directories, revocation, and troubleshooting. Write users support mkdir, upload, rename, overwrite, and delete. Read-only users can list and download only.

## TLS, networking, and backups

Blank certificate fields create a persistent RSA-3072 self-signed pair under App `/data`. To use Home Assistant TLS, enter relative `/ssl` names such as `fullchain.pem` and `privkey.pem`. Plain FTP requires the explicit combination `require_tls: false` and `allow_plain_ftp: true` and is only appropriate on a trusted isolated LAN.

Give Home Assistant a DHCP reservation or static address. For camera VLANs, allow only camera VLAN → Home Assistant IP → control TCP port and TCP 30000–30019. Never expose FTP/FTPS or its passive range directly to the public Internet; use a VPN.

Recordings stay outside App `/data` and may be hundreds of gigabytes. They generally should not be part of ordinary Home Assistant backups. The App does not claim to change global backup behavior for arbitrary `/media` or `/share` data.

## Troubleshooting and full documentation

See [reolink_ftps/DOCS.md](reolink_ftps/DOCS.md) for missing-mount recovery, marker initialization, FTPS handshake and certificate issues, passive/VLAN firewall failures, 0-byte files, permissions, low-space behavior, retention safety, and development commands.

## Publishing

Create a GitHub release tag matching `reolink_ftps/config.yaml`, for example `v1.0.0`. The release workflow tests and publishes `amd64`, `aarch64`, and the generic `ghcr.io/robby-z/reolink-ftps:1.0.0` manifest. The repository owner must make the GHCR package public after its first publish: **GitHub profile/organization → Packages → reolink-ftps → Package settings → Change visibility → Public**.

## License

[MIT](LICENSE)
