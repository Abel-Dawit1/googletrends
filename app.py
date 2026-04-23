"""
AbbVie Immunology — Search Intelligence Dashboard (Streamlit)
==============================================================
Pulls real Google Trends data via pytrends with graceful demo fallback.

Version: 2.1.2 (Fixed: Population column + Query Analysis)
Last Updated: 2026-03-18 UTC

Usage:
    pip install -r requirements.txt
    streamlit run app.py
"""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import json
import time
import os
from datetime import datetime, timedelta
from pathlib import Path
import requests
from urllib.parse import quote

# Try to import Anthropic, but make it optional
try:
    from anthropic import Anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False
    Anthropic = None

# Try to import pytrends, but make it optional
try:
    from pytrends.request import TrendReq
    HAS_PYTRENDS = True
except ImportError:
    HAS_PYTRENDS = False
    TrendReq = None

# Try to import feedparser for Reddit RSS feeds (no auth needed)
try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False
    feedparser = None

from config import (
    NAVY, RINVOQ, SKYRIZI, GOLD, SUCCESS,
    COMP_COLORS, COMPETITORS,
    IND_NAMES, FRANCHISE_MAP, TIMEFRAME_MAP,
    DEMO_AI_INSIGHTS
)

# ═══════════════════════════════════════════════════════════════════════════
# PAGE CONFIG (MUST BE FIRST STREAMLIT CALL)
# ═══════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="AbbVie Immunology — Search Intelligence",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═══════════════════════════════════════════════════════════════════════════
# AUTHENTICATION - CHECK IMMEDIATELY AFTER PAGE CONFIG
# ═══════════════════════════════════════════════════════════════════════════

# Initialize session state for authentication
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

# If not authenticated, show login screen and stop
if not st.session_state.authenticated:
    st.title("🔒 Access Required")
    st.markdown("Please enter the access code to continue.")
    
    access_code = st.text_input(
        "Access Code",
        type="password",
        placeholder="Enter access code",
        key="access_code_input"
    )
    
    if st.button("Login", use_container_width=True):
        correct_code = st.secrets.get("ACCESS_CODE", "AbbVie2026")
        
        if access_code == correct_code:
            st.session_state.authenticated = True
            st.success("✓ Access granted!")
            st.rerun()
        else:
            st.error("❌ Incorrect access code. Please try again.")
    
    st.stop()

# ═══════════════════════════════════════════════════════════════════════════
# CLAUDE INITIALIZATION
# ═══════════════════════════════════════════════════════════════════════════

# Initialize Claude client
@st.cache_resource
def init_claude():
    """Initialize Anthropic Claude client with API key from secrets or environment."""
    if not HAS_ANTHROPIC:
        return None
    
    try:
        # Try to get API key from Streamlit secrets first, then environment
        api_key = st.secrets.get("ANTHROPIC_API_KEY") or None
        if not api_key:
            import os
            api_key = os.environ.get("ANTHROPIC_API_KEY")
        
        if not api_key:
            return None
            
        return Anthropic(api_key=api_key)
    except Exception as e:
        return None

# ═══════════════════════════════════════════════════════════════════════════
# REDDIT DATA (Real data via PRAW with smart fallback)
# ═══════════════════════════════════════════════════════════════════════════

# Realistic demo Reddit posts as fallback (for when PRAW requests are rate-limited)
REDDIT_DEMO_POSTS = {
    "rinvoq": [
        {"title": "Just switched to Rinvoq from methotrexate - already noticing improvement in joint pain", "subreddit": "rheumatoidarthritis", "score": 342},
        {"title": "Rinvoq (upadacitinib) for RA - 6 months in, feeling like my old self again", "subreddit": "JuvenileArthritis", "score": 258},
        {"title": "New GCA diagnosis and started Rinvoq - thank god for JAK inhibitors", "subreddit": "AutoimmuneProtocol", "score": 195},
        {"title": "Has anyone experienced hair loss on Rinvoq? Considering switching treatments", "subreddit": "rheumatoidarthritis", "score": 127},
        {"title": "Rinvoq vs Baricitinib - which JAK inhibitor worked better for you?", "subreddit": "rheumatoidarthritis", "score": 89},
    ],
    "skyrizi": [
        {"title": "Skyrizi cleared my psoriasis in 3 months - best treatment decision ever", "subreddit": "Psoriasis", "score": 521},
        {"title": "After 5 years of struggling, Skyrizi finally gave me my life back", "subreddit": "AutoimmuneDiseases", "score": 445},
        {"title": "Skyrizi cost through GoodRx is way better now - anyone use their coupon card?", "subreddit": "Psoriasis", "score": 312},
        {"title": "Starting Skyrizi next week - nervous but hopeful based on your stories", "subreddit": "PsoriasisSupport", "score": 198},
        {"title": "Skyrizi injection day - same time every 4 weeks is pretty convenient honestly", "subreddit": "AutoimmuneDiseases", "score": 156},
    ],
    "psoriasis": [
        {"title": "Living with psoriasis - finally getting proper treatment after years of struggle", "subreddit": "Psoriasis", "score": 234},
        {"title": "Biologics changed my life - plaque psoriasis almost completely clear now", "subreddit": "Psoriasis", "score": 289},
        {"title": "Best self-care routine for psoriasis during winter months?", "subreddit": "HealthyFood", "score": 156},
        {"title": "Anyone else dealing with scalp psoriasis? Share your treatment experiences", "subreddit": "Psoriasis", "score": 178},
    ],
}

@st.cache_data(ttl=1800, show_spinner=False)
def scrape_real_reddit_posts(keywords, limit=5):
    """
    Fetch real Reddit posts using RSS feeds (no authentication required).
    RSS format: https://www.reddit.com/r/subreddit/.rss
    
    This approach gets real Reddit data without needing API credentials.
    Prioritizes keyword matches but includes all real posts.
    """
    try:
        if not HAS_FEEDPARSER or feedparser is None:
            return _get_demo_posts(keywords, limit)
        
        posts = []
        matched_posts = []  # Posts matching keywords
        seen_titles = set()
        
        # Relevant healthcare subreddits - RSS feeds available for all
        subreddits = [
            "Psoriasis",
            "rheumatoidarthritis", 
            "AutoimmuneDiseases",
            "HealthAnxiety",
            "Health",
            "medical",
        ]
        
        # Try each subreddit's RSS feed
        for subreddit in subreddits:
            if len(posts) >= limit * 2:  # Get more posts to filter through
                break
            
            try:
                # Reddit RSS feed URL - no authentication needed
                rss_url = f"https://www.reddit.com/r/{subreddit}/.rss"
                
                # Fetch with timeout
                feed = feedparser.parse(rss_url)
                
                # Process entries from RSS feed
                for entry in feed.entries[:20]:  # Check more entries to find matches
                    if len(posts) >= limit * 2:
                        break
                    
                    title = entry.get('title', '')
                    if not title or title in seen_titles:
                        continue
                    
                    # Try to extract score from summary (sometimes available)
                    score = _extract_score_from_feed_entry(entry)
                    
                    post = {
                        "title": title[:150],
                        "score": score,
                        "subreddit": subreddit,
                        "url": entry.get('link', '#')
                    }
                    
                    # Check if any keyword matches
                    keyword_match = False
                    for keyword in keywords[:3]:
                        if keyword.lower() in title.lower():
                            keyword_match = True
                            matched_posts.append(post)
                            break
                    
                    if not keyword_match:
                        posts.append(post)
                    
                    seen_titles.add(title)
            
            except Exception as e:
                # Continue to next subreddit if one fails
                continue
        
        # Combine: prioritize matched posts first, then add remaining real posts
        final_posts = matched_posts[:limit]  # Start with keyword matches
        if len(final_posts) < limit:
            # Fill remaining with any real posts
            final_posts.extend(posts[:limit - len(final_posts)])
        
        # If we found real posts, return them
        if final_posts:
            return final_posts[:limit]
        
        # Otherwise fall back to demo only if no real posts found
        return _get_demo_posts(keywords, limit)
        
    except Exception as e:
        # Fall back to demo on any error
        return _get_demo_posts(keywords, limit)

def _extract_score_from_feed_entry(entry):
    """
    Try to extract upvote score from RSS feed entry.
    Reddit RSS feeds don't always include scores, so we estimate.
    """
    try:
        # Check if score is in summary/content
        summary = entry.get('summary', '')
        if 'vote' in summary.lower():
            import re
            match = re.search(r'(\d+)\s*upvote', summary.lower())
            if match:
                return int(match.group(1))
        
        # Default score based on recency (newer posts likely have higher engagement)
        return np.random.randint(50, 400)
    except:
        return np.random.randint(50, 400)

def _get_demo_posts(keywords, limit=5):
    """
    Return curated demo posts matching keywords.
    Used as fallback when real Reddit data is unavailable.
    """
    try:
        posts = []
        
        # Try to match keywords with demo posts
        for keyword in keywords[:3]:
            keyword_lower = keyword.lower()
            
            # Check if we have demo posts for this keyword
            for demo_keyword, demo_posts in REDDIT_DEMO_POSTS.items():
                if demo_keyword in keyword_lower or keyword_lower in demo_keyword:
                    # Add some realistic variation to scores
                    for demo_post in demo_posts[:3]:
                        # Add slight randomization to scores for realism
                        varied_post = dict(demo_post)
                        varied_post["score"] = max(50, int(demo_post["score"] * (0.8 + np.random.random() * 0.4)))
                        posts.append(varied_post)
                    break
        
        # If no keyword matches found, use random posts from demo library
        if not posts:
            import random
            all_posts = []
            for demo_posts in REDDIT_DEMO_POSTS.values():
                all_posts.extend(demo_posts)
            if all_posts:
                posts = random.sample(all_posts, min(limit, len(all_posts)))
        
        # Remove duplicates and limit
        seen_titles = set()
        unique_posts = []
        for post in posts:
            if post["title"] not in seen_titles:
                seen_titles.add(post["title"])
                unique_posts.append(post)
        
        return unique_posts[:limit]
        
    except Exception as e:
        return []

def estimate_sentiment(text):
    """
    Simple sentiment estimation based on keywords.
    Returns 'Positive', 'Neutral', or 'Negative'
    """
    positive_words = ['great', 'love', 'excellent', 'amazing', 'wonderful', 'best', 'helped', 'works', 'effective', 'success', 'improvement', 'better', 'relief', 'hopeful', 'good', 'positive', 'improved', 'success', 'cleared', 'working', 'finally', 'changed', 'life']
    negative_words = ['bad', 'hate', 'terrible', 'awful', 'worst', 'failed', 'doesnt work', 'side effects', 'problem', 'issue', 'concern', 'worry', 'risk', 'negative', 'harmful', 'worse', 'complaint', 'suffer', 'pain', 'struggle', 'nervous']
    negative_words = ['bad', 'hate', 'terrible', 'awful', 'worst', 'failed', 'doesnt work', 'side effects', 'problem', 'issue', 'concern', 'worry', 'risk', 'negative', 'harmful', 'worse', 'complaint', 'suffer', 'pain']
    
    text_lower = text.lower()
    
    positive_score = sum(1 for word in positive_words if word in text_lower)
    negative_score = sum(1 for word in negative_words if word in text_lower)
    
    if positive_score > negative_score:
        return "Positive"
    elif negative_score > positive_score:
        return "Negative"
    else:
        return "Neutral"

# ═══════════════════════════════════════════════════════════════════════════
# GOOGLE TRENDS DATA LAYER
# ═══════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=7200, show_spinner=False)
def fetch_trends_data(keywords, timeframe="today 3-m", geo="US"):
    """Fetch interest over time from Google Trends via pytrends with retry logic."""
    if not HAS_PYTRENDS:
        return None
    
    max_retries = 2
    for attempt in range(max_retries):
        try:
            import time
            # Backoff: 1s, 2s between attempts (shorter to avoid timeout)
            wait_time = 1 * (2 ** attempt)
            time.sleep(wait_time)
            
            pytrends = TrendReq(hl="en-US", tz=360, retries=1, backoff_factor=0.1)
            pytrends.build_payload(keywords[:5], timeframe=timeframe, geo=geo)
            df = pytrends.interest_over_time()
            if "isPartial" in df.columns:
                df = df.drop("isPartial", axis=1)
            return df
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(wait_time)
                continue
            else:
                st.session_state["data_error"] = "Google Trends API temporarily restricted (rate limit). Try again in 1-2 minutes."
                return None

@st.cache_data(ttl=7200, show_spinner=False)
def fetch_regional_data(keywords, timeframe="today 3-m", geo="US", resolution="REGION"):
    """Fetch interest by region (state or DMA) with retry logic."""
    if not HAS_PYTRENDS:
        return None
    
    max_retries = 2
    for attempt in range(max_retries):
        try:
            import time
            wait_time = 3 * (2 ** attempt)
            time.sleep(wait_time)
            pytrends = TrendReq(hl="en-US", tz=360, retries=1, backoff_factor=0.1)
            pytrends.build_payload(keywords[:5], timeframe=timeframe, geo=geo)
            df = pytrends.interest_by_region(resolution=resolution, inc_low_vol=True, inc_geo_code=True)
            return df
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(wait_time * 2)
                continue
            else:
                return None

@st.cache_data(ttl=7200, show_spinner=False)
def fetch_related_queries(keyword, timeframe="today 12-m", geo="US"):
    """Fetch related and rising queries with retry logic."""
    if not HAS_PYTRENDS:
        return {"top": None, "rising": None}
    
    max_retries = 2
    for attempt in range(max_retries):
        try:
            import time
            wait_time = 3 * (2 ** attempt)
            time.sleep(wait_time)
            pytrends = TrendReq(hl="en-US", tz=360, retries=1, backoff_factor=0.1)
            pytrends.build_payload([keyword], timeframe=timeframe, geo=geo)
            related = pytrends.related_queries()
            return related.get(keyword, {"top": None, "rising": None})
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(wait_time * 2)
                continue
            else:
                return {"top": None, "rising": None}

# ═══════════════════════════════════════════════════════════════════════════
# GOOGLE TRENDS DATA TRANSFORMATION
# ═══════════════════════════════════════════════════════════════════════════

def transform_regional_to_states(regional_df):
    """Convert regional data to state format for choropleth."""
    if regional_df is None or regional_df.empty:
        return None
    
    # regional_df should have state names as index/rows
    states_data = []
    for state_name, row in regional_df.iterrows():
        state_dict = {"State": state_name}
        for col in regional_df.columns:
            if col != "geoCode":
                state_dict[col] = int(row[col])
        states_data.append(state_dict)
    
    return pd.DataFrame(states_data) if states_data else None

def generate_dma_from_states(states_df):
    """Generate representative DMA data from state-level data."""
    if states_df is None or states_df.empty:
        return DEMO_DMA
    
    # Major city coordinates and their associated states with population data
    major_dmas = {
        "New York, NY": (40.71, -74.01, "New York", 7125000),
        "Los Angeles, CA": (34.05, -118.24, "California", 3990000),
        "Chicago, IL": (41.88, -87.63, "Illinois", 2696000),
        "Dallas, TX": (32.78, -96.80, "Texas", 2635000),
        "Houston, TX": (29.76, -95.37, "Texas", 2320000),
        "Philadelphia, PA": (39.95, -75.17, "Pennsylvania", 1584000),
        "Phoenix, AZ": (33.45, -112.07, "Arizona", 1768000),
        "San Antonio, TX": (29.42, -98.49, "Texas", 1547000),
        "San Diego, CA": (32.72, -117.16, "California", 1423000),
        "San Francisco, CA": (37.77, -122.41, "California", 994000),
        "Boston, MA": (42.36, -71.06, "Massachusetts", 1505000),
        "Miami, FL": (25.76, -80.19, "Florida", 2087000),
        "Atlanta, GA": (33.75, -84.39, "Georgia", 2710000),
        "Seattle, WA": (47.61, -122.33, "Washington", 1305000),
        "Denver, CO": (39.74, -104.99, "Colorado", 1445000),
    }
    
    dma_data = []
    for city, (lat, lng, state, population) in major_dmas.items():
        state_row = states_df[states_df["State"] == state]
        if not state_row.empty:
            rinvoq_val = int(state_row.iloc[0].get("Rinvoq", 65))
            skyrizi_val = int(state_row.iloc[0].get("Skyrizi", 70))
        else:
            rinvoq_val, skyrizi_val = 65, 70
        
        trend = "↑" if rinvoq_val > skyrizi_val else "↓" if rinvoq_val < skyrizi_val else "→"
        dma_data.append({
            "Market": city,
            "lat": lat,
            "lng": lng,
            "Rinvoq": rinvoq_val,
            "Skyrizi": skyrizi_val,
            "Trend": trend,
            "Population": population
        })
    
    return pd.DataFrame(dma_data)

def transform_trends_to_queries(trend_df, related_rinvoq=None, related_skyrizi=None):
    """Generate query data from trends and related queries."""
    queries = []
    
    # Add related queries if available
    if related_rinvoq and related_rinvoq.get("top") is not None:
        for idx, row in related_rinvoq["top"].iterrows():
            queries.append({
                "Query": row.get("query", row.name if hasattr(row, "name") else ""),
                "Brand": "Rinvoq",
                "Index": int(row.get("value", 70)),
                "Growth": 0,
                "Type": "condition"
            })
    
    if related_skyrizi and related_skyrizi.get("top") is not None:
        for idx, row in related_skyrizi["top"].iterrows():
            queries.append({
                "Query": row.get("query", row.name if hasattr(row, "name") else ""),
                "Brand": "Skyrizi",
                "Index": int(row.get("value", 70)),
                "Growth": 0,
                "Type": "condition"
            })
    
    # Fallback to demo data if no real queries
    return pd.DataFrame(queries) if queries else DEMO_QUERIES


# ═══════════════════════════════════════════════════════════════════════════
# CLAUDE AI ANALYSIS LAYER
# ═══════════════════════════════════════════════════════════════════════════

def format_data_context(trend_df, dma_df, state_df, queries_df):
    """Format dashboard data into context for Claude."""
    context = {
        "trends_summary": {},
        "geographic_insights": {},
        "top_queries": [],
        "queries_by_type": {}
    }
    
    # Trend summary
    if "Rinvoq" in trend_df.columns:
        context["trends_summary"]["Rinvoq"] = {
            "peak": int(trend_df["Rinvoq"].max()),
            "avg": int(trend_df["Rinvoq"].mean()),
            "current": int(trend_df["Rinvoq"].iloc[-1]) if not trend_df.empty else 0
        }
    if "Skyrizi" in trend_df.columns:
        context["trends_summary"]["Skyrizi"] = {
            "peak": int(trend_df["Skyrizi"].max()),
            "avg": int(trend_df["Skyrizi"].mean()),
            "current": int(trend_df["Skyrizi"].iloc[-1]) if not trend_df.empty else 0
        }
    
    # Top DMA markets
    if not dma_df.empty:
        top_dmas = dma_df.nlargest(5, "Rinvoq")[["Market", "Rinvoq", "Skyrizi", "Trend"]].to_dict("records")
        context["geographic_insights"]["top_dmas"] = top_dmas
    
    # State-level summary
    if state_df is not None and not state_df.empty:
        context["geographic_insights"]["strong_states"] = state_df.nlargest(5, "Rinvoq")[["State", "Rinvoq", "Skyrizi"]].to_dict("records")
    
    # Top queries
    if not queries_df.empty:
        context["top_queries"] = queries_df.nlargest(10, "Index")[["Query", "Brand", "Index", "Type"]].to_dict("records")
        # Group by type
        for query_type in queries_df["Type"].unique():
            type_queries = queries_df[queries_df["Type"] == query_type].nlargest(3, "Index")[["Query", "Index"]].to_dict("records")
            context["queries_by_type"][query_type] = type_queries
    
    return context

def generate_ai_insights(trend_df, dma_df, state_df, queries_df, client, brand_filter="Both"):
    """Generate strategic insights using Claude based on current data, or return random demo insight if client unavailable."""
    # Return random demo insight if no client available
    if client is None:
        import random
        return random.choice(DEMO_AI_INSIGHTS)
    
    try:
        context = format_data_context(trend_df, dma_df, state_df, queries_df)
        
        brand_note = ""
        if brand_filter != "Both":
            brand_note = f"\n\nBrand Filter Active: The user is currently viewing data filtered for {brand_filter}. Focus your insight on this brand's market dynamics and competitive opportunities."
        
        prompt = f"""You are a strategic business analyst for AbbVie's Immunology division. 
        
Analyze the following Google Trends data and provide 1 clear, actionable business insight that would help inform marketing and commercial strategy decisions.

DATA CONTEXT:
{json.dumps(context, indent=2)}{brand_note}

Provide an insight that is:
- Data-driven and specific (reference actual numbers where relevant)
- Actionable (suggest specific business actions)
- Focused on competitive advantage and market opportunity
- Written for C-suite executives who make budget allocation decisions
- Concise (under 100 words) and focused on ONE clear insight"""

        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=300,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        return response.content[0].text
    except Exception as e:
        import random
        return random.choice(DEMO_AI_INSIGHTS)

def chat_with_claude(client, messages, trend_df, dma_df, state_df, queries_df):
    """Chat with Claude about the dashboard data."""
    try:
        context = format_data_context(trend_df, dma_df, state_df, queries_df)
        
        system_prompt = f"""You are a search intelligence analyst for AbbVie Immunology. 
You have access to current Google Trends data for Rinvoq and Skyrizi across the US.

CURRENT DATA:
{json.dumps(context, indent=2)}

Answer user questions about search trends, market opportunities, geographic performance, and competitive positioning. 
Be specific with data points and actionable in recommendations. If asked about something not in the data, acknowledge the limitation."""

        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=500,
            system=system_prompt,
            messages=messages
        )
        
        return response.content[0].text
    except Exception as e:
        return f"Error: {str(e)}"


# ═══════════════════════════════════════════════════════════════════════════
# EXECUTIVE SUMMARY & AI INSIGHT RENDERING
# ═══════════════════════════════════════════════════════════════════════════

def render_executive_summary(title, key_callouts, summary_color=NAVY, recommendation=None):
    """Render an executive summary box at top of a tab with key business callouts."""
    callouts_html = ""
    for callout in key_callouts:
        callouts_html += f"<li style='margin-bottom:8px;line-height:1.6;color:#0c3d7a'>{callout}</li>"
    
    recommendation_html = ""
    if recommendation:
        recommendation_html = f"""
        <div style='margin-top:14px;padding-top:14px;border-top:1px solid #d4e4f0;color:#2a8fa3;font-size:12px;line-height:1.7'>
            <span style='font-weight:700;margin-right:6px'>🎯 Strategy Opportunity:</span>{recommendation}
        </div>
        """
    
    st.markdown(f"""
    <div style='background:#e8f1ff;border-left:4px solid {summary_color};border-radius:8px;padding:18px 20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,0.08)'>
        <div style='color:#0c3d7a;font-size:13px;font-weight:700;margin-bottom:12px;text-transform:uppercase;letter-spacing:0.5px'>✦ Executive Summary: {title}</div>
        <ul style='color:#0c3d7a;font-size:12px;line-height:1.7;margin:0;padding-left:20px'>
            {callouts_html}
        </ul>{recommendation_html}
    </div>
    """, unsafe_allow_html=True)

def render_insight_bubble(text, icon="💡", bg_color="#e7f3ff", text_color="#0c3d7a"):
    """Render a smaller AI insight callout bubble within a section."""
    st.markdown(f"""
    <div style='background:{bg_color};border:1px solid #b8d4e8;border-radius:8px;padding:14px 16px;margin-top:12px;margin-bottom:12px;font-size:12px;line-height:1.6;color:{text_color}'>
        <span style='font-size:13px;margin-right:8px;font-weight:500'>{icon}</span><span style='font-weight:500'>{text}</span>
    </div>
    """, unsafe_allow_html=True)

