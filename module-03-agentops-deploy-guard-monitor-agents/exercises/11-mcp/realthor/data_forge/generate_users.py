from pathlib import Path
import pandas as pd

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"

USERS = [
    # Analysts — full access to all regions
    ("analyst_001", "Maria Santos",  "analyst", "all",         True),
    ("analyst_002", "James Chen",    "analyst", "all",         True),
    ("analyst_003", "Sofia Müller",  "analyst", "all",         True),
    ("analyst_004", "Karim Hassan",  "analyst", "all",         True),
    # Single-region brokers
    ("broker_west_001",   "Emma Rossi",     "broker", "west",         True),
    ("broker_west_002",   "Lucas Neves",    "broker", "west",         True),
    ("broker_north_001",  "Yuki Tanaka",    "broker", "north",        True),
    ("broker_south_001",  "Ana Lima",       "broker", "south",        True),
    ("broker_east_001",   "Dmitri Volkov",  "broker", "east",         True),
    ("broker_east_002",   "Priya Patel",    "broker", "east",         True),
    ("broker_center_001", "Mohamed Ali",    "broker", "center",       True),
    # Multi-region brokers
    ("broker_multi_001",  "Sarah Connor",   "broker", "west|south",   True),
    ("broker_multi_002",  "Carlos Silva",   "broker", "north|east",   True),
    ("broker_multi_003",  "Nina Reeves",    "broker", "east|center",  True),
]


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(USERS, columns=["user_id", "name", "role", "region_access", "active"])
    df.to_csv(DATA_DIR / "users.csv", index=False)
    analysts = len(df[df["role"] == "analyst"])
    brokers = len(df[df["role"] == "broker"])
    print(f"  users.csv ({len(df)} rows: {analysts} analysts, {brokers} brokers)")


if __name__ == "__main__":
    main()
