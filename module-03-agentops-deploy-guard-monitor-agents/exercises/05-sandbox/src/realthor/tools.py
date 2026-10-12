import pandas as pd
from langchain.tools import tool, ToolRuntime

from realthor.guardrails import UserContext
from realthor.sandbox import run_sandboxed, validate_code


def make_tools(
    demand: pd.DataFrame,
    supply: pd.DataFrame,
    neighborhoods: pd.DataFrame,
    velocity: pd.DataFrame,
    supply_opportunities: pd.DataFrame,
    listings: pd.DataFrame,
    sales: pd.DataFrame,
) -> list:
    """Build all fourteen tools, closing over the loaded DataFrames."""

    # ------------------------------------------------------------------
    # Carried from M03
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # New in M04 — data access tools
    # ------------------------------------------------------------------

    @tool
    def get_neighborhood_profile(neighborhood: str) -> str:
        """Get profile data for a Ciudaty neighborhood.

        Returns pricing index, turnover rate, risk flag, and context notes.

        Args:
            neighborhood: Neighborhood name (e.g., Westgate, Harbor View)
        """
        row = neighborhoods[
            neighborhoods["neighborhood"].str.lower() == neighborhood.lower()
        ]
        if row.empty:
            return f"No profile found for neighborhood: {neighborhood}"
        return row.to_string(index=False)

    @tool
    def get_listing_velocity(region: str, property_type: str, bedrooms: int) -> str:
        """Get listing velocity metrics for a real estate segment in Ciudaty.

        Returns average days to offer, days to close, velocity score, and confidence.

        Args:
            region: Ciudaty region (west, north, south, east, center)
            property_type: Property type (apartment, house, studio)
            bedrooms: Number of bedrooms
        """
        v = velocity[
            (velocity["region"] == region)
            & (velocity["property_type"] == property_type)
            & (velocity["bedrooms"] == bedrooms)
        ]
        if v.empty:
            return "No velocity data available for this segment."
        return v.to_string(index=False)

    # ------------------------------------------------------------------
    # New in M04 — action tools (require analyst role, enforced by guardrail)
    # ------------------------------------------------------------------

    @tool
    def flag_segment_for_review(
        region: str,
        property_type: str,
        bedrooms: int,
        reason: str,
        runtime: ToolRuntime[UserContext],
    ) -> str:
        """Flag a Ciudaty segment for manual analyst review.

        Logs the flag with the caller's resolved identity.
        Requires analyst role — blocked for brokers and guests by guardrail.

        Args:
            region: Ciudaty region
            property_type: Property type (apartment, house, studio)
            bedrooms: Number of bedrooms
            reason: Reason for flagging the segment
        """
        user_id = runtime.context.user_id
        segment = f"{region}/{property_type}/{bedrooms}br"
        return (
            f"Segment '{segment}' flagged for review by {user_id}.\n"
            f"Reason: {reason}\n"
            f"Status: pending review"
        )

    @tool
    def create_segment_report(
        region: str,
        property_type: str,
        bedrooms: int,
        runtime: ToolRuntime[UserContext],
    ) -> str:
        """Create an internal segment report for a Ciudaty market segment.

        Aggregates demand, supply, and velocity data into a report stub.
        Requires analyst role — blocked for brokers and guests by guardrail.

        Args:
            region: Ciudaty region
            property_type: Property type (apartment, house, studio)
            bedrooms: Number of bedrooms
        """
        user_id = runtime.context.user_id
        segment = f"{region}/{property_type}/{bedrooms}br"

        d = demand[
            (demand["region"] == region)
            & (demand["property_type"] == property_type)
            & (demand["bedrooms"] == bedrooms)
        ]
        s = supply[
            (supply["region"] == region)
            & (supply["property_type"] == property_type)
            & (supply["bedrooms"] == bedrooms)
        ]
        if d.empty or s.empty:
            return f"No data available for segment {segment}."

        demand_score = float(d.iloc[0]["demand_score"])
        supply_score = float(s.iloc[0]["supply_score"])
        active_listings = int(s.iloc[0]["active_listings"])

        return (
            f"Internal segment report for {segment}\n"
            f"Created by: {user_id}\n"
            f"Demand score: {demand_score}\n"
            f"Supply score: {supply_score}\n"
            f"Active listings: {active_listings}\n"
            f"Status: draft"
        )

    # ------------------------------------------------------------------
    # New in M04 — data retrieval tools (sensitive fields redacted by guardrail)
    # ------------------------------------------------------------------

    @tool
    def list_neighborhoods(region: str = "") -> str:
        """List available Ciudaty neighborhoods, optionally filtered by region.

        Args:
            region: Ciudaty region to filter by (optional — omit for all neighborhoods)
        """
        if region:
            filtered = neighborhoods[neighborhoods["region"] == region.lower()]
        else:
            filtered = neighborhoods
        if filtered.empty:
            return f"No neighborhoods found for region: {region}"
        return filtered[["neighborhood", "region"]].to_string(index=False)

    @tool
    def get_supply_opportunities(region: str, property_type: str, bedrooms: int) -> str:
        """Get supply opportunities in the pipeline for a Ciudaty segment.

        Returns opportunity IDs, stage, estimated value, and context fields.
        Sensitive fields (internal_score, owner_contact, acquisition_strategy)
        are redacted by the guardrail before the model sees them.

        Args:
            region: Ciudaty region (west, north, south, east, center)
            property_type: Property type (apartment, house, studio)
            bedrooms: Number of bedrooms
        """
        rows = supply_opportunities[
            (supply_opportunities["region"] == region)
            & (supply_opportunities["property_type"] == property_type)
            & (supply_opportunities["bedrooms"] == bedrooms)
        ]
        if rows.empty:
            return "No supply opportunities found for this segment."
        safe_cols = [c for c in rows.columns if c not in {"internal_score", "owner_contact", "acquisition_strategy"}]
        return rows[safe_cols].to_string(index=False)

    @tool
    def get_listings(region: str, property_type: str, bedrooms: int) -> str:
        """Get active listings for a Ciudaty segment.

        Returns listing IDs, asking price, days on market, and context fields.
        Sensitive fields (seller_name, seller_motivation) are redacted by the guardrail.

        Args:
            region: Ciudaty region (west, north, south, east, center)
            property_type: Property type (apartment, house, studio)
            bedrooms: Number of bedrooms
        """
        rows = listings[
            (listings["region"] == region)
            & (listings["property_type"] == property_type)
            & (listings["bedrooms"] == bedrooms)
            & (listings["status"] == "active")
        ]
        if rows.empty:
            return "No active listings found for this segment."
        safe_cols = [c for c in rows.columns if c not in {"seller_name", "seller_motivation"}]
        return rows[safe_cols].to_string(index=False)

    @tool
    def get_sales(region: str, property_type: str, bedrooms: int) -> str:
        """Get recent sales for a Ciudaty segment.

        Returns sale IDs, final price, days to close, and context fields.
        Sensitive fields (commission_amount, agent_performance_score) are redacted.

        Args:
            region: Ciudaty region (west, north, south, east, center)
            property_type: Property type (apartment, house, studio)
            bedrooms: Number of bedrooms
        """
        rows = sales[
            (sales["region"] == region)
            & (sales["property_type"] == property_type)
            & (sales["bedrooms"] == bedrooms)
        ]
        if rows.empty:
            return "No sales data found for this segment."
        safe_cols = [c for c in rows.columns if c not in {"commission_amount", "agent_performance_score"}]
        return rows[safe_cols].to_string(index=False)

    # ------------------------------------------------------------------
    # New in M04 — mutation stubs (blocked by guardrail before body runs)
    # ------------------------------------------------------------------

    @tool
    def update_asking_price(listing_id: str, new_price: float) -> str:
        """Update the asking price for a listing."""
        return f"Updated asking price for {listing_id} to {new_price}."

    @tool
    def delete_lead(lead_id: str) -> str:
        """Delete a demand lead record."""
        return f"Deleted lead {lead_id}."

    @tool
    def overwrite_csv(filename: str, data: str) -> str:
        """Overwrite a CSV dataset with new data."""
        return f"Overwrote {filename}."

    @tool
    def add_record(table: str, record: str) -> str:
        """Add a new record to a dataset."""
        return f"Added record to {table}."

    return [
        get_demand_signals,
        get_supply_snapshot,
        get_neighborhood_profile,
        get_listing_velocity,
        flag_segment_for_review,
        create_segment_report,
        list_neighborhoods,
        get_supply_opportunities,
        get_listings,
        get_sales,
        update_asking_price,
        delete_lead,
        overwrite_csv,
        add_record,
    ]


