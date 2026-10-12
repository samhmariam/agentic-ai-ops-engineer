from pathlib import Path
import pandas as pd

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"

BUYER_NAMES = [
    "Oliver T.", "Aisha K.", "Marco F.", "Lin W.", "Elena V.",
    "Samuel O.", "Fatima H.", "Chris B.", "Nadia C.", "Raj S.",
]
BUDGET_RANGES = [
    "200k-300k", "300k-400k", "400k-500k", "500k-650k", "650k-800k",
]
PRE_APPROVAL_STATUSES = ["approved", "pending", "not_started"]
CREDIT_SCORE_BANDS = ["excellent", "good", "fair", "needs_improvement"]
LEAD_TYPES = ["ibuyer_inquiry", "marketplace"]


def _agents_for_region(users: pd.DataFrame, region: str) -> list:
    def has_access(row):
        return row["region_access"] == "all" or region in row["region_access"].split("|")
    return users[users.apply(has_access, axis=1)]["user_id"].tolist()


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    demand = pd.read_csv(DATA_DIR / "demand_signals.csv")
    users = pd.read_csv(DATA_DIR / "users.csv")

    rows = []
    lead_counter = 1

    for _, seg in demand.iterrows():
        region = seg["region"]
        property_type = seg["property_type"]
        bedrooms = int(seg["bedrooms"])
        n = int(seg["lead_count"])

        agents = _agents_for_region(users, region)

        for i in range(n):
            rows.append({
                "lead_id": f"LEAD-{lead_counter:05d}",
                "region": region,
                "property_type": property_type,
                "bedrooms": bedrooms,
                "lead_type": LEAD_TYPES[i % 2],
                "buyer_name": BUYER_NAMES[i % len(BUYER_NAMES)],
                "budget_range": BUDGET_RANGES[i % len(BUDGET_RANGES)],
                "pre_approval_status": PRE_APPROVAL_STATUSES[i % len(PRE_APPROVAL_STATUSES)],
                "credit_score_band": CREDIT_SCORE_BANDS[i % len(CREDIT_SCORE_BANDS)],
                "lead_score": round(0.30 + (i % 10) * 0.07, 2),
                "assigned_agent_id": agents[i % len(agents)] if agents else "analyst_001",
            })
            lead_counter += 1

    df = pd.DataFrame(rows)
    df.to_csv(DATA_DIR / "demand_leads.csv", index=False)
    print(f"  demand_leads.csv ({len(df)} rows)")


if __name__ == "__main__":
    main()
