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

Untested future iPadOS versions have no compatibility claim. Do not infer a range
of support from the original minimum deployment target, CPU architecture, one OS
pass, host tests or successful signing alone.

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
