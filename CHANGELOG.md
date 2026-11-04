# Changelog

All notable changes to `lake-openmetadata-ingestion` are documented here.

## 0.1.1 — 2026-11-03

Security hardening for how the tool handles credentials: the bot JWT, the Lake DSN password and the
OpenMetadata admin credential. Two changes are **breaking** for anything that scripts `init-bot`; the
migration steps are in the [Upgrade notes](README.md#upgrade-notes).

### Breaking

- `init-bot` no longer prints the bot JWT to stdout by default. The JWT is written to a `0600` file
  instead: `--write-token PATH` (default `.state/bot_token`, relative to the process working
  directory). `--print-token` restores the previous stdout output byte for byte (plus a warning on
  stderr), or read the token file: `export OM_JWT_TOKEN=$(cat .state/bot_token)`.
- The default token path is written even when `--write-token` is not passed, so a deployment with a
  read-only rootfs or a non-writable working directory (e.g. a Kubernetes initContainer with
  `workingDir: /`) must pass an explicit writable `--write-token` path.

### Security

- The token file is written atomically (`mkstemp` + `fchmod` + `rename`) instead of
  `write_text()` followed by `chmod`: closes the window in which the JWT existed with the prevailing
  umask (commonly world-readable), and no longer follows a pre-existing symlink at the target path.
  The token path must therefore be a real file, not a symlink. On Windows the `0600` mode is
  best-effort: `os.fchmod` is Unix-only, so the `os.chmod` fallback (and the `mkstemp` default mode)
  is used instead.
- Config credentials are now visible: `Config.load` warns when a `${VAR}` referenced by the config
  file is not set (it still expands to an empty string, matching the old parse semantics) and when
  the config file is group/world readable, since the Lake DSN password lives in it.
- `OpenMetadataClient` warns when `openmetadata.host` is plaintext `http://` on a non-loopback host:
  every request carries the bot JWT, and `init-bot` also sends the OpenMetadata admin password.
- `init-bot` provisions an **instance-wide** bot + policy + role. OpenMetadata policy rules match by
  resource type and carry no condition, so the grant covers every service, database, schema and
  table in the instance, not only `service.name`. The misleading "least-privilege" wording was
  removed from the CLI help and README, and the scope caveat is documented.
- The success message of `init-bot` now includes a non-reversible `sha256:<prefix>` fingerprint of
  the token, so a rotated token can be identified without reading it.

### Fixed

- `cmd_init_bot` no longer raises `AttributeError` when it is called programmatically with an
  `argparse.Namespace` that only has some of the CLI flags (the flags are read with `getattr`).

### Notes

- Security-relevant warnings go through `logging`, i.e. to **stderr** by default; stdout keeps only
  the machine-readable result lines.
- The tool still has no secret-manager integration: inject `LAKE_PASSWORD` / `OM_JWT_TOKEN` through
  the environment (Kubernetes Secret, CI secret, or a `0600` env file) rather than a plaintext
  config file.
