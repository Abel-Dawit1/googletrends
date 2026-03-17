# Reddit Data Integration Setup

The dashboard can display real Reddit posts about healthcare topics. To enable this feature, follow these steps:

## Step 1: Create a Reddit App

**Note**: Reddit has updated their developer platform. Follow these steps:

1. Navigate to your Reddit user preferences: **https://www.reddit.com/user/[YOUR_USERNAME]/preferences/apps**
   (Replace `[YOUR_USERNAME]` with your Reddit username)

2. Scroll to the bottom where it says **"Authorized applications"** or **"Developed applications"**

3. Click **"Create an app"** or **"Create another app"**

4. Fill in the form:
   - **Name**: e.g., "Healthcare Analytics Dashboard"
   - **App type**: Select **"script"** (for personal script use)
   - **Description**: "Personal healthcare analytics application"
   - **Redirect URI**: `http://localhost:8000`

5. Click **"Create app"**

6. You'll see your credentials:
   - **Client ID**: The string shown below your app name
   - **Client Secret**: The password-like string labeled "secret"

For more details on Reddit's updated policies, see:
https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy

## Step 2: Configure the App

Choose one of these options:

### Option A: Streamlit Secrets (Recommended for Streamlit Cloud)

Create or edit `~/.streamlit/secrets.toml`:

```toml
REDDIT_CLIENT_ID = "your_client_id_here"
REDDIT_CLIENT_SECRET = "your_client_secret_here"
```

### Option B: Environment Variables (Local Development)

```bash
export REDDIT_CLIENT_ID="your_client_id_here"
export REDDIT_CLIENT_SECRET="your_client_secret_here"
streamlit run app.py
```

### Option C: Manual Entry in Streamlit Cloud

In your Streamlit Cloud settings, add these secrets:
- Key: `REDDIT_CLIENT_ID`, Value: your client ID
- Key: `REDDIT_CLIENT_SECRET`, Value: your client secret

## Step 3: Restart the App

Once credentials are configured, restart the Streamlit app:

```bash
streamlit run app.py
```

## Verification

When properly configured:
- ✅ Real Reddit posts will appear in the "Social Media Conversation" section
- ✅ Posts will be from r/Psoriasis, r/rheumatoidarthritis, etc.
- ✅ Sentiment analysis will work on actual discussion titles
- ✅ Upvote counts will reflect real engagement

If credentials aren't configured:
- 🔄 The app falls back to curated demo posts
- 💬 Demo posts still show realistic discussions from healthcare communities
- Everything continues to work normally

## Troubleshooting

**"403 Forbidden" errors?**
- Make sure you selected "script" app type, not "web app"
- Verify Client ID and Client Secret are correct (copy-paste carefully)
- Check that secrets are in the right location (`~/.streamlit/secrets.toml`)

**Still getting demo posts?**
- Check that environment variables are set: `echo $REDDIT_CLIENT_ID`
- Verify PRAW is installed: `pip show praw`
- Restart the app after setting secrets

## Privacy & Rate Limiting

- PRAW respects Reddit's rate limits (60 requests per minute)
- No user data is scraped (only public post titles and scores)
- Your credentials are never logged or shared
- This follows Reddit's Terms of Service for official API usage

For questions, see: https://praw.readthedocs.io/
