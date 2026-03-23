# AbbVie Immunology — Search Intelligence Dashboard
## App Architecture Summary

---

## **NLP LAYER**

### Text Extraction & Normalization
- **Reddit Title Extraction**: Parses RSS feed entries to extract post titles with deduplication
- **Query Normalization**: Lowercase and whitespace-standardized keyword matching for brand/indication filtering
- **Content Cleaning**: Removes excessive whitespace, strips URLs, normalizes encoding from RSS feeds

### Brand & Indication Matching
- **Alias Matching**: Fuzzy keyword matching for Rinvoq & Skyrizi across search terms and Reddit posts
- **Indication Categorization**: Maps franchises (RA, GCA, Psoriasis, etc.) from trend queries and patient intent data
- **Related Query Mapping**: Associates brand-specific related queries with parent keywords and rise/stable/falling trends

### Sentiment Scoring
- **Keyword-Based Sentiment Analysis**: Custom positive/negative lexicon (no VADER)
  - Positive words: "great", "love", "cleared", "improvement", "success", "relief"
  - Negative words: "side effects", "problem", "struggle", "pain", "worry", "failed"
  - Neutral: scores balance between positive & negative keyword counts
- **Reddit Post Sentiment**: Applied to titles for trend correlation analysis
- **Scoring Range**: Positive | Neutral | Negative (categorical, not numeric)

---

## **STRUCTURING LAYER**

### Time Series Normalization
- **Date Indexing**: Pandas datetime index on all trend data (daily granularity)
- **Timeframe Mapping**: Standardizes 5 available timeframes into internal format
  - `now 7-d` → 7 days (recent trends)
  - `today 1-m` → 30 days (short-term)
  - `today 3-m` → 90 days (medium-term)
  - `today 12-m` → 1 year (annual patterns)
  - `today 5-y` → 5 years (long-term trends)
- **Index Normalization**: Converts all search indices to 0-100 scale (Google Trends standard)

### Geographic Transformation
- **Regional → State Conversion**: Collapses Google Trends regional data (DMAs) to state-level aggregation
  - Extracts state names from regional_df index
  - Converts all values to integers
  - Preserves brand-specific indices (Rinvoq vs Skyrizi per state)
- **State → DMA Market Expansion**: Generates 15 major DMA markets from state-level data
  - Maps cities (NYC, LA, Chicago, etc.) to parent states via geolocation
  - Inherits parent state's index values for DMA visualization
  - Adds trend indicator (↑↓→) via relative value comparison
- **Geomap CSV Loading**: Dual-format support
  - Regional format (Region column, state names as values)
  - Auto-detection of format type per CSV
  - Graceful fallback if one brand is time-series only

### Content Type Tagging
- **Query Classification**:
  - **Top Queries**: Most common searches for brand/condition
  - **Rising Queries**: Fastest-growing associated searches (week-over-week momentum)
  - **Falling Queries**: Declining interest patterns (potential market shifts)
- **Indication Tagging**: Categories assigned from FRANCHISE_MAP
  - "All" wildcard (applies universally)
  - Brand-specific indications (Rinvoq → RA/GCA, Skyrizi → Psoriasis)

### Patient Insight Extraction
- **Parent Condition Extraction**: Derives primary condition from search branch
  - Root keywords: "Rinvoq", "Skyrizi", "RA", "GCA", "Psoriasis"
  - Branches: Symptoms, treatments, side effects, lifestyle impact
- **Query Intent Mapping**: Categorizes by user journey stage
  - Awareness: condition-focused searches ("what is psoriasis")
  - Consideration: treatment comparisons ("Rinvoq vs Xeljanz")
  - Conversion: side effects & usage ("Skyrizi injection frequency")
- **Sentiment Context**: Links sentiment to query type for intent strength

### Data Merging & Aggregation
- **Multi-Brand Merge**: Outer joins Rinvoq + Skyrizi on State/Date for comparison
- **NaN Handling**: Drops rows with missing values in either brand (ensures data integrity)
- **Brand Filtering**: Single-brand or both-brand display modes
  - "Both" mode: shows side-by-side comparisons and DMA averages
  - Single brand: isolates individual product trends
- **Aggregation**: Peak, average, and trend direction calculations

---

## **STORAGE LAYER**

### Primary Data Sources

#### **Google Trends CSV Files** (Local Files)
**Trend Time-Series**:
- Naming: `[Brand] Search Intent [Timeframe] new.csv`
- Format: Date (index) × Search Index Value
- Cadence: Historical, updated monthly
- Examples:
  - `Rinvoq Search Intent 1 year new.csv`
  - `Skyrizi Search Intent 90 days new.csv`

**Geographic (Geomap) Data**:
- Naming: `[Brand] Search Intent [Timeframe] geomap.csv`
- Format: State/Region (rows) × Index Values (columns)
- Cadence: Weekly to monthly refresh
- Supports dual formats: Regional (by state) or Time-series (by date)

#### **Session State** (Streamlit)
- **Fast Cache**: Stores frequently accessed data between interactions
  - Current timeframe selection
  - Last refresh timestamp
  - Brand and indication filters
  - Chat history
