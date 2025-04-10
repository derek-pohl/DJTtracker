import time
import re
import html
import json
from datetime import datetime
from playwright.sync_api import sync_playwright, Playwright, Page, Error # Import Error instead of APIError

# Requires 'playwright': pip install playwright
# Requires browser binaries: python -m playwright install

API_URL = "https://truthsocial.com/api/v1/accounts/114311127114777163/statuses?exclude_replies=true&with_muted=true"
# Increased interval slightly as browser automation can be slower
CHECK_INTERVAL_SECONDS = 10

# Store the ID of the latest post seen
latest_seen_post_id = None

def clean_html(raw_html):
    """Removes HTML tags and decodes HTML entities."""
    clean_text = re.sub(r'<[^>]+>', '', raw_html)
    clean_text = html.unescape(clean_text)
    return clean_text.strip()

def fetch_latest_posts_playwright(page: Page):
    """Navigates to the API URL and attempts to parse the displayed JSON."""
    try:
        # Navigate the main frame to the API URL
        response = page.goto(API_URL, timeout=15000, wait_until='domcontentloaded') # Or 'commit' might be faster if page load fails

        if response is None or not response.ok:
             status = response.status if response else "N/A"
             status_text = response.status_text if response else "Navigation failed"
             print(f"[{datetime.now()}] Network error navigating to API: Status {status} - {status_text}")
             return None

        # Get the text content, assuming JSON is displayed directly or in a <pre> tag
        # Using page.content() might be more robust if JSON is wrapped in HTML
        # json_text = page.locator('body').inner_text() # Might fail if page structure is complex
        json_text = page.content()
        # Basic cleanup if it's wrapped in simple HTML (like <pre>)
        if '<pre' in json_text.lower():
             match = re.search(r'<pre.*?>(.*)</pre>', json_text, re.DOTALL | re.IGNORECASE)
             if match:
                  json_text = match.group(1).strip()
        elif '<body>' in json_text.lower():
             match = re.search(r'<body.*?>(.*)</body>', json_text, re.DOTALL | re.IGNORECASE)
             if match:
                  json_text = match.group(1).strip()
                  # Further strip potential HTML tags if JSON isn't the only content
                  json_text = re.sub(r'<[^>]+>', '', json_text)

        # Attempt to parse the extracted text as JSON
        return json.loads(json_text)

    except Error as e: # Catch Playwright errors (navigation, timeout, etc.)
        print(f"[{datetime.now()}] Playwright error during navigation/fetch: {e}")
    except json.JSONDecodeError as e:
        print(f"[{datetime.now()}] Error decoding JSON response: {e}")
    except Exception as e:
        print(f"[{datetime.now()}] An unexpected error occurred during fetch: {e}")
    return None

def run_monitor(playwright: Playwright):
    global latest_seen_post_id # Allow modification of the global variable

    # Launch browser (Chromium is often reliable)
    # Set headless=False to make the browser window visible
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36'
    )
    page = context.new_page()

    print(f"[{datetime.now()}] Starting Truth Social monitor using Playwright (Visible Window - API Navigation Mode)...")

    # No initial base URL navigation needed for this approach

    print(f"[{datetime.now()}] Performing initial navigation to API URL...")

    # Initial fetch
    initial_data = fetch_latest_posts_playwright(page)
    if initial_data and isinstance(initial_data, list) and len(initial_data) > 0:
        try:
            latest_seen_post_id = initial_data[0]['id']
            print(f"[{datetime.now()}] Initial latest post ID set to: {latest_seen_post_id}")
        except (KeyError, IndexError) as e:
            print(f"[{datetime.now()}] Error accessing initial post data: {e}")
            latest_seen_post_id = None
    else:
        print(f"[{datetime.now()}] Could not fetch initial data or response was empty/invalid.")

    print(f"[{datetime.now()}] Monitoring for new posts...")

    try:
        while True:
            posts = fetch_latest_posts_playwright(page)

            if posts and isinstance(posts, list) and len(posts) > 0:
                try:
                    current_latest_post = posts[0]
                    current_latest_id = current_latest_post['id']

                    if latest_seen_post_id is None or current_latest_id != latest_seen_post_id:
                        if latest_seen_post_id is not None:
                            print(f"\n--- New Post Detected ({datetime.now()}) ---")

                            media_attachments = current_latest_post.get('media_attachments', [])
                            if media_attachments and isinstance(media_attachments, list) and len(media_attachments) > 0:
                                first_attachment = media_attachments[0]
                                preview_url = first_attachment.get('preview_url')
                                if preview_url:
                                    print(f"Media Preview: {preview_url}")

                            content_html = current_latest_post.get('content', '')
                            cleaned_content = clean_html(content_html)
                            if cleaned_content:
                                print(f"Content: {cleaned_content}")
                            else:
                                if media_attachments:
                                    print("[Post has media but no text content]")
                                else:
                                    print("[Post has no text content or media]")

                            print("------------------------------------------")

                        latest_seen_post_id = current_latest_id

                except (KeyError, IndexError) as e:
                    print(f"[{datetime.now()}] Error processing post data: {e}")
                except Exception as e:
                     print(f"[{datetime.now()}] An unexpected error occurred processing posts: {e}")

            time.sleep(CHECK_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print(f"\n[{datetime.now()}] Monitor stopped by user.")
    except Exception as e:
        print(f"\n[{datetime.now()}] An critical error occurred: {e}")
    finally:
        print(f"[{datetime.now()}] Closing browser...")
        browser.close()
        print(f"[{datetime.now()}] Browser closed.")


if __name__ == "__main__":
    with sync_playwright() as playwright_instance:
        run_monitor(playwright_instance)
