# Privacy and publication safeguards

Only original source, synthetic tests and sanitized documentation belong in publication. Never include game packages/binaries/assets, saves, signing material, credentials, raw diagnostics, account/device identifiers or personal filesystem paths.

`.gitignore` excludes common private artifacts and local operational notes. Ignore rules do not protect files already tracked or force-added. The dependency-free publication guard checks the complete index; `--worktree` additionally supports review of the current publication candidates. Checks are heuristic and do not establish ownership, license compliance or absence of every secret.

Before an approved commit, run `python3 scripts/check_publication.py`, review the complete staged diff and verify actual author/committer identities. Use an owner-verified GitHub noreply address; never invent one or change global Git settings. Local hooks are not automatically enabled by cloning and can be bypassed.

For publication, separately review all reachable history, branches/tags and remotes. Raw private evidence remains local; public result summaries distinguish device traces, owner observations, synthetic tests and untested claims. No proprietary disassembly or game implementation source belongs here.

The local portfolio audit found no commits, branches/tags or remote. Tool-managed checkpoint refs and unreachable objects exist locally, including a historical filesystem metadata file. These are not portfolio content: never mirror-push, push all refs or upload the Git metadata directory. Approve only an explicitly reviewed branch/file set. No checkpoint/history deletion was performed.

At the portfolio preparation milestone, nothing had been published. A code license has not been selected; no license grant for game content is implied. Publication, commits, pushes, history changes and account/security changes require explicit authorization.
