# --- reporter_scraper.py (Phase 8.0: Asynchronous Scraping with Pagination & URL Skipping) ---

import asyncio
import aiohttp
import time
import re
import json
import os
import sys
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote
from datetime import datetime, timezone
import traceback

# --- Configuration ---

STARTING_URLS = [
    # Core News/Sections
    "https://www.ethiopianreporter.com/news/",
    "https://www.ethiopianreporter.com/politics/",
    "https://www.ethiopianreporter.com/business/",
    "https://www.ethiopianreporter.com/editorial/",
    "https://www.ethiopianreporter.com/interview/",
    "https://www.ethiopianreporter.com/youth/",
    "https://www.ethiopianreporter.com/society/",
    "https://www.ethiopianreporter.com/sport/",
    "https://www.ethiopianreporter.com/kinin-and-bahil/",  # Arts & Culture
    "https://www.ethiopianreporter.com/advertorial/",
    "https://www.ethiopianreporter.com/world/",
    "https://www.ethiopianreporter.com/life/",  # = ሥነ ፍጥረት
    "https://www.ethiopianreporter.com/science-and-technology/",
    # Columns/Segments
    "https://www.ethiopianreporter.com/kibur-minister/",
    "https://www.ethiopianreporter.com/what-are-they-going-to-do/",
    "https://www.ethiopianreporter.com/temuaget/",
    "https://www.ethiopianreporter.com/speak-your-mind/",
    "https://www.ethiopianreporter.com/yesamintu-getemegn/",
    "https://www.ethiopianreporter.com/ene-emilew/",
    "https://www.ethiopianreporter.com/opinion/",
    "https://www.ethiopianreporter.com/fermata/",
    "https://www.ethiopianreporter.com/tesfish-and-gebrish/",
    "https://www.ethiopianreporter.com/ferekenafir/",
    "https://www.ethiopianreporter.com/zinik/",
    "https://www.ethiopianreporter.com/buyers/",
    "https://www.ethiopianreporter.com/delalaw/",
    "https://www.ethiopianreporter.com/taxi/",
    "https://www.ethiopianreporter.com/yidires-le-reporter/",
    "https://www.ethiopianreporter.com/baltina/",
    "https://www.ethiopianreporter.com/rule-of-law/",
    "https://www.ethiopianreporter.com/what-where/",
]

JSONL_OUTPUT_FILE = "ethiopianreporter_classified_data_v3.jsonl"  # Changed version
FETCH_DELAY_CATEGORY = 1  # Reduced delays for asyncio (adjust as needed)
FETCH_DELAY_ARTICLE = 1
MAX_PAGES_PER_CATEGORY = 100  # Increased page limit for deeper scraping
MAX_ARTICLES_TO_PROCESS = None  # Set to None to process ALL found articles
MAX_RETRIES = 3
RETRY_INITIAL_DELAY = 5
RETRY_BACKOFF_FACTOR = 2
HEADERS = {'User-Agent': 'AmharicLLMScraperBot/1.7 (+your_email@example.com)'}  # Please provide your email

# Selectors & Patterns
TITLE_SELECTORS = ['h1.tdb-title-text', 'h1.entry-title', 'header.td-post-title h1']
AUTHOR_SELECTORS = ['div.td-post-author-name a', '.td-author-name span a', '.td-author-name span']
DATE_SELECTORS = ['span.td-post-date time.entry-date', 'time.entry-date', '.td-post-date']
CATEGORY_SELECTORS = ['ul.td-category li.entry-category a', '.tdb-cat-bg', '.td-post-category']
TAG_SELECTORS = ['div.td-post-source-tags ul.td-tags li a']
ARTICLE_CONTENT_SELECTOR = 'div.td-post-content'
ARTICLE_LINK_PATTERN = re.compile(r'ethiopianreporter\.com/\d+/?$')
AMHARIC_STRICT_PATTERN = re.compile(r'[\u1200-\u137F\u1380-\u139F\u2D80-\u2DDF\uAB00-\uAB2F፡።፣፤፥፧\s]+')
WHITESPACE_CLEANUP_PATTERN = re.compile(r'\s{2,}')

RELAXED_EXTRACTION_CATEGORIES = ["interview", "kibur-minister", "ቆይታ", "ምን እየሰሩ ነው?",
                                 "ክቡር ሚኒስትር", "yesamintu-getemegn", "ene-emilew",
                                 "ተስፍሽ ና ገብርሽ", "ፌርማታ", "ደላላው", "ታክሲ", "temuaget",
                                 "ተሟገት", "speak-your-mind", "ልናገር"]
