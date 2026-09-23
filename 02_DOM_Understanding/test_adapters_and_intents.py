import sys
import asyncio
from typing import Dict, Any

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from pipeline.site_adapters import get_adapter, match_cross_site_intent, ALL_ADAPTERS
from pipeline.site_adapters.youtube import YouTubeAdapter
from pipeline.site_adapters.amazon import AmazonAdapter
from pipeline.site_adapters.flipkart import FlipkartAdapter
from pipeline.site_adapters.reddit import RedditAdapter
from pipeline.site_adapters.gmail import GmailAdapter
from pipeline.site_adapters.google_search import GoogleSearchAdapter
from pipeline.site_adapters.github import GitHubAdapter
from pipeline.site_adapters.linkedin import LinkedInAdapter
from pipeline.site_adapters.instagram import InstagramAdapter
from pipeline.site_adapters.chatgpt import ChatGPTAdapter
from pipeline.site_adapters.claude_ai import ClaudeAdapter
from pipeline.site_adapters.gemini import GeminiAdapter
from pipeline.site_adapters.cinejoy import CinejoyAdapter
from pipeline.site_adapters.gogoanime import GoGoAnimeAdapter
from pipeline.intent_router import match_tier1_intent, find_search_input


class MockPage:
    def __init__(self, url: str):
        self.url = url


