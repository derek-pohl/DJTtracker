import time
import re
import html
import json
import os  # Added for environment variables
import smtplib # Added for email
from email.message import EmailMessage # Added for email
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
API_URL = os.environ.get("API_URL", "https://truthsocial.com/api/v1/accounts/107780257626128497/statuses?exclude_replies=true&with_muted=true")
CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL_SECONDS", 10)) # Convert to int
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_APP_PASSWORD = os.environ.get("SENDER_APP_PASSWORD")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL")
FOCUS = os.environ.get("FOCUS") # Load FOCUS
# Load NOTIFY_ALL and convert to boolean, default to False if not set or invalid
NOTIFY_ALL_STR = os.environ.get("NOTIFY_ALL", "False")
NOTIFY_ALL = NOTIFY_ALL_STR.strip().lower() == 'true'


# --- Validation ---
if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY not found in environment variables or .env file.")
    exit(1)
if not SENDER_EMAIL:
    print("Error: SENDER_EMAIL not found in environment variables or .env file.")
    exit(1)
if not SENDER_APP_PASSWORD:
    print("Error: SENDER_APP_PASSWORD not found in environment variables or .env file.")
    exit(1)
if not RECIPIENT_EMAIL:
    print("Error: RECIPIENT_EMAIL not found in environment variables or .env file.")
    exit(1)
# --- End Validation ---


# Configure Gemini client
try:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_client = genai.GenerativeModel('gemini-2.0-flash-thinking-exp-01-21')
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

{focus_section}

**Tweet to Analyze:**

"{tweet_content}"
"""

# Store the ID of the latest post seen
latest_seen_post_id = None

def clean_html(raw_html):
    """Removes HTML tags and decodes HTML entities."""
    # Decode HTML entities first
    clean_text = html.unescape(raw_html)
    # Remove all HTML tags
    clean_text = re.sub(r'<[^>]+>', '', clean_text)
    # Strip leading/trailing whitespace and return
    return clean_text.strip()

def format_gemini_for_email(gemini_response_text):
    """Formats the raw Gemini response string for email, removing labels."""
    if not gemini_response_text or not isinstance(gemini_response_text, str):
        return "Invalid Gemini response received."

    # Find all bracketed sections
    parts = re.findall(r'\[(.*?)\]', gemini_response_text)
    if not parts:
        return gemini_response_text # Return raw if no brackets found

    justification = parts[-1] # Last part is justification
    analysis_parts = parts[:-1] # All other parts are analysis

    if not analysis_parts: # Only justification found?
        return justification

    if analysis_parts[0].upper() == 'NONE':
        formatted_analysis = "NONE"
    else:
        # Process analysis parts (Entity, Ticker/Sector, Impact) - Handles 2 or 3 parts per entity
        formatted_lines = []
        i = 0
        while i < len(analysis_parts):
            entity = analysis_parts[i]
            ticker_sector = "" # Default to empty
            impact_text = ""
            impact_display = ""
            detail = ""

            # Check for 3-item sequence first (Entity, Ticker/Sector, Impact)
            if i + 2 < len(analysis_parts) and analysis_parts[i+2].upper() in ['UP', 'DOWN', 'MENTIONED']:
                ticker_sector = analysis_parts[i+1]
                impact_text = analysis_parts[i+2].upper()
                i += 3 # Move index forward by 3
            # Check for 2-item sequence (Entity, Impact)
            elif i + 1 < len(analysis_parts) and analysis_parts[i+1].upper() in ['UP', 'DOWN', 'MENTIONED']:
                impact_text = analysis_parts[i+1].upper()
                i += 2 # Move index forward by 2
            else:
                # Unexpected format, just append the entity and move on
                formatted_lines.append(f"[{entity}]") # Fallback for unexpected item
                i += 1
                continue # Skip emoji mapping for this item

            # Map impact text to emoji
            if impact_text == 'UP':
                impact_display = '📈'
            elif impact_text == 'DOWN':
                impact_display = '📉'
            elif impact_text == 'MENTIONED':
                impact_display = '💬'
            else: # Should not happen based on checks above, but keep as fallback
                impact_display = impact_text

            # Include ticker/sector if it exists and is different from entity
            detail = f" ({ticker_sector})" if ticker_sector and ticker_sector != entity else ""
            # Construct the new output format
            formatted_lines.append(f"{entity}{detail}: {impact_display}")

        formatted_analysis = "\n".join(formatted_lines)


    # Add an extra newline between analysis and justification
    return f"{formatted_analysis}\n\n{justification}"


def send_email(subject, body, to_email, from_email, app_password):
    """Sends an email using Gmail SMTP."""
    msg = EmailMessage()
    msg.set_content(body)
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to_email

    try:
        print(f"[{datetime.now()}] Attempting to send email to {to_email}...")
        # Connect to Gmail SMTP server
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()  # Secure the connection
        server.login(from_email, app_password)
        server.send_message(msg)
        server.quit()
        print(f"[{datetime.now()}] Email sent successfully.")
    except smtplib.SMTPAuthenticationError:
        print(f"[{datetime.now()}] Email Error: Authentication failed. Check SENDER_EMAIL and SENDER_APP_PASSWORD.")
    except Exception as e:
        print(f"[{datetime.now()}] Email Error: Failed to send email: {e}")


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

                            # --- Gemini Analysis & Email ---
                            if cleaned_content:
                                print("--- Analyzing with Gemini ---")
                                gemini_response_text = None # Initialize
                                try:
                                    # Conditionally add focus section to the prompt
                                    focus_section_text = ""
                                    if FOCUS:
                                        focus_section_text = f"Focus on: {FOCUS}. Also consider the broader market.\n\n"

                                    final_prompt = GEMINI_PROMPT_TEMPLATE.format(
                                        focus_section=focus_section_text,
                                        tweet_content=cleaned_content
                                    )
                                    response = gemini_client.generate_content(contents=[final_prompt])
                                    gemini_response_text = response.text.strip() # Strip whitespace
                                    print(f"Gemini Response: {gemini_response_text}")
                                except Exception as gemini_error:
                                    print(f"Error calling Gemini API: {gemini_error}")
                                print("-----------------------------") # Separator after Gemini attempt

                                # --- Send Email Logic ---
                                should_send_email = False
                                if gemini_response_text:
                                    # Check if NOTIFY_ALL is True OR if Gemini response is not '[NONE]'
                                    if NOTIFY_ALL or not gemini_response_text.startswith("[NONE]"):
                                        should_send_email = True
                                    else:
                                         print(f"[{datetime.now()}] Skipping email: NOTIFY_ALL is False and Gemini response is '[NONE]'.")

                                    if should_send_email:
                                        formatted_gemini = format_gemini_for_email(gemini_response_text)
                                        email_subject = "New Truth Social Post"
                                        email_body = f"{cleaned_content}\n\n{formatted_gemini}" # Use the cleaned content
                                        send_email(email_subject, email_body, RECIPIENT_EMAIL, SENDER_EMAIL, SENDER_APP_PASSWORD)

                                else:
                                    print(f"[{datetime.now()}] Skipping email due to Gemini error or empty response.")
                                # --- End Send Email Logic ---

                            # --- End Gemini Analysis & Email ---
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
