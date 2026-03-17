# Reddit Data Integration Setup

The dashboard can display real Reddit posts about healthcare topics. To enable this feature, follow these steps:

## Step 1: Create a Reddit App

1. Navigate to: **https://www.reddit.com/prefs/apps**
2. Click **"Create an app"** or **"Create another app"**
3. Fill in the form:
   - **Name**: e.g., "Healthcare Analytics Dashboard"
   - **App type**: Select **"script"** (important!)
   - **Description**: "Personal healthcare analytics application"
   - **Redirect URI**: `http://localhost:8000`
4. Click **"Create app"**
5. You'll see your credentials:
   - **Client ID**: Shown below the app name
   - **Client Secret**: The password-like string next to "secret"

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
