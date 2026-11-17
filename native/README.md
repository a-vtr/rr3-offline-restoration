# Native resource initialization

The original Objective-C++ implementation has three layers:

- `RRResourceRuntime.h/.mm`: streaming SHA-256 verification, atomic resource restoration, interprocess locking and a serial asynchronous coordinator. The host API requires a marked scratch container. The experimental API checks its application identity and discovers its own writable directories. Resource allowlists exclude progress/account state.
- `ios/ResourceLabApp.mm`: a UIKit test application for small sample resources and lifecycle/recovery tests. It contains no game code.
- `ios/RR3Bootstrap.mm`: the tested pre-nib game adapter. It restores resources off the main thread, waits for readiness and activation, loads the original nib, and forwards original launch/activation callbacks. Partial handoff failure requires restart. The Firebase adapter is narrowly scoped to invalid in-bundle configuration input.

Host tests exercise integrity, missing/corrupt repair, interruption, retry, contention, activation, cancellation, deadlines and synthetic save isolation. The native iPadOS lab passed major lifecycle/recovery tests. Actual-game startup and offline racing/save persistence passed on the environment recorded in the [compatibility matrix](../docs/COMPATIBILITY_MATRIX.md); actual-game cache-purge recovery is still untested.

## Host harness

For a self-contained test using generated non-game fixtures:

```sh
python3 tests/run_native_synthetic.py
```

For privately held sample inputs on macOS with Apple developer tools, supply a private three-file seed and its manifest report to a new output directory outside the repository:

```sh
python3 scripts/test_native_resources.py "$SEED_DIR" "$SEED_REPORT" "$OUTPUT_DIR"
```

`SEED_REPORT` is a JSON object with a `manifest` array of `path`, `bytes` and `sha256` records. The harness expects exactly three allowed resource files; synthetic fixtures can be used instead of game content. Add `--asan` for AddressSanitizer. Outputs contain local diagnostics and stay private. This command builds a macOS test binary; it neither signs nor installs an iPad app and does not establish iPadOS compatibility.

The restoration core is independent of fixed container UUIDs and exact OS versions. The game adapter and Mach-O layout assumptions remain application-specific. Significant OS updates require new runtime results rather than inferred future compatibility.
