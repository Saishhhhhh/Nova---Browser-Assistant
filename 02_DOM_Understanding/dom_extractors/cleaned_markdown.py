"""
Representation C: Cleaned Text / Markdown Extractor.
Extracts visible text, headings, buttons, and form inputs as clean markdown.
"""

import time
from typing import Dict, Any, Tuple
from playwright.async_api import Page
from .base import BaseDOMExtractor


class CleanedMarkdownExtractor(BaseDOMExtractor):
    name = "cleaned_markdown"

    async def extract(self, page: Page) -> Tuple[str, Dict[str, Any]]:
        t0 = time.perf_counter_ns()
        
        md_text = await page.evaluate("""
            (() => {
                const lines = [];
                const walker = document.createTreeWalker(
                    document.body,
                    NodeFilter.SHOW_ELEMENT,
                    {
                        acceptNode: (node) => {
                            if (node.offsetParent === null && node.tagName !== 'BODY') return NodeFilter.FILTER_REJECT;
                            const tag = node.tagName.toLowerCase();
                            if (['script', 'style', 'svg', 'noscript'].includes(tag)) return NodeFilter.FILTER_REJECT;
                            return NodeFilter.FILTER_ACCEPT;
                        }
                    }
                );

                let curr;
                while (curr = walker.nextNode()) {
                    const tag = curr.tagName.toLowerCase();
                    const text = (curr.innerText || '').trim();
                    
                    if (['h1', 'h2', 'h3'].includes(tag) && curr.childNodes.length === 1) {
                        lines.push(`\\n### ${text}\\n`);
                    } else if (tag === 'button') {
                        lines.push(`[Button: "${text}"]`);
                    } else if (tag === 'input') {
                        const type = curr.type || 'text';
                        const placeholder = curr.placeholder || '';
                        const id = curr.id ? `#${curr.id}` : '';
                        lines.push(`[Input (${type}) ${id}: "${placeholder}"]`);
                    } else if (tag === 'select') {
                        const id = curr.id ? `#${curr.id}` : '';
                        lines.push(`[Dropdown ${id}]`);
                    } else if (curr.childNodes.length === 1 && curr.childNodes[0].nodeType === 3 && text.length > 0) {
                        // Leaf text node
                        if (!['button', 'label'].includes(tag)) {
                            lines.push(text);
                        }
                    }
                }
                return lines.join('\\n');
            })()
        """)
        
        elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
        tokens = self.estimate_tokens(md_text)
        
        metadata = {
            "extractor": self.name,
            "extraction_ms": round(elapsed_ms, 2),
            "char_count": len(md_text),
            "token_estimate": tokens
        }
        return md_text, metadata
