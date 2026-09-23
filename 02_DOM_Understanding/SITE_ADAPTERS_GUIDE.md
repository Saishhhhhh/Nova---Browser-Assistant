# Browser Grounding Agent: Site Adapters & 6-Tier Architecture Guide

## Overview

The Browser Grounding Agent uses a **Six-Tier Action Pipeline** designed to make browser interactions as fast and robust as possible. Instead of sending raw, bloated DOM snapshots to a Small Language Model (SLM) for every interaction, the system cascades through deterministic fast-paths first.

For the **14 priority websites**, common interactions (searching, playing videos, toggling fullscreen, navigating to cart/inbox, adding to cart) execute in **0 to 50 milliseconds** with **zero SLM token generation**.

---

## The Six-Tier Architecture

```
Voice Command
      │
      ▼
┌─────────────────────────────────────────────┐
│ TIER 0: Physical Controls                   │  0ms latency
│ (Regex match: scroll, reload, back, forward)│  Zero DOM, zero SLM, zero network
└────────┬────────────────────────────────────┘
         │ not matched
         ▼
┌─────────────────────────────────────────────┐
│ TIER 0.5: Site-Specific Adapters            │  0-50ms latency
│ (14 priority domains + Cross-Site Router)   │  URL direct nav, keyboard shortcuts, direct CSS
└────────┬────────────────────────────────────┘
         │ not matched
         ▼
┌─────────────────────────────────────────────┐
│ TIER 1: Deterministic Intent Router         │  <5ms latency
│ (Search bar focus vs type, aria-labels)     │  DOM element structure, zero SLM
└────────┬────────────────────────────────────┘
         │ not matched
         ▼
┌─────────────────────────────────────────────┐
│ TIER 2: Specific Action Keywords            │  <5ms latency
│ (Add to cart, checkout, sign-in keywords)   │  DOM keyword scan, zero SLM
└────────┬────────────────────────────────────┘
         │ not matched
         ▼
┌─────────────────────────────────────────────┐
│ TIER 3: Constraint Filter                   │  <50ms latency
│ (Cheapest, nonstop, time filters)           │  SLM intent extraction → Python filter/sort
└────────┬────────────────────────────────────┘
         │ not matched
         ▼
┌─────────────────────────────────────────────┐
│ TIER 4: SLM Grounding Fallback              │  200-800ms latency
│ (Compact viewport-only DOM representation)  │  Grammar-constrained action JSON
└──────────────────────────────────────────────┘
```

---

## 14 Priority Site Adapters Reference

### 1. 🔴 YouTube (`youtube.com`, `youtu.be`)
- **Search**: `"search (for) X"` → navigates to `https://www.youtube.com/results?search_query={X}`
- **Playback**:
  - `"play"` / `"pause"` / `"resume"` / `"stop"` → focuses player, presses `k`
  - `"fullscreen"` / `"minimize"` → presses `f`
  - `"theater mode"` → presses `t`
  - `"mute"` / `"unmute"` → presses `m`
  - `"skip forward"` / `"skip ahead"` → presses `l` (+10s)
  - `"skip back"` / `"rewind"` → presses `j` (-10s)
  - `"volume up"` / `"volume down"` → presses `ArrowUp` / `ArrowDown` ×3
  - `"captions"` / `"subtitles"` → presses `c`
  - `"speed up"` / `"slow down"` → presses `Shift+.` / `Shift+,`
  - `"next video"` / `"previous video"` → presses `Shift+N` / `Shift+P`
  - `"miniplayer"` → presses `i`
- **Actions**:
  - `"like"` / `"like video"` → clicks `like-button-view-model button, button#like-button`
  - `"subscribe"` → clicks `ytd-subscribe-button-renderer button`
- **Navigation**:
  - `"go to home"` → `https://www.youtube.com`
  - `"subscriptions"` → `https://www.youtube.com/feed/subscriptions`

---

### 2. 🟠 Amazon (`amazon.in`, `amazon.com`, `amazon.co.uk`, etc.)
- **Search**: `"search (for) X"` → navigates to `https://www.{domain}/s?k={X}`
- **Purchase Actions**:
  - `"add to cart"` → clicks `#add-to-cart-button`
  - `"buy now"` → clicks `#buy-now-button`
  - `"checkout"` → clicks `#sc-buy-box-ptc-button`
