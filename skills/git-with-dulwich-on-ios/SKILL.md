---
name: git-with-dulwich-on-ios
description: Use when working with git in Pythonista through dulwich directly (beyond the git tool), when a git operation fails with hook, subprocess or path errors, or before the first commit in a repository
---

pycoder's git tool and `!git` already handle these; follow them when writing your own dulwich code.

1. Install `dulwich==0.22.8`. Newer releases need urllib3 2.x, which breaks the requests Pythonista ships.
2. Disable shell hooks before committing. dulwich runs every hook with `subprocess.call` and only expects
   OSError for a missing hook file; on iOS subprocess raises RuntimeError, so every commit fails even in a
   repository with no hooks. Call `pycoder.tools.git.disable_shell_hooks()`, or set
   `dulwich.hooks.ShellHook.execute = lambda self, *args: None`. Git hooks can't run on iOS anyway.
3. Pass absolute paths to `porcelain.add`. With `paths=None` it resolves against the process's working
   directory, which in Pythonista is not the repository.
4. A `.git` file pointing at a path that doesn't exist (a Mac checkout synced to an iPhone through
   iCloud) opens as an empty repository instead of failing; check `porcelain.active_branch(repo)` and
   `repo.head()` before trusting it.
5. `porcelain.reset(repo, 'hard', sha)` does not move the branch; set `repo.refs[b'refs/heads/<branch>']`
   first, then reset.
6. Send a GitHub token only when the remote's parsed host is exactly `github.com`
   (`urllib.parse.urlparse(url).hostname`), never on a string-prefix match.
7. Commits need the user's identity. Without `user.name` and `user.email` in the repository's
   `.git/config` (or in `os.path.expanduser('~/.gitconfig')`, Pythonista's own home, not pycoder's
   `~`), dulwich makes one up from the device's user and host names. Check `repo.get_config()`
   before the first commit; if it has no `user` section, ask the user for their name and email, then
   `c = repo.get_config(); c.set((b'user',), b'name', name.encode()); c.set((b'user',), b'email',
   email.encode()); c.write_to_path()`.
