# AGENT.md — Macsist website

Operating instructions for the agent building/maintaining the Macsist landing
site **on its own server/repo**. Read `SPEC.md` (next to this file) first — it
is the source of truth for *what* to build. This file is *how* to build, run,
and ship it.

## Mission

Ship one polished, static landing page that gets macOS users to install Macsist
via two paths: download the `.dmg`, or `git clone … && ./install.sh`. Nothing
more — no backend, no accounts, no CMS.

## Source of truth & guardrails

- **Facts come from two places only:** this `SPEC.md`, and the public repo
  README at `https://github.com/junidude/macsist` (and its translations
  `README.<lang>.md`). **Do not invent features, specs, or claims.** If a detail
  isn't in either, leave it out or ask the owner.
- **Never change these literals:**
  - Download link: `https://github.com/junidude/macsist/releases/latest/download/Macsist.dmg`
  - Source install: `git clone https://github.com/junidude/macsist.git` then `cd macsist && ./install.sh`
  - Requirements: macOS 26.2+, Apple Silicon.
- **The first-open / self-signed note (SPEC §6) is mandatory** and must be
  visible to anyone who downloads. Removing or burying it is a bug.
- Keep the promise the product makes: **private, local-first** → no invasive
  trackers, no cookie walls.

## Recommended stack

Pick the lightest thing that builds to **static files**:
- Default: **Astro** (component-friendly, zero-JS by default, trivial static
  build) — or plain **HTML + CSS** if even simpler is preferred.
- Tailwind or vanilla CSS, your call. Must support dark theme + `prefers-color-scheme`.
- No SSR, no runtime server. Output is a folder of static assets.

## Suggested layout

```
/                # site repo root
  src/ (or public/)   # pages, components, styles
  assets/             # vendored, optimized icon + screenshots (see SPEC §8)
  dist/ (or build/)   # static build output -> this is what gets served
  SPEC.md  AGENT.md   # copied from the macsist repo's website/ folder
```

## Getting the assets

Vendor optimized copies (don't hot-link) from the public repo:

```bash
base=https://raw.githubusercontent.com/junidude/macsist/main
curl -L "$base/app/assets/macsist-1024.png"      -o assets/icon.png
curl -L "$base/assets/HotKeyEx-test.png"         -o assets/shot-text.png
curl -L "$base/assets/HotKeyEx-image-2.png"      -o assets/shot-region.png
# then convert to WebP/AVIF and lazy-load them
```

## Build / dev / deploy

Document the exact commands in the site repo's own README once the stack is
chosen. The shape (self-hosted on the owner's server):

```bash
# local preview
npm install
npm run dev            # http://localhost:4321 (or framework default)

# production build -> static files in dist/
npm run build

# deploy to the owner's server (example — adapt to their setup)
rsync -avz --delete dist/ user@server:/var/www/macsist/
#   served by nginx/Caddy as static files; HTTPS via the server's existing TLS
```

If the owner uses a static host (Vercel/Netlify/Cloudflare Pages/GitHub Pages)
instead, wire `npm run build` + the `dist/` output dir into that host and skip
rsync. Keep deploy to **one command**.

## Content checklist (from SPEC §4)

- [ ] Hero: icon, name, tagline, two CTAs, "macOS 26.2+ · Apple Silicon"
- [ ] In-action: two screenshots + captions
- [ ] Features: 6–8 items, wording aligned with the README
- [ ] Download: DMG button + **first-open note** + source one-liner
- [ ] How it works: brief + link to repo
- [ ] FAQ: privacy / API-or-local / security warning / which Macs
- [ ] Footer: repo link, license, credits

## Verify before publishing

- [ ] Download button hits the live DMG (HTTP 200, file downloads).
- [ ] Source command block copies cleanly (one line, no smart quotes).
- [ ] First-open instructions visible on the download section (and the
      `xattr` command is selectable/copyable).
- [ ] Responsive at 375 / 768 / 1440 px; no horizontal scroll on mobile.
- [ ] Dark + light (`prefers-color-scheme`) both look right.
- [ ] Lighthouse perf & a11y ≥ 95; images lazy-loaded; no CLS.
- [ ] Keyboard navigable; `prefers-reduced-motion` honored.
- [ ] No third-party tracker loaded by default.

## Maintenance (later)

- New app version → the download link is version-less and **does not change**;
  just refresh the screenshots/copy if the UI changed.
- Screenshots/feature copy live in the macsist repo; re-pull when it updates.
- If localizing, mirror the repo's `README.<lang>.md` set and add a language
  switcher (SPEC §9).
