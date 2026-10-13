# Powerwall energy-device schemas

These are the unchanged energy-device schemas from Teslemetry/tesla-protocol
1.4.0, commit `faac4a0ef9cf036b4d81b262528118ec3aa0ce4d`:
https://github.com/Teslemetry/tesla-protocol/tree/faac4a0ef9cf036b4d81b262528118ec3aa0ce4d/proto/energy_device

Only the transitive dependencies of PowerSync's five transport imports are
included. The Tesla schemas and the upstream google/rpc/status.proto excerpt
are Apache-2.0; see LICENSE. The descriptor bundle also includes Google's
well-known protobuf types from protoc 25.0, covered by LICENSE.protobuf.

PowerSync loads the descriptors with the public protobuf descriptor-pool and
message-factory APIs, using a private pool. This preserves the Tesla wire names
and field numbers while avoiding collisions with a separately installed Tesla
package. It uses HA's protobuf runtime (4.25.0 or newer) without installing or
overriding packages at runtime. The bundle is embedded in a Python module so
loading it requires no additional synchronous data-file read in HA.

Regenerate from the checked-in sources in an isolated Python build environment:

```sh
python -m pip install grpcio-tools==1.60.0 setuptools==70.3.0
python scripts/build_powerwall_schemas.py
```

The script requires protoc 25.0 and generates the same descriptor bytes. It is a
development tool; grpcio-tools is not an integration requirement. Keep the source
revision and licenses with future schema updates, and verify wire fixtures,
private-pool coexistence, and the supported Core protobuf pins before releasing.
