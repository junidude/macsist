# Macsist website — handoff kit

This folder is a **self-contained brief** for building the Macsist landing /
download site on a separate server. It is documentation only — nothing here
runs; the site is built and hosted elsewhere.

Copy this `website/` folder into the new site's repo and have the agent there
start from these two files:

- **[SPEC.md](SPEC.md)** — *what* to build: purpose, page structure, the two
  install paths, the mandatory self-signed first-open note, assets, visual
  direction, success criteria.
- **[AGENT.md](AGENT.md)** — *how* to build, run, and deploy it: stack, layout,
  asset fetching, build/dev/deploy commands, verification checklist, guardrails.

Fixed facts the site depends on (see SPEC for the rest):

- Download (stable): `https://github.com/junidude/macsist/releases/latest/download/Macsist.dmg`
- From source: `git clone https://github.com/junidude/macsist.git && cd macsist && ./install.sh`
- Requirements: macOS 26.2+, Apple Silicon. The DMG is self-signed (not
  notarized) — the first-open instructions are mandatory on the page.
