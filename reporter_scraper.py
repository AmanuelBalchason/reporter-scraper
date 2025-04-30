# --- reporter_scraper.py (Phase 7.2: NameError Fix) ---

import requests
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
    "https://www.ethiopianreporter.com/news/", "https://www.ethiopianreporter.com/politics/",
    "https://www.ethiopianreporter.com/business/", "https://www.ethiopianreporter.com/editorial/",
    "https://www.ethiopianreporter.com/interview/", "https://www.ethiopianreporter.com/kibur-minister/",
    "https://www.ethiopianreporter.com/youth/", "https://www.ethiopianreporter.com/society/",
    "https://www.ethiopianreporter.com/sport/", "https://www.ethiopianreporter.com/kinin-and-bahil/",
    "https://www.ethiopianreporter.com/yesamintu-getemegn/", "https://www.ethiopianreporter.com/advertorial/",
    "https://www.ethiopianreporter.com/yidires-le-reporter/", "https://www.ethiopianreporter.com/baltina/",
    "https://www.ethiopianreporter.com/rule-of-law/", "https://www.ethiopianreporter.com/science-and-technology/",
    "https://www.ethiopianreporter.com/life/", "https://www.ethiopianreporter.com/what-where/",
    "https://www.ethiopianreporter.com/ene-emilew/", "https://www.ethiopianreporter.com/opinion/",
    "https://www.ethiopianreporter.com/fermata/", "https://www.ethiopianreporter.com/temuaget/",
    "https://www.ethiopianreporter.com/speak-your-mind/", "https://www.ethiopianreporter.com/tesfish-and-gebrish/",
    "https://www.ethiopianreporter.com/ferekenafir/", "https://www.ethiopianreporter.com/zinik/",
    "https://www.ethiopianreporter.com/world/", "https://www.ethiopianreporter.com/buyers/",
    "https://www.ethiopianreporter.com/delalaw/", "https://www.ethiopianreporter.com/taxi/",
]
JSONL_OUTPUT_FILE = "ethiopianreporter_classified_data_v2.jsonl"
FETCH_DELAY_CATEGORY = 2; FETCH_DELAY_ARTICLE = 3
# Change this:
MAX_PAGES_PER_CATEGORY = 50 # Or 100, or higher - how deep do you want to go? Deeper = much longer runtime!
# Change this:
MAX_ARTICLES_TO_PROCESS = None # Set to None to process ALL found articles
MAX_RETRIES = 3; RETRY_INITIAL_DELAY = 5; RETRY_BACKOFF_FACTOR = 2
HEADERS = { 'User-Agent': 'AmharicLLMScraperBot/1.6 (+amanuel@example.com)' }

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

# Keywords for relaxed extraction
RELAXED_EXTRACTION_CATEGORIES = [ "interview", "kibur-minister", "ቆይታ", "ምን እየሰሩ ነው?", "ክቡር ሚኒስትር", "yesamintu-getemegn", "ene-emilew", "ተስፍሽ ና ገብርሽ", "ፌርማታ", "ደላላው", "ታክሲ", "temuaget", "ተሟገት", "speak-your-mind", "ልናገር"]
# Dialogue detection pattern
DIALOGUE_MARKERS = re.compile(r'[፡:\?፧]+') # Adjusted to include Amharic Q-mark
POTENTIAL_DIALOGUE_MARKER_THRESHOLD = 0.008 # Markers per word threshold

# --- Functions ---