def make_execute_python_tool(cfg: dict):
    """Build the execute_python tool, loading and pre-stripping sensitive columns."""
    listings = pd.read_csv(cfg["paths"]["listings_data"]).drop(
        columns=["seller_name", "seller_motivation"], errors="ignore"
    )
    supply_opps = pd.read_csv(cfg["paths"]["supply_opportunities_data"]).drop(
        columns=["owner_contact", "internal_score", "acquisition_strategy"], errors="ignore"
    )
    demand_leads = pd.read_csv(cfg["paths"]["demand_leads_data"]).drop(
        columns=["buyer_name", "credit_score_band", "pre_approval_status"], errors="ignore"
    )
    sales = pd.read_csv(cfg["paths"]["sales_data"]).drop(
        columns=["commission_amount", "agent_performance_score"], errors="ignore"
    )

    dataframes = {
        "listings": listings,
        "supply_opportunities": supply_opps,
        "demand_leads": demand_leads,
        "sales": sales,
    }

    @tool
    def execute_python(code: str) -> str:
        """Run pandas analysis code against RealThor datasets.

        Available DataFrames (already loaded, no imports needed):
          - listings: listing_id, region, neighborhood, property_type, bedrooms,
                      listing_type, asking_price, sqft, year_built, days_on_market, status
          - supply_opportunities: supply_opportunity_id, region, property_type, bedrooms,
                                  stage, estimated_value, listing_id
          - demand_leads: lead_id, region, property_type, bedrooms, source, status, sale_id
          - sales: sale_id, listing_id, lead_id, region, property_type, bedrooms,
                   final_price, days_to_close, agent_id

        Do not import pandas or any other module. Use print() for output.

        Args:
            code: Python code to execute. pandas (pd), math, and the DataFrames are
                  pre-injected. No imports are allowed.
        """
        ok, reason = validate_code(code)
        if not ok:
            return f"BLOCKED: {reason}"
        output, error = run_sandboxed(code, dataframes, timeout=cfg.get("sandbox", {}).get("timeout", 30))
        if error:
            return f"ERROR: {error}"
        return output or "(no output)"

    return execute_python
