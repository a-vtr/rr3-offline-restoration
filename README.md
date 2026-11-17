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

Gameplay and save persistence were confirmed through hands-on testing on an **11-inch iPad Pro M5 running iPadOS 27.2.1**. Device traces also confirm resource readiness before the original startup sequence.

## How offline restoration works

The application carries an immutable copy of the preserved resources. A native initializer verifies and prepares them in the restored app's own storage before handing control to the game. No separate manual cache transfer is required.

The most significant engineering work involved coordinating startup without skipping original application setup, separating application and signing identities, and resolving a configuration failure caused by the renamed app. Integration changes are isolated and reversible; original backups and game instruction bodies were preserved.

**Built with:** Objective-C++, UIKit, Foundation, Python, Xcode and ARM64 Mach-O analysis. The [native implementation](native/), [diagnostic scripts](scripts/) and [tests](tests/) are available for inspection.

## Gameplay demonstration

Screenshots and a short video showing offline racing and saved progress after relaunch are planned for this page.

## Future improvements

- Explore enhanced graphics and stable **120 FPS**, with measured performance and frame pacing.
- Verify more cars, tracks and events, plus resource recovery after system cache removal.
- Retest compatibility after significant iPadOS updates.

The tested gameplay works; exhaustive content coverage and future OS compatibility are not yet established. Some additional manifest references remain unresolved. Graphics enhancements and 120 FPS are goals, not current results. See the [compatibility matrix](docs/COMPATIBILITY_MATRIX.md) for details.

## Attribution and availability

An independent personal project, unaffiliated with EA or Firemonkeys. This repository shares original restoration tools and documentation. **Game IPAs, proprietary assets, saves and signing material are not distributed.** Redistribution of game content requires permission from its rights holders.

**AI assistance:** I directed the project requirements and performed device testing. Codex provided substantial assistance with analysis, implementation, debugging and documentation.