- **TTL Caching**: API responses cached for 2 hours
  - `@st.cache_data(ttl=7200)`
  - Reduces API rate limiting
  - Graceful fallback to CSV if API unavailable

#### **Reddit RSS Feeds** (Real-Time, No Auth)
- **Data Source**: Reddit public RSS feeds (no API key required)
- **URL Pattern**: `https://www.reddit.com/r/[subreddit]/.rss`
- **Subreddits**: Psoriasis, rheumatoidarthritis, AutoimmuneDiseases, etc.
- **Post Metadata**: Title, subreddit, score (estimated), URL
- **Fallback**: Demo posts library if RSS unavailable

#### **Demo Data** (Fallback Layer)
- **Purpose**: Graceful degradation when APIs fail
- **Reddit Posts**: Curated realistic posts per brand/condition
- **Trends**: Synthetic sine-wave patterns with noise
- **DMA**: Pre-generated market data with variance

### Storage Architecture Pattern

```
Live Data (Best)
    ↓ (on API success) Cache to Session
    ↓ (on API failure)
CSV Files (Good)
    ↓ (if CSV missing)
Demo Data (Acceptable)
```

### Data Freshness
- **Trend Data**: 2-hour cache, manual refresh via Rerun button
- **Related Queries**: 2-hour cache per query
- **Reddit Posts**: Fresh per session (no caching)
- **Geographic Data**: Loaded with geomap CSVs (weekly refresh cadence)
- **Dashboard Timestamp**: Updated on every page load

---

## **API INTEGRATIONS**

### Google Trends (pytrends)
```
fetch_trends_data() → Interest Over Time (daily)
fetch_regional_data() → Interest by Region (state/DMA level)
fetch_related_queries() → Top & Rising queries with growth metrics
```
- **Retry Logic**: 2 attempts with exponential backoff (1s, 2s)
- **Rate Limits**: 100-120 requests/minute (automatic backoff)
- **Timeout**: Falls back to CSV on persistent failures

### Reddit RSS Feeds (feedparser)
```
scrape_real_reddit_posts() → Keywords → RSS fetch → Post extraction
  ├─ Keyword matching (prioritized)
  └─ Fallback to demo posts
```
- **No Authentication**: Public RSS feeds only
- **Deduplication**: Title-based deduplication across subreddits
- **Score Estimation**: Extracted from summary or randomized

### Claude AI (Anthropic)
```
generate_ai_insights() → Contextual analysis & recommendations
chat_with_claude() → Real-time Q&A with trend data context
```
- **Optional**: Graceful degradation if ANTHROPIC_API_KEY missing
- **Context**: Formatted trend_df, dma_df, state_df, queries_df
- **Output**: Executive summaries, key callouts, strategic recommendations

### Streamlit (UI Framework)
- **Caching**: Reduces reruns and API calls
- **Session State**: Persists user selections across interactions
- **Rendering**: Plotly charts, Folium maps, Streamlit components

---

## **KEY DATA TRANSFORMATIONS**

| Input | Function | Output | Purpose |
|-------|----------|--------|---------|
| Regional DF | `transform_regional_to_states()` | State DF | Normalize geographic granularity |
| State DF | `generate_dma_from_states()` | DMA DF | Generate market-level visualization |
| Trends + Related | `transform_trends_to_queries()` | Queries DF | Structure patient intent data |
| Trend DF | `format_data_context()` | Formatted String | Prepare for Claude analysis |
| Trend/Query Data | `generate_overview_executive_summary()` | Callouts & Rec | Create actionable insights |

---

## **ERROR HANDLING & FALLBACKS**

### Graceful Degradation Hierarchy
1. **Live API Success**: Use real Google Trends + Reddit data
2. **API Rate Limit**: Cache from session/CSV, skip live calls
3. **CSV Available**: Load from local data files
4. **Demo Only**: Use pre-built synthetic data with notice
5. **Error Logging**: Session state tracks data_source ("live" vs "csv" vs "demo")

### User Notifications
- Error banner on API failure
- Data source indicator (Top of dashboard)
- Last refresh timestamp
- Fallback data warning in tooltip

---

## **CONFIG & CONSTANTS** (config.py)

- **Brand Colors**: RINVOQ, SKYRIZI, NAVY, GOLD, SUCCESS
- **Competitors**: Up to 5 competitor brands for benchmarking
- **Franchises**: Indications mapped to brand-specific conditions
- **Timeframe Map**: User-friendly labels → pytrends codes
- **Demo Data Sets**: Pre-built insights, posts, and trend patterns

---

## **TECH STACK**

- **Backend**: Python 3.x + Streamlit
- **Data**: Pandas, NumPy
- **Visualizations**: Plotly, Folium (choropleth maps)
- **APIs**: pytrends, feedparser, Anthropic Claude
- **Caching**: Streamlit's `@st.cache_data` decorator
- **Storage**: Local CSV files + session state

---

## **PERFORMANCE NOTES**

- **API Calls**: ~5-10 per session (trend, regional, related × 2 brands)
- **Cache Hit Rate**: ~70% for typical user flows
- **Page Load Time**: 1-3 seconds (first load), <500ms (cached)
- **CSV Load Time**: <100ms per file (5 files typical)
- **DMA Generation**: <50ms (state DF → 15 DMA markets)
