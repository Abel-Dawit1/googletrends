"""
AbbVie Immunology Dashboard — Data Configuration
==================================================
Centralized configuration for filter categories, color schemes, and groupings.

This file defines:
- Brand colors and competitor mapping
- Clinical indication codes and display names
- Therapeutic franchise groupings
- Timeframe options for Google Trends queries

Modify these dictionaries to customize dashboard filter options and display naming.
"""

# ═══════════════════════════════════════════════════════════════════════════
# BRAND COLORS & COMPETITOR MAPPING
# ═══════════════════════════════════════════════════════════════════════════
NAVY = "#071d49"
RINVOQ = "#FFB84D"
SKYRIZI = "#4db8ff"
GOLD = "#b8860b"
SUCCESS = "#1a7f4f"

COMP_COLORS = {
    "Enbrel": "#6b4c9a", 
    "Humira": "#e67e22", 
    "Xeljanz": "#3498db",
    "Tremfya": "#27ae60", 
    "Cosentyx": "#8e44ad", 
    "Bimzelx": "#e84393",
    "Dupixent": "#e74c3c", 
    "Ebglyss": "#fd79a8", 
    "Nemluvio": "#636e72",
    "Otezla": "#fdcb6e", 
    "Icotrokinra": "#00cec9", 
    "Entyvio": "#2980b9",
}

COMPETITORS = list(COMP_COLORS.keys())


# ═══════════════════════════════════════════════════════════════════════════
# CLINICAL INDICATIONS
# ═══════════════════════════════════════════════════════════════════════════
# Maps indication codes to their display names
IND_NAMES = {
    "ra": "RA", 
    "pso": "Psoriasis", 
    "psa": "PsA", 
    "as": "AS",
    "ad": "AD", 
    "cd": "Crohn's", 
    "uc": "UC", 
    "gca": "GCA"
}


# ═══════════════════════════════════════════════════════════════════════════
# THERAPEUTIC FRANCHISE GROUPINGS
# ═══════════════════════════════════════════════════════════════════════════
# Groups indications into therapeutic franchises for easier filtering and analysis
FRANCHISE_MAP = {
    "Rheumatology": ["ra", "psa", "as", "gca"],
    "Dermatology": ["pso", "psa", "ad"],
    "Gastroenterology": ["uc", "cd"],
}


# ═══════════════════════════════════════════════════════════════════════════
# GOOGLE TRENDS TIMEFRAME OPTIONS
# ═══════════════════════════════════════════════════════════════════════════
# Maps user-friendly timeframe labels to Google Trends API parameters
TIMEFRAME_MAP = {
    "7 Days": "now 7-d", 
    "30 Days": "today 1-m", 
    "90 Days": "today 3-m",
    "12 Months": "today 12-m", 
    "5 Years": "today 5-y",
}


# ═══════════════════════════════════════════════════════════════════════════
# DEMO DATA - AI INSIGHTS
# ═══════════════════════════════════════════════════════════════════════════
DEMO_AI_INSIGHTS = [
    "**Skyrizi Outpacing Rinvoq in Growth Rate**\n\n📈 Skyrizi YoY growth +45% vs Rinvoq +38%. Gap widening across all quarters in 2024. Suggests stronger momentum in dermatology indication expansion, particularly psoriasis and newer areas.",
    "**Skyrizi Crohn's Breakout: +42% Spike**\n\n📈 Crohn's disease searches for Skyrizi jumped 42% YoY—highest growth among any tracked indication. Marks successful entry into GI market with legitimate clinical demand signal.",
    "**Rinvoq Command in RA/Rheumatology Searches**\n\n📈 Rheumatoid arthritis searches favor Rinvoq (94 index) over Skyrizi (88 index). Upadacitinib JAK mechanism maintains strong HCP research activity, particularly around clinical data.",
    "**Northeast Duopoly: Both Brands Dominate**\n\n📈 Rinvoq and Skyrizi both sustained 15-25 pts above national average in Northeast DMAs. NYC/Boston/Philadelphia show deepest market penetration for both products combined.",
    "**Skyrizi Emerging in New Indications**\n\n📈 Atopic dermatitis searches up 52% YoY for Skyrizi. Signals successful label expansion beyond plaque psoriasis gaining traction with patients exploring treatment options.",
    "**Safety Research: Patients Evaluating Both**\n\n📈 JAK inhibitor safety searches (+82 index) tracking Rinvoq research. Patients in evaluation phase want evidence-based safety profiles as part of treatment selection."
]