- **Navigation**:
  - `"go to cart"` / `"view cart"` → `https://www.{domain}/gp/cart/view.html`
  - `"my orders"` → `https://www.{domain}/gp/css/order-history`
  - `"my wishlist"` → `https://www.{domain}/hz/wishlist/ls`
  - `"sign in"` → `https://www.{domain}/ap/signin`
  - `"go to home"` → `https://www.{domain}`

---

### 3. 🟡 Flipkart (`flipkart.com`)
- **Search**: `"search (for) X"` → navigates to `https://www.flipkart.com/search?q={X}`
- **Actions**:
  - `"add to cart"` → clicks `button:has-text('ADD TO CART')`
  - `"buy now"` → clicks `button:has-text('BUY NOW')`
- **Navigation**:
  - `"go to cart"` → `https://www.flipkart.com/viewcart`
  - `"my orders"` → `https://www.flipkart.com/account/orders`
  - `"go to home"` → `https://www.flipkart.com`

---

### 4. 🟢 Reddit (`reddit.com`, `old.reddit.com`)
- **Subreddit Nav**: `"go to r/{subreddit}"` → `https://www.reddit.com/r/{subreddit}/`
- **Search**: `"search (for) X"` → `https://www.reddit.com/search/?q={X}`
- **Keyboard Shortcuts**:
  - `"next post"` → presses `j`
  - `"previous post"` → presses `k`
  - `"upvote"` → presses `a`
  - `"downvote"` → presses `z`
  - `"open post"` / `"expand"` → presses `Enter`
  - `"save post"` → presses `s`
  - `"reply"` → presses `r`
  - `"new post"` → presses `c`

---

### 5. 🔵 Gmail (`mail.google.com`)
- **Enable Shortcuts**: `"enable gmail shortcuts"` → presses `?` to open Gmail shortcuts dialog
- **Search**: `"search (for) X"` → `https://mail.google.com/mail/u/0/#search/{X}`
- **Compose**: `"compose"` / `"new email"` → clicks `div[role='button'][gh='cm']`
- **Navigation**:
  - `"inbox"` → `https://mail.google.com/mail/u/0/#inbox`
  - `"sent"` → `https://mail.google.com/mail/u/0/#sent`
  - `"drafts"` → `https://mail.google.com/mail/u/0/#drafts`
  - `"starred"` → `https://mail.google.com/mail/u/0/#starred`
  - `"trash"` → `https://mail.google.com/mail/u/0/#trash`
- **Keyboard Shortcuts**:
  - `"reply"` → presses `r`
  - `"reply all"` → presses `a`
  - `"forward"` → presses `f`
  - `"archive"` → presses `e`
  - `"delete email"` → presses `#`
  - `"send"` → presses `Control+Enter`
  - `"next email"` / `"previous email"` → presses `j` / `k`

---

### 6. 🟣 Google Search (`google.com`, `google.co.in`, etc.)
- **Search**: `"search (for) X"` / `"google X"` → `https://www.google.com/search?q={X}`
- **Tabs**:
  - `"images"` / `"image search"` → `https://www.google.com/search?q={current_query}&tbm=isch`
  - `"news"` → `https://www.google.com/search?q={current_query}&tbm=nws`
  - `"videos"` → `https://www.google.com/search?q={current_query}&tbm=vid`
- **Results**:
  - `"first result"` / `"open first result"` → clicks `#search a:first-of-type, div.g a:first-of-type`
  - `"next page"` → clicks `#pnnext`

---

### 7. ⬛ GitHub (`github.com`)
- **Search**: `"search (for) X"` → `https://github.com/search?q={X}`
- **Repo Navigation**:
  - `"issues"` → navigates to `{current_repo}/issues`
  - `"pull requests"` / `"prs"` → navigates to `{current_repo}/pulls`
  - `"notifications"` → `https://github.com/notifications`
- **Shortcuts**:
  - `"file finder"` → presses `t`
  - `"command palette"` → presses `Control+k`
  - `"open in editor"` → presses `.` (launches github.dev)

---

### 8. 🔷 LinkedIn (`linkedin.com`)
- **Search**: `"search (for) X"` → `https://www.linkedin.com/search/results/all/?keywords={X}`
- **Jobs**: `"search jobs {X}"` → `https://www.linkedin.com/jobs/search/?keywords={X}`
- **Navigation**:
  - `"feed"` / `"home"` → `https://www.linkedin.com/feed/`
  - `"messages"` → `https://www.linkedin.com/messaging/`
  - `"notifications"` → `https://www.linkedin.com/notifications/`
  - `"my profile"` → `https://www.linkedin.com/in/me/`
  - `"my network"` → `https://www.linkedin.com/mynetwork/`

