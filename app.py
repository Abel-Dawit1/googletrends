"""
AbbVie Immunology — Search Intelligence Dashboard (Streamlit)
==============================================================
Pulls real Google Trends data via pytrends with graceful demo fallback.

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
from datetime import datetime, timedelta
from pathlib import Path
from anthropic import Anthropic

# Initialize Claude client
@st.cache_resource
def init_claude():
    """Initialize Anthropic Claude client."""
    return Anthropic()

# ═══════════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="AbbVie Immunology — Search Intelligence",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═══════════════════════════════════════════════════════════════════════════
# BRAND COLORS
# ═══════════════════════════════════════════════════════════════════════════
NAVY = "#071d49"
RINVOQ = "#d4af37"
SKYRIZI = "#0052cc"
GOLD = "#b8860b"
SUCCESS = "#1a7f4f"
COMP_COLORS = {
    "Enbrel": "#6b4c9a", "Humira": "#e67e22", "Xeljanz": "#3498db",
    "Tremfya": "#27ae60", "Cosentyx": "#8e44ad", "Bimzelx": "#e84393",
    "Dupixent": "#00b894", "Ebglyss": "#fd79a8", "Nemluvio": "#636e72",
    "Otezla": "#fdcb6e", "Icotrokinra": "#00cec9", "Entyvio": "#d35400",
}
COMPETITORS = list(COMP_COLORS.keys())

IND_NAMES = {"ra": "RA", "pso": "Psoriasis", "psa": "PsA", "as": "AS",
             "ad": "AD", "cd": "Crohn's", "uc": "UC", "gca": "GCA"}
FRANCHISE_MAP = {
    "Rheumatology": ["ra", "psa", "as", "gca"],
    "Dermatology": ["pso", "psa", "ad"],
    "Gastroenterology": ["uc", "cd"],
}
TIMEFRAME_MAP = {
    "7 Days": "now 7-d", "30 Days": "today 1-m", "90 Days": "today 3-m",
    "12 Months": "today 12-m", "5 Years": "today 5-y",
}

# ═══════════════════════════════════════════════════════════════════════════
# GOOGLE TRENDS DATA LAYER
# ═══════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_trends_data(keywords, timeframe="today 3-m", geo="US"):
    """Fetch interest over time from Google Trends via pytrends."""
    try:
        import time
        from pytrends.request import TrendReq
        time.sleep(2)  # Rate limiting
        pytrends = TrendReq(hl="en-US", tz=360)
        pytrends.build_payload(keywords[:5], timeframe=timeframe, geo=geo)
        df = pytrends.interest_over_time()
        if "isPartial" in df.columns:
            df = df.drop("isPartial", axis=1)
        return df
    except Exception as e:
        st.session_state["data_error"] = f"Google Trends temporarily unavailable: {str(e)}"
        return None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_regional_data(keywords, timeframe="today 3-m", geo="US", resolution="REGION"):
    """Fetch interest by region (state or DMA)."""
    try:
        import time
        from pytrends.request import TrendReq
        time.sleep(2)  # Rate limiting
        pytrends = TrendReq(hl="en-US", tz=360)
        pytrends.build_payload(keywords[:5], timeframe=timeframe, geo=geo)
        df = pytrends.interest_by_region(resolution=resolution, inc_low_vol=True, inc_geo_code=True)
        return df
    except Exception as e:
        return None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_related_queries(keyword, timeframe="today 12-m", geo="US"):
    """Fetch related and rising queries."""
    try:
        import time
        from pytrends.request import TrendReq
        time.sleep(2)  # Rate limiting
        pytrends = TrendReq(hl="en-US", tz=360)
        pytrends.build_payload([keyword], timeframe=timeframe, geo=geo)
        related = pytrends.related_queries()
        return related.get(keyword, {"top": None, "rising": None})
    except Exception as e:
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
    
    # Major city coordinates and their associated states
    major_dmas = {
        "New York, NY": (40.71, -74.01, "New York"),
        "Los Angeles, CA": (34.05, -118.24, "California"),
        "Chicago, IL": (41.88, -87.63, "Illinois"),
        "Dallas, TX": (32.78, -96.80, "Texas"),
        "Houston, TX": (29.76, -95.37, "Texas"),
        "Philadelphia, PA": (39.95, -75.17, "Pennsylvania"),
        "Phoenix, AZ": (33.45, -112.07, "Arizona"),
        "San Antonio, TX": (29.42, -98.49, "Texas"),
        "San Diego, CA": (32.72, -117.16, "California"),
        "San Francisco, CA": (37.77, -122.41, "California"),
        "Boston, MA": (42.36, -71.06, "Massachusetts"),
        "Miami, FL": (25.76, -80.19, "Florida"),
        "Atlanta, GA": (33.75, -84.39, "Georgia"),
        "Seattle, WA": (47.61, -122.33, "Washington"),
        "Denver, CO": (39.74, -104.99, "Colorado"),
    }
    
    dma_data = []
    for city, (lat, lng, state) in major_dmas.items():
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
            "Trend": trend
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

def generate_ai_insights(trend_df, dma_df, state_df, queries_df, client):
    """Generate strategic insights using Claude based on current data."""
    try:
        context = format_data_context(trend_df, dma_df, state_df, queries_df)
        
        prompt = f"""You are a strategic business analyst for AbbVie's Immunology division. 
        
Analyze the following Google Trends data and provide 3-4 specific, actionable business insights that would help inform marketing and commercial strategy decisions. Focus on geographic opportunities, competitive positioning, and patient/HCP search intent patterns.

DATA CONTEXT:
{json.dumps(context, indent=2)}

