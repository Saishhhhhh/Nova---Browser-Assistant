"""Position hints: "click the second result", "the link at the top left", "the last button".

No model. A spoken target is split into (corner/edge, ordinal, kind, label words), and resolved against the
elements the page reader already knows, using their on-screen positions.

    hint = parse_position("the second link at the top")
    element, note = resolve_position(elements, hint, viewport)      # viewport = (scroll_x, scroll_y, width, height)

Only what is on screen right now counts: "first / last" means the first / last one you can see, not on the
whole page, because that is what a person pointing at the screen means.
"""
import re
from dataclasses import dataclass
from typing import Optional

ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
    "ninth": 9, "tenth": 10, "last": -1, "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6,
    "7th": 7, "8th": 8, "9th": 9, "10th": 10,
}
KINDS = {
    "button": "button", "buttons": "button", "link": "link", "links": "link",
    "field": "field", "fields": "field", "input": "field", "inputs": "field", "textbox": "field", "searchbox": "field",
    "tab": "tab", "tabs": "tab", "image": "image", "images": "image", "picture": "image", "photo": "image",
    "thumbnail": "image", "icon": "image",
}
ITEM_WORDS = {
    "result", "results", "item", "items", "product", "products", "book", "books", "video", "videos", "post", "posts",
    "story", "stories", "article", "articles", "card", "cards", "listing", "listings", "entry", "entries", "option",
    "options", "choice", "choices", "one", "ones", "thing", "issue", "issues",
}
# What the address of a link to that kind of thing usually looks like. Used to prefer "the first video" over a channel
# card, or "the second product" over a footer link. A general lexicon, not per-site code; if nothing matches it is ignored.
NOUN_URL_HINTS = {
    "video": ("watch", "/video", "/v/", "/shorts"), "videos": ("watch", "/video", "/v/", "/shorts"),
    "product": ("/p/", "/dp/", "/product", "/item", "/itm", "/gp/"), "products": ("/p/", "/dp/", "/product", "/item", "/itm", "/gp/"),
    "post": ("/comments/", "/post", "/status/"), "posts": ("/comments/", "/post", "/status/"),
    "issue": ("/issues/",), "issues": ("/issues/",),
    "article": ("/article", "/wiki/", "/news/"), "articles": ("/article", "/wiki/", "/news/"),
}
EDGES = {"top", "bottom", "left", "right", "middle", "center"}
FILLER = {"the", "a", "an", "at", "in", "on", "of", "to", "corner", "side", "part", "page", "screen", "hand", "area",
          "region", "very", "most", "from", "near", "bit", "that", "is", "it", "this", "there", "one"}
PHRASAL = {"in", "out", "up", "on", "off"}
CLICKABLE_INPUT_TYPES = {"submit", "button", "image", "reset", "checkbox", "radio"}


@dataclass
class PositionHint:
    corner: str = ""            # "top left", "bottom right", "top", "left", "center", or ""
    ordinal: int = 0            # 1.. or -1 for "last", 0 for none
    kind: str = ""              # button | link | field | tab | image | item | "" (any clickable)
    label: str = ""             # leftover words, e.g. "sign in" in "the sign in button at the top right"
    noun: str = ""              # the thing named for kind "item": video, product, result, ...


def _tokens(text: str) -> list:
    t = (text or "").lower().replace("’", "").replace("'", "")
    t = t.replace("text box", "textbox").replace("search box", "searchbox").replace("upper", "top").replace("lower", "bottom")
    t = t.replace("centre", "center").replace("-", " ")
    return re.sub(r"[^a-z0-9 ]+", " ", t).split()


def parse_position(target: str) -> Optional[PositionHint]:
    """A PositionHint if the target talks about where something is or which one of several; else None."""
    toks = _tokens(target)
    if not toks:
        return None
    hint = PositionHint()
    used = set()
    # corner or edge: "top left", "top right corner", "bottom", "left"
    for i, w in enumerate(toks):
        if w in ("top", "bottom"):
            nxt = next((j for j in range(i + 1, min(i + 3, len(toks))) if toks[j] in ("left", "right")), None)
            if nxt is not None and all(toks[k] in FILLER for k in range(i + 1, nxt)):
                hint.corner = f"{w} {toks[nxt]}"
                used |= {i, nxt}
                break
    if not hint.corner:
        for i, w in enumerate(toks):
            if w in EDGES:
                hint.corner = w
                used.add(i)
                break
    for i, w in enumerate(toks):
        if w in ORDINALS and i not in used:
            hint.ordinal = ORDINALS[w]
            used.add(i)
            break
    for i, w in enumerate(toks):
        if i in used:
            continue
        if w in KINDS:
            hint.kind = KINDS[w]
            used.add(i)
            break
    if not hint.kind:
        for i, w in enumerate(toks):
            if i not in used and w in ITEM_WORDS and w != "one":
                hint.kind = "item"
                hint.noun = w
                used.add(i)
                break
    if not hint.corner and not hint.ordinal:
        return None
    rest = [w for i, w in enumerate(toks) if i not in used]
    skip = FILLER | ITEM_WORDS | set(KINDS)
    while rest and rest[0] in skip:         # trim filler at the edges only, so "sign in" keeps its "in"
        rest.pop(0)
    while rest and rest[-1] in skip:
        if rest[-1] in PHRASAL and len(rest) >= 2 and rest[-2] not in skip:
            break                            # "sign in", "log out", "sign up": the last word belongs to the label
        rest.pop()
    hint.label = " ".join(rest)
    return hint