---

### 9. 📸 Instagram (`instagram.com`)
- **Profiles**: `"go to profile {username}"` / `"open @{username}"` → `https://www.instagram.com/{username}/`
- **Navigation**:
  - `"reels"` → `https://www.instagram.com/reels/`
  - `"explore"` → `https://www.instagram.com/explore/`
  - `"direct"` / `"messages"` → `https://www.instagram.com/direct/inbox/`
  - `"home"` → `https://www.instagram.com/`

---

### 10, 11, 12. 🤖 AI Chat Assistants (ChatGPT, Claude, Gemini)
- **ChatGPT** (`chatgpt.com`):
  - `"new chat"` → `https://chatgpt.com/`
  - `"ask {question}"` / `"type {prompt}"` → types into `#prompt-textarea`, presses `Enter`
- **Claude** (`claude.ai`):
  - `"new chat"` → `https://claude.ai/new`
  - `"ask {question}"` → types into `div[contenteditable='true']`, presses `Enter`
- **Gemini** (`gemini.google.com`):
  - `"new chat"` → `https://gemini.google.com/app`
  - `"ask {question}"` → types into `rich-textarea, textarea`, presses `Enter`

---

### 13 & 14. 🎬 Cinejoy & 🎌 GoGoAnime (Dynamic Google Search Routing)
Because streaming domain extensions rotate frequently (e.g. `.lol`, `.to`, `.pe`, `.gr`), navigation and searches are automatically routed via Google Search:
- **Cinejoy**:
  - `"search for {movie} on cinejoy"` → `https://www.google.com/search?q=cinejoy+{movie}`
  - `"open cinejoy"` → `https://www.google.com/search?q=cinejoy+movies&btnI=1`
  - `"play"` / `"pause"` → presses `Space` on player
  - `"fullscreen"` → presses `f`
- **GoGoAnime**:
  - `"search for {anime} on gogoanime"` → `https://www.google.com/search?q=gogoanime+{anime}`
  - `"open gogoanime"` → `https://www.google.com/search?q=gogoanime+watch+anime&btnI=1`
  - `"next episode"` → clicks `.anime_video_body_episodes_r a`
  - `"previous episode"` → clicks `.anime_video_body_episodes_l a`

---

## Cross-Site Global Router
From **any** tab or URL, cross-site commands route immediately without requiring prior navigation:
- *"search 24 inch monitor on amazon"* → instantly opens Amazon search
- *"watch interstellar on cinejoy"* → instantly routes Cinejoy search via Google
- *"watch naruto on gogoanime"* → instantly routes GoGoAnime search via Google
- *"open youtube"* / *"open gmail"* / *"open chatgpt"* → opens target site directly

---

## Core Pipeline Enhancements

### Deep Shadow DOM Piercing
`context_aware_json.py` recursively traverses all open `shadowRoot` elements up to 350 interactive nodes. This unlocks custom Web Components used heavily on YouTube (`<ytd-app>`, `<ytd-player>`), Gmail, and Lit/Polymer applications.

### Multi-Property Visibility Checks
Replaced naive `style.display` checks with:
1. `offsetParent` pre-filtering (catches parent container `display:none`)
2. `el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})`
3. `aria-hidden="true"` filtering
4. Bounding client rectangle dimensions (`width >= 2`, `height >= 2`)

### Deterministic Tier-1 Intent Router (`pipeline/intent_router.py`)
- Distinguishes meta-referents: *"click on the search bar"* focuses the input; *"search for mechanical keyboard"* types into it and submits.
- Direct button matching by exact or substring text.
- Media controls mapped via `aria-label`.

### SPA-Safe DOM Stability & Action Safety
- Replaced fragile `framenavigated` races with `domcontentloaded` wait + MutationObserver quiescence + execution context recovery.
- Pre-action editability checks ensure non-editable elements (like `<a>` or hidden `<select>` tags) are not targeted with `.fill()`, preventing 30-second Playwright freezes.

---

## How to Run

### 1. Interactive Demo
Run the live interactive agent where you can type commands or test any site:
```bash
python interactive_demo.py
```

### 2. Automated Visual Tour (Watch All Sites Tested in Live Chrome)
Run the visual tour script to see the agent test priority sites in a live visible Chrome window:
```bash
python visual_live_tour.py
```

### 3. Unit / Smoke Test Suite
Run the headless validation suite:
```bash
python test_adapters_and_intents.py
```
