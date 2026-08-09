# Read-only tool contract

Milestone 003 gives LocalCode eyes, not hands. These functions return bounded
observations and cannot edit repository files or run repository code.

## Tools

| Tool | Observation | Hard boundary |
|---|---|---|
| `list_files` | Stable repository-relative file list | 1,000 results and depth 20 maximum |
| `read_file` | UTF-8 excerpt with line numbers | 1 MiB input, 1,000 lines, 65,536 output characters |
| `search_code` | Literal or regex line matches | 200 matches, 5,000 files, 16 MiB scanned |
| `git_diff` | Unstaged or staged tracked diff | 65,536 output bytes and 10-second Git timeout |

All results are immutable `ToolResult` values containing `content`, a
`truncated` flag, and scalar metadata. Expected policy failures are typed
`ToolError` values with stable codes such as `path_escape`, `excluded_path`,
`binary_file`, and `file_too_large`.

## Path policy

Before reading, every user-supplied path must be:

1. a non-empty repository-relative path;
2. free of `..` traversal and NUL bytes;
3. outside excluded runtime, model, VCS, dependency, and generated-data paths;
4. outside secret-like names and credential directories; and
5. free of symlinks in every component.

Rejecting all symlinks is deliberately stricter than merely checking the final
resolved location. It makes the Version 1 boundary understandable and avoids
time-of-check/time-of-use surprises while we learn the system.

`.env.example` is allowed because it is a conventional source-controlled
template; `.env`, `.env.local`, keys, certificates, and credential files are
excluded.

## Git boundary

`git_diff` invokes Git with a fixed argument vector, no shell, no standard
input, a timeout, no pager, and `--no-ext-diff --no-textconv`. It first obtains
changed filenames, filters them through the same repository policy, and asks
Git for a diff containing only allowed paths. Therefore a tracked `.env` change
does not leak merely because a safe source file changed beside it.

Untracked files are intentionally absent from `git_diff`; adding a safe
untracked-file representation is a separate future contract.

## Truncation is evidence

`truncated=True` means the observation is incomplete. A future controller must
not let the model treat it as the whole repository, file, result set, or diff.
The correct response is a narrower follow-up action, not an unsupported claim.