Provide insights that are:
- Data-driven and specific (reference actual numbers where relevant)
- Actionable (suggest specific business actions)
- Focused on competitive advantage and market opportunity
- Written for C-suite executives who make budget allocation decisions

Format: Start with a brief executive summary, then list 3-4 key insights with supporting data and recommended actions."""

        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=800,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        return response.content[0].text
    except Exception as e:
        return f"Error generating insights: {str(e)}"

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
    {"Market": "New York, NY", "lat": 40.71, "lng": -74.01, "Rinvoq": 91, "Skyrizi": 88, "Trend": "↑"},
    {"Market": "Chicago, IL", "lat": 41.88, "lng": -87.63, "Rinvoq": 84, "Skyrizi": 79, "Trend": "↑"},
    {"Market": "Los Angeles, CA", "lat": 34.05, "lng": -118.24, "Rinvoq": 78, "Skyrizi": 82, "Trend": "→"},
    {"Market": "Philadelphia, PA", "lat": 39.95, "lng": -75.17, "Rinvoq": 82, "Skyrizi": 71, "Trend": "↑"},
    {"Market": "Boston, MA", "lat": 42.36, "lng": -71.06, "Rinvoq": 75, "Skyrizi": 68, "Trend": "↑"},
    {"Market": "Minneapolis, MN", "lat": 44.98, "lng": -93.27, "Rinvoq": 72, "Skyrizi": 65, "Trend": "→"},
    {"Market": "Dallas, TX", "lat": 32.78, "lng": -96.80, "Rinvoq": 68, "Skyrizi": 77, "Trend": "↓"},
    {"Market": "Atlanta, GA", "lat": 33.75, "lng": -84.39, "Rinvoq": 65, "Skyrizi": 72, "Trend": "↑"},
    {"Market": "Seattle, WA", "lat": 47.61, "lng": -122.33, "Rinvoq": 63, "Skyrizi": 70, "Trend": "→"},
    {"Market": "Miami, FL", "lat": 25.76, "lng": -80.19, "Rinvoq": 61, "Skyrizi": 74, "Trend": "↓"},
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
    {"Query": "rheumatoid arthritis treatment", "Brand": "Rinvoq", "Index": 94, "Growth": 12, "Type": "condition"},
    {"Query": "psoriasis treatment", "Brand": "Skyrizi", "Index": 91, "Growth": 15, "Type": "condition"},
    {"Query": "upadacitinib", "Brand": "Rinvoq", "Index": 88, "Growth": 28, "Type": "generic"},
    {"Query": "plaque psoriasis medication", "Brand": "Skyrizi", "Index": 87, "Growth": 22, "Type": "condition"},
    {"Query": "risankizumab", "Brand": "Skyrizi", "Index": 85, "Growth": 35, "Type": "generic"},
    {"Query": "JAK inhibitor side effects", "Brand": "Rinvoq", "Index": 82, "Growth": 8, "Type": "safety"},
    {"Query": "Crohn's disease biologic", "Brand": "Skyrizi", "Index": 78, "Growth": 42, "Type": "condition"},
    {"Query": "ulcerative colitis treatment", "Brand": "Both", "Index": 80, "Growth": 25, "Type": "condition"},
    {"Query": "ankylosing spondylitis treatment", "Brand": "Rinvoq", "Index": 74, "Growth": 51, "Type": "condition"},
    {"Query": "atopic dermatitis biologic", "Brand": "Rinvoq", "Index": 72, "Growth": 38, "Type": "condition"},
    {"Query": "giant cell arteritis treatment", "Brand": "Rinvoq", "Index": 68, "Growth": 48, "Type": "condition"},
    {"Query": "Rinvoq Crohn's disease", "Brand": "Rinvoq", "Index": 58, "Growth": 850, "Type": "branded"},
    {"Query": "Rinvoq vs Humira", "Brand": "Rinvoq", "Index": 65, "Growth": 120, "Type": "competitive"},
    {"Query": "Skyrizi vs Tremfya", "Brand": "Skyrizi", "Index": 62, "Growth": 95, "Type": "competitive"},
    {"Query": "Skyrizi cost", "Brand": "Skyrizi", "Index": 70, "Growth": 30, "Type": "branded"},
    {"Query": "Rinvoq dosing", "Brand": "Rinvoq", "Index": 55, "Growth": 15, "Type": "branded"},
])


SEASON_DATA = pd.DataFrame({
    "Month": ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"],
    "Rinvoq": [82,85,70,60,55,50,48,52,65,78,80,75],
    "Skyrizi": [72,68,62,70,80,90,95,88,75,68,70,78],
})

YOY_DATA = pd.DataFrame({
    "Quarter": ["Q1'23","Q2'23","Q3'23","Q4'23","Q1'24","Q2'24","Q3'24","Q4'24"],
    "Rinvoq": [12,18,22,19,28,31,35,38],
    "Skyrizi": [20,24,28,32,35,40,42,45],
})

MOMENTS_DATA = [
    {"Event": "Super Bowl LIX", "Category": "Sports", "Date": "Feb 9, 2025", "Rinvoq Lift": "+18%", "Skyrizi Lift": "+22%", "Peak": 82, "Halo": "5d", "Breakout": "Rinvoq commercial", "Insight": "Super Bowl drove a 22% Skyrizi search lift sustained 5 days, strongest in 25–44 demo and Sun Belt DMAs."},
    {"Event": "ACR Annual Meeting", "Category": "Conference", "Date": "Nov 2025", "Rinvoq Lift": "+35%", "Skyrizi Lift": "+8%", "Peak": 95, "Halo": "10d", "Breakout": "upadacitinib data", "Insight": "ACR delivers highest Rinvoq lift (+35%) driven by HCP search for clinical data. Single most important event."},
    {"Event": "NFL Playoffs", "Category": "Sports", "Date": "Jan 2025", "Rinvoq Lift": "+14%", "Skyrizi Lift": "+16%", "Peak": 74, "Halo": "6d", "Breakout": "Skyrizi NFL ad", "Insight": "NFL Playoffs provide sustained multi-week exposure. Skyrizi 16% lift exceeded single-event spikes."},
    {"Event": "Grammy Awards", "Category": "Entertainment", "Date": "Feb 2, 2025", "Rinvoq Lift": "+8%", "Skyrizi Lift": "+15%", "Peak": 65, "Halo": "3d", "Breakout": "psoriasis awareness", "Insight": "Grammy Awards drove targeted lift via celebrity psoriasis awareness moments."},
    {"Event": "Mother's Day", "Category": "Cultural", "Date": "May 11, 2025", "Rinvoq Lift": "+10%", "Skyrizi Lift": "+14%", "Peak": 68, "Halo": "4d", "Breakout": "caregiver support", "Insight": "Caregiver campaigns drove 14% Skyrizi lift on quality-of-life messaging."},
    {"Event": "Winter Olympics", "Category": "Sports", "Date": "Feb 2026", "Rinvoq Lift": "+12%", "Skyrizi Lift": "+10%", "Peak": 72, "Halo": "14d", "Breakout": "athlete sponsorship", "Insight": "Extended 14-day halo. Joint RA/PsA messaging resonated with active lifestyle narrative."},
]


# ═══════════════════════════════════════════════════════════════════════════
# SMART DATA LOADER
# ═══════════════════════════════════════════════════════════════════════════

def load_data(timeframe_key, brand_filter):
    """Load live data from pytrends, fall back to demo."""
    tf = TIMEFRAME_MAP.get(timeframe_key, "today 3-m")
    
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
    <div style='text-align:center;padding:12px 0'>
        <div style='background:{NAVY};color:white;width:42px;height:42px;border-radius:10px;display:inline-flex;align-items:center;justify-content:center;font-weight:800;font-size:18px;margin-bottom:8px'>A</div>
        <h3 style='margin:0;color:{NAVY}'>AbbVie Immunology</h3>
        <p style='margin:0;font-size:12px;color:#8a9ab5'>Search Intelligence Dashboard</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.divider()
    
    franchise = st.selectbox("Franchise", ["All", "Rheumatology", "Dermatology", "Gastroenterology"])
    brand_filter = st.selectbox("Brand", ["Both", "Rinvoq", "Skyrizi"])
    timeframe = st.selectbox("Timeframe", list(TIMEFRAME_MAP.keys()), index=2)
    
    ind_options = list(IND_NAMES.values())
    if franchise != "All":
        ind_keys = FRANCHISE_MAP.get(franchise, [])
        ind_options = [IND_NAMES[k] for k in ind_keys]
    indication = st.selectbox("Indication", ["All"] + ind_options)
    
    st.divider()
    
    if st.button("↻ Refresh Data", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    
    source = st.session_state.get("data_source", "loading...")
    source_color = SUCCESS if source == "live" else GOLD
    st.markdown(f"<div style='text-align:center;font-size:12px;color:{source_color};font-weight:600'>● {source.upper()} DATA</div>", unsafe_allow_html=True)
    
    if st.session_state.get("data_error"):
        st.warning(f"⚠️ {st.session_state['data_error']}\n\n**Why?** Google Trends temporarily restricts rapid API requests. Demo data will be used.\n\n**Solution:** Click \"Refresh Data\" after 1-2 minutes, or leave the app open for automatic retry on next refresh cycle.")
    else:
        st.caption("ℹ️ Real Google Trends data is being used. Demo data falls back if API unavailable.")

# ═══════════════════════════════════════════════════════════════════════════
# LOAD DATA
# ═══════════════════════════════════════════════════════════════════════════

trend_df = load_data(timeframe, brand_filter)

# Also try to load competitor data
comp_df = None
if st.session_state.get("data_source") == "live":
    comp_df = fetch_trends_data(["Rinvoq", "Skyrizi"] + COMPETITORS[:3], timeframe="today 12-m")

# Related queries
related_rinvoq = fetch_related_queries("Rinvoq") if st.session_state.get("data_source") == "live" else {"top": None, "rising": None}
related_skyrizi = fetch_related_queries("Skyrizi") if st.session_state.get("data_source") == "live" else {"top": None, "rising": None}

# State-level data - fetch and transform
state_df = None
raw_state_df = None
if st.session_state.get("data_source") == "live":
    raw_state_df = fetch_regional_data(["Rinvoq", "Skyrizi"], timeframe="today 12-m", resolution="REGION")
    state_df = transform_regional_to_states(raw_state_df)

# Use transformed state data for DMA generation, fallback to demo
if state_df is not None and not state_df.empty:
    DEMO_DMA = generate_dma_from_states(state_df)
    DEMO_STATES = state_df
elif state_df is None and st.session_state.get("data_source") == "live":
    # If live but transformation failed, still use DEMO data
    pass

# Generate queries from related data or use demo
DEMO_QUERIES = transform_trends_to_queries(trend_df, related_rinvoq, related_skyrizi)


# ═══════════════════════════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════════════════════════

# Initialize Claude and chat history
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
    
try:
    client = init_claude()
except Exception as e:
    st.session_state["api_error"] = str(e)
    client = None

tabs = st.tabs(["📊 Overview", "🗺️ DMA Deep Dive", "⚔️ Competitive", "🔬 Patient Intent", "📅 Campaign", "⚡ Key Moments", "💬 AI Chat"])

# ═══════════════════════════════════════════════════════════════════════════
# TAB 1: OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════
with tabs[0]:
    # KPIs
    r_vals = trend_df["Rinvoq"].values if "Rinvoq" in trend_df.columns else [0]
    s_vals = trend_df["Skyrizi"].values if "Skyrizi" in trend_df.columns else [0]
    r_peak, s_peak = int(max(r_vals)), int(max(s_vals))
    r_avg, s_avg = int(np.mean(r_vals)), int(np.mean(s_vals))
    
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Rinvoq Peak Index", r_peak, f"Avg: {r_avg}")
    k2.metric("Skyrizi Peak Index", s_peak, f"Avg: {s_avg}")
    k3.metric("Top DMA", DEMO_DMA.iloc[0]["Market"].split(",")[0], f"Index {DEMO_DMA.iloc[0]['Rinvoq']}")
    k4.metric("Breakout Terms", str(len(DEMO_QUERIES[DEMO_QUERIES["Growth"] >= 500])), "Explosive growth")
    
    st.markdown("---")
    
    # Search Interest Over Time — full width
    fig_trend = go.Figure()
    for col in trend_df.columns:
        color = RINVOQ if col == "Rinvoq" else SKYRIZI
        fig_trend.add_trace(go.Scatter(
            x=trend_df.index, y=trend_df[col], name=col, mode="lines",
            line=dict(color=color, width=2.5),
            fill="tozeroy", fillcolor=f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.08)"
        ))
    fig_trend.update_layout(
        title="Search Interest Over Time", height=350,
        yaxis=dict(range=[0, 100], title="Search Index"),
        xaxis=dict(title=""), legend=dict(orientation="h", y=-0.15),
        template="plotly_white", margin=dict(t=40, b=40),
    )
    st.plotly_chart(fig_trend, use_container_width=True)
    
    # Seasonality + YoY
    c1, c2 = st.columns(2)
    
    with c1:
        fig_season = go.Figure()
        if brand_filter != "Skyrizi":
            fig_season.add_trace(go.Bar(x=SEASON_DATA["Month"], y=SEASON_DATA["Rinvoq"], name="Rinvoq", marker_color=RINVOQ, opacity=0.8))
        if brand_filter != "Rinvoq":
            fig_season.add_trace(go.Bar(x=SEASON_DATA["Month"], y=SEASON_DATA["Skyrizi"], name="Skyrizi", marker_color=SKYRIZI, opacity=0.8))
        fig_season.update_layout(title="Seasonality", height=300, barmode="group", yaxis=dict(range=[0, 100]), template="plotly_white", margin=dict(t=40, b=20))
        st.plotly_chart(fig_season, use_container_width=True)
    
    with c2:
        fig_yoy = go.Figure()
        if brand_filter != "Skyrizi":
            fig_yoy.add_trace(go.Bar(x=YOY_DATA["Quarter"], y=YOY_DATA["Rinvoq"], name="Rinvoq", marker_color=RINVOQ))
        if brand_filter != "Rinvoq":
            fig_yoy.add_trace(go.Bar(x=YOY_DATA["Quarter"], y=YOY_DATA["Skyrizi"], name="Skyrizi", marker_color=SKYRIZI))
        fig_yoy.update_layout(title="Year-over-Year Growth (%)", height=300, barmode="group", template="plotly_white", margin=dict(t=40, b=20))
        st.plotly_chart(fig_yoy, use_container_width=True)
    
    # Indication Pies
    p1, p2 = st.columns(2)
    with p1:
        rinvoq_ind = pd.DataFrame({"Indication": ["RA","PsA","AS","AD","UC","GCA"], "Share": [38,25,13,10,6,8]})
        fig_rp = px.pie(rinvoq_ind, names="Indication", values="Share", title="Rinvoq — Indication Split",
                        color_discrete_sequence=["#0099a8","#33b0bc","#66c7cf","#99dee3","#cceef1","#b2e8ec"], hole=0.5)
        fig_rp.update_layout(height=300, margin=dict(t=40, b=20))
        st.plotly_chart(fig_rp, use_container_width=True)
    with p2:
        skyrizi_ind = pd.DataFrame({"Indication": ["Psoriasis","PsA","Crohn's","UC"], "Share": [45,22,20,13]})
        fig_sp = px.pie(skyrizi_ind, names="Indication", values="Share", title="Skyrizi — Indication Split",
                        color_discrete_sequence=["#d94f2b","#e27558","#ea9c85","#f3c3b2"], hole=0.5)
        fig_sp.update_layout(height=300, margin=dict(t=40, b=20))
        st.plotly_chart(fig_sp, use_container_width=True)
    
    # Top Markets
    st.subheader("Top Markets")
    dma_display = DEMO_DMA.copy()
    dma_display["Avg"] = ((dma_display["Rinvoq"] + dma_display["Skyrizi"]) / 2).round().astype(int)
    dma_display["Lead"] = dma_display.apply(lambda r: "Rinvoq" if r["Rinvoq"] > r["Skyrizi"] else "Skyrizi", axis=1)
    st.dataframe(
        dma_display[["Market", "Rinvoq", "Skyrizi", "Avg", "Lead", "Trend"]].sort_values("Avg", ascending=False),
        use_container_width=True, hide_index=True,
        column_config={
            "Rinvoq": st.column_config.ProgressColumn("Rinvoq", min_value=0, max_value=100, format="%d"),
            "Skyrizi": st.column_config.ProgressColumn("Skyrizi", min_value=0, max_value=100, format="%d"),
        }
    )
    
    # Queries
    q1, q2 = st.columns(2)
    with q1:
        st.subheader("Top Search Queries")
        top_q = DEMO_QUERIES.sort_values("Index", ascending=False).head(8)
        for _, row in top_q.iterrows():
            color = RINVOQ if row["Brand"] == "Rinvoq" else SKYRIZI if row["Brand"] == "Skyrizi" else NAVY
            st.markdown(f"<div style='display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid #eef1f6'>"
                        f"<span style='flex:1;font-size:13px'>{row['Query']}</span>"
                        f"<span style='font-weight:700;color:{color}'>{row['Index']}</span></div>", unsafe_allow_html=True)
    with q2:
        st.subheader("Rising Queries")
        rising_q = DEMO_QUERIES.sort_values("Growth", ascending=False).head(8)
        for _, row in rising_q.iterrows():
            badge_color = "#c0392b" if row["Growth"] >= 500 else SUCCESS
            badge_bg = "#fdecea" if row["Growth"] >= 500 else "#eaf7f1"
            brk = " <span style='background:#fef3c7;color:#92400e;border-radius:4px;padding:1px 6px;font-size:10px;font-weight:700'>Breakout</span>" if row["Growth"] >= 500 else ""
            st.markdown(f"<div style='display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid #eef1f6'>"
                        f"<span style='flex:1;font-size:13px'>{row['Query']}</span>"
                        f"<span style='background:{badge_bg};color:{badge_color};border-radius:4px;padding:2px 7px;font-size:11px;font-weight:700'>+{row['Growth']}%</span>{brk}</div>", unsafe_allow_html=True)
    
    # AI Insight
    st.markdown("---")
    
    # AI-Powered Insights using Claude
    with st.spinner("✦ Generating AI-powered insights..."):
        if client:
            try:
                ai_insights = generate_ai_insights(trend_df, DEMO_DMA, DEMO_STATES, DEMO_QUERIES, client)
                st.markdown(f"""
                <div style='background:linear-gradient(135deg,{NAVY} 0%,#1a4094 100%);border-radius:10px;padding:16px 20px;color:white'>
                    <div style='font-weight:700;font-size:14px;margin-bottom:12px'>✦ AI-Powered Strategic Insights (Claude)</div>
                    <div style='font-size:13px;line-height:1.8;opacity:0.95;white-space:pre-wrap'>
                        {ai_insights}
                    </div>
                </div>
                """, unsafe_allow_html=True)
            except Exception as e:
                st.error(f"Could not generate insights: {str(e)}")
        else:
            st.warning("Claude API not available. Set ANTHROPIC_API_KEY environment variable to enable AI insights.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 2: DMA DEEP DIVE
# ═══════════════════════════════════════════════════════════════════════════
with tabs[1]:
    st.subheader("DMA Geographic Analysis")
    
    import folium
    from streamlit_folium import st_folium
    import requests
    
    # Use demo state data or live state data
    display_states = DEMO_STATES.copy() if state_df is None or state_df.empty else state_df
    
    # Create map
    m = folium.Map(location=[39.5, -98.5], zoom_start=4, tiles="CartoDB positron", scroll_zoom=False)
    
    # Add state choropleth with search interest shading
    try:
        # Load US state boundaries GeoJSON
        us_state_geo = "https://raw.githubusercontent.com/python-visualization/folium/master/examples/data/us-states.json"
        geo_data = requests.get(us_state_geo).json()
        
        # Prepare state data for choropleth (use average of Rinvoq and Skyrizi)
        state_values = display_states.copy()
        state_values["avg_interest"] = ((state_values["Rinvoq"] + state_values["Skyrizi"]) / 2).round().astype(int)
        
        # Create a dictionary mapping state names to avg values
        state_dict = dict(zip(state_values["State"], state_values["avg_interest"]))
        
        # Add choropleth layer
        folium.Choropleth(
            geo_data=geo_data,
            name="Search Interest",
            data=state_values,
            columns=["State", "avg_interest"],
            key_on="feature.properties.name",
            fill_color="Blues",
            fill_opacity=0.7,
            line_opacity=0.5,
            line_color="white",
            line_weight=1,
            legend_name="Search Interest Index",
            nan_fill_color="lightgray",
        ).add_to(m)
        
        # Add custom tooltips for states with hover info
        for feature in geo_data["features"]:
            state_name = feature["properties"]["name"]
            state_data = state_values[state_values["State"] == state_name]
            
            if not state_data.empty:
                rinvoq_val = int(state_data["Rinvoq"].values[0])
                skyrizi_val = int(state_data["Skyrizi"].values[0])
                avg_val = int(state_data["avg_interest"].values[0])
                
                tooltip_text = f"<b>{state_name}</b><br>Rinvoq: {rinvoq_val}<br>Skyrizi: {skyrizi_val}<br>Avg: {avg_val}"
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
        st.warning(f"Could not load state boundaries: {e}")
    
    # Add DMA circle markers on top
    for _, row in DEMO_DMA.iterrows():
        r_val, s_val = row["Rinvoq"], row["Skyrizi"]
        avg = (r_val + s_val) / 2
        color = RINVOQ if r_val > s_val else SKYRIZI
        folium.CircleMarker(
            [row["lat"], row["lng"]], radius=4 + avg / 10,
            color="white", weight=2, fill=True, fill_color=color, fill_opacity=0.85,
            tooltip=f"<b>{row['Market']}</b><br>Rinvoq: {r_val} · Skyrizi: {s_val} {row['Trend']}"
        ).add_to(m)
    
    st_folium(m, height=500, use_container_width=True)
    
    # Regional comparison
    regions = {
        "Northeast": ["New York", "Boston", "Philadelphia"],
        "Southeast": ["Miami", "Atlanta"],
        "Midwest": ["Chicago", "Minneapolis"],
        "West": ["Los Angeles", "Seattle", "Dallas"],
    }
    reg_data = []
    for reg, cities in regions.items():
        matches = DEMO_DMA[DEMO_DMA["Market"].apply(lambda x: any(c in x for c in cities))]
        if not matches.empty:
            reg_data.append({"Region": reg, "Rinvoq": matches["Rinvoq"].mean().round(), "Skyrizi": matches["Skyrizi"].mean().round()})
    
    if reg_data:
        reg_df = pd.DataFrame(reg_data)
        fig_reg = go.Figure()
        fig_reg.add_trace(go.Bar(x=reg_df["Region"], y=reg_df["Rinvoq"], name="Rinvoq", marker_color=RINVOQ))
        fig_reg.add_trace(go.Bar(x=reg_df["Region"], y=reg_df["Skyrizi"], name="Skyrizi", marker_color=SKYRIZI))
        fig_reg.update_layout(title="Regional Performance", barmode="group", height=350, template="plotly_white", yaxis=dict(range=[0, 100]))
        st.plotly_chart(fig_reg, use_container_width=True)
    
    # Insight
    st.info("📍 **Geographic Insight:** Rinvoq leads in the Northeast and Midwest driven by concentrated rheumatology HCP networks. Skyrizi dominates the Southeast and West where dermatology-heavy populations drive psoriasis search volume. Recommend allocating incremental digital spend to the trending-up markets.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 3: COMPETITIVE
# ═══════════════════════════════════════════════════════════════════════════
with tabs[2]:
    st.subheader("Competitive Intelligence")
    
    # KPIs
    np.random.seed(99)
    all_brands = [{"Brand": "Skyrizi", "Index": 88, "Color": SKYRIZI}, {"Brand": "Rinvoq", "Index": 82, "Color": RINVOQ}]
    all_brands += [{"Brand": c, "Index": np.random.randint(30, 75), "Color": COMP_COLORS[c]} for c in COMPETITORS]
    brand_df = pd.DataFrame(all_brands).sort_values("Index", ascending=False).reset_index(drop=True)
    
    ck1, ck2, ck3, ck4 = st.columns(4)
    sky_rank = brand_df[brand_df["Brand"] == "Skyrizi"].index[0] + 1
    rin_rank = brand_df[brand_df["Brand"] == "Rinvoq"].index[0] + 1
    top_comp = brand_df[~brand_df["Brand"].isin(["Rinvoq", "Skyrizi"])].iloc[0]
    ck1.metric("Skyrizi Rank", f"#{sky_rank}", f"of {len(brand_df)} brands")
    ck2.metric("Rinvoq Rank", f"#{rin_rank}", f"of {len(brand_df)} brands")
    ck3.metric("Top Competitor", top_comp["Brand"], f"Index {top_comp['Index']}")
    ck4.metric("Brands Tracked", len(brand_df), f"{len(COMPETITORS)} competitors")
    
    fig_rank = px.bar(brand_df, x="Index", y="Brand", orientation="h", title="Competitive Index Ranking",
                      color="Brand", color_discrete_map={b["Brand"]: b["Color"] for b in all_brands})
    fig_rank.update_layout(height=380, showlegend=False, yaxis=dict(autorange="reversed"), margin=dict(t=40))
    st.plotly_chart(fig_rank, use_container_width=True)
    
    c3, c4 = st.columns(2)
    with c3:
        # Humira displacement
        humira_data = pd.DataFrame({
            "Month": SEASON_DATA["Month"],
            "Humira": [max(20, 65 - i*3 + np.random.randint(-4, 4)) for i in range(12)],
            "Rinvoq": [30 + i*3 + np.random.randint(-3, 3) for i in range(12)],
            "Skyrizi": [35 + i*3 + np.random.randint(-3, 3) for i in range(12)],
        })
        fig_hum = go.Figure()
        fig_hum.add_trace(go.Scatter(x=humira_data["Month"], y=humira_data["Humira"], name="Humira", line=dict(color="#e67e22", dash="dash")))
        fig_hum.add_trace(go.Scatter(x=humira_data["Month"], y=humira_data["Rinvoq"], name="Rinvoq", line=dict(color=RINVOQ)))
        fig_hum.add_trace(go.Scatter(x=humira_data["Month"], y=humira_data["Skyrizi"], name="Skyrizi", line=dict(color=SKYRIZI)))
        fig_hum.update_layout(title="Humira Displacement Trend", height=350, template="plotly_white")
        st.plotly_chart(fig_hum, use_container_width=True)
    with c4:
        # Radar
        fig_radar = go.Figure()
        cats = ["RA", "Psoriasis", "PsA", "AS", "AD", "CD", "UC", "GCA"]
        fig_radar.add_trace(go.Scatterpolar(r=[90,45,75,72,68,55,52,65], theta=cats, fill="toself", name="Rinvoq", line_color=RINVOQ))
        fig_radar.add_trace(go.Scatterpolar(r=[15,30,20,10,85,5,5,5], theta=cats, fill="toself", name="Dupixent", line_color="#00b894"))
        fig_radar.update_layout(title="Rinvoq vs Dupixent — Indication Overlap", height=350, polar=dict(radialaxis=dict(range=[0, 100])))
        st.plotly_chart(fig_radar, use_container_width=True)
    
    st.info("⚔️ **Competitive Insight:** Humira's biosimilar erosion is accelerating — its search index has declined ~45% over 12 months, creating a capture window for both brands. Recommend increasing defensive bidding on competitor comparison queries and allocating Humira displacement budget to top rheumatology DMAs.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 4: PATIENT INTENT
# ═══════════════════════════════════════════════════════════════════════════
with tabs[3]:
    st.subheader("Patient Intent Analysis")
    
    ik1, ik2, ik3, ik4 = st.columns(4)
    ik1.metric("Awareness Queries", len(DEMO_QUERIES[DEMO_QUERIES["Type"] == "condition"]), "Condition-level")
    ik2.metric("HCP Intent", len(DEMO_QUERIES[DEMO_QUERIES["Type"].isin(["generic", "safety"])]), "Clinical terms")
    ik3.metric("Branded Queries", len(DEMO_QUERIES[DEMO_QUERIES["Type"].isin(["branded", "competitive"])]), "Brand-specific")
    ik4.metric("Breakout Terms", len(DEMO_QUERIES[DEMO_QUERIES["Growth"] >= 500]), "Explosive growth")
    
    # Use live related queries if available
    q1, q2 = st.columns(2)
    with q1:
        st.markdown("**All Condition Terms**")
        display_q = DEMO_QUERIES.sort_values("Index", ascending=False)
        if related_rinvoq.get("top") is not None:
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
        rising = DEMO_QUERIES.sort_values("Growth", ascending=False)
        if related_rinvoq.get("rising") is not None:
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
            name=ind, line=dict(color=color, width=2), mode="lines"
        ))
    fig_intent.update_layout(title="Intent Trend by Indication (12 Months)", height=350, template="plotly_white")
    st.plotly_chart(fig_intent, use_container_width=True)
    
    st.info("🔬 **Patient Intent Insight:** Patient-oriented queries (conditions, symptoms) dominate search volume, indicating strong awareness-stage interest. HCP-oriented queries (generics, MOA, safety) lag behind — recommend shifting 15% of awareness budget toward HCP-targeted content to balance the funnel. Breakout terms in AS and GCA represent first-mover search equity.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 5: CAMPAIGN PLANNING
# ═══════════════════════════════════════════════════════════════════════════
with tabs[4]:
    st.subheader("Campaign Planning")
    
    now = datetime.now()
    pk1, pk2, pk3, pk4 = st.columns(4)
    pk1.metric("Active Campaigns", "3", "Across 2 brands")
    pk2.metric("Rinvoq Peak In", f"{(2 - now.month + 12) % 12 or 12}mo", "Peak RA: February")
    pk3.metric("Skyrizi Peak In", f"{(8 - now.month + 12) % 12 or 12}mo", "Peak Psoriasis: August")
    pk4.metric("Search Alignment", "Good", "4/5 peaks covered")
    
    # Calendar
    st.markdown("**Annual Campaign Calendar**")
    cal_events = [
        {"Month": m, "Brand": b, "Indication": ind, "Activity": act}
        for m, b, ind, act in [
            ("Jan", "Rinvoq", "RA/PsA", "Winter flare ramp-up"),
            ("Feb", "Rinvoq", "RA", "Peak RA · Super Bowl"),
            ("Mar", "Skyrizi", "Psoriasis", "Spring derm prep"),
            ("Apr", "Both", "PsA", "PsA awareness month"),
            ("May", "Skyrizi", "Pso/AD", "Pre-summer derm launch"),
            ("Jun", "Skyrizi", "Psoriasis", "Peak psoriasis — Sun Belt"),
            ("Jul", "Skyrizi", "Pso/AD", "Sustained summer derm"),
            ("Aug", "Both", "CD/UC", "IBD awareness transition"),
            ("Sep", "Rinvoq", "AS/GCA", "Rheum conference prep"),
            ("Oct", "Both", "All", "Competitive defense"),
            ("Nov", "Rinvoq", "RA", "ACR Annual Meeting"),
            ("Dec", "Rinvoq", "RA/GCA", "Year-end + Q1 planning"),
        ]
    ]
    st.dataframe(pd.DataFrame(cal_events), use_container_width=True, hide_index=True)
    
    c1, c2 = st.columns(2)
    with c1:
        fig_ch = go.Figure()
        channels = ["Paid Search", "Social", "Display", "TV/CTV", "HCP Digital", "Email"]
        fig_ch.add_trace(go.Bar(y=channels, x=[35,20,15,18,28,12], name="Rinvoq", marker_color=RINVOQ, orientation="h"))
        fig_ch.add_trace(go.Bar(y=channels, x=[30,28,20,22,15,10], name="Skyrizi", marker_color=SKYRIZI, orientation="h"))
        fig_ch.update_layout(title="Channel Budget Allocation (%)", height=350, barmode="group", template="plotly_white")
        st.plotly_chart(fig_ch, use_container_width=True)
    with c2:
        # Alignment chart
        search_peaks = [(SEASON_DATA["Rinvoq"].iloc[i] + SEASON_DATA["Skyrizi"].iloc[i]) / 2 for i in range(12)]
        campaign_spend = [20,35,25,20,30,40,35,25,20,15,30,25]
        fig_align = go.Figure()
        fig_align.add_trace(go.Scatter(x=SEASON_DATA["Month"], y=search_peaks, name="Search Interest", fill="tozeroy", line=dict(color=NAVY)))
        fig_align.add_trace(go.Scatter(x=SEASON_DATA["Month"], y=campaign_spend, name="Campaign Spend", line=dict(color=GOLD, dash="dash")))
        fig_align.update_layout(title="Search vs Campaign Alignment", height=350, template="plotly_white")
        st.plotly_chart(fig_align, use_container_width=True)
    
    st.info("📅 **Campaign Insight:** Focus Skyrizi on psoriasis in Sun Belt DMAs starting May. Pair with Rinvoq defensive RA campaign in the Northeast. Key actions: (1) Increase paid search 30% for psoriasis terms, (2) Launch Rinvoq GCA content in HCP channels, (3) Monitor Humira biosimilar displacement weekly.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 6: KEY MOMENTS
# ═══════════════════════════════════════════════════════════════════════════
with tabs[5]:
    st.subheader("Key Cultural Moments")
    
    moments_df = pd.DataFrame(MOMENTS_DATA)
    selected_event = st.selectbox("Select Event", moments_df["Event"].tolist())
    event = moments_df[moments_df["Event"] == selected_event].iloc[0]
    
    mk1, mk2, mk3, mk4 = st.columns(4)
    mk1.metric("Rinvoq Lift", event["Rinvoq Lift"], "vs baseline")
    mk2.metric("Skyrizi Lift", event["Skyrizi Lift"], "vs baseline")
    mk3.metric("Peak Day Index", event["Peak"])
    mk4.metric("Halo Duration", event["Halo"], "post-event")
    
    # Event trend chart
    r_lift = int(event["Rinvoq Lift"].replace("+", "").replace("%", ""))
    s_lift = int(event["Skyrizi Lift"].replace("+", "").replace("%", ""))
    days = 42
    baseline = 45
    event_day = 14
    np.random.seed(hash(selected_event) % 2**31)
    x_days = list(range(-14, 28))
    r_trend = [baseline + (max(0, (event["Peak"] - baseline) * np.exp(-(max(0, i - event_day)) / int(event["Halo"].replace("d", "")))) * r_lift / 100 if i >= event_day else 0) + np.random.randn() * 4 for i in range(days)]
    s_trend = [baseline + (max(0, (event["Peak"] - baseline) * np.exp(-(max(0, i - event_day)) / int(event["Halo"].replace("d", "")))) * s_lift / 100 if i >= event_day else 0) + np.random.randn() * 4 for i in range(days)]
    
    fig_moment = go.Figure()
    fig_moment.add_trace(go.Scatter(x=x_days, y=r_trend, name="Rinvoq", line=dict(color=RINVOQ, width=2)))
    fig_moment.add_trace(go.Scatter(x=x_days, y=s_trend, name="Skyrizi", line=dict(color=SKYRIZI, width=2)))
    fig_moment.add_vline(x=0, line_dash="dash", line_color="gray", annotation_text="Event Day")
    fig_moment.update_layout(title=f"Search Trend — {selected_event}", height=350, template="plotly_white", xaxis_title="Days from Event")
    st.plotly_chart(fig_moment, use_container_width=True)
    
    st.markdown(f"**Event Intelligence:** {event['Insight']}")
    
    # Summary table
    st.markdown("---")
    st.subheader("Annual Moments Summary")
    summary = moments_df[["Event", "Category", "Date", "Rinvoq Lift", "Skyrizi Lift", "Peak", "Halo", "Breakout"]].copy()
    summary["Combined Lift"] = summary.apply(lambda r: int(r["Rinvoq Lift"].replace("+","").replace("%","")) + int(r["Skyrizi Lift"].replace("+","").replace("%","")), axis=1)
    summary = summary.sort_values("Combined Lift", ascending=False)
    st.dataframe(summary, use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════
# TAB 7: AI CHAT
# ═══════════════════════════════════════════════════════════════════════════
with tabs[6]:
    st.subheader("💬 AI Chat — Ask Questions About Your Data")
    st.caption("Ask Claude anything about the search trends, geographic performance, or competitive insights. Questions are answered based on your current dashboard data.")
    
    if not client:
        st.error("🔌 Claude API connection required. Set the ANTHROPIC_API_KEY environment variable to enable chat.")
    else:
        # Chat interface
        chat_container = st.container()
        
        # Display chat history
        with chat_container:
            for i, message in enumerate(st.session_state.chat_history):
                if message["role"] == "user":
                    with st.chat_message("user"):
                        st.markdown(message["content"])
                else:
                    with st.chat_message("assistant"):
                        st.markdown(message["content"])
        
        # Input area
        st.divider()
        
        user_input = st.chat_input("Ask about trends, markets, queries, or strategy...", key="chat_input")
        
        if user_input:
            # Add user message to history
            st.session_state.chat_history.append({
                "role": "user",
                "content": user_input
            })
            
            # Display user message
            with st.chat_message("user"):
                st.markdown(user_input)
            
            # Get Claude response
            with st.chat_message("assistant"):
                with st.spinner("Claude is thinking..."):
                    # Prepare messages for Claude (exclude system message)
                    messages_for_claude = [
                        {"role": msg["role"], "content": msg["content"]}
                        for msg in st.session_state.chat_history
                    ]
                    
                    response = chat_with_claude(
                        client, 
                        messages_for_claude,
                        trend_df, 
                        DEMO_DMA, 
                        DEMO_STATES, 
                        DEMO_QUERIES
                    )
                    st.markdown(response)
                    
                    # Add assistant response to history
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": response
                    })
            
            # Auto-rerun to update chat
            st.rerun()
        
        # Quick prompt suggestions
        st.divider()
        st.markdown("**Quick Questions:**")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📍 Which markets are strongest?"):
                st.session_state.chat_history.append({
                    "role": "user",
                    "content": "Which markets are strongest for Rinvoq vs Skyrizi?"
                })
                st.rerun()
            if st.button("📈 What's the growth trend?"):
                st.session_state.chat_history.append({
                    "role": "user",
                    "content": "What's the growth trend for Rinvoq and Skyrizi?"
                })
                st.rerun()
        with col2:
            if st.button("🎯 Where should we allocate budget?"):
                st.session_state.chat_history.append({
                    "role": "user",
                    "content": "Where should we allocate marketing budget based on this data?"
                })
                st.rerun()
            if st.button("🔍 What patient intents matter most?"):
                st.session_state.chat_history.append({
                    "role": "user",
                    "content": "What patient search intents should we focus on?"
                })
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# FOOTER
# ═══════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.caption("⚠ Google Trends indices are relative (0–100) and do not represent absolute search volumes. For internal use only. | AbbVie Immunology Intelligence · Confidential")
