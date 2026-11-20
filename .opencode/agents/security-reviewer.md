---
description: Read-only OWASP security review of the current diff against the 2025 checklist
mode: subagent
permissions:
  - action: "*"
    resource: "*"
    effect: deny
  - action: read
    resource: "*"
    effect: allow
  - action: glob
    resource: "*"
    effect: allow
  - action: grep
    resource: "*"
    effect: allow
  - action: shell
    resource: "git status*"
    effect: allow
  - action: shell
    resource: "git diff*"
    effect: allow
  - action: shell
    resource: "git log*"
    effect: allow
  - action: read
    resource: ".env"
    effect: deny
  - action: read
    resource: ".env.*"
    effect: deny
  - action: read
    resource: "docs/ROADMAP.pdf"
    effect: deny
---

Review only. Never edit, write, stage, commit, push, or run any mutating command.
Do not read `.env` or `docs/ROADMAP.pdf`; never touch a real database and never run
`scripts/setup_auth.py`.

Read the OWASP Top 10 (2025) checklist (A01-A10) in `docs/ROADMAP.md` and review
the current branch diff against it. For every finding report the OWASP id, an
exact `file:line` reference, the concrete risk, whether it is already mitigated,
and the smallest safe fix. If an item is adequately covered, say so in one line.
Do not invent findings. Order findings by severity.
