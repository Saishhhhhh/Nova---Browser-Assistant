"""Part B of Experiment 8: do position hints pick the element a person would point at?

  python position_bench.py            # real pages, no model calls, nothing is clicked (free)

Loads three pages at a fixed 1280x800 window, reads the page with the router's own page reader, and for each
spoken target asks the position resolver which element it would click. Compared with what a person pointing
at the screen would mean (written down from looking at the pages, see EXPECT below).
"""
import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "02_Reasoning_and_Routing"))

from browser_use import Browser  # noqa: E402
from browser_use.browser.events import NavigateToUrlEvent  # noqa: E402
from dom_fastpath import FastPath, norm  # noqa: E402
from position_hints import parse_position, resolve_position  # noqa: E402

# (page, spoken target, expected: ("label", text) or ("href", text) that the chosen element must contain)
BOOKS, QUOTES, WIKI = "https://books.toscrape.com", "https://quotes.toscrape.com", "https://en.wikipedia.org/wiki/Alan_Turing"
EXPECT = [
    (BOOKS, "the first book", ("href", "a-light-in-the-attic")),
    (BOOKS, "the second book", ("href", "tipping-the-velvet")),
    (BOOKS, "the last book", ("href", "sharp-objects")),
    (BOOKS, "the link at the top left", ("label", "books to scrape")),
    (BOOKS, "the third result", ("href", "soumission")),
    (QUOTES, "the link at the top right", ("label", "login")),
    (QUOTES, "the top left link", ("label", "quotes to scrape")),
    (QUOTES, "the third link", ("label", "love")),
    (QUOTES, "the login link at the top right", ("label", "login")),
    (QUOTES, "the last link", ("label", "humor")),
    (WIKI, "the link at the top left", ("href", "main_page")),
    (WIKI, "the top right link", ("label", "log in")),
    (WIKI, "the button at the top", ("label", "search")),
    (WIKI, "the field at the top", ("label", "search wikipedia")),
    (WIKI, "the second link", ("label", "donate")),
    # the right answer is to refuse (nothing on the page matches), never to guess
    (WIKI, "the sign in link at the top right", ("refuse", "")),   # the page says "Log in", not "sign in"
    (BOOKS, "the button at the bottom right", ("label", "add to basket")),   # the book cards have buttons
    (QUOTES, "the second button", ("refuse", "")),                 # no buttons on this page
    (WIKI, "the twelfth link on the left", ("refuse", "")),        # "twelfth" is not an ordinal it knows
]


async def main() -> int:
    b = Browser(headless=True, keep_alive=True, window_size={"width": 1280, "height": 800},
                viewport={"width": 1280, "height": 800})
    await b.start()
    fp = FastPath(b, picker=None)
    rows, current = [], None
    for page, target, (field, want) in EXPECT:
        if page != current:
            await b.event_bus.dispatch(NavigateToUrlEvent(url=page))
            await asyncio.sleep(3)
            elements = await fp._read_page()
            current = page
        hint = parse_position(target)
        if hint is None:
            rows.append({"page": page, "target": target, "ok": field == "refuse", "got": "(not read as a position phrase)", "note": ""})
            continue
        e, note = resolve_position(elements, hint, fp.viewport)
        if e is None:
            rows.append({"page": page, "target": target, "ok": field == "refuse", "got": f"(refused: {note})", "note": note})
            continue
        if field == "refuse":
            rows.append({"page": page, "target": target, "ok": False, "got": f"WRONG, picked {e.tag} '{(e.labels or [''])[0][:30]}'", "note": note})
            continue
        label = (e.labels[0] if e.labels else "")
        href = (e.attrs.get("href") or "").lower()
        ok = want in (norm(label) if field == "label" else href) or any(want in norm(l) for l in e.labels)
        rows.append({"page": page, "target": target, "ok": ok, "got": f"{e.tag} '{label[:30]}' {href[-40:]}", "note": note,
                     "expected": f"{field} contains '{want}'"})
    await b.kill()
    good = sum(r["ok"] for r in rows)
    for r in rows:
        print(f"[{'OK ' if r['ok'] else 'BAD'}] {r['page'].split('//')[1][:22]:<22} {r['target']:<36} -> {r['got'][:62]:<62} {r['note']}")
    print(f"\n{good} of {len(rows)} resolved to the expected element")
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "position_bench.json").write_text(json.dumps({"correct": good, "total": len(rows), "rows": rows},
                                                                     indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