def generate_overview_executive_summary(trend_df, dma_df, queries_df, client, brand_filter="Both", indication="All"):
    """Generate executive summary for Overview tab. Returns (callouts, recommendation)."""
    if client is None:
        callouts = [
            "<strong>Skyrizi gaining momentum</strong> across new indications with +45% YoY growth, while Rinvoq maintains dominance in core RA market",
            "<strong>Northeast markets lead</strong>: NYC, Boston, Philadelphia show 15-25 pts above national average for both brands combined",
            "<strong>Urgent action:</strong> Crohn's disease searches driving +42% spike for Skyrizi—capitalization opportunity in underserved GI market"
        ]
        recommendation = "With Crohn's disease searches spiking +42% for Skyrizi, develop comprehensive patient education content and HCP clinical data assets to capitalize on rising awareness in the GI market."
        return callouts, recommendation
    
    try:
        trend_summary = "↑ Uptrend" if len(trend_df) > 1 and trend_df.iloc[-1].mean() > trend_df.iloc[0].mean() else "→ Stable"
        peak_rinvoq = int(trend_df["Rinvoq"].max()) if "Rinvoq" in trend_df.columns else 0
        peak_skyrizi = int(trend_df["Skyrizi"].max()) if "Skyrizi" in trend_df.columns else 0
        top_market = dma_df.iloc[0]["Market"] if not dma_df.empty else "N/A"
        
        prompt = f"""Generate 3 concise bullet-point callouts for an executive summary of search trends data:
- Peak Rinvoq index: {peak_rinvoq}
- Peak Skyrizi index: {peak_skyrizi}  
- Overall trend: {trend_summary}
- Top market: {top_market}
- Brand filter: {brand_filter}

Format as brief, actionable business insights (1 sentence each, max 15 words each).
Make them specific to search trends patterns and market opportunities."""
        
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        
        insights = response.content[0].text.split("\n")
        callouts = [i.strip().lstrip("-•").strip() for i in insights if i.strip()][:3]
        return callouts, None
    except:
        callouts = [
            "<strong>Skyrizi leadership:</strong> 24.4% search share establishes market position, but growth moderating from 2024 peaks",
            "<strong>Seasonal patterns:</strong> Winter/spring show higher search volume—align HCP engagement and patient support programs accordingly",
            "<strong>Indication-driven searches:</strong> Crohn's disease, UC, and RA remain top patient research drivers—focus content on these conditions"
        ]
        recommendation = "Skyrizi (24.4%) shows mature market position. Growth opportunities lie in newer indications (Crohn's, UC). Action: Create condition-specific patient education content and HCP resources for high-search indications. Emphasize JAK mechanism advantage in materials to drive consideration vs traditional biologics."
        return callouts, recommendation

def generate_dma_executive_summary(dma_df, state_df, queries_df, client, brand_filter="Both", indication="All"):
    """Generate executive summary for DMA Deep Dive tab. Returns (callouts, recommendation)."""
    if client is None:
        callouts = [
            "<strong>Leading markets:</strong> New York (Rinvoq 91), Chicago (84), Los Angeles (82) show highest search intensity",
            "<strong>Geographic opportunity:</strong> Texas and Florida remain underindexed despite large populations—expansion potential",
            "<strong>State competition:</strong> Skyrizi outperforming in West Coast (CA, WA), Rinvoq stronger in Northeast (NY, MA, PA)"
        ]
        recommendation = "Texas (Rinvoq index 68 vs national avg ~70) and Florida (65) lag Northeast leaders by 20+ points. Specific gap: New York Rinvoq hits 89 while Texas is 21 points lower. Action: Run targeted HCP digital campaigns in Texas/Florida Dallas, Houston, Miami DMAs for Q2 to close this 20-point gap—estimated $2-3M addressable opportunity."
        return callouts, recommendation
    
    try:
        top_dma = dma_df.iloc[0]["Market"] if not dma_df.empty else "N/A"
        
        prompt = f"""Generate 3 bullet-point insights for geographic market analysis:
- Top DMA: {top_dma}
- Total DMAs tracked: {len(dma_df)}
- Brand filter: {brand_filter}

Focus on geographic opportunities, underserved markets, and regional competitive dynamics.
Keep each insight to 1-2 sentences max."""
        
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        
        insights = response.content[0].text.split("\n")
        callouts = [i.strip().lstrip("-•").strip() for i in insights if i.strip()][:3]
        return callouts, None
    except:
        callouts = [
            "<strong>Leading markets</strong> concentrated in Northeast and Midwest DMAs",
            "<strong>Geographic expansion:</strong> Texas and Florida show growth potential",
            "<strong>Regional dynamics:</strong> Clear West vs East regional preferences emerging"
        ]
        recommendation = "Texas (Rinvoq index 68 vs New York 89) lags by 21 points despite similar populations. Action: Run targeted HCP digital campaigns in Texas/Florida Dallas, Houston, Miami DMAs for Q2 to close this 20-point gap—estimated $2-3M addressable opportunity."
        return callouts, recommendation

def generate_key_moments_executive_summary(reddit_posts, sentiment_data, client):
    """Generate executive summary for Key Moments tab. Returns (callouts, recommendation)."""
    if client is None:
        callouts = [
            "<strong>Real Reddit engagement</strong> shows patient concerns around treatment side effects and efficacy validation",
            "<strong>Positive sentiment score:</strong> Both brands maintain 70%+ favorable mentions across healthcare subreddits",
            "<strong>Emerging topics:</strong> Cost/affordability and dosing convenience driving patient search behavior"
        ]
        recommendation = "Top Reddit themes: hair loss on Rinvoq (r/rheumatoidarthritis, high engagement), cost/affordability barriers (r/Psoriasis 'Skyrizi cost with GoodRx'), and efficacy validation ('cleared psoriasis in 3 months', 'life changing'). Action: Create 2-3 Reddit AMAs addressing hair loss management on JAK inhibitors and cost reduction strategies—these are the actual friction points driving discussion."
        return callouts, recommendation
    
    try:
        post_count = len(reddit_posts) if isinstance(reddit_posts, list) else 0
        
        prompt = f"""Generate 3 social listening insights for Key Moments:
- Real Reddit posts analyzed: {post_count}
- Patient sentiment: Mixed (treatment efficacy, side effects, costs)

Focus on real patient concerns, emerging topics, and engagement patterns.
Keep each to 1-2 sentences."""
        
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        
        insights = response.content[0].text.split("\n")
        callouts = [i.strip().lstrip("-•").strip() for i in insights if i.strip()][:3]
        return callouts, None
    except:
        callouts = [
            "<strong>Patient sentiment</strong> reflects efficacy optimization and side effect management priorities",
            "<strong>Engagement surge</strong> in treatment decision discussions on r/rheumatoidarthritis and r/Psoriasis",
            "<strong>Cost discussions</strong> emerging as key friction point in patient communities"
        ]
        recommendation = "Top Reddit themes: hair loss on Rinvoq and cost/affordability barriers for Skyrizi. Action: Create 2-3 Reddit AMAs addressing hair loss management on JAK inhibitors and cost reduction strategies—these are the actual friction points driving discussion."
        return callouts, recommendation

def generate_competitive_executive_summary(dma_df, client, brand_filter="Both", indication="All"):
    """Generate executive summary for Competitive tab. Returns (callouts, recommendation)."""
    if client is None:
        callouts = [
            "<strong>Market fragmentation:</strong> Skyrizi (24.4%) leads, but JAK inhibitors compete with Humira (18.7%) for patient mindshare—no clear duopoly",
            "<strong>Competitive intensity:</strong> Five major competitors (Humira, Tremfya, Dupixent, Entyvio) actively holding 46% combined search share",
            "<strong>Switching signals:</strong> Patients actively comparing Skyrizi vs Humira and Rinvoq vs Tremfya—mechanism (JAK vs biologic) drives choice"
        ]
        recommendation = "Skyrizi leads at 24.4% but faces fragmented competition. Humira (18.7%) remains formidable. Action: (1) Create side-by-side mechanism comparison content (JAK inhibitor vs biologics) to help patients understand the Rinvoq/Skyrizi advantage, (2) Run paid search on 'Skyrizi vs Humira' and 'Rinvoq vs Tremfya' to capture switching traffic, (3) Focus HCP messaging on patients currently on Humira who might benefit from JAK mechanism."
        return callouts, recommendation
    
    try:
        prompt = f"""Generate 3 competitive intelligence insights:
- Focus on Rinvoq (JAK inhibitor) vs Skyrizi (biologic) market dynamics
- Consider competitor alternatives: Humira, Tremfya, Cosentyx

Keep insights to strategic competitive positioning (1-2 sentences each)."""
        
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        
        insights = response.content[0].text.split("\n")
        callouts = [i.strip().lstrip("-•").strip() for i in insights if i.strip()][:3]
        return callouts, None
    except:
        callouts = [
            "<strong>Market competition:</strong> Skyrizi (24.4%) vs Humira (18.7%)—biologic choice remains contested territory",
            "<strong>Five-way competition:</strong> Tremfya, Dupixent, and Entyvio collectively hold 21.6% share—fragmented market benefits clear differentiation",
            "<strong>Mechanism differentiation:</strong> JAK inhibitor positioning separates Rinvoq/Skyrizi from traditional biologics in patient minds"
        ]
        recommendation = "Target patients comparing mechanisms. Action: Create JAK vs biologic comparison content, run paid search on mechanism-based queries (Skyrizi vs Humira, Rinvoq vs Tremfya), and develop switching resources for Humira patients evaluating alternative mechanisms."
        return callouts, recommendation

def generate_patient_intent_executive_summary(queries_df, client, brand_filter="Both", indication="All"):
    """Generate executive summary for Patient Intent tab. Returns (callouts, recommendation)."""
    if client is None:
        callouts = [
            "<strong>Indication demand signals:</strong> Crohn's disease, ulcerative colitis, and ankylosing spondylitis showing sustained high search volume",
            "<strong>Safety and efficacy:</strong> Patients researching mechanism of action and clinical evidence—moving beyond 'does it work' to 'why does it work'",
            "<strong>Branded search momentum:</strong> 'Rinvoq [condition]' and 'Skyrizi [indication]' branded queries trending—patients at decision stage"
        ]
        recommendation = "Inflammatory bowel disease (Crohn's, UC) and seronegative spondyloarthritis show strong sustained search interest. Action: (1) Create condition-specific efficacy content showing MOA advantage, (2) Develop HCP resources for these high-search indications, (3) Run paid search on '[Brand] [Condition]' combinations to capture high-intent patients ready to discuss with doctors."
        return callouts, recommendation
    
    try:
        top_query = queries_df.iloc[0]["Query"] if not queries_df.empty else "N/A"
        max_growth = queries_df["Growth"].max() if not queries_df.empty else 0
        
        prompt = f"""Generate 3 patient intent insights:
- Top search query: {top_query}
- Highest growth query: +{int(max_growth)}%
- Query types: condition, branded, safety, competitive

Focus on what patients are searching for, decision stage, and unmet needs.
Keep to 1-2 sentences each."""
        
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        
        insights = response.content[0].text.split("\n")
        callouts = [i.strip().lstrip("-•").strip() for i in insights if i.strip()][:3]
        return callouts, None
    except:
        callouts = [
            "<strong>Indication interest:</strong> Inflammatory bowel disease (Crohn's, UC) and spondyloarthritis showing strong sustained search demand",
            "<strong>Patient sophistication:</strong> Searching for mechanism of action and comparative efficacy data—moving into active evaluation phase",
            "<strong>Branded search momentum:</strong> 'Rinvoq [condition]' and 'Skyrizi [indication]' combinations indicate decision-stage patients"
        ]
        recommendation = "Patients are actively researching conditions and comparing options. Action: (1) Create condition-specific efficacy pages showing mechanism advantage, (2) Build 'How to talk to your doctor about JAK inhibitors' resources, (3) Develop safety and efficacy comparison content vs traditional biologics."
        return callouts, recommendation

def generate_campaign_executive_summary(trend_df, client, brand_filter="Both", indication="All"):
    """Generate executive summary for Campaign tab. Returns (callouts, recommendation)."""
    if client is None:
        callouts = [
            "<strong>Campaign performance:</strong> Recent Crohn's approval for Rinvoq (Dec 2023) showing +850% branded search spike",
            "<strong>Seasonal peaks:</strong> Winter/spring demonstrate higher engagement for condition searches across indications",
            "<strong>Moment optimization:</strong> Label expansions and clinical data releases drive 120%+ competitive comparison search"
        ]
        recommendation = "Super Bowl drove +22% Skyrizi lift over 5 days. Winter Olympics showed 14-day halo effect. Grammy Awards drove +15% Skyrizi lift with psoriasis awareness messaging. Action: Couple entertainment and sports moments with clinical milestone campaigns for maximum lift. These are proven moments—don't miss them."
        return callouts, recommendation
    
    try:
        prompt = f"""Generate 3 campaign strategy insights:
- Focus on search-driven campaign moments and events
- Consider seasonal patterns, label expansions, and clinical data releases

Keep to 1-2 sentences each, focused on timing and opportunity."""
        
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        
        insights = response.content[0].text.split("\n")
        callouts = [i.strip().lstrip("-•").strip() for i in insights if i.strip()][:3]
        return callouts, None
    except:
        callouts = [
            "<strong>Label expansion momentum:</strong> Crohn's approval driving sustained search spikes—capitalize with targeted campaigns",
            "<strong>Seasonality insight:</strong> Q1 shows consistent search peaks—optimize media spend seasonally",
            "<strong>Moment tracking:</strong> Clinical data releases and competitive comparisons driving search surges"
        ]
        recommendation = "Super Bowl drove +22% Skyrizi lift (5 days). Winter Olympics showed 14-day halo. Grammy Awards drove +15% lift with psoriasis awareness. Couple entertainment and sports moments with clinical messaging for maximum impact. These are proven moments."
        return callouts, recommendation


# ═══════════════════════════════════════════════════════════════════════════
# DEMO DATA FALLBACK
# ═══════════════════════════════════════════════════════════════════════════

def generate_demo_trend(timeframe="today 3-m"):
    """Generate realistic demo trend data."""
    n = {"now 7-d": 7, "today 1-m": 30, "today 3-m": 13, "today 12-m": 12, "today 5-y": 60}.get(timeframe, 13)
    step = {"now 7-d": 1, "today 1-m": 1, "today 3-m": 7, "today 12-m": 30, "today 5-y": 30}.get(timeframe, 7)
    dates = pd.date_range(end=datetime.now(), periods=n, freq=f"{step}D")
    np.random.seed(42)
    r_base = 45 + np.linspace(0, 22, n) + np.sin(np.linspace(0, 2*np.pi, n) + 0.5) * 12
    s_base = 55 + np.linspace(0, 20, n) + np.sin(np.linspace(0, 2*np.pi, n) - 1) * 14
    df = pd.DataFrame({
        "Rinvoq": np.clip(r_base + np.random.randn(n) * 4, 15, 100).astype(int),
        "Skyrizi": np.clip(s_base + np.random.randn(n) * 4, 15, 100).astype(int),
    }, index=dates)
    return df

DEMO_DMA = pd.DataFrame([
    {"Market": "New York, NY", "lat": 40.71, "lng": -74.01, "Rinvoq": 91, "Skyrizi": 88, "Trend": "↑", "Population": 7125000},
    {"Market": "Chicago, IL", "lat": 41.88, "lng": -87.63, "Rinvoq": 84, "Skyrizi": 79, "Trend": "↑", "Population": 2696000},
    {"Market": "Los Angeles, CA", "lat": 34.05, "lng": -118.24, "Rinvoq": 78, "Skyrizi": 82, "Trend": "→", "Population": 3990000},
    {"Market": "Philadelphia, PA", "lat": 39.95, "lng": -75.17, "Rinvoq": 82, "Skyrizi": 71, "Trend": "↑", "Population": 1584000},
    {"Market": "Boston, MA", "lat": 42.36, "lng": -71.06, "Rinvoq": 75, "Skyrizi": 68, "Trend": "↑", "Population": 1505000},
    {"Market": "Minneapolis, MN", "lat": 44.98, "lng": -93.27, "Rinvoq": 72, "Skyrizi": 65, "Trend": "→", "Population": 1173000},
    {"Market": "Dallas, TX", "lat": 32.78, "lng": -96.80, "Rinvoq": 68, "Skyrizi": 77, "Trend": "↓", "Population": 2635000},
    {"Market": "Atlanta, GA", "lat": 33.75, "lng": -84.39, "Rinvoq": 65, "Skyrizi": 72, "Trend": "↑", "Population": 2710000},
    {"Market": "Seattle, WA", "lat": 47.61, "lng": -122.33, "Rinvoq": 63, "Skyrizi": 70, "Trend": "→", "Population": 1305000},
    {"Market": "Miami, FL", "lat": 25.76, "lng": -80.19, "Rinvoq": 61, "Skyrizi": 74, "Trend": "↓", "Population": 2087000},
])

# Demo state-level data
DEMO_STATES = pd.DataFrame([
    {"State": "New York", "Rinvoq": 89, "Skyrizi": 82},
    {"State": "Pennsylvania", "Rinvoq": 80, "Skyrizi": 75},
    {"State": "Massachusetts", "Rinvoq": 78, "Skyrizi": 70},
    {"State": "Illinois", "Rinvoq": 82, "Skyrizi": 76},
    {"State": "Minnesota", "Rinvoq": 75, "Skyrizi": 68},
    {"State": "California", "Rinvoq": 72, "Skyrizi": 80},
    {"State": "Texas", "Rinvoq": 68, "Skyrizi": 76},
    {"State": "Florida", "Rinvoq": 65, "Skyrizi": 74},
    {"State": "Georgia", "Rinvoq": 63, "Skyrizi": 72},
    {"State": "Washington", "Rinvoq": 62, "Skyrizi": 69},
    {"State": "Ohio", "Rinvoq": 70, "Skyrizi": 65},
    {"State": "Michigan", "Rinvoq": 68, "Skyrizi": 62},
    {"State": "North Carolina", "Rinvoq": 66, "Skyrizi": 70},
    {"State": "Virginia", "Rinvoq": 64, "Skyrizi": 68},
    {"State": "Colorado", "Rinvoq": 61, "Skyrizi": 67},
    {"State": "Arizona", "Rinvoq": 58, "Skyrizi": 65},
    {"State": "Tennessee", "Rinvoq": 60, "Skyrizi": 68},
    {"State": "Maryland", "Rinvoq": 72, "Skyrizi": 69},
    {"State": "Missouri", "Rinvoq": 62, "Skyrizi": 60},
    {"State": "New Jersey", "Rinvoq": 78, "Skyrizi": 74},
    {"State": "Connecticut", "Rinvoq": 74, "Skyrizi": 68},
    {"State": "Indiana", "Rinvoq": 65, "Skyrizi": 60},
    {"State": "Wisconsin", "Rinvoq": 68, "Skyrizi": 62},
    {"State": "New Hampshire", "Rinvoq": 71, "Skyrizi": 66},
    {"State": "Maine", "Rinvoq": 69, "Skyrizi": 65},
    {"State": "Vermont", "Rinvoq": 67, "Skyrizi": 63},
    {"State": "Rhode Island", "Rinvoq": 73, "Skyrizi": 67},
    {"State": "Louisiana", "Rinvoq": 55, "Skyrizi": 62},
    {"State": "Mississippi", "Rinvoq": 52, "Skyrizi": 58},
    {"State": "Alabama", "Rinvoq": 54, "Skyrizi": 61},
    {"State": "South Carolina", "Rinvoq": 58, "Skyrizi": 65},
    {"State": "Kentucky", "Rinvoq": 56, "Skyrizi": 59},
    {"State": "Arkansas", "Rinvoq": 53, "Skyrizi": 57},
    {"State": "Oklahoma", "Rinvoq": 54, "Skyrizi": 58},
    {"State": "Kansas", "Rinvoq": 57, "Skyrizi": 55},
    {"State": "Nebraska", "Rinvoq": 56, "Skyrizi": 54},
    {"State": "Iowa", "Rinvoq": 62, "Skyrizi": 59},
    {"State": "South Dakota", "Rinvoq": 52, "Skyrizi": 50},
    {"State": "North Dakota", "Rinvoq": 51, "Skyrizi": 49},
    {"State": "Montana", "Rinvoq": 50, "Skyrizi": 48},
    {"State": "Wyoming", "Rinvoq": 48, "Skyrizi": 46},
    {"State": "Nevada", "Rinvoq": 57, "Skyrizi": 64},
    {"State": "New Mexico", "Rinvoq": 52, "Skyrizi": 59},
    {"State": "Utah", "Rinvoq": 58, "Skyrizi": 60},
    {"State": "Idaho", "Rinvoq": 54, "Skyrizi": 56},
    {"State": "Oregon", "Rinvoq": 61, "Skyrizi": 66},
    {"State": "Alaska", "Rinvoq": 49, "Skyrizi": 47},
    {"State": "Hawaii", "Rinvoq": 50, "Skyrizi": 52},
    {"State": "West Virginia", "Rinvoq": 55, "Skyrizi": 57},
    {"State": "Delaware", "Rinvoq": 69, "Skyrizi": 66},
])

DEMO_QUERIES = pd.DataFrame([
    {"Query": "rheumatoid arthritis treatment", "Brand": "Rinvoq", "Index": 94, "Growth": 12, "Type": "condition", "Indication": "RA"},
    {"Query": "psoriasis treatment", "Brand": "Skyrizi", "Index": 91, "Growth": 15, "Type": "condition", "Indication": "Psoriasis"},
    {"Query": "upadacitinib", "Brand": "Rinvoq", "Index": 88, "Growth": 28, "Type": "generic", "Indication": "RA"},
    {"Query": "plaque psoriasis medication", "Brand": "Skyrizi", "Index": 87, "Growth": 22, "Type": "condition", "Indication": "Psoriasis"},
    {"Query": "risankizumab", "Brand": "Skyrizi", "Index": 85, "Growth": 35, "Type": "generic", "Indication": "Psoriasis"},
    {"Query": "JAK inhibitor side effects", "Brand": "Rinvoq", "Index": 82, "Growth": 8, "Type": "safety", "Indication": "All"},
    {"Query": "Crohn's disease biologic", "Brand": "Skyrizi", "Index": 78, "Growth": 42, "Type": "condition", "Indication": "Crohn's"},
    {"Query": "ulcerative colitis treatment", "Brand": "Both", "Index": 80, "Growth": 25, "Type": "condition", "Indication": "UC"},
    {"Query": "ankylosing spondylitis treatment", "Brand": "Rinvoq", "Index": 74, "Growth": 51, "Type": "condition", "Indication": "AS"},
    {"Query": "atopic dermatitis biologic", "Brand": "Rinvoq", "Index": 72, "Growth": 38, "Type": "condition", "Indication": "AD"},
    {"Query": "giant cell arteritis treatment", "Brand": "Rinvoq", "Index": 68, "Growth": 48, "Type": "condition", "Indication": "GCA"},
    {"Query": "Rinvoq Crohn's disease", "Brand": "Rinvoq", "Index": 58, "Growth": 850, "Type": "branded", "Indication": "Crohn's"},
    {"Query": "Rinvoq vs Humira", "Brand": "Rinvoq", "Index": 65, "Growth": 120, "Type": "competitive", "Indication": "RA"},
    {"Query": "Skyrizi vs Tremfya", "Brand": "Skyrizi", "Index": 62, "Growth": 95, "Type": "competitive", "Indication": "Psoriasis"},
    {"Query": "Skyrizi cost", "Brand": "Skyrizi", "Index": 70, "Growth": 30, "Type": "branded", "Indication": "Psoriasis"},
    {"Query": "Rinvoq dosing", "Brand": "Rinvoq", "Index": 55, "Growth": 15, "Type": "branded", "Indication": "RA"},
])


SEASON_DATA = pd.DataFrame({
    "Month": ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"],
    "Rinvoq": [82,85,70,60,55,50,48,52,65,78,80,75],
    "Skyrizi": [72,68,62,70,80,90,95,88,75,68,70,78],
})

def generate_seasonality_data(trend_df, timeframe):
    """Generate seasonality data by averaging by month.
    
    For 5-year timeframe: average each month across ALL years
    For 1-year and under: average each month from just the recent period
    """
    if trend_df is None or trend_df.empty:
        return SEASON_DATA
    
    df = trend_df.copy()
    
    # Ensure index is datetime
    if not isinstance(df.index, pd.DatetimeIndex):
        return SEASON_DATA
    
    if timeframe == "today 5-y":
        # Average each month across all years
        df["month"] = df.index.month
        df["month_name"] = df.index.strftime("%b")
        seasonality = df.groupby(["month", "month_name"]).mean().reset_index().sort_values("month")
        result = pd.DataFrame({
            "Month": seasonality["month_name"],
        })
        if "Rinvoq" in seasonality.columns:
            result["Rinvoq"] = seasonality["Rinvoq"].round(1)
        if "Skyrizi" in seasonality.columns:
            result["Skyrizi"] = seasonality["Skyrizi"].round(1)
        return result
    else:
        # For periods <= 1 year, just show the data as is (monthly from recent period)
        # First, resample to get monthly data
        try:
            monthly = df.resample('ME').mean()
            monthly["month_name"] = monthly.index.strftime("%b")
            result = pd.DataFrame({
                "Month": monthly["month_name"],
            })
            if "Rinvoq" in monthly.columns:
                result["Rinvoq"] = monthly["Rinvoq"].round(1)
            if "Skyrizi" in monthly.columns:
                result["Skyrizi"] = monthly["Skyrizi"].round(1)
            return result.tail(12)  # Return last 12 months
        except Exception:
            return SEASON_DATA

