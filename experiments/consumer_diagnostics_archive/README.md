# Consumer diagnostics archive

This branch consolidates the 12 historical consumer-throughput, backlog, rendering, ETW, native-stack and sparse-processing investigation branches listed in `manifest.json`.

The native-stack-capture-calibration history already contains 11 source tips; sparse-processing-experiments-20261021 is merged separately. Original commit histories are retained. This archive does not imply that every experimental implementation was adopted or that every hypothesis was confirmed.

Uncommitted evidence from three source worktrees was copied without changing those worktrees. Identical files shared by multiple worktrees are stored once at their original relative path. The manifest records each source and SHA-256 digest.

Report Agent development remains separate on `codex/walk-offline-compute-diagnosis` (worktree `report-agent-presentation`). The production branches `main` and `vae/iron_jump` are unchanged.
