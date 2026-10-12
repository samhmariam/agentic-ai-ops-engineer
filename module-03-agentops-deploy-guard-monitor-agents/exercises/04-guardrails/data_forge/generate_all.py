from pathlib import Path
import subprocess
import sys


SCRIPTS = [
    "generate_static.py",
    "generate_users.py",
    "generate_listings.py",
    "generate_supply_opportunities.py",
    "generate_demand_leads.py",
    "generate_sales.py",
    "generate_scenarios.py",
]


def main():
    data_forge_dir = Path(__file__).parent
    print("Generating datasets...")
    for script in SCRIPTS:
        subprocess.run(
            [sys.executable, data_forge_dir / script],
            check=True,
        )
    print("\nValidating...")
    subprocess.run(
        [sys.executable, data_forge_dir / "validate.py"],
        check=True,
    )
    print("\nAll 9 datasets + eval_scenarios.csv generated and validated.")


if __name__ == "__main__":
    main()
