# Real Racing 3 Offline Restoration

Restoring a mobile racing game as a standalone, self-contained offline experience on iPad.

**Working milestone:** the restored application launches independently, plays races offline and retains progress after closing and reopening the game.

## About the project

Real Racing 3 is a mobile racing game developed by Firemonkeys and published by EA. This independent preservation project brings a personally preserved copy and its game resources together so gameplay can continue without relying on EA's asset download servers.

The application alone was not enough: it expected additional resources in specific locations before gameplay could begin. The challenge was to make those resources available locally while preserving the game's startup behaviour and keeping existing player data safe.

## What I achieved

- A single sideloadable application containing the preserved game and approximately **8.31 GB of local resources**.
- Native resource initialization that completes before the original game starts.
- Working offline menus, tutorial and races, with **saved progress retained after a full quit and relaunch**.
- A separate “RR3 Restored” installation that coexists with the original App Store application without changing its progress.
- Integrity verification covering all **26,043 preserved files** in the package.
- **120 FPS observed during offline racing**, independently checked using Apple’s Metal Performance HUD.
- Local save import and **WASD keyboard driving**, tested with a Logitech Combo Touch.

Gameplay and save persistence were confirmed through hands-on testing on an **11-inch iPad Pro M5 running iPadOS 27.2.1**. Device traces also confirm resource readiness before the original startup sequence.

During the latest race check, Apple’s HUD showed **120 FPS** and **3.18 ms GPU time**. Captured Apple HUD records independently counted **2,058 drawable presentations over 17.15 seconds**, approximately 120 per second. This is a measured gameplay milestone, not a guarantee of sustained performance across every track or a long session; later capture rates fell with activity context unconfirmed. See the [test results](docs/COMPATIBILITY_MATRIX.md#performance-observation--2026-11-18) for measurement limits.

## How offline restoration works

The application carries an immutable copy of the preserved resources. A native initializer verifies and prepares them in the restored app's own storage before handing control to the game. No separate manual cache transfer is required.

The most significant engineering work involved coordinating startup without skipping original application setup, separating application and signing identities, and resolving a configuration failure caused by the renamed app. Integration changes are isolated and reversible; original backups and game instruction bodies were preserved.

**Built with:** Objective-C++, UIKit, Foundation, Game Controller, Python, Xcode and ARM64 Mach-O analysis. The [native implementation](native/), [diagnostic scripts](scripts/) and [tests](tests/) are available for inspection.

## Gameplay demonstration

Screenshots and a short video showing offline racing and saved progress after relaunch are planned for this page.

## Future improvements

- Explore enhanced graphics and validate sustained **120 FPS**, frame pacing and thermal performance across more races.
- Verify more cars, tracks and events, plus resource recovery after system cache removal.
- Resolve optional Apple Metal HUD activation after normal Home Screen launches; its in-app Show/Hide control works during diagnostic launches.
- Retest compatibility after significant iPadOS updates.

The tested gameplay works; exhaustive content coverage and future OS compatibility are not yet established. Some additional manifest references remain unresolved. Enhanced graphics and sustained performance across all content remain future work. See the [compatibility matrix](docs/COMPATIBILITY_MATRIX.md) for details.

## Attribution and availability

An independent personal project, unaffiliated with EA or Firemonkeys. This repository shares original restoration tools and documentation. **Game IPAs, proprietary assets, saves and signing material are not distributed.** Redistribution of game content requires permission from its rights holders.

**AI assistance:** I directed the project requirements and performed device testing. Codex provided substantial assistance with analysis, implementation, debugging and documentation.
