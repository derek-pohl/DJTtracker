# Truth Social Post Monitor & Market Impact Analyzer

This script monitors a specified Truth Social account feed for new posts. When a new post is detected, it analyzes the content using Google's Gemini AI to assess potential impacts on publicly traded stocks, market sectors, or the overall market. If a potential impact is identified (or if configured to notify on all posts), it sends an email notification via Gmail.

## Features

*   Monitors a Truth Social feed via its API endpoint using Playwright.
*   Cleans HTML content from posts.
*   Utilizes Google Gemini AI to analyze post content for market relevance.
*   Identifies potentially impacted stocks/sectors (UP, DOWN, MENTIONED).
*   Sends email notifications for relevant posts via Gmail SMTP.
*   Configurable check interval and notification settings.
*   Optional focus parameter to guide AI analysis.

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <your-repo-url>
    cd <your-repo-directory>
    ```

2.  **Install dependencies:**
    Make sure you have Python 3 installed.
    ```bash
    pip install -r requirements.txt
    ```
    *(Ensure `requirements.txt` includes `playwright`, `google-generativeai`, and `python-dotenv`)*

3.  **Install Playwright browsers:**
    ```bash
    python -m playwright install
    ```

4.  **Create a `.env` file:**
    Create a file named `.env` in the root directory and add the necessary environment variables (see below).

5.  **Configure Gmail for Sending:**
    *   You'll need a Gmail account to send notifications from.
    *   Enable 2-Step Verification for that Google Account.
    *   Create an "App Password" for this script. Google provides instructions here: [https://support.google.com/accounts/answer/185833](https://support.google.com/accounts/answer/185833)
    *   Use the generated 16-character App Password for `SENDER_APP_PASSWORD` in your `.env` file.

## Environment Variables

Create a `.env` file in the project root with the following structure. **Do not commit this file to version control.**

```dotenv
# --- Configuration ---

# Optional: URL of the Truth Social API endpoint to monitor
# Defaults to a Trump's account if not set
# API_URL=https://truthsocial.com/api/v1/accounts/ACCOUNT_ID/statuses?exclude_replies=true&with_muted=true

# Optional: How often to check for new posts, in seconds
# Defaults to 10 if not set
# CHECK_INTERVAL_SECONDS=10

# Required: Your Google Gemini API Key
GEMINI_API_KEY="YOUR_GEMINI_API_KEY"

# Required: Gmail address to send notifications FROM
SENDER_EMAIL="your_sender_email@gmail.com"

# Required: 16-character Gmail App Password for the SENDER_EMAIL
SENDER_APP_PASSWORD="YOUR_GMAIL_APP_PASSWORD"

# Required: Email address to send notifications TO
RECIPIENT_EMAIL="your_recipient_email@example.com"

# Optional: Add specific instructions or context for the Gemini AI analysis
# FOCUS="Analyze impact on tech stocks specifically."

# Optional: Set to "true" to receive an email for EVERY new post,
# regardless of Gemini's analysis. Defaults to "false".
# NOTIFY_ALL="false"
