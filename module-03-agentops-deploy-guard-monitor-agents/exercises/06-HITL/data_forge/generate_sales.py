from pathlib import Path
import pandas as pd

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    demand = pd.read_csv(DATA_DIR / "demand_signals.csv")
    listings = pd.read_csv(DATA_DIR / "listings.csv")
    leads = pd.read_csv(DATA_DIR / "demand_leads.csv")
    velocity = pd.read_csv(DATA_DIR / "listing_velocity.csv")

    # Build segment-keyed index for FK lookups
    def seg_key(row):
        return (row["region"], row["property_type"], int(row["bedrooms"]))

    listing_by_seg = {}
    for _, row in listings.iterrows():
        k = seg_key(row)
        listing_by_seg.setdefault(k, []).append(row)

    lead_by_seg = {}
    for _, row in leads.iterrows():
        k = seg_key(row)
        lead_by_seg.setdefault(k, []).append(row)

    vel_map = {}
    for _, row in velocity.iterrows():
        k = seg_key(row)
        vel_map[k] = row

    rows = []
    sale_counter = 1

    for _, seg in demand.iterrows():
        region = seg["region"]
        property_type = seg["property_type"]
        bedrooms = int(seg["bedrooms"])
        n = int(seg["recent_sales"])
        k = (region, property_type, bedrooms)

        seg_listings = listing_by_seg.get(k, [])
        seg_leads = lead_by_seg.get(k, [])
        vel_row = vel_map.get(k)
        base_days_close = int(vel_row["avg_days_to_close"]) if vel_row is not None else 30

        nbhd_pool = list({r["neighborhood"] for r in seg_listings}) if seg_listings else [region]

        for i in range(n):
            lst = seg_listings[i % len(seg_listings)] if seg_listings else None
            lead = seg_leads[i % len(seg_leads)] if seg_leads else None

            listing_id = lst["listing_id"] if lst is not None else f"LST-HIST-{sale_counter:05d}"
            lead_id = lead["lead_id"] if lead is not None else f"LEAD-HIST-{sale_counter:05d}"
            sale_type = lst["listing_type"] if lst is not None else "marketplace"

            # Price slightly below asking
            asking = int(lst["asking_price"]) if lst is not None else 300_000
            final_price = int(asking * (0.96 + (i % 5) * 0.01))

            commission_pct = 0.025 + (i % 4) * 0.0025
            rows.append({
                "sale_id": f"SALE-{sale_counter:05d}",
                "listing_id": listing_id,
                "lead_id": lead_id,
                "region": region,
                "neighborhood": nbhd_pool[i % len(nbhd_pool)],
                "property_type": property_type,
                "bedrooms": bedrooms,
                "sale_type": sale_type,
                "final_price": final_price,
                "days_to_close": max(7, base_days_close + (i % 20) - 10),
                "commission_amount": round(final_price * commission_pct, 2),
                "agent_performance_score": round(0.55 + (i % 10) * 0.045, 2),
            })
            sale_counter += 1

    df = pd.DataFrame(rows)
    df.to_csv(DATA_DIR / "sales.csv", index=False)
    print(f"  sales.csv ({len(df)} rows)")


if __name__ == "__main__":
    main()
