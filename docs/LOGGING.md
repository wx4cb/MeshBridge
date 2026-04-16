# MeshBridge Logging Reference

MeshBridge logging now has **two controls**:

- `log_level`
- `log_modes`

These work together but do different jobs.

## `log_level`

`log_level` is the normal Python logging severity threshold.

Allowed values:

- `DEBUG`
- `INFO`
- `WARNING`
- `ERROR`
- `CRITICAL`

### Quick rule

- use `DEBUG` while developing or diagnosing
- use `INFO` for normal testing
- use `WARNING` or above for quieter operation

## `log_modes`

`log_modes` selects which **bridge categories** are enabled.

Allowed values:

- `DEBUG`
- `SYSTEM`
- `TRAFFICONLY`
- `RFONLY`
- `QUIET`

You can enable **multiple modes at once**.

Example:

```hjson
log_level: "DEBUG"
log_modes: [
  "TRAFFICONLY"
  "RFONLY"
]
