---
name: commit
description: Create a git commit with staged changes
when_to_use: When changes are ready to commit
argument_hint: "[-m message]"
---

# Git Commit

Follow this protocol to create a git commit:

1. Run `git status` (no -uall flag) and `git diff --staged` to see staged changes
2. Run `git log --oneline -10` to see recent commit message style
3. Draft a concise commit message (1-2 sentences, focus on "why")
4. Run `git commit -m "..."` with the message
5. Run `git status` to verify

## Git Safety Protocol
- NEVER amend commits unless explicitly requested
- NEVER force push to main/master
- NEVER skip hooks (--no-verify, --no-gpg-sign)
- NEVER commit .env, credentials, or large binaries
- Prefer adding specific files rather than `git add -A` or `git add .`

## Commit Message Format
Use a concise subject line and, when needed, a short body that explains why the
change was made.
