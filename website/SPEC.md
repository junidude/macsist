# Macsist — Marketing / Download Site SPEC

> This is the **source of truth** for the Macsist website. It is written to be
> self-contained: an agent building the site on a fresh server does **not** need
> the app source to follow it. The canonical product copy lives in the public
> repo's README (`https://github.com/junidude/macsist`) — pull wording/features
> from there; never invent features.

## 1. Purpose & audience

A single landing page whose only job is to **explain Macsist and get people to
install it**, via two paths:

1. **Download the app** — a one-file `.dmg` for non-technical macOS users.
2. **Install from source** — `git clone … && ./install.sh` for developers who
   want the full local-model stack.

Audience: macOS power users, developers, researchers, students — people who read
dense text / foreign-language material / papers and want instant local
explanations.

## 2. What Macsist is (one paragraph — safe to paraphrase)

Macsist is a **native macOS menu-bar assistant** that explains anything you
select — instantly, locally, in your language. Press a hotkey to get a concise,
streamed explanation of the **selected text** (any app) or a **screen region**
you drag-select, in a floating glass panel by the cursor. It runs on a **local**
MLX model or any OpenAI-compatible API. No cloud required, no Electron, private
by default. Requires **macOS 26.2+ on Apple Silicon**.

## 3. Goals / non-goals

- **Goals:** communicate value in <10s; make both install paths obvious; set
  correct expectations about the self-signed first-open step; look as polished
  as the product (glassy, dark, calm).
- **Non-goals:** no account/login, no payment, no backend, no blog/CMS. Static
  site only. No tracking that compromises the "private by default" promise.

## 4. Page structure (single page, anchored sections)

1. **Hero** — app icon, name "Macsist", one-line tagline, two primary buttons
   (**Download for macOS** / **Install via Terminal**), small "macOS 26.2+ ·
   Apple Silicon" line.
2. **In action** — the two product screenshots with one-line captions
   (text-explain, region-explain).
3. **Features** — 6–8 cards/bullets pulled from the README feature list (text
   explain, region explain, follow-up chat, 6 languages, glass panel +
   drag-to-move, history, bring-your-own model, private/local-first).
4. **Download** — the two paths side by side:
   - **macOS app:** the Download button + the **First-open note** (§6, must be
     impossible to miss).
   - **From source:** the clone+install one-liner in a copy-able code block.
5. **How it works** — 2–3 sentences + the tiny proxy diagram (optional), link to
   the repo for depth.
6. **FAQ** — Is it private? (yes, local-first) · Do I need a GPU/API key?
   (local model or external API) · Why the security warning? (self-signed —
   see first-open) · Which Macs? (Apple Silicon, macOS 26.2+).
7. **Footer** — link to GitHub repo, license, "Built with MLX + PyObjC".

## 5. The two install paths (exact, do not alter)

- **Download (stable link, never changes across versions):**
  `https://github.com/junidude/macsist/releases/latest/download/Macsist.dmg`
- **From source:**
  ```bash
  git clone https://github.com/junidude/macsist.git
  cd macsist && ./install.sh
  ```
- Repo: `https://github.com/junidude/macsist` (public).

## 6. First-open note (CRITICAL — the build is self-signed, NOT notarized)

The DMG is signed with a self-signed certificate, **not** notarized by Apple, so
Gatekeeper blocks the first launch. The site MUST show this clearly near the
Download button (a callout, or a step list that appears after clicking
Download). Exact instructions to surface:

> **First time you open it:** macOS will say it can't verify the developer.
> 1. Drag **Macsist** into **Applications**.
> 2. In Applications, **right-click Macsist → Open → Open**.
> 3. If macOS still refuses ("damaged" / "can't be opened"), run once in
>    Terminal, then open again:
>    ```
>    xattr -dr com.apple.quarantine /Applications/Macsist.app
>    ```

Do not hide this — a surprised user who hits "damaged" with no explanation will
assume the app is broken.

## 7. After install (set expectation, 1 line)

On first launch Macsist asks how to connect: an **external OpenAI-compatible
API** (paste a key — works instantly) or a **local model** (guided server
install). Then grant Accessibility (and Screen Recording for region capture).

## 8. Assets (all in the public repo — fetch via raw URL or vendor a copy)

- **App icon:** `app/assets/macsist-1024.png`
  (`https://raw.githubusercontent.com/junidude/macsist/main/app/assets/macsist-1024.png`)
- **Screenshot — text explain:** `assets/HotKeyEx-test.png`
- **Screenshot — region explain:** `assets/HotKeyEx-image-2.png`
- Prefer vendoring optimized copies into the site (WebP/AVIF, lazy-loaded) over
  hot-linking, for performance and stability.

## 9. Localization (optional, nice-to-have)

The product ships in **6 languages** (ko/en/zh/ja/fr/de) and the repo has a full
translated README per language (`README.ko.md`, `README.zh.md`, …) — use those
as the translation source if you localize the site. English is the default. A
simple top-right language switcher mirroring the README set is enough; don't
block launch on full localization.

## 10. Visual direction

- Match the product: **dark**, calm, glassy. The icon is a dark rounded square
  with a warm cream/peach card + a spark — pull the accent from it (soft
  orange/peach on near-black). Generous whitespace, large type, subtle blur.
- Responsive (looks right on phones), respects `prefers-color-scheme`,
  accessible contrast, keyboard-navigable, reduced-motion friendly.

## 11. Tech constraints

- **Static output only** — must deploy as plain files behind any web server
  (nginx/Caddy/Vercel/Netlify/GitHub Pages). Self-hosted on the owner's server.
- No server-side code, no database. Any framework is fine **as long as it builds
  to static** (plain HTML/CSS, Astro, Eleventy, Next static export, etc.).
  Default recommendation: the lightest thing that ships — plain HTML/CSS or
  Astro.
- Privacy-friendly: no third-party trackers by default. If analytics are
  wanted, use a privacy-respecting, cookieless option.

## 12. Success criteria

- The two CTAs are visible without scrolling on desktop.
- The download link resolves to the latest DMG.
- The first-open instructions are visible to anyone who downloads.
- Lighthouse: performance & accessibility ≥ 95, no layout shift.
- Builds to static files and serves from the owner's server with one deploy
  command (documented in AGENT.md).