DIALOGUE_MARKERS = re.compile(r'[፡:\?፧]+')  # Adjusted to include Amharic Q-mark
POTENTIAL_DIALOGUE_MARKER_THRESHOLD = 0.008  # Markers per word threshold


# --- Functions ---

async def fetch_page(session, url):
    """
    Asynchronously fetches the content of a given URL with retry logic and error handling.
    """
    for attempt in range(MAX_RETRIES + 1):
        wait_time = RETRY_INITIAL_DELAY * (RETRY_BACKOFF_FACTOR ** attempt)
        print(f"  Fetching: {url} (Attempt {attempt + 1}/{MAX_RETRIES + 1})")
        try:
            async with session.get(url, headers=HEADERS, timeout=(15, 45)) as response:
                if response.status >= 500:
                    print(f"  Warning: Server Error {response.status}. Retrying...")
                    await asyncio.sleep(wait_time)
                    continue
                response.raise_for_status()
                print(f"  -> Fetched OK ({response.status})")
                text = await response.text(encoding='utf-8')  # Explicit encoding
                return text
        except aiohttp.ClientError as e:
            print(f"  Error: aiohttp ClientError: {e}. Retrying...")
            await asyncio.sleep(wait_time)
        except asyncio.TimeoutError:
            print(f"  Error: Asyncio Timeout. Retrying...")
            await asyncio.sleep(wait_time)
        except Exception as e:
            print(f"  Unexpected fetch error: {e}")
            traceback.print_exc()
            return None
    print(f"  Failed fetch after {MAX_RETRIES + 1} attempts: {url}")
    return None


def find_article_links(html_content, source_page_url):
    """
    Finds all article links within an HTML content.
    """
    links = set()
    if not html_content:
        print(f"    Warning: Empty HTML content for {source_page_url}, skipping link extraction.")
        return links
    try:
        try:
            soup = BeautifulSoup(html_content, 'lxml')
        except:
            soup = BeautifulSoup(html_content, 'html.parser')
        for link_tag in soup.find_all('a', href=True):
            href = link_tag.get('href')
            if href:
                href = href.strip()
                absolute_url = urljoin(source_page_url, href)
                if ARTICLE_LINK_PATTERN.search(absolute_url):
                    parsed_href = urlparse(absolute_url)
                    if parsed_href.scheme in ['http', 'https']:
                        links.add(absolute_url)
        return links
    except Exception as e:
        print(f"  Error finding links on {source_page_url}: {e}")
        traceback.print_exc()
        return links


def select_first_match(soup, selectors):
    """
    Selects the first matching element from a list of CSS selectors.
    """
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            return element
    return None


