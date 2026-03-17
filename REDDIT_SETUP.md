# Reddit Data Integration Setup

The dashboard now displays **real Reddit posts** using RSS feeds — no authentication or app registration required!

## How It Works

Reddit provides RSS feeds for all subreddits at:
```
https://www.reddit.com/r/{subreddit}/.rss
```

The dashboard:
1. Fetches live RSS feeds from healthcare subreddits
2. Parses and filters posts by your search keywords
3. Displays real post titles and engagement metrics
4. Falls back to curated demo posts if RSS feeds are unavailable

## Subreddits Monitored

The app automatically searches these healthcare communities for discussions:
- r/Psoriasis
- r/rheumatoidarthritis
- r/AutoimmuneDiseases
- r/HealthAnxiety
- r/Health
- r/medical

## What You Get

✅ **Real Reddit data** from active communities  
✅ **No API authentication** needed  
✅ **No rate limiting** concerns  
✅ **Live post titles** relevant to your search  
✅ **Current discussions** from healthcare forums  
✅ **Graceful fallback** to demo data  

## Troubleshooting

**Not seeing Reddit posts?**
- Check your internet connection
- Verify the subreddits exist (Reddit may change community names)
- Check Streamlit Cloud logs for any errors

**Only seeing demo posts?**
- RSS feeds may be temporarily unavailable
- Try refreshing the page
- The fallback demo posts will continue to work

## Technical Details

The implementation uses:
- **feedparser**: Lightweight RSS feed parser (no external dependencies)
- **No credentials needed** – RSS feeds are publicly available
- **Public data only** – Respects Reddit's data scraping policies
- **Efficient caching** – Results cached for 30 minutes

For more information:
- [Reddit RSS Documentation](https://www.reddit.com/r/reddit.com/comments/wuo0th/rss_feeds_are_available_for_all_subreddits/)
- [Feedparser Library](https://pythonhosted.org/feedparser/)

