import time
import re
import html
import json
import os  # Added for environment variables
from datetime import datetime
from dotenv import load_dotenv  # Added for .env file
import google.generativeai as genai # Added for Gemini
from playwright.sync_api import sync_playwright, Playwright, Page, Error # Import Error instead of APIError

# Load environment variables from .env file
load_dotenv()

# Requires 'playwright': pip install playwright
# Requires 'google-generativeai': pip install google-generativeai
# Requires 'python-dotenv': pip install python-dotenv
# Requires browser binaries: python -m playwright install

# Get configuration from environment variables
API_URL = os.environ.get("API_URL", "https://truthsocial.com/api/v1/accounts/114311127114777163/statuses?exclude_replies=true&with_muted=true")
CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL_SECONDS", 10)) # Convert to int
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY not found in environment variables or .env file.")
    exit(1) # Exit if API key is missing

# Configure Gemini client
try:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_client = genai.GenerativeModel('gemini-1.5-flash') # Use the model directly
except Exception as e:
    print(f"Error configuring Gemini client: {e}")
    exit(1)

# Gemini Prompt Template
GEMINI_PROMPT_TEMPLATE = """
**Objective:** Analyze the provided Presidential tweet to identify potential impacts on specific publicly traded stocks, market sectors, or the overall market.

**Input:** A single tweet.

**Instructions:**

1.  **Analyze:** Determine if the tweet's content could reasonably influence investor sentiment or signal policy changes affecting specific companies, sectors, or the broader economy.
2.  **Identify Entities:**
    *   If specific companies are directly mentioned or clearly implied targets/beneficiaries, list them.
    *   If a broader sector is impacted (e.g., energy, tech, healthcare), identify the sector.
    *   If the sentiment is very general (e.g., overall economic optimism/pessimism), use "Entire Market".
3.  **Determine Impact:** For each identified entity, assess the likely short-term sentiment impact based *only* on the tweet:
    *   `[UP]`: Likely positive sentiment/price pressure.
    *   `[DOWN]`: Likely negative sentiment/price pressure.
    *   `[MENTIONED]`: The entity is named, but the tweet doesn't provide a clear directional bias for market impact.
4.  **Format Output:**
    *   **If Impact Identified:** Use the format `[Entity1 Name][Ticker/Sector1][Impact1][Entity2 Name][Ticker/Sector2][Impact2]...`
        *   Include the stock ticker (e.g., AAPL) if readily known for a specific company. If listing a sector or Entire Market, you can omit the ticker field or repeat the Sector name.
    *   **If No Impact Identified:** Respond with `[NONE]`.
5.  **Add Justification:** *After* the list or `[NONE]`, add *one* concise sentence explaining your reasoning, enclosed in brackets. Base the justification strictly on the tweet's content. `[Your justification sentence here]`
6.  **Handle Signature:** Ignore trailing signatures like "DJT" unless the signature *itself* is the relevant content (highly unlikely for market impact).

**Examples:**

*   **Tweet:** "Lowering drug costs is a priority! Big Pharma has taken advantage for too long."
    *   **Response:** `[Pharmaceuticals Sector][DOWN][Healthcare Sector][DOWN][The tweet signals potential policy action negative for pharmaceutical company profits.]`
*   **Tweet:** "Just had a great meeting with the CEO of Ford. Exciting things happening for American auto workers!"
    *   **Response:** `[Ford][F][UP][Auto Sector][UP][The tweet expresses positive sentiment towards Ford and the US auto industry, suggesting potential favorability.]`
*   **Tweet:** "Thinking of visiting the Grand Canyon next week."
    *   **Response:** `[NONE][The tweet discusses personal travel plans with no discernible market or economic relevance.]`
*   **Tweet:** "Just spoke with Tim Cook. Apple is a great American company!"
    *   **Response:** `[Apple][AAPL][MENTIONED][The tweet mentions Apple positively but doesn't indicate specific policy or market action affecting its stock price.]`

**Tweet to Analyze:**

"{tweet_content}"
"""

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

                            # --- Gemini Analysis ---
                            if cleaned_content:
                                try:
                                    print("--- Analyzing with Gemini ---")
                                    final_prompt = GEMINI_PROMPT_TEMPLATE.format(tweet_content=cleaned_content)
                                    # Use generate_content directly from the model instance
                                    response = gemini_client.generate_content(contents=[final_prompt])
                                    print(f"Gemini Response: {response.text}")
                                except Exception as gemini_error:
                                    print(f"Error calling Gemini API: {gemini_error}")
                                print("-----------------------------")
                            # --- End Gemini Analysis ---

                            print("------------------------------------------") # Original separator

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
