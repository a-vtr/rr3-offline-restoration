# Compatibility matrix

Record versioned observations, not predicted support. Current target information
is owner-reported until device-queried. RR3 startup has been traced on the recorded environment; the owner confirms offline races and saved progress after relaunch.

## Device/game results

| Test ID / date | Device / iPadOS | Restoration build | Install / direct startup | Offline menu / race | Save / relaunch | Missing/purged resource recovery | Signing/provisioning | Limits |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| native-ipados-lab01 / 2026-11-17 | iPad17,1 / 27.2.1 queried; owner identifies 11-inch M5 | UIKit lab 42e2a5d8386dc133; SDK 27.2, minimum 15.0 | Install + CoreDevice launch pass; Home Screen not tested | Not tested (no game code) | Synthetic progress sentinel preserved; relaunch pending | Initial restoration/hash readback + missing/corrupt repair pass; activation during work + cancellation/retry pass | Impactor export; strict host verification/profile coherence pass, profile expires 2026-11-24 UTC | Resource gate precedes simulated startup; 24 main-loop heartbeats. No RR3 or future-release compatibility claim. |
| rr3-prenib-4d4488a240d223e1 / 2026-11-17 | Target iPadOS 27.2.1; not run | Actual RR3 + native pre-nib gate; SDK 27.2, minimum 15.0, 3-file seed | Not tested; unsigned IPA build/CRC/Mach-O validation pass | Not tested | Not tested | Not tested in RR3; native lab evidence separate | Not signed; app/widget/framework profiles and separated groups pending | Original game instruction bytes and nibs retained. Actual UIKit handoff/order and pre-main side effects unverified; offline test required to prevent downloads. |
| rr3-prenib-export01 / 2026-11-17 | Target iPadOS 27.2.1; game not installed/run | Same native build 4d4488a240d223e1 and 3-file seed | Not tested | Not tested | Not tested | Not tested in RR3 | Code signatures/resource seals and profile coherence pass; exact bundle-ID acceptance FAIL (team suffix added) | No installation clearance; no EA app/keychain groups, no installed-ID collision. Original App Store app untouched. |
| rr3-full-d0c32ba8cf9c0f2b / 2026-11-17 | iPad17,1 / iPadOS27.2.1 | Full preserved seed, SDK27.2 | Install PASS after approved Resource Lab removal; owner trust + Home Screen launch PASS into bootstrap | NOT REACHED: original launch throws Firebase invalid-config exception | Not tested | Full manifest restore/verify PASS in44.06s before original nib | Deep/strict full bundle + profiles PASS; suffix IDs accepted | Renamed ID breaks Firebase region selector and loads Icons_ROW.plist. Corrective build e4490d20f33414f8 tested separately below. |
| rr3-full-e4490d20f33414f8 / 2026-11-17 | iPad17,1 / iPadOS27.2.1 | Full preserved seed; corrected Firebase input routing | Same-ID full Upgrade + CoreDevice launch PASS; original nib/didFinish/activation handoff PASS | Offline menu/tutorial and races PASS (owner runtime observation; not exhaustive content coverage) | Full quit/relaunch, initializer and retained progress PASS (owner observation) | Existing resources reverified before game startup in38.37s; no purge test | Deep/strict signatures + profiles/identity separation PASS | Firebase exception resolved. CoreDevice delta update failed SINF requirement; SINF-aware ideviceinstaller full Upgrade succeeded without uninstall. No future OS claim. |
| rr3-keyboard-hud-6c2aef3204e709b0 / 2026-11-18 | Same M5 / iPadOS27.2.1 | V3 graphics + keyboard controller bridge and optional Apple HUD; SDK27.2 | Same-ID Upgrade and CoreDevice launch PASS; resource gate and original delegate handoff traced | Keyboard driving PASS (owner); Apple HUD toggle FAIL (owner correction) | Persistence after this update pending | No purge test | Signatures/profiles/prior certificate/isolated identities PASS | Host input-state tests do not establish iPad keyboard functionality; no future OS claim. |
| rr3-hud-menu-4db2056a5f4f8778 / 2026-11-18 | Same M5 / iPadOS27.2.1 | HUD launch-key/mode correction + three menu-item removals; keyboard source unchanged | Same-ID Upgrade/CoreDevice launch and original delegate handoff PASS | HUD + Hide/Show PASS only after diagnostic environment launch (owner + screenshot); normal activation FAIL | After-update save test pending | No purge test | Signatures/profiles/prior certificate/separate identities PASS | Ordinary launch misses HUD; explicit diagnostic launch works. Persistent activation candidate signed/verified, not yet installed or tested. |
| rr3-persistent-hud-f474d09d5087ff20 / 2026-11-18 | Target: same M5 / iPadOS27.2.1 | App-specific HUD activation preference; keyboard/save backend unchanged | Not installed | Not tested | Not tested | Not tested | Export signatures, profiles and isolated identities PASS | Normal Home Screen HUD activation remains unverified. |