def fetch_page(url):
    # ... (keep exact function) ...
    for attempt in range(MAX_RETRIES + 1):
        wait_time = RETRY_INITIAL_DELAY * (RETRY_BACKOFF_FACTOR ** attempt)
        print(f"  Fetching: {url} (Attempt {attempt + 1}/{MAX_RETRIES + 1})")
        try:
            response = requests.get(url, headers=HEADERS, timeout=(15, 45))
            if response.status_code >= 500: print(f"  Warning: Server Error {response.status_code}. Retrying..."); time.sleep(wait_time); continue
            response.raise_for_status(); print(f"  -> Fetched OK ({response.status_code})");
            response.encoding = response.apparent_encoding if response.apparent_encoding else 'utf-8'
            return response.text
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e: print(f"  Error: {type(e).__name__}. Retrying..."); time.sleep(wait_time)
        except requests.exceptions.RequestException as e: print(f"  Error: RequestException {e}. Not retrying."); return None
        except Exception as e: print(f"  Unexpected fetch error: {e}"); traceback.print_exc(); return None
    print(f"  Failed fetch after {MAX_RETRIES + 1} attempts: {url}"); return None


def find_article_links(html_content, source_page_url):
    # ... (keep exact function) ...
    links = set()
    if not html_content: return links
    try:
        try: soup = BeautifulSoup(html_content, 'lxml')
        except: soup = BeautifulSoup(html_content, 'html.parser')
        for link_tag in soup.find_all('a', href=True):
            href = link_tag.get('href')
            if href:
                href = href.strip(); absolute_url = urljoin(source_page_url, href)
                if ARTICLE_LINK_PATTERN.search(absolute_url):
                     parsed_href = urlparse(absolute_url)
                     if parsed_href.scheme in ['http', 'https']: links.add(absolute_url)
        return links
    except Exception as e: print(f"  Error finding links on {source_page_url}: {e}"); traceback.print_exc(); return links


def select_first_match(soup, selectors):
    # ... (keep exact function) ...
    for selector in selectors:
        element = soup.select_one(selector);
        if element: return element
    return None


def extract_article_data(html_content, url):
    # ... (keep exact function with heuristic checks) ...
    if not html_content: print("    Error: No HTML."); return None
    data = {"url": url,"source_domain": urlparse(url).netloc,"scraped_at": datetime.now(timezone.utc).isoformat(),"published_at": None, "title": None,"author": None,"html_categories": [],"tags": [],"detected_category_from_url": "unknown","content_type": "standard","potential_q_and_a": False, "potentially_conversational_strict": False,"text": None,"extraction_method": None,"metadata_source": "Unknown"}
    try:
        soup = BeautifulSoup(html_content, 'lxml' if 'lxml' in sys.modules else 'html.parser')
        data['metadata_source'] = "CSS Selectors"
        data['title'] = (select_first_match(soup, TITLE_SELECTORS) or soup.new_tag('title')).get_text(strip=True) or None
        cat_els = soup.select(CATEGORY_SELECTORS[0]) or soup.select(CATEGORY_SELECTORS[1]) or soup.select(CATEGORY_SELECTORS[2])
        data['html_categories'] = [el.get_text(strip=True) for el in cat_els if el.get_text(strip=True)] if cat_els else []
        data['author'] = (select_first_match(soup, AUTHOR_SELECTORS) or soup.new_tag('span')).get_text(strip=True) or None
        date_el = select_first_match(soup, DATE_SELECTORS); data['published_at'] = date_el.get('datetime', date_el.get_text(strip=True)) if date_el else None
        tag_els = soup.select(TAG_SELECTORS[0]); data['tags'] = [el.get_text(strip=True) for el in tag_els if el.get_text(strip=True).lower() != 'tags'] if tag_els else []
        if not data['title']: print("    Warning: Title not found.")

        # Classification
        url_cat_part = urlparse(url).path.split('/')[1] if len(urlparse(url).path.split('/')) > 1 else ""
        data['detected_category_from_url'] = url_cat_part.lower()
        html_cats_lower = set(c.lower() for c in data['html_categories'])
        use_relaxed_extraction = False; content_type = "standard"
        matched_cat = next((cat for cat in RELAXED_EXTRACTION_CATEGORIES if cat.lower() == data['detected_category_from_url'] or cat.lower() in html_cats_lower), None)
        if matched_cat:
            content_type = matched_cat; use_relaxed_extraction = True;
            print(f"    Info: Classified as '{content_type}' (Keyword). Relaxed extraction.")
        data['content_type'] = content_type
        data['extraction_method'] = 'relaxed' if use_relaxed_extraction else 'strict_amharic'

        # Text Extraction
        article_body = soup.select_one(ARTICLE_CONTENT_SELECTOR)
        if not article_body: print(f"    Error: Content selector failed."); return None
        unwanted_selectors = ["script", "style", "figure", "figcaption", ".wp-caption-text", ".td-a-rec", ".yarpp-related", ".jp-relatedposts", "ins.adsbygoogle", ".adsbygoogle",".td-post-sharing", ".td-post-source-tags", ".comment-respond", "#comments", ".td_block_related_posts", ".td_block_video_playlist", ".clearfix", ".td-post-views", ".td-post-featured-image", "iframe", ".code-block"]
        for selector in unwanted_selectors: [el.decompose() for el in article_body.select(selector)]
        text_to_process = article_body.get_text(separator=' ', strip=True)
        text_to_process = WHITESPACE_CLEANUP_PATTERN.sub(' ', text_to_process).strip()

        if use_relaxed_extraction:
            data['text'] = text_to_process
        else:
            amharic_segments = AMHARIC_STRICT_PATTERN.findall(text_to_process)
            if amharic_segments:
                data['text'] = WHITESPACE_CLEANUP_PATTERN.sub(' ', ' '.join(seg.strip() for seg in amharic_segments if seg.strip())).strip()
                if data['text']:
                    word_count = len(data['text'].split())
                    marker_count = len(DIALOGUE_MARKERS.findall(data['text']))
                    if word_count > 20 and marker_count / word_count > POTENTIAL_DIALOGUE_MARKER_THRESHOLD:
                         data['potentially_conversational_strict'] = True; print("    Info: Flagged potentially conversational (strict text).")
            else: data['text'] = ""; print("    Warning: No Amharic segments (strict).")
        if not data['text']: print("    Warning: Final text empty.")
        return data
    except Exception as e: print(f"    !! Extract ERROR !! {url}: {e}"); traceback.print_exc(); return None