def _kind_ok(e, kind: str) -> bool:
    if kind == "button":
        return e.tag == "button" or e.role == "button" or (e.tag == "input" and e.input_type in CLICKABLE_INPUT_TYPES)
    if kind == "link":
        return e.tag == "a" or e.role == "link"
    if kind == "field":
        return e.is_text_input
    if kind == "tab":
        return e.role == "tab"
    if kind == "image":
        return e.tag == "img" or e.role == "img"
    if kind == "item":
        # a result has a visible title: icon-only links (upvote arrows, "hide", avatars) are not what "the first story" means
        return (e.tag == "a" or e.role == "link") and not e.in_chrome and any(len(l) >= 2 for l in e.labels)
    return e.is_actionable or e.is_text_input


def resolve_position(elements: list, hint: PositionHint, viewport: Optional[tuple]):
    """-> (element, note) or (None, why). `viewport` is (scroll_x, scroll_y, width, height)."""
    sx, sy, vw, vh = viewport or (0.0, 0.0, 1280.0, 800.0)
    pool = []
    seen = set()
    for e in elements:
        if not e.box or not _kind_ok(e, hint.kind):
            continue
        x, y, w, h = e.box
        cx, cy = x + w / 2 - sx, y + h / 2 - sy
        if w < 2 or h < 2 or not (0 <= cx <= vw and 0 <= cy <= vh):
            continue                       # not on screen right now
        key = (e.attrs.get("href") or "", round(cx / 8), round(cy / 8)) if e.tag == "a" else (e.index,)
        if hint.kind == "item" and e.attrs.get("href"):
            key = (e.attrs.get("href"),)   # the picture and the title of one result are one result
        if key in seen:
            continue
        seen.add(key)
        pool.append((e, cx, cy))
    if hint.kind == "button" and not pool:  # no real <button>: allow links styled as buttons
        for e in elements:
            cls = (e.attrs.get("class") or "").lower()
            if e.box and e.tag == "a" and ("btn" in cls or "button" in cls):
                x, y, w, h = e.box
                cx, cy = x + w / 2 - sx, y + h / 2 - sy
                if 0 <= cx <= vw and 0 <= cy <= vh:
                    pool.append((e, cx, cy))
    dense_ok = False
    if hint.kind == "item" and hint.noun in NOUN_URL_HINTS:
        wanted = NOUN_URL_HINTS[hint.noun]
        preferred = [it for it in pool if any(h in (it[0].attrs.get("href") or "").lower() for h in wanted)]
        if preferred:
            pool = preferred
            dense_ok = True
    if hint.kind == "item" and len(pool) >= 15 and not dense_ok:
        # a feed or results list full of look-alike links, and nothing about the address says which are the real items:
        # picking by position would often hit a domain link, a comment count or a suggestion chip. Let the model step choose.
        return None, f"{len(pool)} look-alike links on screen, not sure which are the {hint.noun}s"
    if hint.label:
        from .dom_fastpath import _best_label_score, norm, strip_generic_words
        q = strip_generic_words(norm(hint.label))
        pool = [(e, cx, cy) for e, cx, cy in pool if _best_label_score(q, e, 0.85) >= 0.6]
    if not pool:
        what = hint.kind or "clickable element"
        return None, f"no {what} on screen" + (f" matching '{hint.label}'" if hint.label else "")

    def corner_metric(item):
        _, cx, cy = item
        c = hint.corner
        if c == "top left":
            return cx * cx + cy * cy
        if c == "top right":
            return (vw - cx) ** 2 + cy * cy
        if c == "bottom left":
            return cx * cx + (vh - cy) ** 2
        if c == "bottom right":
            return (vw - cx) ** 2 + (vh - cy) ** 2
        if c == "top":
            return cy
        if c == "bottom":
            return -cy
        if c == "left":
            return cx
        if c == "right":
            return -cx
        return (cx - vw / 2) ** 2 + (cy - vh / 2) ** 2   # center / middle

    if hint.corner:
        pool.sort(key=corner_metric)
    else:
        pool.sort(key=lambda it: (round(it[2] / 12), it[1]))   # reading order: rows top to bottom, then left to right
    if hint.ordinal:
        n = hint.ordinal
        if n == -1:
            chosen = pool[-1]
            note = f"last of {len(pool)} on screen"
        elif n <= len(pool):
            chosen = pool[n - 1]
            note = f"{n} of {len(pool)} on screen"
        else:
            return None, f"only {len(pool)} on screen, asked for number {n}"
    else:
        chosen = pool[0]
        note = f"nearest to {hint.corner} of {len(pool)} on screen"
    return chosen[0], note