def extract_article_data(html_content, url):
    """
    Extracts article data from HTML content.
    """

    if not html_content:
        print("    Error: No HTML content provided for extraction.")
        return None

    data = {
        "url": url,
        "source_domain": urlparse(url).netloc,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "published_at": None,
        "title": None,
        "author": None,
        "html_categories": [],
        "tags": [],
        "detected_category_from_url": "unknown",
        "content_type": "standard",
        "potential_q_and_a": False,
        "potentially_conversational_strict": False,
        "text": None,
        "extraction_method": None,
        "metadata_source": "Unknown"
    }

    try:
        try:
            soup = BeautifulSoup(html_content, 'lxml' if 'lxml' in sys.modules else 'html.parser')
        except Exception as e:
            print(f"    Error parsing HTML with lxml, falling back to html.parser: {e}")
            soup = BeautifulSoup(html_content, 'html.parser')
        data['metadata_source'] = "CSS Selectors"

        # Improved Title Extraction with Fallback
        title_element = select_first_match(soup, TITLE_SELECTORS)
        data['title'] = title_element.get_text(strip=True) if title_element else None
        if not data['title']:
            print("    Warning: Title not found using selectors.")
            # Attempt to extract from meta tags or other elements (Example - adjust as needed)
            meta_title = soup.find("meta", attrs={"name": "title"}) or soup.find("meta", attrs={"property": "og:title"})
            if meta_title:
                data['title'] = meta_title.get("content", None)
                if data['title']:
                    data['metadata_source'] = "Meta Tag"
                    print("    Info: Found title in meta tag.")
            if not data['title']:
                data['title'] = soup.find("title").get_text(strip=True) if soup.find("title") else None
                if data['title']:
                    data['metadata_source'] = "Title Tag"
                    print("    Info: Found title in title tag.")
            if not data['title']:
                print("    Critical: Could not extract title from any source!")

        # Category Extraction
        cat_els = soup.select(CATEGORY_SELECTORS[0]) or soup.select(CATEGORY_SELECTORS[1]) or soup.select(CATEGORY_SELECTORS[2])
        data['html_categories'] = [el.get_text(strip=True) for el in cat_els if el.get_text(strip=True)] if cat_els else []

        # Author Extraction
        author_element = select_first_match(soup, AUTHOR_SELECTORS)
        data['author'] = author_element.get_text(strip=True) if author_element else None
        if not data['author']:
            print("    Warning: Author not found using selectors.")
            # Add fallback extraction if necessary

        # Date Extraction
        date_el = select_first_match(soup, DATE_SELECTORS)
        data['published_at'] = date_el.get('datetime', date_el.get_text(strip=True)) if date_el else None
        if not data['published_at']:
            print("    Warning: Published date not found using selectors.")
            # Add fallback extraction if necessary

        # Tag Extraction
        tag_els = soup.select(TAG_SELECTORS[0])
        data['tags'] = [el.get_text(strip=True) for el in tag_els if
                        el.get_text(strip=True).lower() != 'tags'] if tag_els else []

        # Classification
        url_cat_part = urlparse(url).path.split('/')[1] if len(urlparse(url).path.split('/')) > 1 else ""
        data['detected_category_from_url'] = url_cat_part.lower()
        html_cats_lower = set(c.lower() for c in data['html_categories'])
        use_relaxed_extraction = False
        content_type = "standard"
        matched_cat = next(
            (cat for cat in RELAXED_EXTRACTION_CATEGORIES if
             cat.lower() == data['detected_category_from_url'] or cat.lower() in html_cats_lower),
            None)
        if matched_cat:
            content_type = matched_cat
            use_relaxed_extraction = True
            print(f"    Info: Classified as '{content_type}' (Keyword). Relaxed extraction.")
        data['content_type'] = content_type
        data['extraction_method'] = 'relaxed' if use_relaxed_extraction else 'strict_amharic'

        # Text Extraction
        article_body = soup.select_one(ARTICLE_CONTENT_SELECTOR)
        if not article_body:
            print(f"    Error: Content selector failed for {url}.")
            return None

        unwanted_selectors = ["script", "style", "figure", "figcaption", ".wp-caption-text",
                             ".td-a-rec", ".yarpp-related", ".jp-relatedposts", "ins.adsbygoogle",
                             ".adsbygoogle", ".td-post-sharing", ".td-post-source-tags", ".comment-respond",
                             "#comments", ".td_block_related_posts", ".td_block_video_playlist",
                             ".clearfix", ".td-post-views", ".td-post-featured-image", "iframe", ".code-block"]
        for selector in unwanted_selectors:
            [el.decompose() for el in article_body.select(selector)]

        text_to_process = article_body.get_text(separator=' ', strip=True)
        text_to_process = WHITESPACE_CLEANUP_PATTERN.sub(' ', text_to_process).strip()

        if use_relaxed_extraction:
            data['text'] = text_to_process
        else:
            amharic_segments = AMHARIC_STRICT_PATTERN.findall(text_to_process)
            if amharic_segments:
                data['text'] = WHITESPACE_CLEANUP_PATTERN.sub(' ',
                                                             ' '.join(seg.strip() for seg in amharic_segments if
                                                                      seg.strip())).strip()
                if data['text']:
                    word_count = len(data['text'].split())
                    marker_count = len(DIALOGUE_MARKERS.findall(data['text']))
                    if word_count > 20 and marker_count / word_count > POTENTIAL_DIALOGUE_MARKER_THRESHOLD:
                        data['potentially_conversational_strict'] = True
                        print("    Info: Flagged potentially conversational (strict text).")
            else:
                data['text'] = ""
                print("    Warning: No Amharic segments (strict).")
        if not data['text']:
            print("    Warning: Final text empty.")

        return data

    except Exception as e:
        print(f"    !! Extract ERROR !! {url}: {e}")
        traceback.print_exc()
        return None


def save_to_jsonl(data_dict, filename):
    """
    Saves a dictionary to a JSON Lines file.
    """
    try:
        with open(filename, 'a', encoding='utf-8') as f:
            json_string = json.dumps(data_dict, ensure_ascii=False)
            f.write(json_string + '\n')
    except Exception as e:
        print(f"    Error saving data: {e}")
        traceback.print_exc()


def extract_next_page_url(soup, current_page_url):
    """
    Extracts the URL of the next page from the current page's HTML.
    This function needs to be robust to handle variations in pagination structures.
    """
    try:
        # Common next