def save_to_jsonl(data_dict, filename):
    # ... (keep exact function) ...
    try:
        with open(filename, 'a', encoding='utf-8') as f: json_string = json.dumps(data_dict, ensure_ascii=False); f.write(json_string + '\n')
    except Exception as e: print(f"    Error saving data: {e}"); traceback.print_exc()

# --- Main Execution ---
if __name__ == "__main__":
    scrape_start_time_obj = datetime.now()
    print(f"Scraper starting - Phase 7.2: NameError Fix - {scrape_start_time_obj.strftime('%Y-%m-%d %H:%M:%S')}")
    all_article_links = set(); processed_urls = 0; failed_fetch = 0; failed_extract = 0
    run_start_time = time.time()

    # --- Step 1: Link Discovery ---
    print("\n--- Finding Links ---")
    links_start_time = time.time()
    for base_category_url in STARTING_URLS:
        print(f"\nProcessing Category: {base_category_url}")
        category_links_found_count = 0 # Count links added by THIS category only
        processed_pages_in_category = 0 # <<--- FIX: Initialize counter HERE
        for page_num in range(1, MAX_PAGES_PER_CATEGORY + 1):
             page_url = base_category_url if page_num == 1 else f"{base_category_url.rstrip('/')}/page/{page_num}/"
             print(f"  Fetching page {page_num}: {page_url}")
             page_html = fetch_page(page_url)
             if not page_html: print(f"  -> Page {page_num} fetch failed or empty, stopping pagination."); break

             processed_pages_in_category += 1 # Increment counter AFTER successful fetch
             found_on_page = find_article_links(page_html, base_category_url)
             new_links = found_on_page - all_article_links
             print(f"    Found {len(found_on_page)} links ({len(new_links)} new).")

             if not new_links and page_num > 1: print(f"    No *new* links found on page {page_num}, stopping."); break
             if new_links: all_article_links.update(new_links); category_links_found_count += len(new_links)

             if page_num < MAX_PAGES_PER_CATEGORY: print(f"  Waiting {FETCH_DELAY_CATEGORY}s..."); time.sleep(FETCH_DELAY_CATEGORY)

        print(f"  Category '{base_category_url}' done ({category_links_found_count} new links from {processed_pages_in_category} pages).")

    links_end_time = time.time(); total_unique_links = len(all_article_links)
    print(f"\n--- Link Discovery Complete: Found {total_unique_links} unique URLs ({links_end_time - links_start_time:.2f}s) ---")
    if total_unique_links == 0: print("\nNo articles found. Exiting."); exit()

    # --- Step 2: Determine Processing List ---
    articles_to_process_list = sorted(list(all_article_links))
    num_to_process_actual = total_unique_links
    if MAX_ARTICLES_TO_PROCESS is not None and 0 < MAX_ARTICLES_TO_PROCESS < total_unique_links:
        articles_to_process_list = articles_to_process_list[:MAX_ARTICLES_TO_PROCESS]; num_to_process_actual = MAX_ARTICLES_TO_PROCESS
        print(f"Limiting run to first {num_to_process_actual} articles.")
    else: print(f"Processing all {total_unique_links} found articles.")
    print(f"Saving output to: '{JSONL_OUTPUT_FILE}'")


    # --- Step 3: Process Articles ---
    print("\n--- Processing Articles ---")
    article_start_time = time.time()
    # ... (Keep exact processing loop logic as before) ...
    for i, url in enumerate(articles_to_process_list):
        print(f"\n[{i+1}/{num_to_process_actual}] Processing: {url}")
        html = fetch_page(url)
        if html:
            data = extract_article_data(html, url)
            if data:
                save_to_jsonl(data, JSONL_OUTPUT_FILE)
                processed_urls += 1
                t_snip = (data.get('title') or "N/A")[:40]; txt_len = len(data.get('text') or "")
                ctype = data.get('content_type'); pot_conv = data.get('potentially_conversational_strict', False)
                print(f"    -> OK [Type:{ctype}{'/Conv?' if pot_conv else ''}] Saved: '{t_snip}...', Text={txt_len} chars")
            else: print(f"    -> FAIL: Extract error."); failed_extract += 1
        else: print(f"    -> FAIL: Fetch error."); failed_fetch += 1
        if i < num_to_process_actual - 1: print(f"  Waiting {FETCH_DELAY_ARTICLE}s..."); time.sleep(FETCH_DELAY_ARTICLE)

    article_end_time = time.time()
    total_duration = article_end_time - run_start_time

    # --- Final Summary ---
    print("\n--- Final Scrape Summary ---")
    # ... (print summary as before) ...
    print(f"Scrape started: {scrape_start_time_obj.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Category URLs checked: {len(STARTING_URLS)}")
    print(f"Total unique URLs found: {total_unique_links}")
    print(f"Article URLs attempted: {num_to_process_actual}")
    print(f"Successfully processed & saved: {processed_urls}")
    print(f"Failed fetches: {failed_fetch}")
    print(f"Failed extractions: {failed_extract}")
    if os.path.exists(JSONL_OUTPUT_FILE):
        try: fsize = os.path.getsize(JSONL_OUTPUT_FILE); print(f"Data saved to '{JSONL_OUTPUT_FILE}' ({fsize/1024:.2f} KB)")
        except OSError: pass
    else: print(f"Output file '{JSONL_OUTPUT_FILE}' not created.")
    print(f"Total duration: {total_duration:.2f} seconds.")
    print(f"Scraper Finished: {datetime.now()}")

# --- END ---