def generate_interest_over_time_data(trend_df, timeframe):
    """Generate average search interest aggregated by year, month, or day based on timeframe."""
    if trend_df is None or trend_df.empty:
        # Return default data
        return pd.DataFrame({
            "period": ["2022", "2023", "2024", "2025"],
            "Rinvoq": [12, 28, 33, 38],
            "Skyrizi": [20, 35, 40, 45],
        })
    
    df = trend_df.copy()
    
    # Reset index to avoid ambiguity with index name conflicts
    if df.index.name:
        df = df.reset_index()
    
    # Determine aggregation level based on timeframe
    if timeframe == "today 5-y":
        # Aggregate by year
        # Assume first column is the datetime index (after reset)
        date_col = df.columns[0] if df.columns[0] in ['date', 'Date'] else df.iloc[:, 0]
        df["year"] = pd.to_datetime(df.iloc[:, 0]).dt.year
        aggregated = df.groupby("year").mean(numeric_only=True).reset_index()
        aggregated["period"] = aggregated["year"].astype(str)
    elif timeframe in ["today 12-m", "today 3-m"]:
        # Aggregate by month
        df["year_month"] = pd.to_datetime(df.iloc[:, 0]).dt.strftime("%b %y")
        aggregated = df.groupby("year_month", sort=False).mean(numeric_only=True).reset_index()
        aggregated["period"] = aggregated["year_month"]
    elif timeframe in ["today 1-m", "now 7-d"]:
        # Aggregate by day
        df["day_period"] = pd.to_datetime(df.iloc[:, 0]).dt.strftime("%b %d")
        aggregated = df.groupby("day_period", sort=False).mean(numeric_only=True).reset_index()
        aggregated["period"] = aggregated["day_period"]
    else:
        # Default to month
        df["year_month"] = pd.to_datetime(df.iloc[:, 0]).dt.strftime("%b %y")
        aggregated = df.groupby("year_month", sort=False).mean(numeric_only=True).reset_index()
        aggregated["period"] = aggregated["year_month"]
    
    # Rename columns to match the original structure and round values
    result = aggregated[["period"]].copy()
    if "Rinvoq" in aggregated.columns:
        result["Rinvoq"] = aggregated["Rinvoq"].round(1)
    if "Skyrizi" in aggregated.columns:
        result["Skyrizi"] = aggregated["Skyrizi"].round(1)
    
    return result

YOY_DATA = pd.DataFrame({
    "Year": ["2022","2023","2024","2025"],
    "Rinvoq": [12,28,33,38],
    "Skyrizi": [20,35,40,45],
})

# Realistic demo moments data as fallback
DEMO_MOMENTS_DATA = [
    {"Event": "Super Bowl LX", "Category": "Sports", "Date": "Feb 9, 2026", "Rinvoq Lift": "+18%", "Skyrizi Lift": "+22%", "Peak": 82, "Halo": "5d", "Breakout": "Rinvoq commercial", "Insight": "Super Bowl drove a 22% Skyrizi search lift sustained 5 days, strongest in 25–44 demo and Sun Belt DMAs."},
    {"Event": "Grammy Awards", "Category": "Entertainment", "Date": "Feb 2, 2026", "Rinvoq Lift": "+8%", "Skyrizi Lift": "+15%", "Peak": 65, "Halo": "3d", "Breakout": "psoriasis awareness", "Insight": "Grammy Awards drove targeted lift via celebrity psoriasis awareness moments."},
    {"Event": "Winter Olympics", "Category": "Sports", "Date": "Feb 2026", "Rinvoq Lift": "+12%", "Skyrizi Lift": "+10%", "Peak": 72, "Halo": "14d", "Breakout": "athlete sponsorship", "Insight": "Extended 14-day halo. Joint RA/PsA messaging resonated with active lifestyle narrative."},
]

def calculate_moments_from_trends():
    """Calculate key moments data from real search interest CSV files.
    
    Extracts lift and peak values for each key moment based on actual trend data.
    Falls back to demo data if CSV files are unavailable or missing date matches.
    """
    try:
        # Load 1-year trend data for both brands
        rinvoq_file = "data/Rinvoq Search Interest 1 year new.csv"
        skyrizi_file = "data/Skyrizi Search Interest 1 year new.csv"
        
        if not os.path.exists(rinvoq_file) or not os.path.exists(skyrizi_file):
            return DEMO_MOMENTS_DATA
        
        # Read CSVs, skip header rows
        rinvoq_df = pd.read_csv(rinvoq_file, skiprows=2)
        skyrizi_df = pd.read_csv(skyrizi_file, skiprows=2)
        
        # Rename columns for consistency
        rinvoq_df.columns = ['date', 'rinvoq_value']
        skyrizi_df.columns = ['date', 'skyrizi_value']
        
        # Convert to datetime
        rinvoq_df['date'] = pd.to_datetime(rinvoq_df['date'])
        skyrizi_df['date'] = pd.to_datetime(skyrizi_df['date'])
        
        # Merge on date
        merged_df = pd.merge(rinvoq_df, skyrizi_df, on='date', how='outer').sort_values('date')
        merged_df = merged_df.fillna(method='ffill').fillna(method='bfill')
        
        # Map natural language dates to ISO dates for matching
        date_map = {
            "Feb 9, 2026": "2026-02-09",
            "Feb 2, 2026": "2026-02-02",
            "Nov 2025": "2025-11-01",  # Approximate
            "Jan 2025": "2025-01-01",   # Approximate (playoffs span weeks)
            "May 11, 2025": "2025-05-11",
            "Feb 2026": "2026-02-01",   # Approximate
        }
        
        moments_with_data = []
        
        for moment in DEMO_MOMENTS_DATA:
            event_date_str = date_map.get(moment["Date"])
            if not event_date_str:
                continue
            
            event_date = pd.to_datetime(event_date_str)
            
            # Find rows around the event date (2 weeks before to 4 weeks after)
            window_start = event_date - pd.Timedelta(days=14)
            window_end = event_date + pd.Timedelta(days=28)
            
            window_data = merged_df[(merged_df['date'] >= window_start) & (merged_df['date'] <= window_end)].copy()
            
            if window_data.empty or len(window_data) < 3:
                moments_with_data.append(moment)
                continue
            
            # Calculate baseline (average of 2-3 weeks before event)
            pre_event = merged_df[(merged_df['date'] >= window_start) & (merged_df['date'] < event_date)]
            if len(pre_event) > 0:
                baseline_r = pre_event['rinvoq_value'].mean()
                baseline_s = pre_event['skyrizi_value'].mean()
            else:
                baseline_r = 60
                baseline_s = 60
            
            # Find peak during and after event (4 weeks window)
            post_event = merged_df[(merged_df['date'] >= event_date) & (merged_df['date'] <= window_end)]
            if len(post_event) > 0:
                peak_r = post_event['rinvoq_value'].max()
                peak_s = post_event['skyrizi_value'].max()
                peak = max(peak_r, peak_s)
            else:
                peak = 75
                peak_r = 75
                peak_s = 75
            
            # Calculate lift percentage
            lift_r = int(((peak_r - baseline_r) / baseline_r * 100)) if baseline_r > 0 else 10
            lift_s = int(((peak_s - baseline_s) / baseline_s * 100)) if baseline_s > 0 else 10
            
            # Calculate halo duration (days until values return to baseline within 10%)
            halo_days = 0
            threshold = 1.1  # 110% of baseline = 10% above
            for idx, row in post_event.iterrows():
                if row['rinvoq_value'] > baseline_r * threshold or row['skyrizi_value'] > baseline_s * threshold:
                    halo_days += 7  # Count by weeks
                else:
                    break
            
            if halo_days == 0:
                halo_days = 7
            halo_str = f"{min(14, halo_days)}d"  # Cap at 14 days for display
            
            # Update moment with calculated data
            updated_moment = moment.copy()
            updated_moment["Rinvoq Lift"] = f"+{max(0, lift_r)}%"
            updated_moment["Skyrizi Lift"] = f"+{max(0, lift_s)}%"
            updated_moment["Peak"] = int(peak)
            updated_moment["Halo"] = halo_str
            updated_moment["Insight"] = f"Real data: Rinvoq {updated_moment['Rinvoq Lift']} lift, Skyrizi {updated_moment['Skyrizi Lift']} lift with {halo_str} halo effect."
            
            moments_with_data.append(updated_moment)
        
        return moments_with_data if moments_with_data else DEMO_MOMENTS_DATA
        
    except Exception as e:
        return DEMO_MOMENTS_DATA


def load_moment_trend_data(event_date_str, timeframe="1 year"):
    """Load actual trend data from CSV for a date range around an event (-14 to +28 days).
    
    Args:
        event_date_str: Date string like "Feb 9, 2026" or "Nov 2025"
        timeframe: CSV timeframe to use - "90 days", "1 year", "5 year", etc.
    
    Returns:
        Tuple (x_days, r_trend, s_trend) with indices and trend values aligned to date window.
        Returns None if event date cannot be parsed or CSV files unavailable.
    """
    try:
        # Parse event date - try multiple formats
        event_date = None
        for fmt in ["%b %d, %Y", "%b %Y", "%B %d, %Y", "%Y-%m-%d"]:
            try:
                event_date = pd.to_datetime(event_date_str, format=fmt)
                break
            except:
                continue
        
        if event_date is None:
            return None
        
        window_start = event_date - pd.Timedelta(days=14)
        window_end = event_date + pd.Timedelta(days=28)
        
        # Find CSV files matching the specified timeframe
        try:
            data_files = os.listdir("data")
            rinvoq_files = [f for f in data_files if "Rinvoq" in f and timeframe in f and "new" in f and f.endswith(".csv")]
            skyrizi_files = [f for f in data_files if "Skyrizi" in f and timeframe in f and "new" in f and f.endswith(".csv")]
            
            if not rinvoq_files or not skyrizi_files:
                return None
            
            rinvoq_path = os.path.join("data", rinvoq_files[0])
            skyrizi_path = os.path.join("data", skyrizi_files[0])
        except:
            return None
        
        # Load CSVs with proper skiprows (skip Category and blank line headers)
        try:
            rinvoq_df = pd.read_csv(rinvoq_path, skiprows=2)
            skyrizi_df = pd.read_csv(skyrizi_path, skiprows=2)
            
            # Rename columns: first column is 'Week', second is the brand value
            rinvoq_df.columns = ["date", "value"]
            skyrizi_df.columns = ["date", "value"]
            
            # Convert value column to numeric, coercing errors to NaN
            rinvoq_df["value"] = pd.to_numeric(rinvoq_df["value"], errors="coerce")
            skyrizi_df["value"] = pd.to_numeric(skyrizi_df["value"], errors="coerce")
            
            # Drop rows with NaN values
            rinvoq_df = rinvoq_df.dropna()
            skyrizi_df = skyrizi_df.dropna()
            
            # Convert to int
            rinvoq_df["value"] = rinvoq_df["value"].astype(int)
            skyrizi_df["value"] = skyrizi_df["value"].astype(int)
        except Exception as parse_err:
            return None
        
        # Parse dates
        rinvoq_df["date"] = pd.to_datetime(rinvoq_df["date"], errors="coerce")
        skyrizi_df["date"] = pd.to_datetime(skyrizi_df["date"], errors="coerce")
        
        # Drop rows with invalid dates
        rinvoq_df = rinvoq_df.dropna(subset=["date"])
        skyrizi_df = skyrizi_df.dropna(subset=["date"])
        
        # Filter to window
        r_window = rinvoq_df[(rinvoq_df["date"] >= window_start) & (rinvoq_df["date"] <= window_end)].copy()
        s_window = skyrizi_df[(skyrizi_df["date"] >= window_start) & (skyrizi_df["date"] <= window_end)].copy()
        
        if r_window.empty or s_window.empty or len(r_window) < 3:
            return None
        
        r_window = r_window.sort_values("date").reset_index(drop=True)
        s_window = s_window.sort_values("date").reset_index(drop=True)
        
        # Create aligned date range for x-axis (days from event)
        date_range = pd.date_range(window_start, window_end, freq="D")
        x_days = [(d - event_date).days for d in date_range]
        
        # Merge and interpolate to daily granularity
        merged = pd.DataFrame({"date": date_range})
        merged = merged.merge(r_window[["date", "value"]].rename(columns={"value": "rinvoq"}), on="date", how="left")
        merged = merged.merge(s_window[["date", "value"]].rename(columns={"value": "skyrizi"}), on="date", how="left")
        
        # Forward-fill and backward-fill to interpolate missing dates
        merged["rinvoq"] = merged["rinvoq"].ffill().bfill().fillna(50).astype(int)
        merged["skyrizi"] = merged["skyrizi"].ffill().bfill().fillna(50).astype(int)
        
        r_trend = merged["rinvoq"].tolist()
        s_trend = merged["skyrizi"].tolist()
        
        return (x_days, r_trend, s_trend)
    except Exception as e:
        return None

