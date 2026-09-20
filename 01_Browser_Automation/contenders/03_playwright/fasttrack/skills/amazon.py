"""
Fast-Track Amazon Product & Price Filter Skill.
Implements direct parameterized search URL formulation and sub-30ms in-memory product extraction.
"""

import urllib.parse
from typing import Dict, Any, List
from ..engine import FastPlaywrightEngine


SORT_CODES = {
    "price_low_to_high": "price-asc-rank",
    "price_high_to_low": "price-desc-rank",
    "customer_reviews": "review-rank",
    "featured": "exact-aware-popularity-rank"
}


class AmazonSkill:
    def __init__(self, engine: FastPlaywrightEngine, domain: str = "amazon.in"):
        self.engine = engine
        self.domain = domain

    async def search_and_sort(self, query: str, sort_by: str = "price_low_to_high") -> float:
        """Navigates directly to sorted search results, bypassing form typing & dropdown clicks."""
        sort_param = SORT_CODES.get(sort_by, "price-asc-rank")
        encoded_query = urllib.parse.quote(query)
        target_url = f"https://www.{self.domain}/s?k={encoded_query}&s={sort_param}"

        await self.engine.notify_action(f"Amazon: Search '{query}' ({sort_by})")
        nav_ms = await self.engine.navigate_direct(target_url)
        return nav_ms

    async def extract_top_products(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Evaluates in-memory JS to extract clean structured product data in <30ms."""
        # Wait for product grid
        try:
            await self.engine.page.wait_for_selector(
                "div[data-component-type='s-search-result']",
                state="visible",
                timeout=8000
            )
        except Exception:
            pass

        products = await self.engine.evaluate_js(f"""
            (() => {{
                const cards = Array.from(document.querySelectorAll("div[data-component-type='s-search-result']"));
                const results = [];
                for (const card of cards) {{
                    if (results.length >= {limit}) break;
                    
                    const titleEl = card.querySelector("h2 a span, h2 span");
                    const priceWhole = card.querySelector(".a-price-whole");
                    const priceFraction = card.querySelector(".a-price-fraction");
                    const ratingEl = card.querySelector(".a-icon-alt");
                    const linkEl = card.querySelector("h2 a");

                    if (titleEl && priceWhole) {{
                        const price = '₹' + priceWhole.textContent.replace(/[.,]/g, '') + (priceFraction ? '.' + priceFraction.textContent : '');
                        results.push({{
                            title: titleEl.textContent.trim(),
                            price: price,
                            rating: ratingEl ? ratingEl.textContent.trim() : 'N/A',
                            asin: card.getAttribute('data-asin') || '',
                            link: linkEl ? linkEl.href : ''
                        }});
                    }}
                }}
                return results;
            }})()
        """)

        # Visually highlight top product on screen
        await self.engine.highlight_element("div[data-component-type='s-search-result']")
        return products or []

    async def click_product(self, index: int = 1):
        """Visually highlights and clicks product by 1-based index."""
        selector = f"div[data-component-type='s-search-result']:nth-of-type({index}) h2 a"
        return await self.engine.click_with_visual(selector, f"Opening Product #{index}")
