from pathlib import Path
import pandas as pd

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"

SELLER_NAMES = [
    "Carlos M.", "Lucia P.", "David K.", "Sarah T.", "Ahmad R.",
    "Maria S.", "Robert L.", "Yuki N.", "Eva B.", "James W.",
]
SELLER_MOTIVATIONS = ["relocation", "upgrading", "investment_exit", "downsizing", "estate_sale"]

BASE_PRICES = {
    ("studio",    1): (150_000, 280_000),
    ("apartment", 1): (200_000, 350_000),
    ("apartment", 2): (280_000, 450_000),
    ("house",     2): (350_000, 520_000),
    ("house",     3): (400_000, 620_000),
    ("house",     4): (500_000, 700_000),
}
SQFT_RANGES = {
    ("studio",    1): (320, 560),
    ("apartment", 1): (480, 780),
    ("apartment", 2): (680, 1050),
    ("house",     2): (880, 1350),
    ("house",     3): (1100, 1750),
    ("house",     4): (1400, 2100),
}


def _agents_for_region(users: pd.DataFrame, region: str) -> list:
    def has_access(row):
        return row["region_access"] == "all" or region in row["region_access"].split("|")
    return users[users.apply(has_access, axis=1)]["user_id"].tolist()


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    supply = pd.read_csv(DATA_DIR / "supply_snapshot.csv")
    nbhds = pd.read_csv(DATA_DIR / "neighborhood_profiles.csv")
    users = pd.read_csv(DATA_DIR / "users.csv")

    nbhd_map = nbhds.groupby("region")["neighborhood"].apply(list).to_dict()

    rows = []
    listing_counter = 1

    for _, seg in supply.iterrows():
        region = seg["region"]
        property_type = seg["property_type"]
        bedrooms = int(seg["bedrooms"])
        n_active = int(seg["active_listings"])
        n_under_offer = max(1, n_active // 5)  # ~20% extra rows as under_offer
        total = n_active + n_under_offer

        lo_price, hi_price = BASE_PRICES.get((property_type, bedrooms), (200_000, 500_000))
        lo_sqft, hi_sqft = SQFT_RANGES.get((property_type, bedrooms), (500, 1000))
        price_step = (hi_price - lo_price) // max(total - 1, 1)
        sqft_step = (hi_sqft - lo_sqft) // max(total - 1, 1)

        region_nbhds = nbhd_map.get(region, [region])
        agents = _agents_for_region(users, region)

        avg_dom = int(seg["avg_days_on_market"])

        for i in range(total):
            status = "active" if i < n_active else "under_offer"
            listing_type = "ibuyer" if i % 5 < 2 else "marketplace"  # ~40% ibuyer

            rows.append({
                "listing_id": f"LST-{listing_counter:05d}",
                "region": region,
                "neighborhood": region_nbhds[i % len(region_nbhds)],
                "property_type": property_type,
                "bedrooms": bedrooms,
                "listing_type": listing_type,
                "asking_price": lo_price + price_step * i,
                "sqft": lo_sqft + sqft_step * i,
                "year_built": 1970 + (i % 50),
                "days_on_market": max(1, avg_dom + (i % 30) - 15),
                "status": status,
                "seller_name": SELLER_NAMES[i % len(SELLER_NAMES)],
                "seller_motivation": SELLER_MOTIVATIONS[i % len(SELLER_MOTIVATIONS)],
                "assigned_agent_id": agents[i % len(agents)] if agents else "analyst_001",
            })
            listing_counter += 1

    df = pd.DataFrame(rows)
    df.to_csv(DATA_DIR / "listings.csv", index=False)
    active_count = len(df[df["status"] == "active"])
    print(f"  listings.csv ({len(df)} rows: {active_count} active, {len(df) - active_count} under_offer)")


if __name__ == "__main__":
    main()