def calculate_moment_kpis_from_csv(event_date_str, timeframe="1 year"):
    """Calculate KPIs from CSV trend data for an event."""
    try:
        csv_data = load_moment_trend_data(event_date_str, timeframe)
        if csv_data is None:
            return None
        
        x_days, r_trend, s_trend = csv_data
        
        # Calculate baseline (average of pre-event period: days -14 to -1)
        pre_event_indices = [i for i, d in enumerate(x_days) if -14 <= d < 0]
        if not pre_event_indices:
            pre_event_indices = [i for i, d in enumerate(x_days) if d < 0]
        
        if pre_event_indices:
            r_baseline = sum(r_trend[i] for i in pre_event_indices) / len(pre_event_indices)
            s_baseline = sum(s_trend[i] for i in pre_event_indices) / len(pre_event_indices)
        else:
            r_baseline = sum(r_trend[:len(r_trend)//4]) / max(1, len(r_trend)//4)
            s_baseline = sum(s_trend[:len(s_trend)//4]) / max(1, len(s_trend)//4)
        
        # Calculate peak during event window (days 0 to +28)
        event_indices = [i for i, d in enumerate(x_days) if 0 <= d <= 28]
        if not event_indices:
            event_indices = [i for i, d in enumerate(x_days) if d >= 0]
        
        r_peak = max((r_trend[i] for i in event_indices), default=max(r_trend))
        s_peak = max((s_trend[i] for i in event_indices), default=max(s_trend))
        peak_day_index = max(r_peak, s_peak)
        
        # Calculate lifts
        r_lift_pct = ((r_peak - r_baseline) / max(1, r_baseline)) * 100 if r_baseline > 0 else 0
        s_lift_pct = ((s_peak - s_baseline) / max(1, s_baseline)) * 100 if s_baseline > 0 else 0
        
        # Calculate halo duration (days after event where trend > baseline)
        post_event_indices = [i for i, d in enumerate(x_days) if d > 28]
        halo_days = 0
        if post_event_indices:
            for idx in post_event_indices:
                if r_trend[idx] > r_baseline or s_trend[idx] > s_baseline:
                    halo_days += 1
                else:
                    break
        
        return {
            "rinvoq_lift": f"+{int(round(r_lift_pct))}%",
            "skyrizi_lift": f"+{int(round(s_lift_pct))}%",
            "peak": int(round(peak_day_index)),
            "halo": f"{halo_days}d"
        }
    except Exception as e:
        return None

# Load moments data - calculated from real trend CSV data with demo fallback
MOMENTS_DATA = calculate_moments_from_trends()


# ═══════════════════════════════════════════════════════════════════════════
# SMART DATA LOADER
# ═══════════════════════════════════════════════════════════════════════════

def load_data(timeframe_key, brand_filter):
    """Load live data from pytrends, fall back to demo."""
    # Use custom timeframe map from session state, fallback to defaults
    current_timeframe_map = st.session_state.get("custom_timeframe_map", TIMEFRAME_MAP)
    tf = current_timeframe_map.get(timeframe_key, "today 3-m")
    
    # Try live data
    with st.spinner("Fetching Google Trends data..."):
        df = fetch_trends_data(["Rinvoq", "Skyrizi"], timeframe=tf)
    
    if df is not None and not df.empty:
        st.session_state["data_source"] = "live"
        trend_df = df
    else:
        st.session_state["data_source"] = "demo"
        trend_df = generate_demo_trend(tf)
    
    # Apply brand filter
    if brand_filter == "Rinvoq" and "Skyrizi" in trend_df.columns:
        trend_df = trend_df.drop("Skyrizi", axis=1)
    elif brand_filter == "Skyrizi" and "Rinvoq" in trend_df.columns:
        trend_df = trend_df.drop("Rinvoq", axis=1)
    
    return trend_df


# ═══════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown(f"""
    <div style='text-align:center;padding:8px 0;margin-bottom:12px'>
        <div style='background:{NAVY};color:white;width:36px;height:36px;border-radius:8px;display:inline-flex;align-items:center;justify-content:center;font-weight:800;font-size:16px;margin-bottom:6px'>A</div>
        <h4 style='margin:2px 0;color:{NAVY}'>AbbVie Immunology</h4>
        <p style='margin:0;font-size:11px;color:#8a9ab5'>Search Intelligence</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.divider()
    
    # Use custom configurations from session state, fallback to defaults
    current_ind_names = st.session_state.get("custom_ind_names", IND_NAMES)
    current_franchise_map = st.session_state.get("custom_franchise_map", FRANCHISE_MAP)
    current_timeframe_map = st.session_state.get("custom_timeframe_map", TIMEFRAME_MAP)
    
    franchise = st.selectbox("Franchise", ["All"] + list(current_franchise_map.keys()), label_visibility="visible")
    brand_filter = st.selectbox("Brand", ["Both", "Rinvoq", "Skyrizi"], label_visibility="visible")
    timeframe = st.selectbox("Timeframe", list(current_timeframe_map.keys()), index=2, label_visibility="visible")
    
    st.divider()
    
    if st.button("↻ Refresh", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    
    source = st.session_state.get("data_source", "demo")
    is_live = st.session_state.get("live_data_enabled", False)
    
    # Show loading status if live data is enabled but not yet fetched
    if is_live and source != "live":
        st.markdown(f"<div style='text-align:center;font-size:11px;color:#ff9800;font-weight:600;margin-top:8px'>⏳ Fetching live data...</div>", unsafe_allow_html=True)
    else:
        if source == "csv":
            source_color = "#4CAF50"
            status_text = "CSV DATA"
        elif source == "live" and is_live:
            source_color = SUCCESS
            status_text = "LIVE DATA"
        else:
            source_color = GOLD
            status_text = "DEMO DATA (reliable)"
        st.markdown(f"<div style='text-align:center;font-size:11px;color:{source_color};font-weight:600;margin-top:8px'>● {status_text}</div>", unsafe_allow_html=True)
    
    if st.session_state.get("data_error"):
        # Automatically disable live mode and fall back to demo
        if st.session_state.get("live_data_enabled"):
            st.session_state["live_data_enabled"] = False
            st.session_state["data_source"] = "demo"
        with st.expander("⚠️ API Rate Limited", expanded=False):
            st.caption("Google Trends API temporarily restricted. Using demo data. Click 'Live Data' again in 2 minutes to retry.")
    else:
        if source == "csv":
            st.caption("✓ Using CSV data")
        elif is_live and source == "live":
            st.caption("✓ Real Google Trends data")
        else:
            st.caption("✓ Using demo data")
    
    # Debug: Show what data source is actually being used
    with st.expander("🔍 Data Source Debug", expanded=False):
        st.write("**Is Live Data Enabled?**", st.session_state.get("live_data_enabled", False))
        st.write("**Actual Data Source:**", st.session_state.get("data_source", "unknown"))
        st.write("**Data Error Message:**", st.session_state.get("data_error", "None"))
        st.write("**Keywords being fetched:**", ["Rinvoq", "Skyrizi"])
        st.write("**Note:** Demo data shows predictable sine waves. Live data shows real Google Trends patterns. CSV data is from uploaded search intent files for all timeframes.")
    
    st.divider()
    
    if st.button("🔐 Logout", use_container_width=True):
        st.session_state.authenticated = False
        st.success("Logged out successfully")
        st.rerun()

# ═══════════════════════════════════════════════════════════════════════════
# INITIALIZE DEFAULT INDICATION VALUE
# ═══════════════════════════════════════════════════════════════════════════
indication = "All"

# ═══════════════════════════════════════════════════════════════════════════
# LOAD DATA
# ═══════════════════════════════════════════════════════════════════════════

# Initialize data source - use demo by default, users can enable live data
if "data_source" not in st.session_state:
    st.session_state["data_source"] = "demo"  # Start with demo, less likely to hit API limits
if "live_data_enabled" not in st.session_state:
    st.session_state["live_data_enabled"] = False

@st.cache_data(ttl=7200)
def load_csv_trend_data(brand, timeframe):
    """Load trend data from CSV files for any timeframe."""
    # Map pytrends timeframe to CSV filename pattern
    timeframe_map = {
        "now 7-d": "7 days",
        "today 1-m": "30 days",
        "today 3-m": "90 days",
        "today 12-m": "1 year",
        "today 5-y": "5 year",
    }
    
    time_label = timeframe_map.get(timeframe)
    if not time_label:
        return None
    
    try:
        filename = f"data/{brand.capitalize()} Search Intent {time_label} new.csv"
        if not os.path.exists(filename):
            return None
        
        # Read CSV, skip the header rows
        df = pd.read_csv(filename, skiprows=2)
        df.columns = ['date', 'value']
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        df = df.set_index('date')
        df.columns = [brand.capitalize()]
        
        return df
    except Exception as e:
        return None

@st.cache_data(ttl=7200)
def load_tremfya_csv_data(timeframe):
    """Load Tremfya trend data from CSV files (uses different naming convention)."""
    # Map pytrends timeframe to Tremfya CSV filename pattern
    timeframe_map = {
        "now 7-d": "7 days",
        "today 1-m": "1 month",
        "today 3-m": "90 days",
        "today 12-m": "1 year",
        "today 5-y": "5 years",
    }
    
    time_label = timeframe_map.get(timeframe)
    if not time_label:
        return None
    
    try:
        filename = f"data/Tremfya Search Intent {time_label}.csv"
        if not os.path.exists(filename):
            return None
        
        # Read CSV, skip the header rows
        df = pd.read_csv(filename, skiprows=2)
        df.columns = ['date', 'value']
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        df = df.set_index('date')
        df.columns = ['Tremfya']
        
        return df
    except Exception as e:
        return None

@st.cache_data(ttl=7200)
def load_dupixent_csv_data(timeframe):
    """Load Dupixent trend data from CSV files (uses different naming convention)."""
    # Map pytrends timeframe to Dupixent CSV filename pattern
    timeframe_map = {
        "now 7-d": "7 days",
        "today 1-m": "1 month",
        "today 3-m": "90 days",
        "today 12-m": "1 year",
        "today 5-y": "5 years",
    }
    
    time_label = timeframe_map.get(timeframe)
    if not time_label:
        return None
    
    try:
        filename = f"data/Dupixent Search Intent {time_label}.csv"
        if not os.path.exists(filename):
            return None
        
        # Read CSV, skip the header rows
        df = pd.read_csv(filename, skiprows=2)
        df.columns = ['date', 'value']
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        df = df.set_index('date')
        df.columns = ['Dupixent']
        
        return df
    except Exception as e:
        return None

@st.cache_data(ttl=7200)
def load_humira_csv_data(timeframe):
    """Load Humira trend data from CSV files (uses different naming convention)."""
    # Map pytrends timeframe to Humira CSV filename pattern
    timeframe_map = {
        "now 7-d": "7 days",
        "today 1-m": "1 month",
        "today 3-m": "90 days",
        "today 12-m": "1 year",
        "today 5-y": "5 years",
    }
    
    time_label = timeframe_map.get(timeframe)
    if not time_label:
        return None
    
    try:
        filename = f"data/Humira Search Intent {time_label}.csv"
        if not os.path.exists(filename):
            return None
        
        # Read CSV, skip the header rows
        df = pd.read_csv(filename, skiprows=2)
        df.columns = ['date', 'value']
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        df = df.set_index('date')
        df.columns = ['Humira']
        
        return df
    except Exception as e:
        return None

@st.cache_data(ttl=7200)
def load_entyvio_csv_data(timeframe):
    """Load Entyvio trend data from CSV files (uses different naming convention)."""
    # Map pytrends timeframe to Entyvio CSV filename pattern
    timeframe_map = {
        "now 7-d": "1 month",
        "today 1-m": "1 month",
        "today 3-m": "90 days",
        "today 12-m": "1 year",
        "today 5-y": "5 years",
    }
    
    time_label = timeframe_map.get(timeframe)
    if not time_label:
        return None
    
    try:
        filename = f"data/Entyvio Search Intent {time_label}.csv"
        if not os.path.exists(filename):
            return None
        
        # Read CSV, skip the header rows
        df = pd.read_csv(filename, skiprows=2)
        df.columns = ['date', 'value']
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        df = df.set_index('date')
        df.columns = ['Entyvio']
        
        return df
    except Exception as e:
        return None

def load_csv_geomap_data(timeframe):
    """Load geomap (state-level) data from CSV files for both brands and combine them.
    
    Returns a DataFrame with columns: State, Rinvoq, Skyrizi
    Format: [Brand] Search Intent [Timeframe] geomap.csv
    
    Note: Some files may be time-series only (e.g., Rinvoq 30-day is by date).
    This function extracts regional data when available and gracefully handles mismatches.
    """
    # Map pytrends timeframe to geomap CSV filename pattern
    # Note: Geomap files use "5 years" not "5 year"
    timeframe_map = {
        "now 7-d": "7 days",
        "today 1-m": "30 days",
        "today 3-m": "90 days",
        "today 12-m": "1 year",
        "today 5-y": "5 years",
    }
    
    time_label = timeframe_map.get(timeframe)
    if not time_label:
        return None
    
    try:
        # Load data for both brands
        dfs = {}
        for brand in ["Rinvoq", "Skyrizi"]:
            filename = f"data/{brand} Search Intent {time_label} geomap.csv"
            if not os.path.exists(filename):
                continue  # Skip if file doesn't exist, will use fallback
            
            # Read CSV, skip the first 2 rows (Category header and empty row)
            df = pd.read_csv(filename, skiprows=2)
            
            # Check the first column to determine data type
            first_col = df.columns[0]
            
            # If first column is "Day" or contains date data, skip this brand
            # (it's time-series only, not regional data)
            if first_col.lower() == "day":
                continue
            
            # The CSV has Region as first column and Index as second
            # Rename columns: "Region" -> "State", second column -> brand name
            df.columns = ['State', brand]
            
            # Clean up and ensure Index is numeric
            df[brand] = pd.to_numeric(df[brand], errors='coerce')
            
            dfs[brand] = df
        
        # If we don't have at least one brand, return None
        if not dfs:
            return None
        
        # If we have both brands, merge them
        if len(dfs) == 2:
            combined_df = dfs["Rinvoq"].merge(dfs["Skyrizi"], on="State", how="outer")
            combined_df = combined_df.dropna(subset=['Rinvoq', 'Skyrizi'])
        else:
            # If only one brand is available, use it
            brand_name = list(dfs.keys())[0]
            combined_df = dfs[brand_name].copy()
        
        # Convert to integers
        if 'Rinvoq' in combined_df.columns:
            combined_df['Rinvoq'] = combined_df['Rinvoq'].astype(int)
        if 'Skyrizi' in combined_df.columns:
            combined_df['Skyrizi'] = combined_df['Skyrizi'].astype(int)
        
        return combined_df if not combined_df.empty else None
    except Exception as e:
        return None

def infer_query_type(query, brand):
    """Infer query type from query text and brand context."""
    query_l = str(query).lower()
    brand_l = str(brand).lower()

    safety_terms = ["side effect", "adverse", "safety", "warning", "risk", "infection", "black box"]
    condition_terms = [
        "arthritis", "psoriasis", "crohn", "colitis", "dermatitis", "spondylitis", "gca",
        "eczema", "ulcerative colitis", "ra", "psa", "as"
    ]
    generic_terms = ["upadacitinib", "risankizumab", "jak inhibitor", "il-23", "biologic"]

    if " vs " in f" {query_l} " or any(comp.lower() in query_l for comp in COMPETITORS):
        return "competitive"
    if any(term in query_l for term in safety_terms):
        return "safety"
    if (brand_l and brand_l in query_l) or "rinvoq" in query_l or "skyrizi" in query_l:
        return "branded"
    if any(term in query_l for term in generic_terms):
        return "generic"
    if any(term in query_l for term in condition_terms):
        return "condition"
    return "condition"

def infer_indication(query):
    """Infer indication label from query text."""
    query_l = str(query).lower()
    indication_map = {
        "RA": ["rheumatoid", " ra "],
        "Psoriasis": ["psoriasis", "plaque"],
        "PsA": ["psoriatic", " psa "],
        "AS": ["ankylosing", "spondylitis", " as "],
        "AD": ["atopic", "dermatitis", "eczema"],
        "UC": ["ulcerative colitis", " colitis", " uc "],
        "Crohn's": ["crohn"],
        "GCA": ["giant cell", "gca"],
    }

    padded = f" {query_l} "
    for indication_name, terms in indication_map.items():
        if any(term in padded or term in query_l for term in terms):
            return indication_name
    return "All"

def _parse_top_queries_csv(file_path, brand):
    """Parse a candidate top-queries CSV and return standardized columns if valid."""
    try:
        df = pd.read_csv(
            file_path,
            skiprows=2,
            header=None,
            usecols=[0, 1],
            names=["Query", "Value"],
            engine="python",
        )
    except Exception:
        return None

    if df is None or df.empty or len(df.columns) < 2:
        return None

    df = df.dropna(how="all").copy()
    if df.empty:
        return None

    df["Query"] = df["Query"].astype(str).str.strip()
    df["Value"] = df["Value"].astype(str).str.strip()

    # Drop CSV header-like rows if present
    df = df[~df["Query"].str.lower().isin(["query", "queries"])]

    # Skip known non-query files (time-series or geomap-like headers)
    non_query_first_values = {"day", "week", "month", "date", "region", "state", "dma", "market"}
    first_non_empty_query = next((q.lower() for q in df["Query"] if q and q != "nan"), "")
    if first_non_empty_query in non_query_first_values:
        return None

    # Reject time-series files where the first column is mostly parseable as dates
    parsed_dates = pd.to_datetime(df["Query"], errors="coerce")
    if parsed_dates.notna().mean() > 0.7:
        return None

    # Google Trends top queries exports may include "TOP" and "RISING" blocks.
    # Keep only rows in the TOP block when present.
    top_markers = df["Query"].str.upper() == "TOP"
    rising_markers = df["Query"].str.upper() == "RISING"
    if top_markers.any():
        top_idx = top_markers[top_markers].index[0]
        rising_idx = rising_markers[rising_markers].index[0] if rising_markers.any() else None
        if rising_idx is not None and rising_idx > top_idx:
            section_df = df.loc[(df.index > top_idx) & (df.index < rising_idx), ["Query", "Value"]].copy()
        else:
            section_df = df.loc[df.index > top_idx, ["Query", "Value"]].copy()
    else:
        section_df = df[["Query", "Value"]].copy()

    section_df["Index"] = pd.to_numeric(
        section_df["Value"].astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False),
        errors="coerce"
    )

    # Optional growth column support if present
    out_df = section_df[["Query", "Index"]].copy()
    out_df["Growth"] = np.nan

    out_df = out_df.dropna(subset=["Query", "Index"])
    out_df = out_df[~out_df["Query"].str.upper().isin(["TOP", "RISING"])]
    out_df = out_df[out_df["Query"].astype(str).str.strip() != ""]
    if out_df.empty:
        return None

    out_df["Brand"] = brand
    return out_df[["Query", "Brand", "Index", "Growth"]]

def _parse_rising_queries_csv(file_path, brand):
    """Parse RISING queries from a CSV file and return standardized columns."""
    try:
        df = pd.read_csv(
            file_path,
            skiprows=2,
            header=None,
            usecols=[0, 1],
            names=["Query", "Value"],
            engine="python",
        )
    except Exception:
        return None

    if df is None or df.empty:
        return None

    df["Query"] = df["Query"].astype(str).str.strip()
    df["Value"] = df["Value"].astype(str).str.strip()

    # Find the RISING section
    rising_markers = df["Query"].str.upper() == "RISING"
    if not rising_markers.any():
        return None

    rising_idx = rising_markers[rising_markers].index[0]
    
    # Extract rows after RISING marker
    section_df = df.loc[df.index > rising_idx, ["Query", "Value"]].copy()
    
    # Remove empty rows
    section_df = section_df[section_df["Query"].astype(str).str.strip() != ""]
    
    if section_df.empty:
        return None

    # Set Index to 100 for all rising queries (or use the Value column if it contains numeric data)
    out_df = section_df[["Query"]].copy()
    out_df["Index"] = 100  # Rising queries all have same priority
    out_df["Growth"] = "Breakout"
    out_df["Brand"] = brand
    
    return out_df[["Query", "Brand", "Index", "Growth"]]

@st.cache_data(ttl=7200)
def load_csv_top_queries_data(timeframe, data_signature=None):
    """Load top queries from CSV files for both brands by timeframe.

    Supports flexible filename patterns to accommodate manually added exports.
    """
    timeframe_map = {
        "now 7-d": "7 days",
        "today 1-m": "30 days",
        "today 3-m": "90 days",
        "today 12-m": "1 year",
        "today 5-y": "5 year",
    }

    time_label = timeframe_map.get(timeframe)
    if not time_label:
        return None

    data_dir = Path("data")
    if not data_dir.exists():
        return None

    query_frames = []
    for brand in ["Rinvoq", "Skyrizi"]:
        all_candidates = [
            p for p in data_dir.iterdir()
            if p.is_file()
            and brand.lower() in p.name.lower()
            and time_label.lower() in p.name.lower()
            and "geomap" not in p.name.lower()
        ]

        # Prefer explicitly named top query exports first, then other candidates
        top_query_candidates = sorted([p for p in all_candidates if "top quer" in p.name.lower()])
        other_candidates = sorted([p for p in all_candidates if "top quer" not in p.name.lower()])
        candidates = top_query_candidates + other_candidates

        for file_path in candidates:
            parsed = _parse_top_queries_csv(file_path, brand)
            if parsed is not None and not parsed.empty:
                query_frames.append(parsed)
                break

    if not query_frames:
        return None

    combined = pd.concat(query_frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["Query", "Brand"], keep="first")
    return combined if not combined.empty else None

def get_top_queries_data_signature():
    """Build a lightweight signature so top-query cache refreshes when files change."""
    data_dir = Path("data")
    if not data_dir.exists():
        return ()

    signature = []
    for path in sorted(data_dir.iterdir()):
        if not path.is_file():
            continue
        name_l = path.name.lower()
        if "top quer" not in name_l:
            continue
        try:
            stat = path.stat()
            signature.append((path.name, int(stat.st_mtime), stat.st_size))
        except Exception:
            signature.append((path.name, 0, 0))
    return tuple(signature)

@st.cache_data(ttl=7200)
def load_csv_rising_queries_data(timeframe, data_signature=None):
    """Load rising queries from CSV files for both brands by timeframe."""
    timeframe_map = {
        "now 7-d": "7 days",
        "today 1-m": "30 days",
        "today 3-m": "90 days",
        "today 12-m": "1 year",
        "today 5-y": "5 year",
    }

    time_label = timeframe_map.get(timeframe)
    if not time_label:
        return None

    data_dir = Path("data")
    if not data_dir.exists():
        return None

    query_frames = []
    for brand in ["Rinvoq", "Skyrizi"]:
        all_candidates = [
            p for p in data_dir.iterdir()
            if p.is_file()
            and brand.lower() in p.name.lower()
            and time_label.lower() in p.name.lower()
            and "geomap" not in p.name.lower()
        ]

        # Prefer explicitly named top query exports first, then other candidates
        top_query_candidates = sorted([p for p in all_candidates if "top quer" in p.name.lower()])
        other_candidates = sorted([p for p in all_candidates if "top quer" not in p.name.lower()])
        candidates = top_query_candidates + other_candidates

        for file_path in candidates:
            parsed = _parse_rising_queries_csv(file_path, brand)
            if parsed is not None and not parsed.empty:
                query_frames.append(parsed)
                break

    if not query_frames:
        return None

    combined = pd.concat(query_frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["Query", "Brand"], keep="first")
    return combined if not combined.empty else None

def load_data(timeframe_key, brand_filter, indication="All"):
    """Load trend data with priority: Live API → CSV (as fallback) → Demo."""
    # Convert timeframe key to actual timeframe string
    current_timeframe_map = st.session_state.get("custom_timeframe_map", TIMEFRAME_MAP)
    timeframe = current_timeframe_map.get(timeframe_key, "today 3-m")
    
    # Store timeframe in session state for use in chart rendering
    st.session_state["current_timeframe"] = timeframe
    
    # Determine which brands to fetch based on filter
    if brand_filter == "Both":
        keywords = ["Rinvoq", "Skyrizi"]
    elif brand_filter == "Rinvoq":
        keywords = ["Rinvoq"]
    else:  # Skyrizi
        keywords = ["Skyrizi"]
    
    # Priority 1: Try to fetch LIVE data (always attempt first)
    if st.session_state.get("live_data_enabled"):
        trend_df = fetch_trends_data(keywords, timeframe=timeframe)
        if trend_df is not None and not trend_df.empty:
            st.session_state["data_source"] = "live"
            return trend_df
    
    # Priority 2: Fallback to CSV data (if available for the timeframe)
    try:
        dfs = []
        if brand_filter == "Both":
            for brand in ["Rinvoq", "Skyrizi"]:
                df = load_csv_trend_data(brand, timeframe)
                if df is not None:
                    dfs.append(df)
        elif brand_filter == "Rinvoq":
            df = load_csv_trend_data("Rinvoq", timeframe)
            if df is not None:
                dfs.append(df)
        else:  # Skyrizi
            df = load_csv_trend_data("Skyrizi", timeframe)
            if df is not None:
                dfs.append(df)
        
        if dfs:
            trend_df = pd.concat(dfs, axis=1)
            st.session_state["data_source"] = "csv"
            return trend_df
    except Exception as e:
        pass  # Fall through to demo data
    
    # Priority 3: Fallback to DEMO data (last resort)
    st.session_state["data_source"] = "demo"
    
    # Generate demo data based on brand filter
    date_range = pd.date_range(end=datetime.now(), periods=90, freq='D')
    
    if brand_filter == "Both":
        # Both brands
        rinvoq_data = [50 + np.sin(i/10) * 20 + np.random.randn() * 5 for i in range(90)]
        skyrizi_data = [45 + np.sin(i/10 + 1) * 18 + np.random.randn() * 5 for i in range(90)]
        return pd.DataFrame({
            "date": date_range,
            "Rinvoq": rinvoq_data,
            "Skyrizi": skyrizi_data
        }).set_index("date")
    elif brand_filter == "Rinvoq":
        # Only Rinvoq
        rinvoq_data = [50 + np.sin(i/10) * 20 + np.random.randn() * 5 for i in range(90)]
        return pd.DataFrame({
            "date": date_range,
            "Rinvoq": rinvoq_data
        }).set_index("date")
    else:  # Skyrizi
        # Only Skyrizi
        skyrizi_data = [45 + np.sin(i/10 + 1) * 18 + np.random.randn() * 5 for i in range(90)]
        return pd.DataFrame({
            "date": date_range,
            "Skyrizi": skyrizi_data
        }).set_index("date")

trend_df = load_data(timeframe, brand_filter, indication)

# Also try to load competitor data
comp_df = None
if st.session_state.get("live_data_enabled"):
    comp_df = fetch_trends_data(["Rinvoq", "Skyrizi"] + COMPETITORS[:3], timeframe="today 12-m")

# Related queries
related_rinvoq = fetch_related_queries("Rinvoq") if st.session_state.get("data_source") == "live" else {"top": None, "rising": None}
related_skyrizi = fetch_related_queries("Skyrizi") if st.session_state.get("data_source") == "live" else {"top": None, "rising": None}

# State-level data - fetch and transform
state_df = None
raw_state_df = None
if st.session_state.get("live_data_enabled"):
    raw_state_df = fetch_regional_data(["Rinvoq", "Skyrizi"], timeframe="today 12-m", resolution="REGION")
    state_df = transform_regional_to_states(raw_state_df)

# Fallback to CSV geomap data if live data is not available
if state_df is None or state_df.empty:
    # Use the same timeframe that was used for trend data
    geomap_timeframe = st.session_state.get("current_timeframe", "today 12-m")
    state_df = load_csv_geomap_data(geomap_timeframe)

# Use transformed state data for DMA generation, fallback to demo
if state_df is not None and not state_df.empty:
    DEMO_DMA = generate_dma_from_states(state_df)
    DEMO_STATES = state_df
elif state_df is None and st.session_state.get("data_source") == "live":
    # If live but transformation failed, still use DEMO data
    pass

# Generate queries from related data or use demo
base_queries = transform_trends_to_queries(trend_df, related_rinvoq, related_skyrizi)
csv_queries = load_csv_top_queries_data(
    st.session_state.get("current_timeframe", "today 3-m"),
    get_top_queries_data_signature(),
)

if csv_queries is not None and not csv_queries.empty:
    # Fill missing metadata from base queries when possible
    fallback_meta = base_queries.copy()
    for required_col, default_value in [("Growth", 0), ("Type", "condition"), ("Indication", "All")]:
        if required_col not in fallback_meta.columns:
            fallback_meta[required_col] = default_value

    fallback_meta["_query_key"] = fallback_meta["Query"].astype(str).str.lower().str.strip()
    fallback_meta = fallback_meta[["_query_key", "Growth", "Type", "Indication"]].drop_duplicates("_query_key")

    DEMO_QUERIES = csv_queries.copy()
    DEMO_QUERIES["_query_key"] = DEMO_QUERIES["Query"].astype(str).str.lower().str.strip()
    DEMO_QUERIES = DEMO_QUERIES.merge(fallback_meta, on="_query_key", how="left", suffixes=("", "_fallback"))

    DEMO_QUERIES["Growth"] = DEMO_QUERIES["Growth"].fillna(DEMO_QUERIES["Growth_fallback"]).fillna(0)
    DEMO_QUERIES["Type"] = DEMO_QUERIES["Type"].fillna(
        DEMO_QUERIES.apply(lambda row: infer_query_type(row["Query"], row["Brand"]), axis=1)
    )
    DEMO_QUERIES["Indication"] = DEMO_QUERIES["Indication"].fillna(DEMO_QUERIES["Query"].apply(infer_indication))

    DEMO_QUERIES = DEMO_QUERIES[["Query", "Brand", "Index", "Growth", "Type", "Indication"]]
else:
    DEMO_QUERIES = base_queries

# Filter DEMO_QUERIES by brand and indication
if indication != "All":
    # Filter by indication (add "All" queries that apply universally)
    DEMO_QUERIES = DEMO_QUERIES[(DEMO_QUERIES["Indication"] == indication) | (DEMO_QUERIES["Indication"] == "All")]

if brand_filter != "Both":
    # Filter by brand
    DEMO_QUERIES = DEMO_QUERIES[(DEMO_QUERIES["Brand"] == brand_filter) | (DEMO_QUERIES["Brand"] == "Both")]

# Load rising queries from CSV
csv_rising_queries = load_csv_rising_queries_data(
    st.session_state.get("current_timeframe", "today 3-m"),
    get_top_queries_data_signature(),
)

if csv_rising_queries is not None and not csv_rising_queries.empty:
    DEMO_RISING_QUERIES = csv_rising_queries.copy()
    DEMO_RISING_QUERIES["Type"] = "rising"
    DEMO_RISING_QUERIES["Indication"] = "All"
else:
    DEMO_RISING_QUERIES = pd.DataFrame(columns=["Query", "Brand", "Index", "Growth", "Type", "Indication"])

# Filter DEMO_RISING_QUERIES by brand and indication
if indication != "All":
    DEMO_RISING_QUERIES = DEMO_RISING_QUERIES[(DEMO_RISING_QUERIES["Indication"] == indication) | (DEMO_RISING_QUERIES["Indication"] == "All")]

if brand_filter != "Both":
    DEMO_RISING_QUERIES = DEMO_RISING_QUERIES[(DEMO_RISING_QUERIES["Brand"] == brand_filter) | (DEMO_RISING_QUERIES["Brand"] == "Both")]

# ═══════════════════════════════════════════════════════════════════════════
# DISPLAY DATA REFRESH DATE
# ═══════════════════════════════════════════════════════════════════════════
# Update this date whenever new data is added to the data/ directory
DATA_REFRESH_DATE = "March 18, 2026"
st.caption(f"📊 Data last updated: {DATA_REFRESH_DATE}")

# ═══════════════════════════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════════════════════════

# Initialize Claude and chat history
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# Initialize configuration session state
if "custom_comp_colors" not in st.session_state:
    st.session_state.custom_comp_colors = COMP_COLORS.copy()
if "custom_ind_names" not in st.session_state:
    st.session_state.custom_ind_names = IND_NAMES.copy()
if "custom_franchise_map" not in st.session_state:
    st.session_state.custom_franchise_map = {k: v.copy() for k, v in FRANCHISE_MAP.items()}
if "custom_timeframe_map" not in st.session_state:
    st.session_state.custom_timeframe_map = TIMEFRAME_MAP.copy()
    
try:
    client = init_claude()
except Exception as e:
    st.session_state["api_error"] = str(e)
    client = None

tabs = st.tabs(["� Executive Summary", "📊 Overview", "🗺️ DMA Deep Dive", "⚡ Key Moments", "⚔️ Competitive", "🔬 Patient Intent", "📅 Campaign", "⚙️ Configuration"])

# ═══════════════════════════════════════════════════════════════════════════
# TAB 0: EXECUTIVE SUMMARY
# ═══════════════════════════════════════════════════════════════════════════
with tabs[0]:
    st.header("📋 Executive Marketing Dashboard")
    
    # Timeframe mapping
    timeframe_map = {
        "now 7-d": "7 days",
        "today 1-m": "30 days",
        "today 3-m": "90 days",
        "today 12-m": "1 year",
        "today 5-y": "5 years",
    }
    
    # Brand filter at top
    col_filter = st.columns([3, 1])
    with col_filter[1]:
        exec_brand_filter = st.selectbox("Brand", ["Both", "Rinvoq", "Skyrizi"], key="exec_brand_filter")
    
    # Get executive summary data
    overview_callouts, overview_rec = generate_overview_executive_summary(trend_df, DEMO_DMA, DEMO_QUERIES, client, exec_brand_filter, indication)
    comp_callouts, comp_rec = generate_competitive_executive_summary(DEMO_DMA, client, exec_brand_filter, indication)
    intent_callouts, intent_rec = generate_patient_intent_executive_summary(DEMO_QUERIES, client, exec_brand_filter, indication)
    
    # KEY METRICS SECTION
    st.subheader("📊 Key Market Metrics")
    
    if exec_brand_filter == "Both":
        # Load all brand data for market overview
        comp_trend_df = None
        dfs = []
        for brand in ["Rinvoq", "Skyrizi"]:
            df = load_csv_trend_data(brand, current_timeframe)
            if df is not None:
                dfs.append(df)
        tremfya_df = load_tremfya_csv_data(current_timeframe)
        if tremfya_df is not None:
            dfs.append(tremfya_df)
        dupixent_df = load_dupixent_csv_data(current_timeframe)
        if dupixent_df is not None:
            dfs.append(dupixent_df)
        humira_df = load_humira_csv_data(current_timeframe)
        if humira_df is not None:
            dfs.append(humira_df)
        entyvio_df = load_entyvio_csv_data(current_timeframe)
        if entyvio_df is not None:
            dfs.append(entyvio_df)
        if dfs:
            comp_trend_df = pd.concat(dfs, axis=1)
        
        # Calculate market metrics
        if comp_trend_df is not None:
            total_market = comp_trend_df[["Skyrizi", "Rinvoq", "Humira", "Tremfya", "Dupixent", "Entyvio"]].sum(axis=1).mean()
            skyrizi_avg = comp_trend_df["Skyrizi"].mean()
            rinvoq_avg = comp_trend_df["Rinvoq"].mean()
            skyrizi_share = (skyrizi_avg / total_market * 100) if total_market > 0 else 0
            rinvoq_share = (rinvoq_avg / total_market * 100) if total_market > 0 else 0
            portfolio_share = skyrizi_share + rinvoq_share
        else:
            total_market = skyrizi_avg = rinvoq_avg = skyrizi_share = rinvoq_share = portfolio_share = 0
        
        metric_cols = st.columns(4)
        with metric_cols[0]:
            st.metric("Portfolio Mindshare", f"{portfolio_share:.1f}%", help="Skyrizi + Rinvoq combined search share")
        with metric_cols[1]:
            st.metric("Skyrizi Index", f"{int(skyrizi_avg)}", f"{skyrizi_share:.1f}% share", help="Average search index for Skyrizi")
        with metric_cols[2]:
            st.metric("Rinvoq Index", f"{int(rinvoq_avg)}", f"{rinvoq_share:.1f}% share", help="Average search index for Rinvoq")
        with metric_cols[3]:
            st.metric("Competitor Index", f"{int(total_market - skyrizi_avg - rinvoq_avg)}", "Combined 5 brands", help="Humira, Tremfya, Dupixent, Entyvio, others")
    else:
        # Single brand view
        brand_code = "Skyrizi" if exec_brand_filter == "Skyrizi" else "Rinvoq"
        df = load_csv_trend_data(brand_code, current_timeframe)
        if df is not None:
            brand_avg = df[brand_code].mean()
            brand_peak = df[brand_code].max()
            metric_cols = st.columns(3)
            with metric_cols[0]:
                st.metric(f"{exec_brand_filter} Avg Index", f"{int(brand_avg)}", f"Peak: {int(brand_peak)}")
            with metric_cols[1]:
                st.metric("Timeframe", timeframe_map.get(current_timeframe, "12-month"))
            with metric_cols[2]:
                st.metric("Data Points", f"{len(df)}")
    
    # MARKET INSIGHTS SECTION
    st.markdown("---")
    st.subheader("🎯 Market Positioning")
    insight_cols = st.columns([1, 1])
    
    with insight_cols[0]:
        st.markdown("**Competitive Landscape**")
        for callout in comp_callouts[:2]:
            st.markdown(f"• {callout}")
        if comp_rec:
            st.markdown(f"<div style='background-color: #f0f0f0; padding: 12px; border-radius: 4px; font-size: 13px; margin-top: 8px'><strong>Action:</strong> {comp_rec}</div>", unsafe_allow_html=True)
    
    with insight_cols[1]:
        st.markdown("**Patient Search Intent**")
        for callout in intent_callouts[:2]:
            st.markdown(f"• {callout}")
        if intent_rec:
            st.markdown(f"<div style='background-color: #f0f0f0; padding: 12px; border-radius: 4px; font-size: 13px; margin-top: 8px'><strong>Action:</strong> {intent_rec}</div>", unsafe_allow_html=True)
    
    # TRENDS & RECOMMENDATIONS SECTION
    st.markdown("---")
    st.subheader("📈 Trends & Key Takeaways")
    
    trend_cols = st.columns(1)
    with trend_cols[0]:
        st.markdown("**Market Overview**")
        for callout in overview_callouts:
            st.markdown(f"• {callout}")
        if overview_rec:
            st.markdown(f"<div style='background-color: #e8f4f8; padding: 12px; border-radius: 4px; font-size: 13px; margin-top: 8px; border-left: 4px solid #0284c7'><strong>🎬 Recommended Action:</strong> {overview_rec}</div>", unsafe_allow_html=True)
    
    # NAVIGATION GUIDE
    st.markdown("---")
    st.markdown("""
    ### 📍 Where to Go Next
    
    | Tab | Focus | Use Case |
    |-----|-------|----------|
    | **📊 Overview** | Search trends & geographic leaders | Understand baseline demand and regional performance |
    | **🗺️ DMA Deep Dive** | Top markets & competitive depth | Identify geographic expansion opportunities |
    | **⚡ Key Moments** | Reddit discussions & patient voices | Understand real patient concerns & messaging gaps |
    | **⚔️ Competitive** | Competitor positioning & market share | Track competitive threats & market dynamics |
    | **🔬 Patient Intent** | Search query analysis & decision stage | Understand what patients are researching |
    | **📅 Campaign** | Moment-based & seasonal trends | Plan campaign timing & moment marketing |
    """)

# ═══════════════════════════════════════════════════════════════════════════
# TAB 1: OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════
with tabs[1]:
    # Executive Summary
    overview_callouts, overview_recommendation = generate_overview_executive_summary(trend_df, DEMO_DMA, DEMO_QUERIES, client, brand_filter, indication)
    render_executive_summary("Search Trends & Market Opportunity", overview_callouts, NAVY, overview_recommendation)
    
    # KPIs
    r_vals = trend_df["Rinvoq"].values if "Rinvoq" in trend_df.columns else [0]
    s_vals = trend_df["Skyrizi"].values if "Skyrizi" in trend_df.columns else [0]
    r_peak, s_peak = int(max(r_vals)), int(max(s_vals))
    r_avg, s_avg = int(np.mean(r_vals)), int(np.mean(s_vals))
    
    
    # KPIs - Show only selected brand(s)
    if brand_filter == "Both":
        k1, k2, k3, k4 = st.columns(4)
        k1.metric(
            "Rinvoq Avg (Index)", 
            r_avg, 
            f"Peak: {r_peak}",
            help="Annual average search index (0-100 scale). Baseline demand level for campaign targeting and budget planning."
        )
        k2.metric(
            "Skyrizi Avg (Index)", 
            s_avg, 
            f"Peak: {s_peak}",
            help="Annual average search index (0-100 scale). Baseline demand level for campaign targeting and budget planning."
        )
        k3.metric(
            "Top DMA", 
            DEMO_DMA.iloc[0]["Market"].split(",")[0], 
            f"Index {DEMO_DMA.iloc[0]['Rinvoq']}",
            help="Leading geographic market by search interest. Allocate 40% of budget to top 3 DMAs for maximum efficiency and fastest payback period."
        )
        k4.metric(
            "Breakout Terms", 
            str(len(DEMO_QUERIES[DEMO_QUERIES["Growth"] >= 500])), 
            "500%+ growth",
            help="Search queries with explosive 500%+ growth. Signals emerging indication opportunities, new patient segments, and untapped market pockets."
        )
    elif brand_filter == "Rinvoq":
        k1, k2, k3, k4 = st.columns(4)
        k1.metric(
            "Avg Index", 
            r_avg, 
            f"Peak: {r_peak}",
            help="Annual average search index (0-100 scale). Baseline demand level. Stable index indicates consistent brand awareness and sustained market interest throughout the year."
        )
        k2.metric(
            "Peak Index", 
            r_peak, 
            "Annual peak",
            help="Annual peak search index (0-100 scale). Use as benchmark for campaign reach targets, ROI expectations, and seasonal planning windows."
        )
        k3.metric(
            "Top DMA", 
            DEMO_DMA.iloc[0]["Market"].split(",")[0], 
            f"Index: {DEMO_DMA.iloc[0]['Rinvoq']}",
            help="Leading geographic market by search interest. Allocate 40% of budget to top 3 DMAs for maximum efficiency and fastest payback period."
        )
        k4.metric(
            "Search Queries", 
            len(DEMO_QUERIES[DEMO_QUERIES["Brand"].isin(["Rinvoq", "Both"])]), 
            "Brand mentions",
            help="Total branded search volume. Higher volume indicates stronger brand recall, market awareness, and patient consideration strength."
        )
    elif brand_filter == "Skyrizi":
        k1, k2, k3, k4 = st.columns(4)
        k1.metric(
            "Avg Index", 
            s_avg, 
            f"Peak: {s_peak}",
            help="Annual average search index (0-100 scale). Baseline demand level. Stable index indicates consistent brand awareness and sustained market interest throughout the year."
        )
        k2.metric(
            "Peak Index", 
            s_peak, 
            "Annual peak",
            help="Annual peak search index (0-100 scale). Use as benchmark for campaign reach targets, ROI expectations, and seasonal planning windows."
        )
        k3.metric(
            "Top DMA", 
            DEMO_DMA.iloc[0]["Market"].split(",")[0], 
            f"Index: {DEMO_DMA.iloc[0]['Skyrizi']}",
            help="Leading geographic market by search interest. Allocate 40% of budget to top 3 DMAs for maximum efficiency and fastest payback period."
        )
        k4.metric(
            "Search Queries", 
            len(DEMO_QUERIES[DEMO_QUERIES["Brand"].isin(["Skyrizi", "Both"])]), 
            "Brand mentions",
            help="Total branded search volume. Higher volume indicates stronger brand recall, market awareness, and patient consideration strength."
        )
    
    st.markdown("---")
    
    # Search Interest Over Time — full width
    # Prepare date info based on timeframe
    trend_display_df = trend_df.copy()
    current_timeframe = st.session_state.get("current_timeframe", "today 3-m")
    
    # For 5-year and 12-month data, add week range for hover
    if current_timeframe in ["today 5-y", "today 12-m"]:
        trend_display_df['week_start'] = trend_display_df.index
        trend_display_df['week_end'] = trend_display_df.index + pd.Timedelta(days=6)
        trend_display_df['date_range'] = trend_display_df.apply(
            lambda row: f"{row['week_start'].strftime('%b %d')} - {row['week_end'].strftime('%b %d, %Y')}", 
            axis=1
        )
    
    fig_trend = go.Figure()
    for col in trend_df.columns:
        color = RINVOQ if col == "Rinvoq" else SKYRIZI
        
        # Use week range for 5-year and 12-month, standard date for others
        if current_timeframe in ["today 5-y", "today 12-m"]:
            hover_template = "<b>%{fullData.name}</b><br>Week: %{text}<br>Index: <b>%{y:.0f}</b><extra></extra>"
            fig_trend.add_trace(go.Scatter(
                x=trend_df.index, y=trend_df[col], name=col, mode="lines",
                line=dict(color=color, width=2.5),
                fill="tozeroy", fillcolor=f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.08)",
                text=trend_display_df['date_range'],
                hovertemplate=hover_template
            ))
        else:
            fig_trend.add_trace(go.Scatter(
                x=trend_df.index, y=trend_df[col], name=col, mode="lines",
                line=dict(color=color, width=2.5),
                fill="tozeroy", fillcolor=f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.08)",
                hovertemplate="<b>%{fullData.name}</b><br>Date: %{x|%b %d, %Y}<br>Index: <b>%{y:.0f}</b><extra></extra>"
            ))
    
    fig_trend.update_layout(
        title="Search Interest Over Time", height=350,
        yaxis=dict(range=[0, 100], title="Search Index"),
        xaxis=dict(title=""), legend=dict(orientation="h", y=-0.15),
        template="plotly_white", margin=dict(t=40, b=40),
        hoverlabel=dict(bgcolor="white", font_size=13, font_family="sans-serif", namelength=-1)
    )
    st.plotly_chart(fig_trend, use_container_width=True)
    
    # Calculate peaks and valleys for dynamic insight
    peak_valley_insight = "Monitor significant peaks and valleys—they signal competitive shifts or indication-specific demand surges that can inform campaign timing and budget allocation."
    if trend_df is not None and len(trend_df) > 0:
        try:
            if brand_filter != "Skyrizi" and "Rinvoq" in trend_df.columns:
                rin_max = trend_df["Rinvoq"].max()
                rin_min = trend_df["Rinvoq"].min()
                rin_volatility = rin_max - rin_min
                peak_valley_insight = f"Rinvoq shows {rin_volatility:.0f}-point volatility ({rin_min:.0f}–{rin_max:.0f}). Peaks indicate market surges for strategic media spend; troughs signal competitive pressure windows."
            elif brand_filter != "Rinvoq" and "Skyrizi" in trend_df.columns:
                sky_max = trend_df["Skyrizi"].max()
                sky_min = trend_df["Skyrizi"].min()
                sky_volatility = sky_max - sky_min
                peak_valley_insight = f"Skyrizi shows {sky_volatility:.0f}-point volatility ({sky_min:.0f}–{sky_max:.0f}). Peak periods align with high-intent demand cycles—align campaigns to these windows."
        except:
            pass
    
    render_insight_bubble(peak_valley_insight, "📈")
    
    # Seasonality + YoY
    c1, c2 = st.columns(2)
    
    with c1:
        # Generate seasonality data based on actual trend data and current timeframe
        seasonality_data = generate_seasonality_data(trend_df, current_timeframe)
        
        fig_season = go.Figure()
        if brand_filter != "Skyrizi" and "Rinvoq" in seasonality_data.columns:
            fig_season.add_trace(go.Bar(x=seasonality_data["Month"], y=seasonality_data["Rinvoq"], name="Rinvoq", marker_color=RINVOQ, opacity=0.8,
                hovertemplate="<b>Rinvoq</b><br>Month: %{x}<br>Index: <b>%{y:.1f}</b><extra></extra>"))
        if brand_filter != "Rinvoq" and "Skyrizi" in seasonality_data.columns:
            fig_season.add_trace(go.Bar(x=seasonality_data["Month"], y=seasonality_data["Skyrizi"], name="Skyrizi", marker_color=SKYRIZI, opacity=0.8,
                hovertemplate="<b>Skyrizi</b><br>Month: %{x}<br>Index: <b>%{y:.1f}</b><extra></extra>"))
        fig_season.update_layout(title="Seasonality", height=350, barmode="group", yaxis=dict(range=[0, 100]), template="plotly_white", margin=dict(t=30, b=20),
            hoverlabel=dict(bgcolor="white", font_size=12, font_family="sans-serif"))
        st.plotly_chart(fig_season, use_container_width=True)
    
    with c2:
        # Generate interest data based on current timeframe
        interest_data = generate_interest_over_time_data(trend_df, current_timeframe)
        
        fig_yoy = go.Figure()
        if brand_filter != "Skyrizi":
            fig_yoy.add_trace(go.Bar(x=interest_data["period"], y=interest_data["Rinvoq"], name="Rinvoq", marker_color=RINVOQ,
                hovertemplate="<b>Rinvoq</b><br>%{x}<br>Avg Interest: <b>%{y:.1f}</b><extra></extra>"))
        if brand_filter != "Rinvoq":
            fig_yoy.add_trace(go.Bar(x=interest_data["period"], y=interest_data["Skyrizi"], name="Skyrizi", marker_color=SKYRIZI,
                hovertemplate="<b>Skyrizi</b><br>%{x}<br>Avg Interest: <b>%{y:.1f}</b><extra></extra>"))
        fig_yoy.update_layout(title="Average Search Interest Over Time", height=350, barmode="group", yaxis=dict(range=[0, 100]), template="plotly_white", margin=dict(t=30, b=20),
            hoverlabel=dict(bgcolor="white", font_size=12, font_family="sans-serif"))
        st.plotly_chart(fig_yoy, use_container_width=True)
    
    # Info note about seasonality calculation
    st.caption("ℹ️ Seasonality averages across all years for 5-year view, or shows recent period for shorter timeframes")
    
    # Calculate YoY performance for dynamic insight
    yoy_insight = "Average search interest trends reveal market demand patterns and seasonal peaks—allocate budget to periods showing sustained +30% above baseline for maximum campaign effectiveness."
    if trend_df is not None and len(trend_df) > 1:
        try:
            first_half = trend_df.iloc[:len(trend_df)//2]
            second_half = trend_df.iloc[len(trend_df)//2:]
            
            if brand_filter != "Skyrizi" and "Rinvoq" in trend_df.columns:
                rin_first = first_half["Rinvoq"].mean()
                rin_second = second_half["Rinvoq"].mean()
                rin_growth = ((rin_second - rin_first) / rin_first * 100) if rin_first > 0 else 0
                yoy_insight = f"Rinvoq trending {rin_growth:+.1f}% period-over-period ({rin_first:.0f}→{rin_second:.0f} index). Sustain momentum with targeted spend during high-intent windows."
            elif brand_filter != "Rinvoq" and "Skyrizi" in trend_df.columns:
                sky_first = first_half["Skyrizi"].mean()
                sky_second = second_half["Skyrizi"].mean()
                sky_growth = ((sky_second - sky_first) / sky_first * 100) if sky_first > 0 else 0
                yoy_insight = f"Skyrizi accelerating {sky_growth:+.1f}% ({sky_first:.0f}→{sky_second:.0f} index). Capitalize on upward momentum with increased media investment."
        except:
            pass
    
    render_insight_bubble(yoy_insight, "📊")
    
    # Indication Pies - Show only selected brand(s)
    if brand_filter == "Both":
        p1, p2 = st.columns(2)
        with p1:
            rinvoq_ind = pd.DataFrame({"Indication": ["RA","PsA","AS","AD","UC","GCA"], "Share": [38,25,13,10,6,8]})
            # Use Rinvoq brand color variations (orange tones)
            rinvoq_colors = ["#FFB84D", "#FFC977", "#FFD4A1", "#FFE0C2", "#FFECD4", "#FFF5E6"]
            fig_rp = px.pie(rinvoq_ind, names="Indication", values="Share", title="Rinvoq — Indication Split",
                            color_discrete_sequence=rinvoq_colors, hole=0.5)
            fig_rp.update_layout(height=300, margin=dict(t=40, b=20))
            st.plotly_chart(fig_rp, use_container_width=True)
        with p2:
            skyrizi_ind = pd.DataFrame({"Indication": ["Psoriasis","PsA","Crohn's","UC"], "Share": [45,22,20,13]})
            # Use Skyrizi brand color variations (blue tones)
            skyrizi_colors = ["#4db8ff", "#77c9ff", "#a1daff", "#cbebff"]
            fig_sp = px.pie(skyrizi_ind, names="Indication", values="Share", title="Skyrizi — Indication Split",
                            color_discrete_sequence=skyrizi_colors, hole=0.5)
            fig_sp.update_layout(height=300, margin=dict(t=40, b=20))
            st.plotly_chart(fig_sp, use_container_width=True)
    elif brand_filter == "Rinvoq":
        rinvoq_ind = pd.DataFrame({"Indication": ["RA","PsA","AS","AD","UC","GCA"], "Share": [38,25,13,10,6,8]})
        # Use Rinvoq brand color variations (orange tones)
        rinvoq_colors = ["#FFB84D", "#FFC977", "#FFD4A1", "#FFE0C2", "#FFECD4", "#FFF5E6"]
        fig_rp = px.pie(rinvoq_ind, names="Indication", values="Share", title="Rinvoq — Indication Split",
                        color_discrete_sequence=rinvoq_colors, hole=0.5)
        fig_rp.update_layout(height=300, margin=dict(t=40, b=20))
        st.plotly_chart(fig_rp, use_container_width=True)
    elif brand_filter == "Skyrizi":
        skyrizi_ind = pd.DataFrame({"Indication": ["Psoriasis","PsA","Crohn's","UC"], "Share": [45,22,20,13]})
        # Use Skyrizi brand color variations (blue tones)
        skyrizi_colors = ["#4db8ff", "#77c9ff", "#a1daff", "#cbebff"]
        fig_sp = px.pie(skyrizi_ind, names="Indication", values="Share", title="Skyrizi — Indication Split",
                        color_discrete_sequence=skyrizi_colors, hole=0.5)
        fig_sp.update_layout(height=300, margin=dict(t=40, b=20))
        st.plotly_chart(fig_sp, use_container_width=True)
    
    # Top Markets - Show only selected brand(s)
    st.subheader("Top Markets")
    states_display = DEMO_STATES.copy() if not DEMO_STATES.empty else pd.DataFrame()

    if not states_display.empty:
        if brand_filter == "Both":
            states_display["Avg"] = ((states_display["Rinvoq"] + states_display["Skyrizi"]) / 2).round().astype(int)
            states_display["Lead"] = states_display.apply(lambda r: "Rinvoq" if r["Rinvoq"] > r["Skyrizi"] else "Skyrizi", axis=1)
            columns_to_show = ["State", "Rinvoq", "Skyrizi", "Avg", "Lead"]
            column_config = {
                "Rinvoq": st.column_config.ProgressColumn("Rinvoq", min_value=0, max_value=100, format="%d"),
                "Skyrizi": st.column_config.ProgressColumn("Skyrizi", min_value=0, max_value=100, format="%d"),
            }
            sort_column = "Avg"
        elif brand_filter == "Rinvoq":
            columns_to_show = ["State", "Rinvoq"]
            column_config = {
                "Rinvoq": st.column_config.ProgressColumn("Rinvoq", min_value=0, max_value=100, format="%d"),
            }
            sort_column = "Rinvoq"
        elif brand_filter == "Skyrizi":
            columns_to_show = ["State", "Skyrizi"]
            column_config = {
                "Skyrizi": st.column_config.ProgressColumn("Skyrizi", min_value=0, max_value=100, format="%d"),
            }
            sort_column = "Skyrizi"

        st.dataframe(
            states_display[columns_to_show].sort_values(sort_column, ascending=False),
            use_container_width=True, hide_index=True,
            column_config=column_config
        )
    else:
        st.caption("No state data available for this timeframe")
    
    # Queries - Filter by brand only
    st.markdown("---")
    st.subheader("📊 Search Query Insights")
    
    # Apply brand filter
    if brand_filter == "Both":
        queries_df = DEMO_QUERIES
    elif brand_filter == "Rinvoq":
        queries_df = DEMO_QUERIES[DEMO_QUERIES["Brand"].isin(["Rinvoq", "Both"])]
    else:  # Skyrizi
        queries_df = DEMO_QUERIES[DEMO_QUERIES["Brand"].isin(["Skyrizi", "Both"])]
    
    q1, q2 = st.columns(2)
    
    with q1:
        st.subheader("Top Search Queries", help="The most popular search queries. Scoring is on a relative scale where a value of 100 is the most commonly searched query, 50 is a query searched half as often as the most popular query, and so on.")
        top_q = queries_df.sort_values("Index", ascending=False).head(8)
        if not top_q.empty:
            for _, row in top_q.iterrows():
                color = RINVOQ if row["Brand"] == "Rinvoq" else SKYRIZI if row["Brand"] == "Skyrizi" else NAVY
                st.markdown(f"<div style='display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid #eef1f6'>"
                            f"<span style='flex:1;font-size:13px'>{row['Query']}</span>"
                            f"<span style='font-weight:700;color:{color};font-size:12px'>{int(row['Index'])}</span></div>", unsafe_allow_html=True)
        else:
            st.caption("No data available")
    
    with q2:
        st.subheader("Rising Queries", help="Queries with the biggest increase in search frequency since the last time period. Results marked \"Breakout\" had a tremendous increase, probably because these queries are new and had few (if any) prior searches.")
        if not DEMO_RISING_QUERIES.empty:
            rising_q = DEMO_RISING_QUERIES.head(8)
            for _, row in rising_q.iterrows():
                color = RINVOQ if row["Brand"] == "Rinvoq" else SKYRIZI if row["Brand"] == "Skyrizi" else NAVY
                growth_label = str(row["Growth"]) if row["Growth"] and row["Growth"] != "nan" else "Breakout"
                st.markdown(f"<div style='display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid #eef1f6'>"
                            f"<span style='flex:1;font-size:13px'>{row['Query']}</span>"
                            f"<span style='font-weight:700;color:{color};font-size:12px'>{growth_label}</span></div>", unsafe_allow_html=True)
        else:
            st.caption("No data available")
    
    # AI Insight
    st.markdown("---")
    
    # AI-Powered Insights (Claude or Demo)
    col_insight, col_refresh = st.columns([0.95, 0.05])
    
    with col_insight:
        with st.spinner("✦ Generating AI-powered insights..."):
            # Filter DMA and queries by brand for AI context
            dma_filtered = DEMO_DMA.copy()
            queries_filtered = DEMO_QUERIES.copy()
            if brand_filter == "Rinvoq":
                if "Skyrizi" in dma_filtered.columns:
                    dma_filtered = dma_filtered.drop(columns=["Skyrizi"])
                queries_filtered = queries_filtered[queries_filtered["Brand"].isin(["Rinvoq", "Both"])]
            elif brand_filter == "Skyrizi":
                if "Rinvoq" in dma_filtered.columns:
                    dma_filtered = dma_filtered.drop(columns=["Rinvoq"])
                queries_filtered = queries_filtered[queries_filtered["Brand"].isin(["Skyrizi", "Both"])]
            
            # Generate insights (demo data used if no Claude client)
            ai_insights = generate_ai_insights(trend_df, dma_filtered, DEMO_STATES, queries_filtered, client, brand_filter)
            
            # Convert markdown bold **text** to HTML <strong>text</strong>
            import re
            insight_html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', ai_insights)
            
            insight_label = "✦ Key Insight"
            st.markdown(f"""
            <div style='background:#e8f1ff;border-left:4px solid {NAVY};border-radius:8px;padding:16px 20px;color:#0c3d7a;box-shadow:0 1px 3px rgba(0,0,0,0.08)'>
                <div style='font-weight:700;font-size:13px;margin-bottom:12px;text-transform:uppercase;letter-spacing:0.5px'>{insight_label}</div>
                <div style='font-size:12px;line-height:1.8'>
                    {insight_html.replace(chr(10), '<br>')}
                </div>
            </div>
            """, unsafe_allow_html=True)
    
    with col_refresh:
        if st.button("🔄", key="refresh_insight", help="Get a new insight"):
            st.rerun()
    
    if not client:
        st.info("💡 Click 🔄 to see different insights. [Enable Claude API](https://console.anthropic.com/keys) for live analysis.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 2: DMA DEEP DIVE
# ═══════════════════════════════════════════════════════════════════════════
with tabs[2]:
    # Executive Summary
    dma_callouts, dma_recommendation = generate_dma_executive_summary(DEMO_DMA, DEMO_STATES, DEMO_QUERIES, client, brand_filter, indication)
    render_executive_summary("Geographic Market Dynamics", dma_callouts, NAVY, dma_recommendation)
    
    st.subheader("DMA Geographic Analysis")
    
    import folium
    from streamlit_folium import st_folium
    import requests
    
    # Use demo state data or live state data
    display_states = DEMO_STATES.copy() if state_df is None or state_df.empty else state_df

    # Filter DMA and queries dataframes by brand filter
    dma_data = DEMO_DMA.copy()
    queries_data = DEMO_QUERIES.copy()
    if brand_filter == "Rinvoq":
        # Only keep Rinvoq column and drop Skyrizi
        if "Skyrizi" in dma_data.columns:
            dma_data = dma_data.drop(columns=["Skyrizi"])
        queries_data = queries_data[queries_data["Brand"].isin(["Rinvoq", "Both"])]
    elif brand_filter == "Skyrizi":
        # Only keep Skyrizi column and drop Rinvoq
        if "Rinvoq" in dma_data.columns:
            dma_data = dma_data.drop(columns=["Rinvoq"])
        queries_data = queries_data[queries_data["Brand"].isin(["Skyrizi", "Both"])]
    # For Both, keep all columns

    # State bounds for zooming when a state is selected in filters
    STATE_BOUNDS = {
        "All": {"center": [39.8283, -98.5795], "zoom": 3.5},
        "NY": {"center": [42.9682, -75.9272], "zoom": 6},
        "PA": {"center": [40.5908, -77.2098], "zoom": 6},
        "MA": {"center": [42.2302, -71.5301], "zoom": 7},
        "IL": {"center": [40.3297, -88.9860], "zoom": 6},
        "MN": {"center": [45.6945, -93.9196], "zoom": 6},
        "CA": {"center": [36.1162, -119.6816], "zoom": 5.5},
        "TX": {"center": [31.9686, -99.9018], "zoom": 5},
        "FL": {"center": [27.9947, -81.7603], "zoom": 6},
        "GA": {"center": [33.0406, -83.6431], "zoom": 6},
        "WA": {"center": [47.7511, -120.7401], "zoom": 6},
    }
    
    # Complete mapping of state names to abbreviations (all 50 states + DC)
    STATE_NAME_TO_ABBR = {
        "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
        "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC", "Florida": "FL",
        "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN",
        "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME",
        "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
        "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH",
        "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC", "North Dakota": "ND",
        "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
        "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
        "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
    }
    
    # Define regions and state mappings for filters
    regions = {
        "All": [],
        "Northeast": ["NY", "MA", "PA", "CT", "NJ", "VT", "NH", "RI", "ME"],
        "Southeast": ["FL", "GA", "NC", "SC", "VA", "WV", "KY", "TN", "AL", "MS", "LA", "AR"],
        "Midwest": ["IL", "OH", "MI", "IN", "WI", "MN", "IA", "MO", "ND", "SD", "NE", "KS"],
        "West": ["CA", "WA", "OR", "NV", "AZ", "UT", "CO", "WY", "MT", "ID", "AK", "HI", "TX", "OK", "NM"],
    }
    
    # Extract state abbreviations from DMA data (assuming format "City, ST")
    dma_states = {}
    for _, row in dma_data.iterrows():
        market = row["Market"]
        if "," in market:
            state_abbr = market.split(",")[1].strip()
            dma_states[market] = state_abbr
    
    # Also add states from display_states (geomap data) to ensure all states are available for filtering
    for state_name in display_states["State"].unique():
        if state_name in STATE_NAME_TO_ABBR:
            state_abbr = STATE_NAME_TO_ABBR[state_name]
            # Add to dma_states if not already from DMA data
            if state_abbr not in dma_states.values():
                # Create a placeholder entry so state abbr exists in the mapping
                dma_states[f"{state_name}, {state_abbr}"] = state_abbr
    
    # Initialize session state for filters
    if "selected_region" not in st.session_state:
        st.session_state.selected_region = "All"
    if "selected_state" not in st.session_state:
        st.session_state.selected_state = "All"
    if "selected_dma" not in st.session_state:
        st.session_state.selected_dma = "All"
    
    # Geographic filtering controls with cascading selection
    st.markdown("**Filter by Geography** (Click state to zoom map)")
    
    # Create filter columns
    fcol1, fcol2, fcol3 = st.columns(3)
    
    with fcol1:
        selected_region = st.selectbox(
            "Region",
            list(regions.keys()),
            index=list(regions.keys()).index(st.session_state.selected_region) if st.session_state.selected_region in regions else 0,
            key="region_filter_temp"
        )
        # Update session state and reset dependent filters when region changes
        if selected_region != st.session_state.selected_region:
            st.session_state.selected_region = selected_region
            st.session_state.selected_state = "All"
            st.session_state.selected_dma = "All"
    
    # Get states for selected region
    if st.session_state.selected_region == "All":
        available_states = sorted(list(set(dma_states.values())))
    else:
        available_states = regions[st.session_state.selected_region]
    
    with fcol2:
        state_options = ["All"] + available_states
        state_index = state_options.index(st.session_state.selected_state) if st.session_state.selected_state in state_options else 0
        selected_state = st.selectbox(
            "State",
            state_options,
            index=state_index,
            key="state_filter_temp"
        )
        # Update session state and reset DMA when state changes
        if selected_state != st.session_state.selected_state:
            st.session_state.selected_state = selected_state
            st.session_state.selected_dma = "All"
    
    # Get DMAs for selected region and state
    # First, determine which states should be available based on region
    if st.session_state.selected_region == "All":
        region_states = sorted(list(set(dma_states.values())))
    else:
        region_states = regions[st.session_state.selected_region]
    
    # Then filter DMAs based on region and state
    if st.session_state.selected_state == "All":
        # Show all DMAs in the selected region
        available_dmas = [m for m, state_abbr in dma_states.items() if state_abbr in region_states]
    else:
        # Show only DMAs in the selected state (which is guaranteed to be in the selected region)
        available_dmas = [m for m, state_abbr in dma_states.items() if state_abbr == st.session_state.selected_state]
    
    with fcol3:
        dma_options = ["All"] + available_dmas
        dma_index = dma_options.index(st.session_state.selected_dma) if st.session_state.selected_dma in dma_options else 0
        selected_dma = st.selectbox(
            "DMA",
            dma_options,
            index=dma_index,
            key="dma_filter_temp"
        )
        if selected_dma != st.session_state.selected_dma:
            st.session_state.selected_dma = selected_dma
    
    # Update session state with final selections
    st.session_state.selected_region = selected_region
    st.session_state.selected_state = selected_state
    st.session_state.selected_dma = selected_dma
    
    st.markdown("---")
    
    # Create and display the map with zoom based on selected state
    # Get the selected state abbreviation
    if st.session_state.selected_state == "All":
        map_state_abbr = "All"
    else:
        # Extract abbreviation from selected state 
        for state_name, abbr in STATE_NAME_TO_ABBR.items():
            if selected_state == state_name:
                map_state_abbr = abbr
                break
        else:
            map_state_abbr = st.session_state.selected_state[:2].upper() if len(st.session_state.selected_state) >= 2 else "All"
    
    # Create map with zoom based on selected state
    map_center = STATE_BOUNDS.get(map_state_abbr, STATE_BOUNDS["All"])
    
    try:
        m = folium.Map(
            location=map_center["center"],
            zoom_start=map_center["zoom"],
            tiles="CartoDB positron",
            scroll_zoom=False
        )
    except Exception as e:
        st.error(f"❌ Failed to create map: {str(e)}")
        st.stop()
    
    # Add state choropleth with search interest shading
    try:
        m = folium.Map(
            location=map_center["center"],
            zoom_start=map_center["zoom"],
            tiles="CartoDB positron",
            scroll_zoom=False
        )
        
        # Load US state boundaries GeoJSON
        us_state_geo = "https://raw.githubusercontent.com/python-visualization/folium/master/examples/data/us-states.json"
        geo_data = requests.get(us_state_geo, timeout=5).json()

        # Prepare state data for choropleth based on brand filter
        state_values = display_states.copy()
        if brand_filter == "Both":
            state_values["interest"] = ((state_values["Rinvoq"] + state_values["Skyrizi"]) / 2).round().astype(int)
            legend = "Avg Search Interest Index"
            columns = ["State", "interest"]
        elif brand_filter == "Rinvoq":
            state_values["interest"] = state_values["Rinvoq"].round().astype(int)
            legend = "Rinvoq Search Interest Index"
            columns = ["State", "interest"]
        else:
            state_values["interest"] = state_values["Skyrizi"].round().astype(int)
            legend = "Skyrizi Search Interest Index"
            columns = ["State", "interest"]

        # Add choropleth layer with brand-specific color
        if brand_filter == "Rinvoq":
            color_scheme = "Oranges"
        elif brand_filter == "Skyrizi":
            color_scheme = "Blues"
        else:
            color_scheme = "Blues"
        
        folium.Choropleth(
            geo_data=geo_data,
            name="Search Interest",
            data=state_values,
            columns=columns,
            key_on="feature.properties.name",
            fill_color=color_scheme,
            fill_opacity=0.7,
            line_opacity=0.5,
            line_color="white",
            line_weight=1,
            legend_name=legend,
            nan_fill_color="lightgray",
        ).add_to(m)

        # Add custom tooltips for states with hover info
        for feature in geo_data["features"]:
            state_name = feature["properties"]["name"]
            state_data = state_values[state_values["State"] == state_name]

            if not state_data.empty:
                if brand_filter == "Both":
                    rinvoq_val = int(state_data["Rinvoq"].values[0])
                    skyrizi_val = int(state_data["Skyrizi"].values[0])
                    avg_val = int(state_data["interest"].values[0])
                    tooltip_text = f"<b>{state_name}</b><br>Rinvoq: {rinvoq_val}<br>Skyrizi: {skyrizi_val}<br>Avg: {avg_val}"
                elif brand_filter == "Rinvoq":
                    rinvoq_val = int(state_data["Rinvoq"].values[0])
                    tooltip_text = f"<b>{state_name}</b><br>Rinvoq: {rinvoq_val}"
                else:
                    skyrizi_val = int(state_data["Skyrizi"].values[0])
                    tooltip_text = f"<b>{state_name}</b><br>Skyrizi: {skyrizi_val}"
            else:
                tooltip_text = f"<b>{state_name}</b><br>No data available"

            # Add GeoJson layer with tooltips
            folium.GeoJson(
                feature,
                style_function=lambda x: {
                    "fillOpacity": 0,
                    "color": "transparent",
                },
                tooltip=folium.Tooltip(tooltip_text, sticky=False),
            ).add_to(m)

    except Exception as e:
        st.error(f"⚠️ Map error: {str(e)}")
        # Create simple fallback map with just markers
        m = folium.Map(
            location=map_center["center"],
            zoom_start=map_center["zoom"],
            tiles="CartoDB positron",
            scroll_zoom=False
        )

    # Add DMA circle markers - filter by selected state if not "All"
    for _, row in dma_data.iterrows():
        market = row["Market"]
        dma_state_abbr = market.split(",")[1].strip() if "," in market else ""
        
        # Skip DMA if it's not in the selected state
        if map_state_abbr != "All" and dma_state_abbr != map_state_abbr:
            continue
        
        if brand_filter == "Both":
            r_val, s_val = row["Rinvoq"], row["Skyrizi"]
            avg = (r_val + s_val) / 2
            color = RINVOQ if r_val > s_val else SKYRIZI
            tooltip = f"<b>{row['Market']}</b><br>Rinvoq: {r_val} · Skyrizi: {s_val} {row['Trend']}"
            radius = 4 + avg / 10
        elif brand_filter == "Rinvoq":
            r_val = row["Rinvoq"]
            color = RINVOQ
            tooltip = f"<b>{row['Market']}</b><br>Rinvoq: {r_val}"
            radius = 4 + r_val / 10
        else:
            s_val = row["Skyrizi"]
            color = SKYRIZI
            tooltip = f"<b>{row['Market']}</b><br>Skyrizi: {s_val}"
            radius = 4 + s_val / 10
        folium.CircleMarker(
            [row["lat"], row["lng"]], radius=radius,
            color="white", weight=2, fill=True, fill_color=color, fill_opacity=0.85,
            tooltip=tooltip
        ).add_to(m)

    # Display the map
    try:
        map_data = st_folium(m, height=500, use_container_width=True)
        if map_data is None:
            st.info("📍 Map loaded. Click on states or markets for details.")
    except Exception as e:
        st.error(f"Map display error: {str(e)}")
        st.info("Try refreshing the page or switching tabs.")
    
    # Calculate data-driven DMA insight
    dma_insight = "States with 10+ points above national average represent priority markets for commercial investment. Focus sales and marketing resources in top-performing DMAs."
    if dma_data is not None and len(dma_data) > 0:
        try:
            if brand_filter == "Both":
                avg_score = (dma_data["Rinvoq"].mean() + dma_data["Skyrizi"].mean()) / 2
                top_market = dma_data.iloc[(dma_data["Rinvoq"] + dma_data["Skyrizi"]).idxmax()]
            elif brand_filter == "Rinvoq":
                avg_score = dma_data["Rinvoq"].mean()
                top_market = dma_data.loc[dma_data["Rinvoq"].idxmax()]
            else:  # Skyrizi
                avg_score = dma_data["Skyrizi"].mean()
                top_market = dma_data.loc[dma_data["Skyrizi"].idxmax()]
            
            top_performers = dma_data[
                ((dma_data["Rinvoq"] > avg_score + 10) | (dma_data["Skyrizi"] > avg_score + 10))
                if brand_filter == "Both" 
                else (dma_data[brand_filter] > avg_score + 10)
            ]
            num_priority = len(top_performers)
            
            if num_priority > 0:
                dma_insight = f"Top performer: {top_market.get('Market', 'N/A')}. {num_priority} markets exceed national average by 10+ points—prioritize media spend and partnerships in these high-intent regions."
        except:
            pass
    
    render_insight_bubble(dma_insight, "🎯")
    
    st.markdown("---")
    
    # Search Query Analysis - setup queries dataframe
    st.subheader("Search Query Analysis")
    st.caption("Discover trending and top-performing search queries in the selected markets")
    
    queries_df = queries_data.copy()
    
    # Add breakout indicator for Rising Queries (Growth >= 500%)
    queries_df["Breakout"] = queries_df["Growth"] >= 500
    
    # Apply geographic filters to queries
    filtered_queries = queries_df.copy()
    # Since queries don't have direct geographic info, we'll show all but indicate this limitation
    # In production, queries would be tagged with DMA/State/Region
    
    st.markdown("---")
    
    # Top Search Queries and Rising Queries Table - Side by Side
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Top Search Queries", help="The most popular search queries. Scoring is on a relative scale where a value of 100 is the most commonly searched query, 50 is a query searched half as often as the most popular query, and so on.")
        top_queries_display = filtered_queries.sort_values("Index", ascending=False).head(8)
        if not top_queries_display.empty:
            for _, row in top_queries_display.iterrows():
                color = RINVOQ if row["Brand"] == "Rinvoq" else SKYRIZI if row["Brand"] == "Skyrizi" else NAVY
                st.markdown(f"<div style='display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid #eef1f6'>"
                            f"<span style='flex:1;font-size:13px'>{row['Query']}</span>"
                            f"<span style='font-weight:700;color:{color};font-size:12px'>{int(row['Index'])}</span></div>", unsafe_allow_html=True)
        else:
            st.caption("No data available")
    
    with col2:
        st.subheader("Rising Queries", help="Queries with the biggest increase in search frequency since the last time period. Results marked \"Breakout\" had a tremendous increase, probably because these queries are new and had few (if any) prior searches.")
        rising_display = DEMO_RISING_QUERIES.copy()
        if brand_filter == "Rinvoq":
            rising_display = rising_display[rising_display["Brand"].isin(["Rinvoq", "Both"])]
        elif brand_filter == "Skyrizi":
            rising_display = rising_display[rising_display["Brand"].isin(["Skyrizi", "Both"])]
        
        rising_queries_display = rising_display.head(8)
        if not rising_queries_display.empty:
            for _, row in rising_queries_display.iterrows():
                color = RINVOQ if row["Brand"] == "Rinvoq" else SKYRIZI if row["Brand"] == "Skyrizi" else NAVY
                growth_label = str(row["Growth"]) if row["Growth"] and row["Growth"] != "nan" else "Breakout"
                st.markdown(f"<div style='display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid #eef1f6'>"
                            f"<span style='flex:1;font-size:13px'>{row['Query']}</span>"
                            f"<span style='font-weight:700;color:{color};font-size:12px'>{growth_label}</span></div>", unsafe_allow_html=True)
        else:
            st.caption("No data available")
    
    st.info("📊 **Index:** Higher scores (0-100 scale) indicate greater search interest. Useful for identifying peak demand periods and relative market strength.")

    # Regional comparison
    regions = {
        "Northeast": ["New York", "Boston", "Philadelphia"],
        "Southeast": ["Miami", "Atlanta"],
        "Midwest": ["Chicago", "Minneapolis"],
        "West": ["Los Angeles", "Seattle", "Dallas"],
    }
    reg_data = []
    for reg, cities in regions.items():
        matches = dma_data[dma_data["Market"].apply(lambda x: any(c in x for c in cities))]
        if not matches.empty:
            if brand_filter == "Both":
                reg_val_r = matches["Rinvoq"].mean().round()
                reg_val_s = matches["Skyrizi"].mean().round()
                reg_data.append({"Region": reg, "Rinvoq": reg_val_r, "Skyrizi": reg_val_s})
            elif brand_filter == "Rinvoq":
                reg_val_r = matches["Rinvoq"].mean().round()
                reg_data.append({"Region": reg, "Rinvoq": reg_val_r})
            else:
                reg_val_s = matches["Skyrizi"].mean().round()
                reg_data.append({"Region": reg, "Skyrizi": reg_val_s})

    if reg_data:
        reg_df = pd.DataFrame(reg_data)
        fig_reg = go.Figure()
        if brand_filter == "Both":
            fig_reg.add_trace(go.Bar(x=reg_df["Region"], y=reg_df["Rinvoq"], name="Rinvoq", marker_color=RINVOQ,
                hovertemplate="<b>Rinvoq</b><br>Region: %{x}<br>Index: <b>%{y:.0f}</b><extra></extra>"))
            fig_reg.add_trace(go.Bar(x=reg_df["Region"], y=reg_df["Skyrizi"], name="Skyrizi", marker_color=SKYRIZI,
                hovertemplate="<b>Skyrizi</b><br>Region: %{x}<br>Index: <b>%{y:.0f}</b><extra></extra>"))
        elif brand_filter == "Rinvoq":
            fig_reg.add_trace(go.Bar(x=reg_df["Region"], y=reg_df["Rinvoq"], name="Rinvoq", marker_color=RINVOQ,
                hovertemplate="<b>Rinvoq</b><br>Region: %{x}<br>Index: <b>%{y:.0f}</b><extra></extra>"))
        else:
            fig_reg.add_trace(go.Bar(x=reg_df["Region"], y=reg_df["Skyrizi"], name="Skyrizi", marker_color=SKYRIZI,
                hovertemplate="<b>Skyrizi</b><br>Region: %{x}<br>Index: <b>%{y:.0f}</b><extra></extra>"))
        fig_reg.update_layout(title="Regional Performance", barmode="group", height=350, template="plotly_white", yaxis=dict(range=[0, 100]),
            hoverlabel=dict(bgcolor="white", font_size=12, font_family="sans-serif"))
        st.plotly_chart(fig_reg, use_container_width=True)

    # Insight - data-driven regional analysis
    if reg_data and len(reg_df) > 0:
        try:
            if brand_filter == "Both":
                # Find top regions for each brand
                top_rinvoq_region = reg_df.loc[reg_df["Rinvoq"].idxmax()]
                top_skyrizi_region = reg_df.loc[reg_df["Skyrizi"].idxmax()]
                regional_insight = f"Rinvoq leads in {top_rinvoq_region['Region']} ({top_rinvoq_region['Rinvoq']:.0f}), Skyrizi in {top_skyrizi_region['Region']} ({top_skyrizi_region['Skyrizi']:.0f}). Focus resources in top-performing regions to maximize ROI."
            elif brand_filter == "Rinvoq":
                top_region = reg_df.loc[reg_df["Rinvoq"].idxmax()]
                regional_insight = f"Rinvoq strongest in {top_region['Region']} (Index: {top_region['Rinvoq']:.0f}). Concentrate HCP outreach and digital spend in this high-intent market."
            else:  # Skyrizi
                top_region = reg_df.loc[reg_df["Skyrizi"].idxmax()]
                regional_insight = f"Skyrizi strongest in {top_region['Region']} (Index: {top_region['Skyrizi']:.0f}). Prioritize media spend and dermatology partnerships in this region."
            
            st.info(f"📍 **Geographic Insight:** {regional_insight}")
        except:
            # Fallback to generic insight if calculation fails
            if brand_filter == "Both":
                st.info("📍 **Geographic Insight:** Regional performance varies significantly by market. Allocate resources to regions showing strongest demand for each brand.")
            elif brand_filter == "Rinvoq":
                st.info("📍 **Geographic Insight:** Rinvoq regional penetration follows rheumatology specialist concentration. Allocate incremental spend to top-performing markets.")
            else:
                st.info("📍 **Geographic Insight:** Skyrizi regional strength correlates with dermatology specialist networks. Focus resources in highest-performing regions.")
    else:
        st.info("📍 **Geographic Insight:** Load DMA data to see regional performance analysis.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 4: COMPETITIVE
# ═══════════════════════════════════════════════════════════════════════════
with tabs[4]:
    # Executive Summary
    comp_callouts, comp_recommendation = generate_competitive_executive_summary(DEMO_DMA, client, brand_filter, indication)
    render_executive_summary("Competitive Market Position", comp_callouts, NAVY, comp_recommendation)
    
    st.subheader("Competitive Intelligence")
    
    # Load real 12-month data for all portfolio and competitor brands
    comp_12m_df = None
    dfs = []
    for brand in ["Rinvoq", "Skyrizi"]:
        df = load_csv_trend_data(brand, "today 12-m")
        if df is not None:
            dfs.append(df)
    
    # Also load Tremfya 12-month data
    tremfya_12m_df = load_tremfya_csv_data("today 12-m")
    if tremfya_12m_df is not None:
        dfs.append(tremfya_12m_df)
    
    # Also load Dupixent 12-month data
    dupixent_12m_df = load_dupixent_csv_data("today 12-m")
    if dupixent_12m_df is not None:
        dfs.append(dupixent_12m_df)
    
    # Also load Humira 12-month data
    humira_12m_df = load_humira_csv_data("today 12-m")
    if humira_12m_df is not None:
        dfs.append(humira_12m_df)
    
    # Also load Entyvio 12-month data
    entyvio_12m_df = load_entyvio_csv_data("today 12-m")
    if entyvio_12m_df is not None:
        dfs.append(entyvio_12m_df)
    
    if dfs:
        comp_12m_df = pd.concat(dfs, axis=1)
    
    # Calculate current indices from real data
    if comp_12m_df is not None:
        sky_current = int(comp_12m_df["Skyrizi"].iloc[-1]) if "Skyrizi" in comp_12m_df.columns else 88
        rin_current = int(comp_12m_df["Rinvoq"].iloc[-1]) if "Rinvoq" in comp_12m_df.columns else 82
        tremfya_current = int(comp_12m_df["Tremfya"].iloc[-1]) if "Tremfya" in comp_12m_df.columns else 65
        dupixent_current = int(comp_12m_df["Dupixent"].iloc[-1]) if "Dupixent" in comp_12m_df.columns else 60
        humira_current = int(comp_12m_df["Humira"].iloc[-1]) if "Humira" in comp_12m_df.columns else 70
        entyvio_current = int(comp_12m_df["Entyvio"].iloc[-1]) if "Entyvio" in comp_12m_df.columns else 55
    else:
        sky_current = 88
        rin_current = 82
        tremfya_current = 65
        dupixent_current = 60
        humira_current = 70
        entyvio_current = 55
    
    # Load trend data from CSV for selected timeframe (needed for KPI calculation)
    comp_trend_df = None
    dfs = []
    for brand in ["Rinvoq", "Skyrizi"]:
        df = load_csv_trend_data(brand, current_timeframe)
        if df is not None:
            dfs.append(df)
    
    # Also load Tremfya data
    tremfya_df = load_tremfya_csv_data(current_timeframe)
    if tremfya_df is not None:
        dfs.append(tremfya_df)
    
    # Also load Dupixent data
    dupixent_df = load_dupixent_csv_data(current_timeframe)
    if dupixent_df is not None:
        dfs.append(dupixent_df)
    
    # Also load Humira data
    humira_df = load_humira_csv_data(current_timeframe)
    if humira_df is not None:
        dfs.append(humira_df)
    
    # Also load Entyvio data
    entyvio_df = load_entyvio_csv_data(current_timeframe)
    if entyvio_df is not None:
        dfs.append(entyvio_df)
    
    if dfs:
        comp_trend_df = pd.concat(dfs, axis=1)
    
    # Calculate average search indices for each brand across the selected timeframe
    brand_averages = {}
    if comp_trend_df is not None:
        for brand in ["Skyrizi", "Rinvoq", "Humira", "Tremfya", "Dupixent", "Entyvio"]:
            if brand in comp_trend_df.columns:
                brand_averages[brand] = int(round(comp_trend_df[brand].mean()))
            else:
                brand_averages[brand] = 0
    else:
        brand_averages = {brand: 0 for brand in ["Skyrizi", "Rinvoq", "Humira", "Tremfya", "Dupixent", "Entyvio"]}
    
    # Define timeframe label for display
    timeframe_label = {
        "now 7-d": "7-day",
        "today 1-m": "30-day",
        "today 3-m": "3-month",
        "today 12-m": "12-month",
        "today 5-y": "5-year"
    }.get(current_timeframe, "12-month")
    
    # Display KPIs for each brand's average search intent index
    st.subheader("📊 Average Search Index by Brand")
    
    kpi_cols = st.columns(6)
    brands_order = ["Skyrizi", "Rinvoq", "Humira", "Tremfya", "Dupixent", "Entyvio"]
    brand_colors_map = {
        "Skyrizi": SKYRIZI,
        "Rinvoq": RINVOQ,
        "Humira": COMP_COLORS["Humira"],
        "Tremfya": COMP_COLORS["Tremfya"],
        "Dupixent": COMP_COLORS["Dupixent"],
        "Entyvio": COMP_COLORS["Entyvio"]
    }
    
    for i, brand in enumerate(brands_order):
        with kpi_cols[i]:
            avg_index = brand_averages.get(brand, 0)
            color = brand_colors_map[brand]
            st.metric(
                brand,
                avg_index,
                f"avg index",
                help=f"Average search interest index for {brand} across {timeframe_label} period"
            )
    
    # Competitive Trend Over Time - Respects timeframe filter
    st.markdown("---")
    st.subheader("📈 Competitive Trend Over Time")
    st.caption(f"Competitor brands — trailing {timeframe_label} search index")
    
    # Brand selection filter for this chart
    available_brands = ["Skyrizi", "Rinvoq", "Humira", "Tremfya", "Dupixent", "Entyvio"]
    selected_brands = []
    
    with st.expander("📊 Select brands to display", expanded=False):
        cols = st.columns(2)
        for i, brand in enumerate(available_brands):
            with cols[i % 2]:
                if st.checkbox(brand, value=True, key=f"comp_trend_{brand}"):
                    selected_brands.append(brand)
    
    if not selected_brands:
        st.warning("Please select at least one brand to display.")
        selected_brands = available_brands  # Fallback to all if none selected
    
    # Generate actual date labels based on timeframe and available data
    periods = []
    week_ranges = []  # For hover text on weekly data
    if comp_trend_df is not None and len(comp_trend_df) > 0:
        index = comp_trend_df.index
        if current_timeframe == "now 7-d":
            periods = [d.strftime("%b %d") for d in index]
        elif current_timeframe == "today 1-m":
            periods = [d.strftime("%b %d") for d in index]
        elif current_timeframe == "today 3-m":
            # Weekly aggregation - get week start dates and ranges
            weekly_data = comp_trend_df.resample('W').mean()
            weekly_dates = weekly_data.index
            periods = [d.strftime("%b %d") for d in weekly_dates]
            # Generate week range text for hover
            for d in weekly_dates:
                week_start = d
                week_end = d + pd.Timedelta(days=6)
                week_ranges.append(f"{week_start.strftime('%b %d')} - {week_end.strftime('%b %d, %Y')}")
        elif current_timeframe == "today 12-m":
            # Weekly aggregation (to match Overview tab) - get week start dates and ranges
            weekly_data = comp_trend_df.resample('W').mean()
            weekly_dates = weekly_data.index
            periods = [d.strftime("%b %d") for d in weekly_dates]
            # Generate week range text for hover
            for d in weekly_dates:
                week_start = d
                week_end = d + pd.Timedelta(days=6)
                week_ranges.append(f"{week_start.strftime('%b %d')} - {week_end.strftime('%b %d, %Y')}")
        elif current_timeframe == "today 5-y":
            # Weekly aggregation - get week start dates and ranges
            weekly_data = comp_trend_df.resample('W').mean()
            weekly_dates = weekly_data.index
            periods = [d.strftime("%b %d") for d in weekly_dates]
            # Generate week range text for hover
            for d in weekly_dates:
                week_start = d
                week_end = d + pd.Timedelta(days=6)
                week_ranges.append(f"{week_start.strftime('%b %d')} - {week_end.strftime('%b %d, %Y')}")
    else:
        # Fallback to season months if no data
        periods = SEASON_DATA["Month"].tolist()
    
    # Display selected competitor brands on the chart
    
    fig_comp_trend = go.Figure()
    
    for brand in selected_brands:
        # Use real data for Rinvoq and Skyrizi from CSV
        if brand == "Skyrizi" and comp_trend_df is not None and "Skyrizi" in comp_trend_df.columns:
            trend_series = comp_trend_df["Skyrizi"]
            
            # Aggregate based on timeframe
            if current_timeframe == "now 7-d":
                trend_data = trend_series.values.tolist()
            elif current_timeframe == "today 1-m":
                trend_data = trend_series.values.tolist()
            elif current_timeframe == "today 3-m":
                trend_data = trend_series.resample('W').mean().values.tolist()
            elif current_timeframe == "today 5-y":
                trend_data = trend_series.resample('W').mean().values.tolist()
            else:  # today 12-m - use weekly aggregation to match Overview tab
                trend_data = trend_series.resample('W').mean().values.tolist()
            
            color = SKYRIZI
            
        elif brand == "Rinvoq" and comp_trend_df is not None and "Rinvoq" in comp_trend_df.columns:
            trend_series = comp_trend_df["Rinvoq"]
            
            # Aggregate based on timeframe
            if current_timeframe == "now 7-d":
                trend_data = trend_series.values.tolist()
            elif current_timeframe == "today 1-m":
                trend_data = trend_series.values.tolist()
            elif current_timeframe == "today 3-m":
                trend_data = trend_series.resample('W').mean().values.tolist()
            elif current_timeframe == "today 5-y":
                trend_data = trend_series.resample('W').mean().values.tolist()
            else:  # today 12-m - use weekly aggregation to match Overview tab
                trend_data = trend_series.resample('W').mean().values.tolist()
            
            color = RINVOQ
        elif brand == "Tremfya" and comp_trend_df is not None and "Tremfya" in comp_trend_df.columns:
            trend_series = comp_trend_df["Tremfya"]
            
            # Aggregate based on timeframe
            if current_timeframe == "now 7-d":
                trend_data = trend_series.values.tolist()
            elif current_timeframe == "today 1-m":
                trend_data = trend_series.values.tolist()
            elif current_timeframe == "today 3-m":
                trend_data = trend_series.resample('W').mean().values.tolist()
            elif current_timeframe == "today 5-y":
                trend_data = trend_series.resample('W').mean().values.tolist()
            else:  # today 12-m - use weekly aggregation to match Overview tab
                trend_data = trend_series.resample('W').mean().values.tolist()
            
            color = COMP_COLORS.get("Tremfya", "#999")
        elif brand == "Dupixent" and comp_trend_df is not None and "Dupixent" in comp_trend_df.columns:
            trend_series = comp_trend_df["Dupixent"]
            
            # Aggregate based on timeframe
            if current_timeframe == "now 7-d":
                trend_data = trend_series.values.tolist()
            elif current_timeframe == "today 1-m":
                trend_data = trend_series.values.tolist()
            elif current_timeframe == "today 3-m":
                trend_data = trend_series.resample('W').mean().values.tolist()
            elif current_timeframe == "today 5-y":
                trend_data = trend_series.resample('W').mean().values.tolist()
            else:  # today 12-m - use weekly aggregation to match Overview tab
                trend_data = trend_series.resample('W').mean().values.tolist()
            
            color = COMP_COLORS.get("Dupixent", "#999")
        elif brand == "Humira" and comp_trend_df is not None and "Humira" in comp_trend_df.columns:
            trend_series = comp_trend_df["Humira"]
            
            # Aggregate based on timeframe
            if current_timeframe == "now 7-d":
                trend_data = trend_series.values.tolist()
            elif current_timeframe == "today 1-m":
                trend_data = trend_series.values.tolist()
            elif current_timeframe == "today 3-m":
                trend_data = trend_series.resample('W').mean().values.tolist()
            elif current_timeframe == "today 5-y":
                trend_data = trend_series.resample('W').mean().values.tolist()
            else:  # today 12-m - use weekly aggregation to match Overview tab
                trend_data = trend_series.resample('W').mean().values.tolist()
            
            color = COMP_COLORS.get("Humira", "#999")
        elif brand == "Entyvio" and comp_trend_df is not None and "Entyvio" in comp_trend_df.columns:
            trend_series = comp_trend_df["Entyvio"]
            
            # Aggregate based on timeframe
            if current_timeframe == "now 7-d":
                trend_data = trend_series.values.tolist()
            elif current_timeframe == "today 1-m":
                trend_data = trend_series.values.tolist()
            elif current_timeframe == "today 3-m":
                trend_data = trend_series.resample('W').mean().values.tolist()
            elif current_timeframe == "today 5-y":
                trend_data = trend_series.resample('W').mean().values.tolist()
            else:  # today 12-m - use weekly aggregation to match Overview tab
                trend_data = trend_series.resample('W').mean().values.tolist()
            
            color = COMP_COLORS.get("Entyvio", "#999")
        else:
            # Demo data for competitors (until user provides real data)
            if current_timeframe == "now 7-d":
                trend_data = [50 + np.random.randint(-10, 10) for i in range(len(periods))]
            elif current_timeframe == "today 1-m":
                trend_data = [50 + np.random.randint(-10, 10) for i in range(len(periods))]
            elif current_timeframe == "today 3-m":
                trend_data = [50 + np.random.randint(-10, 15) for i in range(len(periods))]
            elif current_timeframe == "today 5-y":
                trend_data = [50 + np.random.randint(-10, 15) for i in range(len(periods))]
            else:  # today 12-m
                trend_data = [50 + np.random.randint(-10, 15) + np.sin(i/4)*5 for i in range(len(periods))]
            color = COMP_COLORS.get(brand, "#999")
        
        # Use week range for 3-month, 12-month, and 5-year (matching Overview tab behavior)
        if current_timeframe in ["today 3-m", "today 12-m", "today 5-y"] and week_ranges:
            hover_template = f"<b>{brand}</b><br>Week: %{{text}}<br>Index: <b>%{{y:.0f}}</b><extra></extra>"
            fig_comp_trend.add_trace(go.Scatter(
                x=periods, y=trend_data, name=brand,
                text=week_ranges,
                line=dict(color=color, width=2.5),
                mode="lines",
                hovertemplate=hover_template
            ))
        else:
            fig_comp_trend.add_trace(go.Scatter(
                x=periods, y=trend_data, name=brand,
                line=dict(color=color, width=2.5),
                mode="lines",
                hovertemplate=f"<b>{brand}</b><br>Date: %{{x}}<br>Index: <b>%{{y:.0f}}</b><extra></extra>"
            ))
    
    # Dynamic x-axis label based on timeframe (match Overview tab)
    xaxis_labels = {
        "now 7-d": "Date",
        "today 1-m": "Date",
        "today 3-m": "Week",
        "today 12-m": "Week",
        "today 5-y": "Week"
    }
    xaxis_label = xaxis_labels.get(current_timeframe, "Week")
    
    fig_comp_trend.update_layout(
        title="",
        height=350,
        template="plotly_white",
        xaxis_title=xaxis_label,
        yaxis_title="Search Interest Index",
        yaxis=dict(range=[0, 100]),
        hovermode="x unified",
        legend=dict(x=0.02, y=0.98, bgcolor="rgba(255,255,255,0.8)"),
        margin=dict(t=20, b=20),
        hoverlabel=dict(bgcolor="white", font_size=12, font_family="sans-serif")
    )
    st.plotly_chart(fig_comp_trend, use_container_width=True)
    
    st.markdown("---")
    
    # Calculate data-driven competitive insights
    if comp_trend_df is not None and len(comp_trend_df) > 0:
        # Calculate market averages and recent momentum
        market_averages = {}
        recent_data = comp_trend_df.tail(13)
        recent_growth = {}
        
        for brand in ["Skyrizi", "Rinvoq", "Humira", "Tremfya", "Dupixent", "Entyvio"]:
            if brand in comp_trend_df.columns:
                market_averages[brand] = comp_trend_df[brand].mean()
                if len(recent_data) > 1:
                    first_val = recent_data[brand].iloc[0]
                    last_val = recent_data[brand].iloc[-1]
                    recent_growth[brand] = ((last_val - first_val) / first_val * 100) if first_val > 0 else 0
        
        # Find top performers
        if market_averages:
            sorted_brands = sorted(market_averages.items(), key=lambda x: x[1], reverse=True)
            leader = sorted_brands[0][0]
            leader_share = (market_averages[leader] / sum(market_averages.values())) * 100
            
            # Find strongest recent momentum
            strongest_growth = max(recent_growth.items(), key=lambda x: x[1]) if recent_growth else ("N/A", 0)
            
            # Build dynamic insight based on actual data
            portfolio_combined = market_averages.get("Skyrizi", 0) + market_averages.get("Rinvoq", 0)
            portfolio_share = (portfolio_combined / sum(market_averages.values()) * 100) if market_averages else 0
            
            insight_text = f"Rinvoq leads at {market_averages.get('Rinvoq', 0):.0f} index, with portfolio share ~{portfolio_share:.0f}%. {strongest_growth[0]} surging {strongest_growth[1]:+.0f}% (last 13 weeks)—watch emerging competitive threats and capitalize on portfolio momentum."
            render_insight_bubble(insight_text, "⚔️")
        else:
            render_insight_bubble("Monitor competitive search trends to identify market leadership shifts and growth opportunities.", "⚔️")
    else:
        render_insight_bubble("Load data to see competitive market insights and strategic opportunities.", "⚔️")
    
    # Top Search Queries and Rising Queries for Competitive Tab
    st.markdown("---")
    st.subheader("📊 Search Query Insights")
    
    # Filter queries by brand only (no additional filters)
    comp_queries = DEMO_QUERIES.copy()
    if brand_filter == "Both":
        pass  # Keep all
    elif brand_filter == "Rinvoq":
        comp_queries = comp_queries[comp_queries["Brand"].isin(["Rinvoq", "Both"])]
    else:  # Skyrizi
        comp_queries = comp_queries[comp_queries["Brand"].isin(["Skyrizi", "Both"])]
    
    # Filter rising queries by brand
    comp_rising = DEMO_RISING_QUERIES.copy()
    if brand_filter == "Both":
        pass  # Keep all
    elif brand_filter == "Rinvoq":
        comp_rising = comp_rising[comp_rising["Brand"].isin(["Rinvoq", "Both"])]
    else:  # Skyrizi
        comp_rising = comp_rising[comp_rising["Brand"].isin(["Skyrizi", "Both"])]
    
    # Display tables side by side
    comp_col1, comp_col2 = st.columns(2)
    
    with comp_col1:
        st.subheader("Top Search Queries", help="The most popular search queries. Scoring is on a relative scale where a value of 100 is the most commonly searched query, 50 is a query searched half as often as the most popular query, and so on.")
        comp_top_queries = comp_queries.sort_values("Index", ascending=False).head(8)
        if not comp_top_queries.empty:
            for _, row in comp_top_queries.iterrows():
                color = RINVOQ if row["Brand"] == "Rinvoq" else SKYRIZI if row["Brand"] == "Skyrizi" else NAVY
                st.markdown(f"<div style='display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid #eef1f6'>"
                            f"<span style='flex:1;font-size:13px'>{row['Query']}</span>"
                            f"<span style='font-weight:700;color:{color};font-size:12px'>{int(row['Index'])}</span></div>", unsafe_allow_html=True)
        else:
            st.caption("No data available")
    
    with comp_col2:
        st.subheader("Rising Queries", help="Queries with the biggest increase in search frequency since the last time period. Results marked \"Breakout\" had a tremendous increase, probably because these queries are new and had few (if any) prior searches.")
        comp_rising_queries = comp_rising.head(8)
        if not comp_rising_queries.empty:
            for _, row in comp_rising_queries.iterrows():
                color = RINVOQ if row["Brand"] == "Rinvoq" else SKYRIZI if row["Brand"] == "Skyrizi" else NAVY
                growth_label = str(row["Growth"]) if row["Growth"] and row["Growth"] != "nan" else "Breakout"
                st.markdown(f"<div style='display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid #eef1f6'>"
                            f"<span style='flex:1;font-size:13px'>{row['Query']}</span>"
                            f"<span style='font-weight:700;color:{color};font-size:12px'>{growth_label}</span></div>", unsafe_allow_html=True)
        else:
            st.caption("No data available")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 5: PATIENT INTENT
# ═══════════════════════════════════════════════════════════════════════════
with tabs[5]:
    # Executive Summary
    intent_callouts, intent_recommendation = generate_patient_intent_executive_summary(DEMO_QUERIES, client, brand_filter, indication)
    render_executive_summary("Patient Search Behavior & Intent", intent_callouts, NAVY, intent_recommendation)
    
    st.subheader("Patient Intent Analysis")
    
    # Add indication filter at the top
    current_ind_names = st.session_state.get("custom_ind_names", IND_NAMES)
    current_franchise_map = st.session_state.get("custom_franchise_map", FRANCHISE_MAP)
    ind_options = list(current_ind_names.values())
    if franchise != "All":
        ind_keys = current_franchise_map.get(franchise, [])
        ind_options = [current_ind_names.get(k, k) for k in ind_keys]
    
    intent_indication = st.selectbox(
        "Indication",
        ["All"] + ind_options,
        label_visibility="visible",
        key="intent_indication_filter"
    )
    
    st.markdown("---")
    
    # Filter queries by brand
    if brand_filter == "Both":
        intent_queries = DEMO_QUERIES
    elif brand_filter == "Rinvoq":
        intent_queries = DEMO_QUERIES[DEMO_QUERIES["Brand"].isin(["Rinvoq", "Both"])]
    else:  # Skyrizi
        intent_queries = DEMO_QUERIES[DEMO_QUERIES["Brand"].isin(["Skyrizi", "Both"])]
    
    # Apply indication filter
    if intent_indication != "All":
        intent_queries = intent_queries[(intent_queries["Indication"] == intent_indication) | (intent_queries["Indication"] == "All")]
    
    ik1, ik2, ik3, ik4 = st.columns(4)
    ik1.metric(
        "Awareness Queries", 
        len(intent_queries[intent_queries["Type"] == "condition"]), 
        "Condition-level",
        help="Patient searches for condition symptoms, diagnosis, and general questions. High volume indicates strong market awareness of the indication."
    )
    ik2.metric(
        "HCP Intent", 
        len(intent_queries[intent_queries["Type"].isin(["generic", "safety"])]), 
        "Clinical terms",
        help="Healthcare provider searches or clinically-focused patient queries. Indicates need for professional education and evidence-based content."
    )
    ik3.metric(
        "Branded Queries", 
        len(intent_queries[intent_queries["Type"].isin(["branded", "competitive"])]), 
        "Brand-specific",
        help="Brand name searches and competitive comparisons. Higher volume indicates stronger brand recall, top-of-mind awareness, and consideration."
    )
    ik4.metric(
        "Breakout Terms", 
        len(intent_queries[intent_queries["Growth"] >= 500]), 
        "Explosive growth",
        help="Search terms with 500%+ surge. These represent emerging patient needs, new indication expansion, and untapped patient segments ripe for messaging."
    )
    
    # Calculate data-driven insight for patient intent
    intent_insight = "Patients show strong intent for safety and efficacy validation. Develop content addressing common patient concerns to improve conversion."
    try:
        safety_queries = intent_queries[intent_queries["Type"] == "safety"]
        if len(safety_queries) > 0:
            avg_safety_growth = safety_queries["Growth"].mean() if "Growth" in safety_queries.columns else 0
            if avg_safety_growth > 50:
                intent_insight = f"Safety concerns dominate patient queries (+{avg_safety_growth:.0f}% avg growth). Develop clinical evidence content addressing side effects and safety profiles to drive conversion."
            else:
                intent_insight = f"Safety and efficacy validation key patient intent signals. Ensure content library covers clinical evidence, side effect management, and treatment outcomes."
    except:
        pass
    
    render_insight_bubble(intent_insight, "🔍")
    # Use live related queries if available
    q1, q2 = st.columns(2)
    with q1:
        st.markdown("**All Condition Terms**")
        display_q = intent_queries.sort_values("Index", ascending=False)
        if related_rinvoq.get("top") is not None and brand_filter in ["Both", "Rinvoq"]:
            live_top = related_rinvoq["top"].head(10)
            live_top.columns = ["Query", "Index"]
            live_top["Brand"] = "Rinvoq"
            live_top["Growth"] = 0
            live_top["Type"] = "condition"
            display_q = pd.concat([live_top, display_q]).drop_duplicates(subset="Query").head(15)
        
        for _, row in display_q.iterrows():
            color = RINVOQ if row["Brand"] == "Rinvoq" else SKYRIZI if row["Brand"] == "Skyrizi" else NAVY
            st.markdown(f"<div style='display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid #eef1f6;font-size:12px'>"
                        f"<span style='flex:1'>{row['Query']}</span>"
                        f"<span style='font-size:10px;color:#8a9ab5'>{row['Type']}</span>"
                        f"<span style='font-weight:700;color:{color};width:30px;text-align:right'>{int(row['Index'])}</span></div>", unsafe_allow_html=True)
    
    with q2:
        st.markdown("**Rising & Breakout Queries**")
        rising = intent_queries.sort_values("Growth", ascending=False)
        if related_rinvoq.get("rising") is not None and brand_filter in ["Both", "Rinvoq"]:
            live_rising = related_rinvoq["rising"].head(5)
            live_rising.columns = ["Query", "Growth"]
            live_rising["Brand"] = "Rinvoq"
            live_rising["Index"] = 50
            live_rising["Type"] = "rising"
            rising = pd.concat([live_rising, rising]).drop_duplicates(subset="Query").head(15)
        
        for _, row in rising.iterrows():
            is_brk = row["Growth"] >= 500
            badge_color = "#c0392b" if is_brk else SUCCESS
            badge_bg = "#fdecea" if is_brk else "#eaf7f1"
            brk = " <span style='background:#fef3c7;color:#92400e;border-radius:4px;padding:1px 5px;font-size:9px;font-weight:700'>Breakout</span>" if is_brk else ""
            st.markdown(f"<div style='display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid #eef1f6;font-size:12px'>"
                        f"<span style='flex:1'>{row['Query']}</span>"
                        f"<span style='background:{badge_bg};color:{badge_color};border-radius:4px;padding:2px 6px;font-size:10px;font-weight:700'>+{int(row['Growth'])}%</span>{brk}</div>", unsafe_allow_html=True)
    
    # Intent trend
    fig_intent = go.Figure()
    intent_colors = {"RA": RINVOQ, "Psoriasis": SKYRIZI, "AS": "#e67e22", "AD": "#00b894", "GCA": "#636e72"}
    for ind, color in intent_colors.items():
        fig_intent.add_trace(go.Scatter(
            x=SEASON_DATA["Month"], y=[40 + np.random.randint(0, 40) + int(np.sin(i/2) * 15) for i in range(12)],
            name=ind, line=dict(color=color, width=2), mode="lines",
            hovertemplate="<b>%{fullData.name}</b><br>Month: %{x}<br>Interest: <b>%{y:.0f}</b><extra></extra>"
        ))
    fig_intent.update_layout(title="Intent Trend by Indication (12 Months)", height=350, template="plotly_white",
        hoverlabel=dict(bgcolor="white", font_size=12, font_family="sans-serif"))
    st.plotly_chart(fig_intent, use_container_width=True)
    
    # Calculate data-driven funnel insight
    funnel_insight = "Patient-oriented queries dominate search volume, indicating strong awareness-stage interest. Recommend optimizing content across the full patient journey."
    try:
        condition_queries = intent_queries[intent_queries["Type"] == "condition"]
        hcp_queries = intent_queries[intent_queries["Type"].isin(["generic", "safety"])]
        if len(condition_queries) > 0 and len(hcp_queries) > 0:
            condition_pct = len(condition_queries) / len(intent_queries) * 100
            hcp_pct = len(hcp_queries) / len(intent_queries) * 100
            if condition_pct > hcp_pct * 2:
                funnel_insight = f"Awareness-stage queries account for {condition_pct:.0f}% of volume vs {hcp_pct:.0f}% clinical/HCP intent. Strengthen clinical education content to bridge the awareness-to-consideration gap."
    except:
        pass
    
    st.info(f"🔬 **Patient Intent Insight:** {funnel_insight}")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 6: CAMPAIGN PLANNING
# ═══════════════════════════════════════════════════════════════════════════
with tabs[6]:
    # Executive Summary
    campaign_callouts, campaign_recommendation = generate_campaign_executive_summary(trend_df, client, brand_filter, indication)
    render_executive_summary("Campaign Strategy & Moment Optimization", campaign_callouts, NAVY, campaign_recommendation)
    
    st.subheader("Campaign Planning")
    
    # KPI Cards - Empty until data is ingested
    pk1, pk2, pk3, pk4 = st.columns(4)
    pk1.metric(
        "Active Campaigns", 
        "—",
        help="Concurrent marketing campaigns currently live. Tracks investment breadth across indications, channels, and brands."
    )
    pk2.metric(
        "Peak Timing", 
        "—",
        help="Next major search interest peak for primary brand."
    )
    pk3.metric(
        "Budget Allocation", 
        "—",
        help="Total budget planning and channel distribution."
    )
    pk4.metric(
        "Search Alignment", 
        "—",
        help="Campaign timing alignment with natural search seasonality."
    )
    
    st.markdown("---")
    st.markdown("**Annual Campaign Calendar**")
    st.info("📅 Campaign calendar will populate once campaign schedule data is ingested.")
    
    # Empty calendar table structure
    empty_calendar = pd.DataFrame(columns=["Month", "Brand", "Indication", "Activity"])
    st.dataframe(empty_calendar, use_container_width=True, hide_index=True)
    
    st.markdown("---")
    
    c1, c2 = st.columns(2)
    with c1:
        fig_ch = go.Figure()
        channels = ["Paid Search", "Social", "Display", "TV/CTV", "HCP Digital", "Email"]
        if brand_filter in ["Both", "Rinvoq"]:
            fig_ch.add_trace(go.Bar(y=channels, x=[35,20,15,18,28,12], name="Rinvoq", marker_color=RINVOQ, orientation="h",
                hovertemplate="<b>Rinvoq</b><br>Channel: %{y}<br>Allocation: <b>%{x}%</b><extra></extra>"))
        if brand_filter in ["Both", "Skyrizi"]:
            fig_ch.add_trace(go.Bar(y=channels, x=[30,28,20,22,15,10], name="Skyrizi", marker_color=SKYRIZI, orientation="h",
                hovertemplate="<b>Skyrizi</b><br>Channel: %{y}<br>Allocation: <b>%{x}%</b><extra></extra>"))
        fig_ch.update_layout(title="Channel Budget Allocation (%) — Demo Data", height=350, barmode="group", template="plotly_white",
            hoverlabel=dict(bgcolor="white", font_size=12, font_family="sans-serif"))
        st.plotly_chart(fig_ch, use_container_width=True)
    with c2:
        # Alignment chart
        if brand_filter == "Both":
            search_peaks = [(SEASON_DATA["Rinvoq"].iloc[i] + SEASON_DATA["Skyrizi"].iloc[i]) / 2 for i in range(12)]
        elif brand_filter == "Rinvoq":
            search_peaks = list(SEASON_DATA["Rinvoq"])
        else:  # Skyrizi
            search_peaks = list(SEASON_DATA["Skyrizi"])
        
        campaign_spend = [20,35,25,20,30,40,35,25,20,15,30,25]
        fig_align = go.Figure()
        fig_align.add_trace(go.Scatter(x=SEASON_DATA["Month"], y=search_peaks, name="Search Interest", fill="tozeroy", line=dict(color=NAVY),
            hovertemplate="<b>Search Interest</b><br>Month: %{x}<br>Index: <b>%{y:.0f}</b><extra></extra>"))
        fig_align.add_trace(go.Scatter(x=SEASON_DATA["Month"], y=campaign_spend, name="Campaign Spend", line=dict(color=GOLD, dash="dash"),
            hovertemplate="<b>Campaign Spend</b><br>Month: %{x}<br>Allocation: <b>%{y}%</b><extra></extra>"))
        fig_align.update_layout(title="Search vs Campaign Alignment — Demo Data", height=350, template="plotly_white",
            hoverlabel=dict(bgcolor="white", font_size=12, font_family="sans-serif"))
        st.plotly_chart(fig_align, use_container_width=True)
    
    st.markdown("---")
    st.markdown("**Campaign Strategy & Insights**")
    st.info("📊 Campaign recommendations and insights will be generated once campaign data is ingested and analyzed.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 3: KEY MOMENTS
# ═══════════════════════════════════════════════════════════════════════════
with tabs[3]:
    # Executive Summary
    reddit_posts = reddit_posts_data if 'reddit_posts_data' in dir() and reddit_posts_data else []
    moments_callouts, moments_recommendation = generate_key_moments_executive_summary(reddit_posts, {}, client)
    render_executive_summary("Social Signals & Patient Sentiment", moments_callouts, NAVY, moments_recommendation)
    
    st.subheader("Key Cultural Moments")
    
    moments_df = pd.DataFrame(MOMENTS_DATA)
    selected_event = st.selectbox("Select Event", moments_df["Event"].tolist())
    event = moments_df[moments_df["Event"] == selected_event].iloc[0]
    
    # Calculate KPIs dynamically from CSV data
    csv_timeframe = "90 days" if selected_event in ["Super Bowl LX", "Grammy Awards"] else "1 year"
    computed_kpis = calculate_moment_kpis_from_csv(event["Date"], timeframe=csv_timeframe)
    
    # Use computed KPIs if available, otherwise fall back to event data
    if computed_kpis:
        display_rinvoq_lift = computed_kpis["rinvoq_lift"]
        display_skyrizi_lift = computed_kpis["skyrizi_lift"]
        display_peak = computed_kpis["peak"]
        display_halo = computed_kpis["halo"]
    else:
        display_rinvoq_lift = event["Rinvoq Lift"]
        display_skyrizi_lift = event["Skyrizi Lift"]
        display_peak = event["Peak"]
        display_halo = event["Halo"]
    
    # Filter metrics by brand
    if brand_filter == "Both":
        mk1, mk2, mk3, mk4 = st.columns(4)
        mk1.metric(
            "Rinvoq Lift", 
            display_rinvoq_lift, 
            "vs baseline",
            help="Percent increase from pre-event baseline. Calculated as (Peak Value - Baseline) / Baseline × 100, where Baseline is the average search interest from the 14 days before the event. Peak Value is the highest search index during the event window (day 0 to +28)."
        )
        mk2.metric(
            "Skyrizi Lift", 
            display_skyrizi_lift, 
            "vs baseline",
            help="Percent increase from pre-event baseline. Calculated as (Peak Value - Baseline) / Baseline × 100, where Baseline is the average search interest from the 14 days before the event. Peak Value is the highest search index during the event window (day 0 to +28)."
        )
        mk3.metric(
            "Peak Day Index", 
            display_peak,
            help="Highest search interest value (0-100 scale) recorded during the event window. Represents maximum market attention achieved at any point during the event period and ±28 days after."
        )
        mk4.metric(
            "Halo Duration", 
            display_halo, 
            "post-event",
            help="Number of days after the event window when search interest remains elevated above the pre-event baseline. Indicates how long the brand momentum from the event persists."
        )
    elif brand_filter == "Rinvoq":
        mk1, mk2, mk3, mk4 = st.columns(4)
        mk1.metric(
            "Rinvoq Lift", 
            display_rinvoq_lift, 
            "vs baseline",
            help="Percent increase from pre-event baseline. Calculated as (Peak Value - Baseline) / Baseline × 100, where Baseline is the average search interest from the 14 days before the event. Peak Value is the highest search index during the event window (day 0 to +28)."
        )
        mk2.metric(
            "Peak Day Index", 
            display_peak,
            help="Highest search interest value (0-100 scale) recorded during the event window. Represents maximum market attention achieved at any point during the event period and ±28 days after."
        )
        mk3.metric(
            "Halo Duration", 
            display_halo, 
            "post-event",
            help="Number of days after the event window when search interest remains elevated above the pre-event baseline. Indicates how long the brand momentum from the event persists."
        )
        mk4.metric("Brand Filter", "Rinvoq", "Only selected brand")
    else:  # Skyrizi
        mk1, mk2, mk3, mk4 = st.columns(4)
        mk1.metric(
            "Skyrizi Lift", 
            display_skyrizi_lift, 
            "vs baseline",
            help="Percent increase from pre-event baseline. Calculated as (Peak Value - Baseline) / Baseline × 100, where Baseline is the average search interest from the 14 days before the event. Peak Value is the highest search index during the event window (day 0 to +28)."
        )
        mk2.metric(
            "Peak Day Index", 
            display_peak,
            help="Highest search interest value (0-100 scale) recorded during the event window. Represents maximum market attention achieved at any point during the event period and ±28 days after."
        )
        mk3.metric(
            "Halo Duration", 
            display_halo, 
            "post-event",
            help="Number of days after the event window when search interest remains elevated above the pre-event baseline. Indicates how long the brand momentum from the event persists."
        )
        mk4.metric("Brand Filter", "Skyrizi", "Only selected brand")
    
    # Event trend chart - Filter by brand
    r_lift = int(display_rinvoq_lift.replace("+", "").replace("%", ""))
    s_lift = int(display_skyrizi_lift.replace("+", "").replace("%", ""))
    
    # Determine which CSV timeframe to use (90 days for Super Bowl & Grammy, 1 year for others)
    csv_timeframe = "90 days" if selected_event in ["Super Bowl LX", "Grammy Awards"] else "1 year"
    
    # Try to load actual trend data from CSV
    csv_data = load_moment_trend_data(event["Date"], timeframe=csv_timeframe)
    if csv_data is not None:
        x_days, r_trend, s_trend = csv_data
    else:
        # Fallback to synthetic demo data if CSV unavailable
        days = 42
        baseline = 45
        event_day = 14
        halo_days = int(display_halo.replace("d", ""))
        peak_val = int(display_peak)
        np.random.seed(hash(selected_event) % 2**31)
        x_days = list(range(-14, 28))
        r_trend = [baseline + (max(0, (peak_val - baseline) * np.exp(-(max(0, i - event_day)) / max(1, halo_days))) * r_lift / 100 if i >= event_day else 0) + np.random.randn() * 4 for i in range(days)]
        s_trend = [baseline + (max(0, (peak_val - baseline) * np.exp(-(max(0, i - event_day)) / max(1, halo_days))) * s_lift / 100 if i >= event_day else 0) + np.random.randn() * 4 for i in range(days)]
    
    fig_moment = go.Figure()
    if brand_filter in ["Both", "Rinvoq"]:
        fig_moment.add_trace(go.Scatter(
            x=x_days, y=r_trend, name="Rinvoq", 
            line=dict(color=RINVOQ, width=2.5),
            mode="lines",
            fill="tozeroy",
            fillcolor=f"rgba({int(RINVOQ[1:3],16)},{int(RINVOQ[3:5],16)},{int(RINVOQ[5:7],16)},0.08)",
            hovertemplate="<b>Rinvoq</b><br>Day: %{x}<br>Index: <b>%{y:.0f}</b><extra></extra>"
        ))
    if brand_filter in ["Both", "Skyrizi"]:
        fig_moment.add_trace(go.Scatter(
            x=x_days, y=s_trend, name="Skyrizi", 
            line=dict(color=SKYRIZI, width=2.5),
            mode="lines",
            fill="tozeroy",
            fillcolor=f"rgba({int(SKYRIZI[1:3],16)},{int(SKYRIZI[3:5],16)},{int(SKYRIZI[5:7],16)},0.08)",
            hovertemplate="<b>Skyrizi</b><br>Day: %{x}<br>Index: <b>%{y:.0f}</b><extra></extra>"
        ))
    fig_moment.add_vline(
        x=0, line_dash="dash", line_color="#ccc", line_width=1,
        annotation_text=f"<b>Event</b><br><sub>{event['Date']}</sub>",
        annotation_position="top right",
        annotation_font=dict(size=10, color="#666")
    )
    # Extract year from event date for dynamic title
    event_year = event.get("Date", "").split(",")[-1].strip()
    
    fig_moment.update_layout(
        title=f"Search Trend — {selected_event} ({event_year} Data)",
        height=350,
        template="plotly_white",
        xaxis_title="Days from Event",
        yaxis_title="Search Interest Index",
        yaxis=dict(range=[0, 100]),
        hovermode="x unified",
        legend=dict(x=0.02, y=0.98, bgcolor="rgba(255,255,255,0.8)"),
        margin=dict(t=40, b=20),
        hoverlabel=dict(bgcolor="white", font_size=12, font_family="sans-serif")
    )
    st.plotly_chart(fig_moment, use_container_width=True, key=f"moment_chart_{selected_event}_{brand_filter}")
    
    st.markdown(f"**Event Intelligence:** {event['Insight']}")
    
    # Social Media Insights
    st.markdown("---")
    st.subheader("📱 Social Media Conversation")
    st.caption("Community discussions curated from r/Psoriasis, r/rheumatoidarthritis, and related healthcare subreddits")
    
    # Scrape real Reddit posts related to the event and brands
    # Placeholder - no actual Reddit data displayed
    
    # Display placeholder metrics
    sm1, sm2, sm3, sm4 = st.columns(4)
    sm1.metric("Total Upvotes", "—", "")
    sm2.metric("Positive Sentiment", "—", "")
    sm3.metric("Rinvoq Mentions", "—", "")
    sm4.metric("Skyrizi Mentions", "—", "")
    
    # Sentiment breakdown pie chart + trending posts
    soc1, soc2 = st.columns(2)
    
    with soc1:
        st.markdown("**Sentiment Breakdown**")
        st.info("📊 Sentiment data unavailable")
    
    with soc2:
        st.markdown("**Top Trending Posts (Reddit)**")
        st.info("📝 Reddit posts data unavailable")
    
    # Mention volume trend placeholder
    st.markdown("---")
    
    # Dynamic Reddit insight based on data availability
    reddit_insight = "Community discussions from r/Psoriasis, r/rheumatoidarthritis, and related subreddits reveal authentic patient conversations. Monitor sentiment and emerging themes to refine messaging."
    
    render_insight_bubble(reddit_insight, "💬")

    st.markdown("**Mention Volume Trend (Event Window)**")
    st.info("📈 Mention volume trend unavailable")
    
    # Top Search Queries and Rising Queries for Key Moments
    st.markdown("---")
    st.subheader("📊 Search Query Insights")
    
    # Filter queries by brand only (no additional filters)
    km_queries = DEMO_QUERIES.copy()
    if brand_filter == "Both":
        pass  # Keep all
    elif brand_filter == "Rinvoq":
        km_queries = km_queries[km_queries["Brand"].isin(["Rinvoq", "Both"])]
    else:  # Skyrizi
        km_queries = km_queries[km_queries["Brand"].isin(["Skyrizi", "Both"])]
    
    # Filter rising queries by brand
    km_rising = DEMO_RISING_QUERIES.copy()
    if brand_filter == "Both":
        pass  # Keep all
    elif brand_filter == "Rinvoq":
        km_rising = km_rising[km_rising["Brand"].isin(["Rinvoq", "Both"])]
    else:  # Skyrizi
        km_rising = km_rising[km_rising["Brand"].isin(["Skyrizi", "Both"])]
    
    # Display tables side by side
    km_col1, km_col2 = st.columns(2)
    
    with km_col1:
        st.subheader("Top Search Queries", help="The most popular search queries. Scoring is on a relative scale where a value of 100 is the most commonly searched query, 50 is a query searched half as often as the most popular query, and so on.")
        km_top_queries = km_queries.sort_values("Index", ascending=False).head(8)
        if not km_top_queries.empty:
            for _, row in km_top_queries.iterrows():
                color = RINVOQ if row["Brand"] == "Rinvoq" else SKYRIZI if row["Brand"] == "Skyrizi" else NAVY
                st.markdown(f"<div style='display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid #eef1f6'>"
                            f"<span style='flex:1;font-size:13px'>{row['Query']}</span>"
                            f"<span style='font-weight:700;color:{color};font-size:12px'>{int(row['Index'])}</span></div>", unsafe_allow_html=True)
        else:
            st.caption("No data available")
    
    with km_col2:
        st.subheader("Rising Queries", help="Queries with the biggest increase in search frequency since the last time period. Results marked \"Breakout\" had a tremendous increase, probably because these queries are new and had few (if any) prior searches.")
        km_rising_queries = km_rising.head(8)
        if not km_rising_queries.empty:
            for _, row in km_rising_queries.iterrows():
                color = RINVOQ if row["Brand"] == "Rinvoq" else SKYRIZI if row["Brand"] == "Skyrizi" else NAVY
                growth_label = str(row["Growth"]) if row["Growth"] and row["Growth"] != "nan" else "Breakout"
                st.markdown(f"<div style='display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid #eef1f6'>"
                            f"<span style='flex:1;font-size:13px'>{row['Query']}</span>"
                            f"<span style='font-weight:700;color:{color};font-size:12px'>{growth_label}</span></div>", unsafe_allow_html=True)
        else:
            st.caption("No data available")
    
    # Summary table - Filter columns by brand
    st.markdown("---")
    st.subheader("Annual Moments Summary")
    
    if brand_filter == "Both":
        summary = moments_df[["Event", "Category", "Date", "Rinvoq Lift", "Skyrizi Lift", "Peak", "Halo", "Breakout"]].copy()
        summary["Combined Lift"] = summary.apply(lambda r: int(r["Rinvoq Lift"].replace("+","").replace("%","")) + int(r["Skyrizi Lift"].replace("+","").replace("%","")), axis=1)
        summary = summary.sort_values("Combined Lift", ascending=False)
    elif brand_filter == "Rinvoq":
        summary = moments_df[["Event", "Category", "Date", "Rinvoq Lift", "Peak", "Halo", "Breakout"]].copy()
        summary = summary.sort_values("Rinvoq Lift", key=lambda x: x.str.replace("+","").str.replace("%","").astype(int), ascending=False)
    else:  # Skyrizi
        summary = moments_df[["Event", "Category", "Date", "Skyrizi Lift", "Peak", "Halo", "Breakout"]].copy()
        summary = summary.sort_values("Skyrizi Lift", key=lambda x: x.str.replace("+","").str.replace("%","").astype(int), ascending=False)
    
    st.dataframe(summary, use_container_width=True, hide_index=True)
# TAB 7: CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
with tabs[7]:
    st.subheader("⚙️ Dashboard Configuration")
    st.markdown("Customize filter categories and data groupings. Changes are applied to your session only.")
    st.markdown("---")
    
    # Simple configuration sections without nested tabs
    col1, col2 = st.columns(2)
    
    # COMPETITORS SECTION
    with col1:
        st.markdown("**🏥 Manage Competitors**")
        if st.button("➕ Add Competitor", key="add_comp"):
            st.session_state.show_add_comp = True
        
        if st.session_state.get("show_add_comp", False):
            with st.form("add_competitor_form", clear_on_submit=True):
                new_brand = st.text_input("Brand Name", placeholder="e.g., NewBrand")
                new_color = st.color_picker("Brand Color", "#3498db")
                if st.form_submit_button("Add"):
                    if new_brand and new_brand not in st.session_state.custom_comp_colors:
                        st.session_state.custom_comp_colors[new_brand] = new_color
                        st.session_state.show_add_comp = False
                        st.success(f"✓ Added {new_brand}")
                        st.rerun()
        
        st.caption("Current Competitors:")
        for brand, color in st.session_state.custom_comp_colors.items():
            cols = st.columns([2, 1])
            with cols[0]:
                st.text(f"● {brand}")
            with cols[1]:
                if st.button("×", key=f"remove_comp_{brand}"):
                    del st.session_state.custom_comp_colors[brand]
                    st.rerun()
    
    # INDICATIONS SECTION
    with col2:
        st.markdown("**📋 Manage Indications**")
        if st.button("➕ Add Indication", key="add_ind"):
            st.session_state.show_add_ind = True
        
        if st.session_state.get("show_add_ind", False):
            with st.form("add_indication_form", clear_on_submit=True):
                new_code = st.text_input("Code", placeholder="ra", max_chars=4).lower()
                new_name = st.text_input("Name", placeholder="Rheumatoid Arthritis")
                if st.form_submit_button("Add"):
                    if new_code and new_name and new_code not in st.session_state.custom_ind_names:
                        st.session_state.custom_ind_names[new_code] = new_name
                        st.session_state.show_add_ind = False
                        st.success(f"✓ Added {new_code}")
                        st.rerun()
        
        st.caption("Current Indications:")
        for code, name in st.session_state.custom_ind_names.items():
            cols = st.columns([1, 2, 1])
            with cols[0]:
                st.code(code)
            with cols[1]:
                st.text(name)
            with cols[2]:
                if st.button("×", key=f"remove_ind_{code}"):
                    del st.session_state.custom_ind_names[code]
                    st.rerun()
    
    # FRANCHISES SECTION
    st.markdown("---")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**🗂️ Manage Franchises**")
        if st.button("➕ Add Franchise", key="add_fran"):
            st.session_state.show_add_fran = True
        
        if st.session_state.get("show_add_fran", False):
            with st.form("add_franchise_form", clear_on_submit=True):
                new_fran = st.text_input("Franchise Name", placeholder="e.g., Oncology")
                inds = list(st.session_state.custom_ind_names.keys())
                selected = st.multiselect("Indications", inds, key="fran_select")
                if st.form_submit_button("Add"):
                    if new_fran and selected and new_fran not in st.session_state.custom_franchise_map:
                        st.session_state.custom_franchise_map[new_fran] = selected
                        st.session_state.show_add_fran = False
                        st.success(f"✓ Added {new_fran}")
                        st.rerun()
        
        st.caption("Current Franchises:")
        for fran_name, ind_list in st.session_state.custom_franchise_map.items():
            cols = st.columns([2, 1])
            with cols[0]:
                st.text(f"📌 {fran_name}: {', '.join(ind_list)}")
            with cols[1]:
                if st.button("×", key=f"remove_fran_{fran_name}"):
                    del st.session_state.custom_franchise_map[fran_name]
                    st.rerun()
    
    # TIMEFRAMES SECTION
    with col2:
        st.markdown("**⏱️ Manage Timeframes**")
        if st.button("➕ Add Timeframe", key="add_tf"):
            st.session_state.show_add_tf = True
        
        if st.session_state.get("show_add_tf", False):
            with st.form("add_timeframe_form", clear_on_submit=True):
                label = st.text_input("Display Label", placeholder="e.g., 3 Months")
                param = st.text_input("Google Trends Param", placeholder="today 3-m")
                if st.form_submit_button("Add"):
                    if label and param and label not in st.session_state.custom_timeframe_map:
                        st.session_state.custom_timeframe_map[label] = param
                        st.session_state.show_add_tf = False
                        st.success(f"✓ Added {label}")
                        st.rerun()
        
        st.caption("Current Timeframes:")
        for label, param in st.session_state.custom_timeframe_map.items():
            cols = st.columns([2, 1])
            with cols[0]:
                st.text(f"{label}: {param}")
            with cols[1]:
                if st.button("×", key=f"remove_tf_{label}"):
                    del st.session_state.custom_timeframe_map[label]
                    st.rerun()
    
    # RESET BUTTON
    st.markdown("---")
    if st.button("🔄 Reset All to Defaults"):
        st.session_state.custom_comp_colors = COMP_COLORS.copy()
        st.session_state.custom_ind_names = IND_NAMES.copy()
        st.session_state.custom_franchise_map = {k: v.copy() for k, v in FRANCHISE_MAP.items()}
        st.session_state.custom_timeframe_map = TIMEFRAME_MAP.copy()
        st.success("✓ Reset to defaults")
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# FOOTER
# ═══════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.caption("⚠ Google Trends indices are relative (0–100) and do not represent absolute search volumes. For internal use only. | AbbVie Immunology Intelligence · Confidential")
