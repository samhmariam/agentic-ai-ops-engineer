from pathlib import Path
import pandas as pd

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"

PIPELINE_STAGES = ["prospect", "qualified", "negotiation"]
OPPORTUNITY_TYPES = ["ibuyer", "marketplace"]
ACQUISITION_STRATEGIES = [
    "direct_acquisition", "off_market_offer", "auction_participation",
    "agent_referral", "portfolio_deal",
]
OWNER_CONTACTS = [
    "owner_a@mail.com", "owner_b@mail.com", "owner_c@mail.com",
    "owner_d@mail.com", "owner_e@mail.com",
]

BASE_VALUES = {
    ("studio",    1): (140_000, 270_000),
    ("apartment", 1): (190_000, 340_000),
    ("apartment", 2): (270_000, 440_000),
    ("house",     2): (340_000, 510_000),
    ("house",     3): (390_000, 610_000),
    ("house",     4): (490_000, 690_000),
}

OPPS_PER_SEGMENT = 5


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    supply = pd.read_csv(DATA_DIR / "supply_snapshot.csv")
    nbhds = pd.read_csv(DATA_DIR / "neighborhood_profiles.csv")

    nbhd_map = nbhds.groupby("region")["neighborhood"].apply(list).to_dict()

    rows = []
    opp_counter = 1

    for _, seg in supply.iterrows():
        region = seg["region"]
        property_type = seg["property_type"]
        bedrooms = int(seg["bedrooms"])

        lo, hi = BASE_VALUES.get((property_type, bedrooms), (200_000, 500_000))
        step = (hi - lo) // (OPPS_PER_SEGMENT - 1) if OPPS_PER_SEGMENT > 1 else 0
        region_nbhds = nbhd_map.get(region, [region])

        for i in range(OPPS_PER_SEGMENT):
            rows.append({
                "supply_opportunity_id": f"OPP-{opp_counter:05d}",
                "region": region,
                "neighborhood": region_nbhds[i % len(region_nbhds)],
                "property_type": property_type,
                "bedrooms": bedrooms,
                "opportunity_type": OPPORTUNITY_TYPES[i % 2],
                "estimated_value": lo + step * i,
                "owner_contact": OWNER_CONTACTS[i % len(OWNER_CONTACTS)],
                "acquisition_strategy": ACQUISITION_STRATEGIES[i % len(ACQUISITION_STRATEGIES)],
                "internal_score": round(0.40 + (i * 0.12), 2),
                "pipeline_stage": PIPELINE_STAGES[i % len(PIPELINE_STAGES)],
            })
            opp_counter += 1

    df = pd.DataFrame(rows)
    df.to_csv(DATA_DIR / "supply_opportunities.csv", index=False)
    print(f"  supply_opportunities.csv ({len(df)} rows)")


if __name__ == "__main__":
    main()
