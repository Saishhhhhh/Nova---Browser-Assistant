"""Benchmark task definitions for browser automation frameworks."""
from dataclasses import dataclass
from typing import Dict, Any, List


@dataclass
class BenchmarkTask:
    id: str
    name: str
    description: str
    initial_url: str
    instruction: str
    expected_result_keys: List[str]
    max_steps: int = 15


BENCHMARK_TASKS: Dict[str, BenchmarkTask] = {
    "ecommerce_filter_extract": BenchmarkTask(
        id="ecommerce_filter_extract",
        name="E-Commerce Category Filter & Deep Extraction",
        description="Navigate to category, find qualifying item, click into detail page, and extract structured data.",
        initial_url="https://books.toscrape.com/",
        instruction=(
            "Go to https://books.toscrape.com/, navigate to the 'Travel' category from the sidebar, "
            "click on the book 'It's Only the Himalayas', extract its price and its UPC from the product information table, "
            "and output the result in JSON format with keys: title, price, upc."
        ),
        expected_result_keys=["title", "price", "upc"],
        max_steps=12,
    ),
    "form_auth_and_state": BenchmarkTask(
        id="form_auth_and_state",
        name="Form Authentication & State Verification",
        description="Fill authentication credentials, trigger submission, and verify post-login state change.",
        initial_url="https://the-internet.herokuapp.com/login",
        instruction=(
            "Go to https://the-internet.herokuapp.com/login, enter username 'tomsmith' and password 'SuperSecretPassword!', "
            "click the Login button, verify that the page displays the secure area message, "
            "and output JSON with key 'success': true and 'message' containing the confirmation banner text."
        ),
        expected_result_keys=["success", "message"],
        max_steps=8,
    ),
    "media_spa_navigation": BenchmarkTask(
        id="media_spa_navigation",
        name="Dynamic SPA & Video Navigation",
        description="Dismiss popups/consent, search media query, and select first organic video.",
        initial_url="https://www.youtube.com",
        instruction=(
            "Go to https://www.youtube.com, search for 'Lofi Girl relaxing beats', "
            "click on the first video result, and return JSON with key 'video_title' containing the title of the video played."
        ),
        expected_result_keys=["video_title"],
        max_steps=10,
    ),
    "github_repo_traversal": BenchmarkTask(
        id="github_repo_traversal",
        name="GitHub Issues Traversal & Multi-Item Extraction",
        description="Traverse repository tabs, inspect issue list, and extract top issue titles.",
        initial_url="https://github.com/microsoft/playwright",
        instruction=(
            "Go to https://github.com/microsoft/playwright, click on the 'Issues' tab, "
            "retrieve the title and issue number of the first 2 open issues, and output JSON with key 'issues' as a list of objects with 'number' and 'title'."
        ),
        expected_result_keys=["issues"],
        max_steps=12,
    ),
}