Untested future iPadOS versions have no compatibility claim. Do not infer a range
of support from the original minimum deployment target, CPU architecture, one OS
pass, host tests or successful signing alone.

## Performance observation — 2026-11-18

Tested build: `fe7e6e1ab31595a0`, on the same 11-inch iPad Pro M5 / iPadOS 27.2.1 environment. The owner confirms racing with the updated app. Signing/profile and separated identity checks passed before its same-identity update; these are distinct from the performance observations below.

| Evidence | Result | Limit |
| --- | --- | --- |
| Custom game presentation counter | Owner observed 120 successful submissions/s during racing | Submission success alone does not prove displayed FPS. |
| Apple Metal Performance HUD | Owner read **120 FPS** and **3.18 ms GPU time** while actively driving | Independent of the custom counter; values were read from the device overlay, not captured in a screenshot. Visible frame interval was not supplied. |
| Captured Apple HUD frame-number records | Initial **2,058 drawable presentations / 17.15 seconds ≈ 120/s** | Not a complete frame-pacing or unique-frame analysis. Later capture rates dropped sharply; activity context was not established, so the entire capture is not a sustained 120 FPS pass. |

The HUD became active after an approved launch with Apple's documented `MTL_HUD_ENABLED` and `MTL_HUD_LOG_ENABLED` options. USB timing fields were privacy-redacted; the screenshot service was unavailable. An Instruments trace failed before recording because its device service listed the connected iPad offline. No GPU trace or long-session thermal result is claimed.

These results support 120 FPS during observed racing, rather than relying on a requested refresh rate or the custom counter alone. Exhaustive track coverage, sustained performance and frame-pacing distributions remain untested. Apple defines the HUD's FPS from its on-glass frame interval and GPU time from command-buffer timings: [metric definitions](https://developer.apple.com/documentation/xcode/understanding-metal-performance-hud-metrics).

## Host harness evidence — separate from iPadOS compatibility

| Test ID / date | Environment | Artifact identity / evidence | Result | Scope limit |
| --- | --- | --- | --- | --- |
| native-host-20261117-normal | macOS 27.2.1 arm64; macOS SDK 27.2 | Native source SHA-256 and build/run records in private verified-normal result | Pass | Native resource backend and simulated lifecycle coordinator only; no UIKit/RR3/iPadOS execution. |
| native-host-20261117-asan | Same host / SDK; AddressSanitizer | Native source SHA-256 and build/run records in private verified-asan result | Pass | Same scope; not proof of future OS support or all possible memory/concurrency behavior. |

Exact private evidence locations are recorded in ignored `.private/LOCAL_STATE.md`.
Do not copy device IDs, account information, profiles or raw proprietary diagnostics
into this matrix. Existing evidence predates the richer runner metadata schema;
do not rewrite historical results as though those extra fields were collected.

## Result-recording contract

Append one result per build/OS/test run; preserve earlier failures and limits.
Record date, public test ID, queried OS/build and device class, restoration code and
seed-manifest identity, SDK/compiler version, and a privacy-safe evidence pointer.
Keep signing/export identity and profile/certificate validity in separate fields;
sensitive values stay private. A new signature can change the IPA hash without
changing the game code or seed; retain those identities separately for comparisons.

Use Pass, Fail, Not tested, or Blocked for individual checks. Record the actual
error and first failing stage. Host-only success, unavailable tools and expired
provisioning must not be recorded as a game compatibility pass/failure.

After a significant iPadOS update, first record the new environment and test the
same code/seed where signing permits. Check direct launch and initialization,
offline menu/race, save/relaunch, resource repair and relevant lifecycle callbacks.
Only simulate purge of isolated test resources with approval; preserve progress.
Change/rebuild an adapter or other component only for an observed dependency or
regression, then append a new result. Existing signing/device-change approval
boundaries remain in force; this document does not authorize automatic tests.

## Graphics and input follow-up — 2026-11-18

- V3 rendered at 2421 × 1668. The owner read Apple’s HUD at 120 FPS, about 4 ms GPU time and about 8 ms frame interval during racing. Sampled app footprint was 901–940 MiB; these observations do not establish long-session stability.
- V4 allocated the requested 1024 × 1024 reflection cubemap. A race screenshot showed 120 FPS, 4.49 ms GPU time and 8.33 ms frame interval, but the owner saw no noticeable visual improvement. V3 graphics were restored rather than claiming a successful enhancement.
- A single existing-texture substitution also produced no reported improvement and was reverted. The engine’s use of that temporary override was not established.
- The owner confirmed local save import and Combo Touch keyboard driving. The custom FPS counter has been removed. Apple’s HUD and its Show/Hide control were confirmed during a diagnostic launch; ordinary Home Screen HUD activation remains unresolved pending the persistent-preference candidate. Keyboard reconnect/focus-loss behaviour and HUD preference persistence have not been device-tested.
