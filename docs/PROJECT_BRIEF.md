# Project brief

## Objective and current result

Preserve a personally held iOS game as one independently installable application with locally packaged resources, offline initialization and persistent progress. Original game source is unavailable; this project implements a restoration layer and diagnostic/build tools.

The current prototype packages every available preserved resource without reducing asset quality. Device traces verify resource readiness before original launch callbacks. The owner confirms standalone launch, offline races and saved progress after a full quit/relaunch on the tested iPad. This is a verified prototype milestone, not exhaustive content or future-OS certification.

## Architecture and boundaries

Keep an immutable seed in the bundle and restore only reviewed resource paths into the experimental application's dynamically discovered writable container. Keep player/account state separate. Preserve original nibs and game instruction bodies; isolate the reversible import adjustment, lifecycle adapter and targeted configuration compatibility shim.

The existing App Store app and its progress remain strictly read-only. Use distinct app/widget identities, separate profile-authorized groups and independent storage. No original-app save migration or keychain access is part of this project.

Preserved originals, game packages, assets, profiles, credentials and raw device diagnostics are private and excluded from publication. Public source consists of original restoration/diagnostic code and synthetic test code; it does not provide game content. Signing, installation, certificate/account actions and publication require explicit owner authorization. Never revoke certificates, alter originals or fabricate authorship.

## Validation and future work

Completed: host/native-lab integrity and lifecycle checks; full preserved seed packaging/catalogue coverage; signature/profile verification; actual standalone offline startup/racing and save/relaunch observations. Detailed environment/result distinctions are in [COMPATIBILITY_MATRIX.md](COMPATIBILITY_MATRIX.md).

Remaining: actual-game cache-purge recovery, exhaustive track/car/event coverage and unresolved extra manifest paths. Broader bundled manifests contain references absent from the preserved cache; a working tested race does not prove every possible dependency exists.

Target modern compatible iPadOS releases using public APIs where feasible, runtime directory/capability discovery and minimal reversible adapters. The current OS is a tested environment, not a permanent dependency or promise of future support. After significant updates, retest startup, offline gameplay, saves and recovery; distinguish provisioning expiry from game compatibility.

Performance/graphics experimentation follows functionality and coverage work. Maximum feasible quality and stable 120 FPS are future goals, not measured achievements. No asset quality reduction or graphics patch is part of the current milestone.

The owner directs scope and performs device testing; Codex provides substantial AI-assisted implementation and analysis. Maintain reproducible input/toolchain identities privately and truthful public result summaries. No commits or publication without separate approval.