async def run_tests():
    print("=" * 60)
    print("🧪 RUNNING BROWSER AGENT V2 ARCHITECTURAL TEST SUITE")
    print("=" * 60)

    # 1. YouTube Adapter Tests
    yt = YouTubeAdapter()
    assert yt.matches("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    res = await yt.handle(MockPage("https://www.youtube.com"), "search for lofi hip hop")
    assert res and res["action"] == "url_navigate" and "lofi+hip+hop" in res["url"]
    
    res = await yt.handle(MockPage("https://www.youtube.com/watch?v=123"), "pause")
    assert res and res["action"] == "keyboard" and res["key"] == "k"

    res = await yt.handle(MockPage("https://www.youtube.com/watch?v=123"), "fullscreen")
    assert res and res["action"] == "keyboard" and res["key"] == "f"
    print("✅ YouTube Adapter: search, pause, fullscreen passed!")

    # 2. Amazon Adapter Tests
    amz = AmazonAdapter()
    assert amz.matches("https://www.amazon.in/dp/B08N5WRWNW")
    res = await amz.handle(MockPage("https://www.amazon.in"), "search for 24 inch monitor")
    assert res and res["action"] == "url_navigate" and "24+inch+monitor" in res["url"]

    res = await amz.handle(MockPage("https://www.amazon.in/dp/123"), "add to cart")
    assert res and res["action"] == "click_selector" and "#add-to-cart-button" in res["selector"]

    res = await amz.handle(MockPage("https://www.amazon.in/dp/123"), "go to cart")
    assert res and res["action"] == "url_navigate" and "cart" in res["url"]
    print("✅ Amazon Adapter: search, add to cart, cart nav passed!")

    # 3. Flipkart Adapter Tests
    fk = FlipkartAdapter()
    assert fk.matches("https://www.flipkart.com/shoes")
    res = await fk.handle(MockPage("https://www.flipkart.com"), "search for running shoes")
    assert res and res["action"] == "url_navigate" and "running+shoes" in res["url"]
    print("✅ Flipkart Adapter: search passed!")

    # 4. Reddit Adapter Tests
    rd = RedditAdapter()
    assert rd.matches("https://www.reddit.com/r/programming")
    res = await rd.handle(MockPage("https://www.reddit.com"), "go to r/technology")
    assert res and res["action"] == "url_navigate" and "r/technology/" in res["url"]

    res = await rd.handle(MockPage("https://www.reddit.com/r/programming"), "next post")
    assert res and res["action"] == "keyboard" and res["key"] == "j"

    res = await rd.handle(MockPage("https://www.reddit.com/r/programming"), "upvote")
    assert res and res["action"] == "keyboard" and res["key"] == "a"
    print("✅ Reddit Adapter: subreddit nav, next post, upvote passed!")

    # 5. Gmail Adapter Tests
    gm = GmailAdapter()
    assert gm.matches("https://mail.google.com/mail/u/0/#inbox")
    res = await gm.handle(MockPage("https://mail.google.com"), "enable gmail shortcuts")
    assert res and res["action"] == "keyboard" and res["key"] == "?"

    res = await gm.handle(MockPage("https://mail.google.com"), "compose")
    assert res and res["action"] == "click_selector"

    res = await gm.handle(MockPage("https://mail.google.com"), "search for invoice")
    assert res and res["action"] == "url_navigate" and "invoice" in res["url"]

    res = await gm.handle(MockPage("https://mail.google.com"), "go to sent")
    assert res and res["action"] == "url_navigate" and "#sent" in res["url"]

    res = await gm.handle(MockPage("https://mail.google.com"), "reply")
    assert res and res["action"] == "keyboard" and res["key"] == "r"

    res = await gm.handle(MockPage("https://mail.google.com"), "send")
    assert res and res["action"] == "keyboard" and res["key"] == "Control+Enter"
    print("✅ Gmail Adapter: shortcut enable, compose, search, sent nav, reply, send passed!")

    # 6. Google Search Adapter Tests
    gs = GoogleSearchAdapter()
    assert gs.matches("https://www.google.com/search?q=test")
    res = await gs.handle(MockPage("https://www.google.com/search?q=test"), "images")
    assert res and res["action"] == "url_navigate" and "tbm=isch" in res["url"]

    res = await gs.handle(MockPage("https://www.google.com/search?q=test"), "first result")
    assert res and res["action"] == "click_selector"
    print("✅ Google Search Adapter: images tab, first result click passed!")

    # 7. GitHub Adapter Tests
    gh = GitHubAdapter()
    assert gh.matches("https://github.com/microsoft/playwright")
    res = await gh.handle(MockPage("https://github.com/microsoft/playwright"), "issues")
    assert res and res["action"] == "url_navigate" and "issues" in res["url"]

    res = await gh.handle(MockPage("https://github.com/microsoft/playwright"), "file finder")
    assert res and res["action"] == "keyboard" and res["key"] == "t"
    print("✅ GitHub Adapter: issues nav, file finder passed!")

    # 8. Cinejoy & GoGoAnime (via Google Search Routing) Tests
    cj = CinejoyAdapter()
    res = await cj.handle(MockPage("https://cinejoy.lol"), "search for interstellar")
    assert res and res["action"] == "url_navigate" and "google.com" in res["url"] and "cinejoy" in res["url"]

    ga = GoGoAnimeAdapter()
    res = await ga.handle(MockPage("https://gogoanime.pe"), "search for jujutsu kaisen")
    assert res and res["action"] == "url_navigate" and "google.com" in res["url"] and "gogoanime" in res["url"]
    print("✅ Cinejoy & GoGoAnime Adapters: Google search routing passed!")

    # 9. Cross-Site Intent Router Tests
    c_res = match_cross_site_intent("search 24 inch monitor on amazon")
    assert c_res and c_res["action"] == "url_navigate" and "amazon" in c_res["url"]

    c_res = match_cross_site_intent("watch Oppenheimer on cinejoy")
    assert c_res and c_res["action"] == "url_navigate" and "google.com" in c_res["url"] and "cinejoy" in c_res["url"]

    c_res = match_cross_site_intent("watch Naruto on gogoanime")
    assert c_res and c_res["action"] == "url_navigate" and "google.com" in c_res["url"] and "gogoanime" in c_res["url"]

    c_res = match_cross_site_intent("open chatgpt")
    assert c_res and c_res["action"] == "url_navigate" and "chatgpt.com" in c_res["url"]
    print("✅ Cross-Site Intent Router: Amazon, Cinejoy, GoGoAnime, ChatGPT routing passed!")

    # 10. Tier-1 Intent Router Tests
    mock_elements = [
        {"id": 1, "tag": "a", "role": "link", "text": "Home"},
        {"id": 2, "tag": "input", "role": "input", "semantic_role": "SEARCH_INPUT", "placeholder": "Search items..."},
        {"id": 3, "tag": "button", "role": "button", "text": "Submit Order"},
        {"id": 4, "tag": "button", "role": "button", "aria_label": "Play video"},
        {"id": 5, "tag": "input", "role": "input", "type": "text", "placeholder": "Your name"}
    ]

    t1_res = match_tier1_intent("click on the search bar", mock_elements)
    assert t1_res and t1_res["action"] == "click" and t1_res["target"] == 2

    t1_res = match_tier1_intent("search for mechanical keyboard", mock_elements)
    assert t1_res and t1_res["action"] == "type" and t1_res["target"] == 2 and t1_res["value"] == "mechanical keyboard"

    t1_res = match_tier1_intent("click Submit Order", mock_elements)
    assert t1_res and t1_res["action"] == "click" and t1_res["target"] == 3

    t1_res = match_tier1_intent("play", mock_elements)
    assert t1_res and t1_res["action"] == "click" and t1_res["target"] == 4
    print("✅ Tier-1 Intent Router: search bar focus, search typing, button text click, aria-label play passed!")

    print("\n🎉 ALL ARCHITECTURAL TESTS PASSED PERFECTLY (10/10)!")


if __name__ == "__main__":
    asyncio.run(run_tests())
