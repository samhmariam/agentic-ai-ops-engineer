import pandas as pd
from langchain_core.tools import tool


def make_tools(demand: pd.DataFrame, supply: pd.DataFrame) -> list:
    @tool
    def get_demand_signals(region: str, property_type: str, bedrooms: int) -> str:
        """Get demand signals for a real estate segment in Ciudaty.

        Args:
            region: Ciudaty region (west, north, south, east, center)
            property_type: Property type (apartment, house, studio)
            bedrooms: Number of bedrooms
        """
        d = demand[
            (demand["region"] == region)
            & (demand["property_type"] == property_type)
            & (demand["bedrooms"] == bedrooms)
        ]
        if d.empty:
            return "No demand data available for this segment."
        return d.to_string(index=False)

    @tool
    def get_supply_snapshot(region: str, property_type: str, bedrooms: int) -> str:
        """Get supply snapshot for a real estate segment in Ciudaty.

        Args:
            region: Ciudaty region (west, north, south, east, center)
            property_type: Property type (apartment, house, studio)
            bedrooms: Number of bedrooms
        """
        s = supply[
            (supply["region"] == region)
            & (supply["property_type"] == property_type)
            & (supply["bedrooms"] == bedrooms)
        ]
        if s.empty:
            return "No supply data available for this segment."
        return s.to_string(index=False)

    return [get_demand_signals, get_supply_snapshot]
