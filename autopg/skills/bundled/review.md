---
name: review
description: Review the current git diff for correctness bugs and improvements
when_to_use: When asked to review code changes or a PR
argument_hint: ""
---

# Code Review

Review the current git diff for correctness, security, and quality.

1. Run `git diff` to see all changes
2. Run `git log --oneline -5` for recent commit context
3. Analyze the diff for:

## Correctness
- Logic errors and off-by-one bugs
- Missing error handling at system boundaries
- Race conditions and thread safety
- Incorrect assumptions about input data

## Security
- SQL injection, XSS, command injection
- Authentication and authorization bypasses
- Sensitive data exposure
- Unsafe deserialization

## Performance
- N+1 queries
- Unnecessary allocations
- Blocking operations in async code
- Missing indexes or caching opportunities

## Code Quality
- Reuse and simplification opportunities
- Code that duplicates existing functionality
- Missing tests for new logic
- Naming that doesn't match conventions

## Output Format
Provide findings as a structured report:
- **High severity**: Must fix before merge
- **Medium severity**: Should fix
- **Low severity**: Nice to have / style suggestions

Reference specific file paths and line numbers.
