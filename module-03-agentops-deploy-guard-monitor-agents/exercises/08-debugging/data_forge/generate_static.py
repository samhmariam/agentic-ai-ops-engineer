from pathlib import Path
import pandas as pd

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"

NEIGHBORHOOD_PROFILES = [
    ("west",   "Westgate",    1.18, 0.31, "low",    "Established residential corridor; below-average vacancy"),
    ("west",   "Harbor View", 1.34, 0.22, "low",    "Coastal proximity; lower stock availability than signal suggests"),
    ("north",  "Northside",   0.89, 0.41, "medium", "Mixed-use transition; higher supply volatility"),
    ("north",  "Millwood",    0.94, 0.38, "medium", "Older stock; renovation pipeline moderates fresh supply"),
    ("south",  "Southpark",   1.02, 0.28, "low",    "Family-oriented mid-market; stable turnover"),
    ("south",  "Riverdale",   0.97, 0.33, "low",    "Below-market stock; steady demand from mid-range buyers"),
    ("east",   "Eastfield",   1.11, 0.44, "medium", "High transaction volume; listings clear faster than avg_days suggests"),
    ("east",   "Ironbridge",  0.85, 0.52, "high",   "Industrial adjacency; risk-flagged for zoning uncertainty"),
    ("center", "Centro",      1.22, 0.19, "low",    "Premium micro-market; low velocity but high value"),
    ("center", "Midtown",     1.09, 0.27, "low",    "Commercial-residential mix; moderate residential demand"),
]

LISTING_VELOCITY = [
    ("west",   "apartment", 1,  8, 21, 0.82, "high"),
    ("west",   "apartment", 2,  5, 18, 0.91, "high"),
    ("west",   "house",     3, 19, 34, 0.63, "medium"),
    ("west",   "studio",    1, 11, 24, 0.71, "medium"),
    ("north",  "apartment", 1, 22, 41, 0.52, "medium"),
    ("north",  "apartment", 2, 12, 29, 0.78, "high"),
    ("north",  "house",     2, 38, 58, 0.39, "low"),
    ("north",  "house",     3, 44, 63, 0.34, "low"),
    ("south",  "apartment", 2, 16, 32, 0.68, "medium"),
    ("south",  "house",     3, 18, 35, 0.65, "medium"),
    ("south",  "house",     4, 29, 47, 0.48, "medium"),
    ("south",  "studio",    1,  9, 22, 0.80, "high"),
    ("east",   "apartment", 1, 21, 38, 0.62, "medium"),
    ("east",   "apartment", 2, 13, 27, 0.77, "high"),
    ("east",   "studio",    1, 31, 51, 0.55, "low"),
    ("east",   "house",     3, 24, 42, 0.58, "medium"),
    ("center", "studio",    1, 44, 64, 0.43, "low"),
    ("center", "apartment", 1, 26, 45, 0.61, "medium"),
    ("center", "apartment", 2, 33, 53, 0.52, "medium"),
    ("center", "house",     2, 37, 57, 0.46, "low"),
]


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    nbhd = pd.DataFrame(NEIGHBORHOOD_PROFILES, columns=[
        "region", "neighborhood", "avg_price_index",
        "listing_turnover_rate", "risk_flag", "demographic_notes",
    ])
    nbhd.to_csv(DATA_DIR / "neighborhood_profiles.csv", index=False)
    print(f"  neighborhood_profiles.csv ({len(nbhd)} rows)")

    vel = pd.DataFrame(LISTING_VELOCITY, columns=[
        "region", "property_type", "bedrooms",
        "avg_days_to_offer", "avg_days_to_close", "velocity_score", "data_confidence",
    ])
    vel.to_csv(DATA_DIR / "listing_velocity.csv", index=False)
    print(f"  listing_velocity.csv ({len(vel)} rows)")


if __name__ == "__main__":
    main()
