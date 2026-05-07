# Copyright 2025 Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tools for mutating Google Ads resources via the MCP server."""

import json
import os
from pathlib import Path

from pydantic import BaseModel

from google.ads.googleads.errors import GoogleAdsException
from google.protobuf import field_mask_pb2

from ads_mcp.coordinator import mcp
import ads_mcp.utils as utils


def _ensure_list(value: object) -> list:
    """Ensure value is a list, parsing JSON string if needed.

    Some MCP clients serialize list parameters as JSON strings.
    This function transparently handles both cases.
    """
    if isinstance(value, str):
        return json.loads(value)
    return value


class KeywordInput(BaseModel):
    """A keyword with text and match type."""

    text: str
    match_type: str = "BROAD"


class AdScheduleInput(BaseModel):
    """An ad schedule entry defining a day and time window."""

    day_of_week: str
    start_hour: int = 0
    start_minute: str = "ZERO"
    end_hour: int = 24
    end_minute: str = "ZERO"


def _validate_status(status: str) -> str | None:
    """Returns an error message if status is invalid, None otherwise."""
    if status not in ("ENABLED", "PAUSED"):
        return f"Error: status must be 'ENABLED' or 'PAUSED', got '{status}'"
    return None


def _format_google_ads_error(ex: GoogleAdsException) -> str:
    """Formats a GoogleAdsException into a readable error string."""
    errors = [e.message for e in ex.failure.errors]
    return f"Google Ads API error: {'; '.join(errors)}"


@mcp.tool()
def update_campaign_status(
    customer_id: str,
    campaign_id: str,
    status: str,
) -> str:
    """Update a campaign's status (ENABLED or PAUSED).

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        campaign_id: The campaign ID to update.
        status: New status — must be "ENABLED" or "PAUSED".
    """
    if err := _validate_status(status):
        return err

    # Proto-plus enum integer values: ENABLED=2, PAUSED=3
    _CAMPAIGN_STATUS = {"ENABLED": 2, "PAUSED": 3}

    try:
        client = utils.get_googleads_client()
        campaign_service = utils.get_googleads_service("CampaignService")
        campaign_operation = client.get_type("CampaignOperation")

        campaign = campaign_operation.update
        campaign.resource_name = campaign_service.campaign_path(
            customer_id, campaign_id
        )
        campaign.status = _CAMPAIGN_STATUS[status]
        campaign_operation.update_mask = field_mask_pb2.FieldMask(
            paths=["status"]
        )

        response = campaign_service.mutate_campaigns(
            customer_id=customer_id, operations=[campaign_operation]
        )
        return (
            f"Updated campaign {response.results[0].resource_name} to {status}"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
def update_campaign_asset_automation(
    customer_id: str,
    campaign_id: str,
    asset_automation_type: str,
    opt_out: bool,
) -> str:
    """Opt a Performance Max campaign in or out of a single AssetAutomationType.

    Replaces the legacy `Campaign.url_expansion_opt_out` field, which was
    removed in Google Ads API v22 (2025-10-15). To disable Final URL expansion,
    pass asset_automation_type="FINAL_URL_EXPANSION_TEXT_ASSET_AUTOMATION" and
    opt_out=True.

    The Campaign.asset_automation_settings field is a repeated message keyed by
    AssetAutomationType. This tool reads the current settings, upserts the
    requested type, and writes the full list back so unrelated automations are
    preserved.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        campaign_id: The campaign ID to update.
        asset_automation_type: AssetAutomationType enum name (e.g.
            "FINAL_URL_EXPANSION_TEXT_ASSET_AUTOMATION", "TEXT_ASSET_AUTOMATION").
        opt_out: True to set OPTED_OUT, False to set OPTED_IN.
    """
    try:
        client = utils.get_googleads_client()
        type_enum = client.enums.AssetAutomationTypeEnum
        status_enum = client.enums.AssetAutomationStatusEnum

        try:
            type_value = type_enum[asset_automation_type]
        except KeyError:
            valid = [
                m.name
                for m in type_enum
                if m.name not in ("UNSPECIFIED", "UNKNOWN")
            ]
            return (
                f"Error: invalid asset_automation_type "
                f"'{asset_automation_type}'. Valid values: {', '.join(valid)}"
            )

        target_status = (
            status_enum.OPTED_OUT if opt_out else status_enum.OPTED_IN
        )

        # Read current settings to preserve unrelated automations.
        ga_service = utils.get_googleads_service("GoogleAdsService")
        query = (
            "SELECT campaign.asset_automation_settings FROM campaign "
            f"WHERE campaign.id = {campaign_id}"
        )
        response = ga_service.search(customer_id=customer_id, query=query)
        existing = []
        for row in response:
            for s in row.campaign.asset_automation_settings:
                existing.append((s.asset_automation_type, s.asset_automation_status))

        # Upsert the target type.
        merged = [
            (t, s) for t, s in existing if t != type_value
        ]
        merged.append((type_value, target_status))

        campaign_service = utils.get_googleads_service("CampaignService")
        campaign_operation = client.get_type("CampaignOperation")
        campaign = campaign_operation.update
        campaign.resource_name = campaign_service.campaign_path(
            customer_id, campaign_id
        )
        setting_type = client.get_type("Campaign").AssetAutomationSetting
        for t, s in merged:
            entry = setting_type()
            entry.asset_automation_type = t
            entry.asset_automation_status = s
            campaign.asset_automation_settings.append(entry)
        campaign_operation.update_mask = field_mask_pb2.FieldMask(
            paths=["asset_automation_settings"]
        )

        mutate_response = campaign_service.mutate_campaigns(
            customer_id=customer_id, operations=[campaign_operation]
        )
        status_str = "OPTED_OUT" if opt_out else "OPTED_IN"
        return (
            f"Updated campaign {mutate_response.results[0].resource_name}: "
            f"{asset_automation_type} -> {status_str} "
            f"(total automation settings: {len(merged)})"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
def update_ad_group_status(
    customer_id: str,
    ad_group_id: str,
    status: str,
) -> str:
    """Update an ad group's status (ENABLED or PAUSED).

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        ad_group_id: The ad group ID to update.
        status: New status — must be "ENABLED" or "PAUSED".
    """
    # Proto-plus enum integer values: ENABLED=2, PAUSED=3
    _AD_GROUP_STATUS = {"ENABLED": 2, "PAUSED": 3}

    if err := _validate_status(status):
        return err

    try:
        client = utils.get_googleads_client()
        ad_group_service = utils.get_googleads_service("AdGroupService")
        ad_group_operation = client.get_type("AdGroupOperation")

        ad_group = ad_group_operation.update
        ad_group.resource_name = ad_group_service.ad_group_path(
            customer_id, ad_group_id
        )
        ad_group.status = _AD_GROUP_STATUS[status]
        ad_group_operation.update_mask = field_mask_pb2.FieldMask(
            paths=["status"]
        )

        response = ad_group_service.mutate_ad_groups(
            customer_id=customer_id, operations=[ad_group_operation]
        )
        return (
            f"Updated ad group {response.results[0].resource_name} to {status}"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
def update_ad_status(
    customer_id: str,
    ad_group_id: str,
    ad_id: str,
    status: str,
) -> str:
    """Update an ad's status (ENABLED or PAUSED).

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        ad_group_id: The ad group ID containing the ad.
        ad_id: The ad ID to update.
        status: New status — must be "ENABLED" or "PAUSED".
    """
    # Proto-plus enum integer values: ENABLED=2, PAUSED=3
    _AD_STATUS = {"ENABLED": 2, "PAUSED": 3}

    if err := _validate_status(status):
        return err

    try:
        client = utils.get_googleads_client()
        ad_group_ad_service = utils.get_googleads_service("AdGroupAdService")
        ad_group_ad_operation = client.get_type("AdGroupAdOperation")

        ad_group_ad = ad_group_ad_operation.update
        ad_group_ad.resource_name = ad_group_ad_service.ad_group_ad_path(
            customer_id, ad_group_id, ad_id
        )
        ad_group_ad.status = _AD_STATUS[status]
        ad_group_ad_operation.update_mask = field_mask_pb2.FieldMask(
            paths=["status"]
        )

        response = ad_group_ad_service.mutate_ad_group_ads(
            customer_id=customer_id, operations=[ad_group_ad_operation]
        )
        return f"Updated ad {response.results[0].resource_name} to {status}"
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
def update_campaign_budget(
    customer_id: str,
    budget_id: str,
    amount_micros: int,
) -> str:
    """Update a campaign budget amount. Amount is in micros (1 currency unit = 1,000,000 micros).

    For example, to set a daily budget of $50, pass amount_micros=50000000.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        budget_id: The campaign budget ID to update.
        amount_micros: New budget amount in micros (e.g., 50000000 = $50). Must be positive.
    """
    if amount_micros <= 0:
        return f"Error: amount_micros must be positive, got {amount_micros}"

    try:
        client = utils.get_googleads_client()
        budget_service = utils.get_googleads_service("CampaignBudgetService")
        budget_operation = client.get_type("CampaignBudgetOperation")

        budget = budget_operation.update
        budget.resource_name = budget_service.campaign_budget_path(
            customer_id, budget_id
        )
        budget.amount_micros = amount_micros
        budget_operation.update_mask = field_mask_pb2.FieldMask(
            paths=["amount_micros"]
        )

        response = budget_service.mutate_campaign_budgets(
            customer_id=customer_id, operations=[budget_operation]
        )
        return (
            f"Updated budget {response.results[0].resource_name} "
            f"to {amount_micros} micros "
            f"({amount_micros / 1_000_000:.2f} currency units)"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)


@mcp.tool()
def update_bidding_strategy(
    customer_id: str,
    campaign_id: str,
    strategy_type: str,
    target_value_micros: int | None = None,
    target_roas: float | None = None,
) -> str:
    """Update a campaign's bidding strategy.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        campaign_id: The campaign ID to update.
        strategy_type: One of "TARGET_CPA", "TARGET_ROAS", "MAXIMIZE_CONVERSIONS", "MAXIMIZE_CONVERSION_VALUE".
        target_value_micros: Target CPA in micros (required for TARGET_CPA, e.g., 5000000 = $5). Optional for MAXIMIZE_CONVERSIONS (uncapped if omitted).
        target_roas: Target ROAS as a float (required for TARGET_ROAS, e.g., 4.0 = 400% ROAS). Optional for MAXIMIZE_CONVERSION_VALUE (uncapped if omitted).
    """
    valid_strategies = (
        "TARGET_CPA",
        "TARGET_ROAS",
        "MAXIMIZE_CONVERSIONS",
        "MAXIMIZE_CONVERSION_VALUE",
    )
    if strategy_type not in valid_strategies:
        return f"Error: strategy_type must be one of {valid_strategies}, got '{strategy_type}'"

    try:
        client = utils.get_googleads_client()
        campaign_service = utils.get_googleads_service("CampaignService")
        campaign_operation = client.get_type("CampaignOperation")

        campaign = campaign_operation.update
        campaign.resource_name = campaign_service.campaign_path(
            customer_id, campaign_id
        )

        if strategy_type == "TARGET_CPA":
            if target_value_micros is None:
                return "Error: target_value_micros is required for TARGET_CPA"
            if target_value_micros <= 0:
                return f"Error: target_value_micros must be positive, got {target_value_micros}"
            campaign.target_cpa.target_cpa_micros = target_value_micros
            mask_path = "target_cpa"
        elif strategy_type == "TARGET_ROAS":
            if target_roas is None:
                return "Error: target_roas is required for TARGET_ROAS"
            if target_roas <= 0:
                return f"Error: target_roas must be positive, got {target_roas}"
            campaign.target_roas.target_roas = target_roas
            mask_path = "target_roas"
        elif strategy_type == "MAXIMIZE_CONVERSIONS":
            campaign.maximize_conversions.target_cpa_micros = (
                target_value_micros or 0
            )
            mask_path = "maximize_conversions.target_cpa_micros"
        elif strategy_type == "MAXIMIZE_CONVERSION_VALUE":
            campaign.maximize_conversion_value.target_roas = target_roas or 0
            mask_path = "maximize_conversion_value.target_roas"

        campaign_operation.update_mask = field_mask_pb2.FieldMask(
            paths=[mask_path]
        )

        response = campaign_service.mutate_campaigns(
            customer_id=customer_id, operations=[campaign_operation]
        )
        return f"Updated campaign {response.results[0].resource_name} bidding strategy to {strategy_type}"
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)


@mcp.tool()
def add_keywords(
    customer_id: str,
    ad_group_id: str,
    keywords: list[KeywordInput],
) -> str:
    """Add keywords to an ad group.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        ad_group_id: The ad group ID to add keywords to.
        keywords: List of keyword objects, each with "text" (str) and "match_type" ("EXACT", "PHRASE", or "BROAD").
    """
    keywords = [
        KeywordInput(**kw) if isinstance(kw, dict) else kw
        for kw in _ensure_list(keywords)
    ]
    valid_match_types = ("EXACT", "PHRASE", "BROAD")
    client = utils.get_googleads_client()
    ad_group_criterion_service = utils.get_googleads_service(
        "AdGroupCriterionService"
    )

    operations = []
    for i, kw in enumerate(keywords):
        if not kw.text:
            return f"Error: keyword text must not be empty (index {i})"
        if kw.match_type not in valid_match_types:
            return f"Error: match_type must be one of {valid_match_types}, got '{kw.match_type}' (index {i})"

        operation = client.get_type("AdGroupCriterionOperation")
        criterion = operation.create
        criterion.ad_group = ad_group_criterion_service.ad_group_path(
            customer_id, ad_group_id
        )
        criterion.keyword.text = kw.text
        # Proto-plus enum integer values: EXACT=2, PHRASE=3, BROAD=4
        _MATCH_TYPE = {"EXACT": 2, "PHRASE": 3, "BROAD": 4}
        criterion.keyword.match_type = _MATCH_TYPE[kw.match_type]
        operations.append(operation)

    try:
        response = ad_group_criterion_service.mutate_ad_group_criteria(
            customer_id=customer_id, operations=operations
        )
        return f"Added {len(response.results)} keyword(s) to ad group {ad_group_id}"
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)


@mcp.tool()
def add_negative_keywords(
    customer_id: str,
    campaign_id: str,
    keywords: list[KeywordInput],
) -> str:
    """Add negative keywords to a campaign.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        campaign_id: The campaign ID to add negative keywords to.
        keywords: List of keyword objects, each with "text" (str) and "match_type" ("EXACT", "PHRASE", or "BROAD").
    """
    keywords = [
        KeywordInput(**kw) if isinstance(kw, dict) else kw
        for kw in _ensure_list(keywords)
    ]
    valid_match_types = ("EXACT", "PHRASE", "BROAD")
    client = utils.get_googleads_client()
    campaign_criterion_service = utils.get_googleads_service(
        "CampaignCriterionService"
    )

    operations = []
    for i, kw in enumerate(keywords):
        if not kw.text:
            return f"Error: keyword text must not be empty (index {i})"
        if kw.match_type not in valid_match_types:
            return f"Error: match_type must be one of {valid_match_types}, got '{kw.match_type}' (index {i})"

        operation = client.get_type("CampaignCriterionOperation")
        criterion = operation.create
        criterion.campaign = campaign_criterion_service.campaign_path(
            customer_id, campaign_id
        )
        criterion.negative = True
        criterion.keyword.text = kw.text
        # Proto-plus enum integer values: EXACT=2, PHRASE=3, BROAD=4
        _MATCH_TYPE = {"EXACT": 2, "PHRASE": 3, "BROAD": 4}
        criterion.keyword.match_type = _MATCH_TYPE[kw.match_type]
        operations.append(operation)

    try:
        response = campaign_criterion_service.mutate_campaign_criteria(
            customer_id=customer_id, operations=operations
        )
        return f"Added {len(response.results)} negative keyword(s) to campaign {campaign_id}"
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)


# Proto-plus enum integer values for advertising channel types
_CHANNEL_TYPE = {
    "SEARCH": 2,
    "DISPLAY": 3,
    "SHOPPING": 4,
    "VIDEO": 6,
    "MULTI_CHANNEL": 7,
    "LOCAL": 8,
    "SMART": 9,
    "PERFORMANCE_MAX": 10,
    "DEMAND_GEN": 13,
    "TRAVEL": 15,
}


@mcp.tool()
def create_campaign(
    customer_id: str,
    name: str,
    budget_amount_micros: int,
    advertising_channel_type: str = "SEARCH",
) -> str:
    """Create a new campaign in PAUSED state with a new daily budget.

    The campaign is created with MAXIMIZE_CONVERSIONS bidding (uncapped)
    and standard network settings (Google Search + Search Partners).

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        name: Campaign name.
        budget_amount_micros: Daily budget in micros (e.g., 50000000 = $50/day). Must be positive.
        advertising_channel_type: Channel type — "SEARCH", "DISPLAY", "SHOPPING", "VIDEO", etc. Defaults to "SEARCH".
    """
    if budget_amount_micros <= 0:
        return (
            f"Error: budget_amount_micros must be positive, "
            f"got {budget_amount_micros}"
        )
    if advertising_channel_type not in _CHANNEL_TYPE:
        return (
            f"Error: advertising_channel_type must be one of "
            f"{list(_CHANNEL_TYPE.keys())}, "
            f"got '{advertising_channel_type}'"
        )

    try:
        client = utils.get_googleads_client()

        # Create a non-shared budget
        budget_service = utils.get_googleads_service("CampaignBudgetService")
        budget_operation = client.get_type("CampaignBudgetOperation")
        budget = budget_operation.create
        budget.name = f"{name} Budget"
        budget.amount_micros = budget_amount_micros
        budget.delivery_method = 2  # STANDARD
        budget.explicitly_shared = False

        budget_response = budget_service.mutate_campaign_budgets(
            customer_id=customer_id, operations=[budget_operation]
        )
        budget_resource_name = budget_response.results[0].resource_name

        # Create campaign
        campaign_service = utils.get_googleads_service("CampaignService")
        campaign_operation = client.get_type("CampaignOperation")
        campaign = campaign_operation.create
        campaign.name = name
        campaign.status = 3  # PAUSED
        campaign.advertising_channel_type = _CHANNEL_TYPE[
            advertising_channel_type
        ]
        campaign.campaign_budget = budget_resource_name
        campaign.maximize_conversions.target_cpa_micros = 0
        campaign.network_settings.target_google_search = True
        campaign.network_settings.target_search_network = True
        campaign.network_settings.target_content_network = False
        campaign.contains_eu_political_advertising = 3  # NO

        response = campaign_service.mutate_campaigns(
            customer_id=customer_id, operations=[campaign_operation]
        )
        return (
            f"Created campaign {response.results[0].resource_name} "
            f"(PAUSED, budget: "
            f"{budget_amount_micros / 1_000_000:.2f}/day)"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)


@mcp.tool()
def create_ad_group(
    customer_id: str,
    campaign_id: str,
    name: str,
    cpc_bid_micros: int,
) -> str:
    """Create a new ad group in PAUSED state.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        campaign_id: The campaign ID to create the ad group in.
        name: Ad group name.
        cpc_bid_micros: CPC bid in micros (e.g., 1000000 = $1.00 CPC). Must be positive.
    """
    if cpc_bid_micros <= 0:
        return f"Error: cpc_bid_micros must be positive, got {cpc_bid_micros}"

    try:
        client = utils.get_googleads_client()
        campaign_service = utils.get_googleads_service("CampaignService")
        ad_group_service = utils.get_googleads_service("AdGroupService")
        ad_group_operation = client.get_type("AdGroupOperation")

        ad_group = ad_group_operation.create
        ad_group.name = name
        ad_group.campaign = campaign_service.campaign_path(
            customer_id, campaign_id
        )
        ad_group.status = 3  # PAUSED
        ad_group.cpc_bid_micros = cpc_bid_micros

        response = ad_group_service.mutate_ad_groups(
            customer_id=customer_id, operations=[ad_group_operation]
        )
        return (
            f"Created ad group {response.results[0].resource_name} "
            f"(PAUSED, CPC bid: {cpc_bid_micros / 1_000_000:.2f})"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)


@mcp.tool()
def update_ad_final_url(
    customer_id: str,
    ad_id: str,
    final_url: str,
) -> str:
    """Update an ad's final URL.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        ad_id: The ad ID to update.
        final_url: New final URL (e.g., "https://example.com/landing").
    """
    if not final_url:
        return "Error: final_url must not be empty"

    try:
        client = utils.get_googleads_client()
        ad_service = utils.get_googleads_service("AdService")
        ad_operation = client.get_type("AdOperation")

        ad = ad_operation.update
        ad.resource_name = ad_service.ad_path(customer_id, ad_id)
        ad.final_urls.append(final_url)
        ad_operation.update_mask = field_mask_pb2.FieldMask(
            paths=["final_urls"]
        )

        response = ad_service.mutate_ads(
            customer_id=customer_id, operations=[ad_operation]
        )
        return (
            f"Updated ad {response.results[0].resource_name} "
            f"final URL to {final_url}"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)


@mcp.tool()
def update_asset_group_final_url(
    customer_id: str,
    asset_group_id: str,
    final_url: str,
) -> str:
    """Update a Performance Max asset group's final URL.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        asset_group_id: The asset group ID to update.
        final_url: New final URL (e.g., "https://example.com/landing").
    """
    if not final_url:
        return "Error: final_url must not be empty"

    try:
        client = utils.get_googleads_client()
        asset_group_service = utils.get_googleads_service("AssetGroupService")
        asset_group_operation = client.get_type("AssetGroupOperation")

        asset_group = asset_group_operation.update
        asset_group.resource_name = asset_group_service.asset_group_path(
            customer_id, asset_group_id
        )
        asset_group.final_urls.append(final_url)
        asset_group_operation.update_mask = field_mask_pb2.FieldMask(
            paths=["final_urls"]
        )

        response = asset_group_service.mutate_asset_groups(
            customer_id=customer_id, operations=[asset_group_operation]
        )
        return (
            f"Updated asset group {response.results[0].resource_name} "
            f"final URL to {final_url}"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)


@mcp.tool()
def update_asset_group_status(
    customer_id: str,
    asset_group_id: str,
    status: str,
) -> str:
    """Update a Performance Max asset group's status (ENABLED or PAUSED).

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        asset_group_id: The asset group ID to update.
        status: New status — must be "ENABLED" or "PAUSED".
    """
    if err := _validate_status(status):
        return err

    # Proto-plus enum integer values: ENABLED=2, PAUSED=3
    _ASSET_GROUP_STATUS = {"ENABLED": 2, "PAUSED": 3}

    try:
        client = utils.get_googleads_client()
        asset_group_service = utils.get_googleads_service("AssetGroupService")
        asset_group_operation = client.get_type("AssetGroupOperation")

        asset_group = asset_group_operation.update
        asset_group.resource_name = asset_group_service.asset_group_path(
            customer_id, asset_group_id
        )
        asset_group.status = _ASSET_GROUP_STATUS[status]
        asset_group_operation.update_mask = field_mask_pb2.FieldMask(
            paths=["status"]
        )

        response = asset_group_service.mutate_asset_groups(
            customer_id=customer_id, operations=[asset_group_operation]
        )
        return (
            f"Updated asset group {response.results[0].resource_name} "
            f"to {status}"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
def update_campaign_conversion_goal(
    customer_id: str,
    campaign_id: str,
    category: str,
    origin: str,
    biddable: bool,
) -> str:
    """Update a campaign conversion goal's biddable setting.

    Controls whether the campaign's automated bidding strategy optimizes
    for this conversion goal.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        campaign_id: The campaign ID.
        category: Conversion goal category (e.g., "SIGNUP", "PURCHASE", "SUBMIT_LEAD_FORM").
        origin: Conversion goal origin (e.g., "WEBSITE", "GOOGLE_HOSTED").
        biddable: Whether the bidding strategy should optimize for this goal.
    """
    try:
        client = utils.get_googleads_client()
        service = utils.get_googleads_service("CampaignConversionGoalService")
        operation = client.get_type("CampaignConversionGoalOperation")

        goal = operation.update
        goal.resource_name = service.campaign_conversion_goal_path(
            customer_id, campaign_id, category, origin
        )
        goal.biddable = biddable
        operation.update_mask = field_mask_pb2.FieldMask(paths=["biddable"])

        response = service.mutate_campaign_conversion_goals(
            customer_id=customer_id, operations=[operation]
        )
        return (
            f"Updated {response.results[0].resource_name} "
            f"biddable to {biddable}"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
def add_shared_set_negative_keywords(
    customer_id: str,
    shared_set_id: str,
    keywords: list[KeywordInput],
) -> str:
    """Add negative keywords to a shared negative keyword list.

    Shared sets are account-level negative keyword lists that can be linked
    to multiple campaigns. Use the ``search`` tool with resource
    ``shared_set`` (conditions: ``shared_set.type = 'NEGATIVE_KEYWORDS'``)
    to find shared set IDs and names.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        shared_set_id: The shared set ID to add negative keywords to.
        keywords: List of keyword objects, each with "text" (str) and "match_type" ("EXACT", "PHRASE", or "BROAD").
    """
    keywords = [
        KeywordInput(**kw) if isinstance(kw, dict) else kw
        for kw in _ensure_list(keywords)
    ]
    valid_match_types = ("EXACT", "PHRASE", "BROAD")
    client = utils.get_googleads_client()
    shared_criterion_service = utils.get_googleads_service(
        "SharedCriterionService"
    )

    # Proto-plus enum integer values: EXACT=2, PHRASE=3, BROAD=4
    _MATCH_TYPE = {"EXACT": 2, "PHRASE": 3, "BROAD": 4}

    operations = []
    for i, kw in enumerate(keywords):
        if not kw.text:
            return f"Error: keyword text must not be empty (index {i})"
        if kw.match_type not in valid_match_types:
            return f"Error: match_type must be one of {valid_match_types}, got '{kw.match_type}' (index {i})"

        operation = client.get_type("SharedCriterionOperation")
        criterion = operation.create
        criterion.shared_set = (
            f"customers/{customer_id}/sharedSets/{shared_set_id}"
        )
        criterion.keyword.text = kw.text
        criterion.keyword.match_type = _MATCH_TYPE[kw.match_type]
        operations.append(operation)

    try:
        response = shared_criterion_service.mutate_shared_criteria(
            customer_id=customer_id, operations=operations
        )
        return (
            f"Added {len(response.results)} negative keyword(s) "
            f"to shared set {shared_set_id}"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)


@mcp.tool()
def link_shared_set_to_campaign(
    customer_id: str,
    campaign_id: str,
    shared_set_id: str,
) -> str:
    """Link a shared set (e.g., negative keyword list) to a campaign.

    Use the ``search`` tool with resource ``shared_set`` to find
    shared set IDs and names.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        campaign_id: The campaign ID to link the shared set to.
        shared_set_id: The shared set ID to link.
    """
    try:
        client = utils.get_googleads_client()
        service = utils.get_googleads_service("CampaignSharedSetService")
        operation = client.get_type("CampaignSharedSetOperation")

        campaign_shared_set = operation.create
        campaign_shared_set.campaign = (
            f"customers/{customer_id}/campaigns/{campaign_id}"
        )
        campaign_shared_set.shared_set = (
            f"customers/{customer_id}/sharedSets/{shared_set_id}"
        )

        response = service.mutate_campaign_shared_sets(
            customer_id=customer_id, operations=[operation]
        )
        return (
            f"Linked shared set {shared_set_id} to campaign "
            f"{campaign_id}: "
            f"{response.results[0].resource_name}"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
def create_responsive_search_ad(
    customer_id: str,
    ad_group_id: str,
    headlines: list[str],
    descriptions: list[str],
    final_url: str,
    path1: str = "",
    path2: str = "",
) -> str:
    """Create a new responsive search ad (RSA) in PAUSED state.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        ad_group_id: The ad group ID to create the ad in.
        headlines: List of headline texts (min 3, max 15). Each headline max 30 characters.
        descriptions: List of description texts (min 2, max 4). Each description max 90 characters.
        final_url: The landing page URL (e.g., "https://example.com/landing").
        path1: Optional display URL path 1 (max 15 characters, e.g., "products").
        path2: Optional display URL path 2 (max 15 characters, e.g., "shoes"). Only used if path1 is set.
    """
    if len(headlines) < 3 or len(headlines) > 15:
        return f"Error: headlines must have 3-15 items, got {len(headlines)}"
    if len(descriptions) < 2 or len(descriptions) > 4:
        return (
            f"Error: descriptions must have 2-4 items, got {len(descriptions)}"
        )
    if not final_url:
        return "Error: final_url must not be empty"

    try:
        client = utils.get_googleads_client()
        ad_group_service = utils.get_googleads_service("AdGroupService")
        ad_group_ad_service = utils.get_googleads_service("AdGroupAdService")
        operation = client.get_type("AdGroupAdOperation")

        ad_group_ad = operation.create
        ad_group_ad.ad_group = ad_group_service.ad_group_path(
            customer_id, ad_group_id
        )
        ad_group_ad.status = 3  # PAUSED

        rsa = ad_group_ad.ad.responsive_search_ad
        for text in headlines:
            headline = client.get_type("AdTextAsset")
            headline.text = text
            rsa.headlines.append(headline)

        for text in descriptions:
            description = client.get_type("AdTextAsset")
            description.text = text
            rsa.descriptions.append(description)

        ad_group_ad.ad.final_urls.append(final_url)

        if path1:
            rsa.path1 = path1
        if path1 and path2:
            rsa.path2 = path2

        response = ad_group_ad_service.mutate_ad_group_ads(
            customer_id=customer_id, operations=[operation]
        )
        return (
            f"Created responsive search ad {response.results[0].resource_name} "
            f"(PAUSED, {len(headlines)} headlines, {len(descriptions)} descriptions)"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
def update_ad_group_bid(
    customer_id: str,
    ad_group_id: str,
    cpc_bid_micros: int,
) -> str:
    """Update an ad group's CPC bid amount.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        ad_group_id: The ad group ID to update.
        cpc_bid_micros: New CPC bid in micros (e.g., 1500000 = $1.50 CPC). Must be positive.
    """
    if cpc_bid_micros <= 0:
        return f"Error: cpc_bid_micros must be positive, got {cpc_bid_micros}"

    try:
        client = utils.get_googleads_client()
        ad_group_service = utils.get_googleads_service("AdGroupService")
        ad_group_operation = client.get_type("AdGroupOperation")

        ad_group = ad_group_operation.update
        ad_group.resource_name = ad_group_service.ad_group_path(
            customer_id, ad_group_id
        )
        ad_group.cpc_bid_micros = cpc_bid_micros
        ad_group_operation.update_mask = field_mask_pb2.FieldMask(
            paths=["cpc_bid_micros"]
        )

        response = ad_group_service.mutate_ad_groups(
            customer_id=customer_id, operations=[ad_group_operation]
        )
        return (
            f"Updated ad group {response.results[0].resource_name} "
            f"CPC bid to {cpc_bid_micros / 1_000_000:.2f}"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)


# Day of week enum integer values
_DAY_OF_WEEK = {
    "MONDAY": 2,
    "TUESDAY": 3,
    "WEDNESDAY": 4,
    "THURSDAY": 5,
    "FRIDAY": 6,
    "SATURDAY": 7,
    "SUNDAY": 8,
}

# Minute of hour enum integer values
_MINUTE_OF_HOUR = {
    "ZERO": 2,
    "FIFTEEN": 3,
    "THIRTY": 4,
    "FORTY_FIVE": 5,
}


@mcp.tool()
def set_ad_schedule(
    customer_id: str,
    campaign_id: str,
    schedules: list[AdScheduleInput],
) -> str:
    """Set ad schedules for a campaign. This replaces all existing ad schedules.

    Each schedule defines a day and time window when ads should run.
    To run ads Monday-Friday all day, pass 5 schedule entries (one per day)
    with start_hour=0, end_hour=24.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        campaign_id: The campaign ID to set schedules for.
        schedules: List of schedule objects, each with:
            - "day_of_week": "MONDAY"|"TUESDAY"|"WEDNESDAY"|"THURSDAY"|"FRIDAY"|"SATURDAY"|"SUNDAY"
            - "start_hour": 0-23
            - "start_minute": "ZERO"|"FIFTEEN"|"THIRTY"|"FORTY_FIVE" (default: "ZERO")
            - "end_hour": 0-24 (24 means end of day)
            - "end_minute": "ZERO"|"FIFTEEN"|"THIRTY"|"FORTY_FIVE" (default: "ZERO")
    """
    schedules = [
        AdScheduleInput(**s) if isinstance(s, dict) else s
        for s in _ensure_list(schedules)
    ]
    # Use a single client instance for all operations to avoid
    # proto-plus type incompatibility between separate client instances.
    client = utils.get_googleads_client()
    campaign_criterion_service = client.get_service("CampaignCriterionService")

    # Step 1: Remove existing ad schedules
    ga_service = client.get_service("GoogleAdsService")
    query = (
        f"SELECT campaign_criterion.resource_name, "
        f"campaign_criterion.type "
        f"FROM campaign_criterion "
        f"WHERE campaign.id = {campaign_id} "
        f"AND campaign_criterion.type = 'AD_SCHEDULE'"
    )
    try:
        response = ga_service.search(customer_id=customer_id, query=query)
        remove_operations = []
        for row in response:
            operation = client.get_type("CampaignCriterionOperation")
            operation.remove = row.campaign_criterion.resource_name
            remove_operations.append(operation)

        if remove_operations:
            campaign_criterion_service.mutate_campaign_criteria(
                customer_id=customer_id, operations=remove_operations
            )
    except GoogleAdsException as ex:
        return (
            f"Error removing existing schedules: {_format_google_ads_error(ex)}"
        )

    # Step 2: Add new schedules
    if not schedules:
        return "Removed all ad schedules (ads will run all days/times)"

    create_operations = []
    for i, sched in enumerate(schedules):
        if sched.day_of_week not in _DAY_OF_WEEK:
            return (
                f"Error: day_of_week must be one of "
                f"{list(_DAY_OF_WEEK.keys())}, got '{sched.day_of_week}' (index {i})"
            )

        if sched.start_minute not in _MINUTE_OF_HOUR:
            return f"Error: invalid start_minute '{sched.start_minute}' (index {i})"
        if sched.end_minute not in _MINUTE_OF_HOUR:
            return f"Error: invalid end_minute '{sched.end_minute}' (index {i})"

        operation = client.get_type("CampaignCriterionOperation")
        criterion = operation.create
        criterion.campaign = campaign_criterion_service.campaign_path(
            customer_id, campaign_id
        )
        criterion.ad_schedule.day_of_week = _DAY_OF_WEEK[sched.day_of_week]
        criterion.ad_schedule.start_hour = sched.start_hour
        criterion.ad_schedule.start_minute = _MINUTE_OF_HOUR[sched.start_minute]
        criterion.ad_schedule.end_hour = sched.end_hour
        criterion.ad_schedule.end_minute = _MINUTE_OF_HOUR[sched.end_minute]
        create_operations.append(operation)

    try:
        response = campaign_criterion_service.mutate_campaign_criteria(
            customer_id=customer_id, operations=create_operations
        )
        days = [s.day_of_week for s in schedules]
        return (
            f"Set {len(response.results)} ad schedule(s) for campaign "
            f"{campaign_id}: {', '.join(days)}"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)


# ---------------------------------------------------------------------------
# Performance Max (P-MAX) tools
# ---------------------------------------------------------------------------

# Proto-plus enum integer values for asset field types used by P-MAX.
# Reference: AssetFieldTypeEnum.AssetFieldType
_ASSET_FIELD_TYPE = {
    "HEADLINE": 2,
    "DESCRIPTION": 3,
    "MARKETING_IMAGE": 5,
    "YOUTUBE_VIDEO": 7,
    "PROMOTION": 10,
    "CALLOUT": 11,
    "STRUCTURED_SNIPPET": 12,
    "SITELINK": 13,
    "MOBILE_APP": 14,
    "HOTEL_CALLOUT": 15,
    "CALL": 16,
    "LONG_HEADLINE": 17,
    "BUSINESS_NAME": 18,
    "SQUARE_MARKETING_IMAGE": 19,
    "PORTRAIT_MARKETING_IMAGE": 20,
    "LOGO": 21,
    "LANDSCAPE_LOGO": 22,
    "PRICE": 24,
}

_TEXT_ASSET_FIELD_TYPES = {
    "HEADLINE",
    "LONG_HEADLINE",
    "DESCRIPTION",
    "BUSINESS_NAME",
    "CALLOUT",
}

_IMAGE_ASSET_FIELD_TYPES = {
    "MARKETING_IMAGE",
    "SQUARE_MARKETING_IMAGE",
    "PORTRAIT_MARKETING_IMAGE",
    "LOGO",
    "LANDSCAPE_LOGO",
}


class AssetLink(BaseModel):
    """An asset to link to an asset group with a specific field type."""

    asset_id: str
    field_type: str


def _read_image_bytes(image_path: str) -> bytes:
    """Read raw image bytes from a local file path.

    Raises:
        FileNotFoundError: When the path does not point to an existing file.
        ValueError: When the file is empty.
    """
    path = Path(os.path.expanduser(image_path))
    if not path.is_file():
        raise FileNotFoundError(f"image not found: {image_path}")
    data = path.read_bytes()
    if not data:
        raise ValueError(f"image is empty: {image_path}")
    return data


@mcp.tool()
def create_pmax_campaign(
    customer_id: str,
    name: str,
    budget_amount_micros: int,
    brand_guidelines_enabled: bool = False,
    campaign_assets: list[AssetLink] | None = None,
) -> str:
    """Create a new Performance Max campaign in PAUSED state with a new daily budget.

    Performance Max campaigns auto-target Search, Display, YouTube, Discover,
    Gmail, and Maps using the supplied asset group(s). The campaign is created
    with MAXIMIZE_CONVERSIONS bidding (uncapped). Asset groups must be created
    separately via ``create_asset_group`` and populated via ``upload_image_asset``,
    ``create_text_asset``, and ``link_assets_to_asset_group``.

    Brand Guidelines:
      When ``brand_guidelines_enabled`` is True, the campaign requires at least
      one BUSINESS_NAME and one LOGO linked at the campaign level
      (CampaignAsset). Pass them via ``campaign_assets`` so they are attached
      atomically with the campaign creation (the API rejects either side if
      the other is missing). Note: ``brand_guidelines_enabled`` cannot be
      changed after creation, so set it correctly here.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        name: Campaign name.
        budget_amount_micros: Daily budget in micros (e.g., 3000000000 = ¥3,000/day). Must be positive.
        brand_guidelines_enabled: Whether to enable Brand Guidelines on the campaign. Defaults to False.
        campaign_assets: List of {"asset_id": "...", "field_type": "..."} entries
            to attach as CampaignAsset entries atomically with the campaign.
            Required when ``brand_guidelines_enabled`` is True (at least one
            BUSINESS_NAME and one LOGO).
    """
    if budget_amount_micros <= 0:
        return (
            f"Error: budget_amount_micros must be positive, "
            f"got {budget_amount_micros}"
        )

    asset_links = (
        [
            AssetLink(**a) if isinstance(a, dict) else a
            for a in _ensure_list(campaign_assets)
        ]
        if campaign_assets
        else []
    )
    valid_field_types = set(_ASSET_FIELD_TYPE.keys()) | {"YOUTUBE_VIDEO"}
    for i, link in enumerate(asset_links):
        if link.field_type not in valid_field_types:
            return (
                f"Error: campaign_assets[{i}].field_type must be one of "
                f"{sorted(valid_field_types)}, got '{link.field_type}'"
            )
        if not link.asset_id:
            return f"Error: campaign_assets[{i}].asset_id must not be empty"

    try:
        client = utils.get_googleads_client()

        budget_service = utils.get_googleads_service("CampaignBudgetService")
        budget_operation = client.get_type("CampaignBudgetOperation")
        budget = budget_operation.create
        budget.name = f"{name} Budget"
        budget.amount_micros = budget_amount_micros
        budget.delivery_method = 2  # STANDARD
        # P-MAX requires a non-shared budget.
        budget.explicitly_shared = False

        budget_response = budget_service.mutate_campaign_budgets(
            customer_id=customer_id, operations=[budget_operation]
        )
        budget_resource_name = budget_response.results[0].resource_name

        # Without campaign_assets, fall back to the simple single-mutate path.
        if not asset_links:
            campaign_service = utils.get_googleads_service("CampaignService")
            campaign_operation = client.get_type("CampaignOperation")
            campaign = campaign_operation.create
            campaign.name = name
            campaign.status = 3  # PAUSED
            campaign.advertising_channel_type = 10  # PERFORMANCE_MAX
            campaign.campaign_budget = budget_resource_name
            campaign.maximize_conversions.target_cpa_micros = 0
            campaign.contains_eu_political_advertising = 3  # NO
            campaign.brand_guidelines_enabled = brand_guidelines_enabled

            response = campaign_service.mutate_campaigns(
                customer_id=customer_id, operations=[campaign_operation]
            )
            return (
                f"Created P-MAX campaign {response.results[0].resource_name} "
                f"(PAUSED, budget: "
                f"{budget_amount_micros / 1_000_000:.2f}/day)"
            )

        # Atomic mutate: Campaign + CampaignAssets in one transaction
        # using a temporary resource name (-1) for the campaign.
        ga_service = utils.get_googleads_service("GoogleAdsService")
        temp_campaign_resource = f"customers/{customer_id}/campaigns/-1"

        mutate_operations = []

        camp_mutate = client.get_type("MutateOperation")
        campaign = camp_mutate.campaign_operation.create
        campaign.resource_name = temp_campaign_resource
        campaign.name = name
        campaign.status = 3  # PAUSED
        campaign.advertising_channel_type = 10  # PERFORMANCE_MAX
        campaign.campaign_budget = budget_resource_name
        campaign.maximize_conversions.target_cpa_micros = 0
        campaign.contains_eu_political_advertising = 3  # NO
        campaign.brand_guidelines_enabled = brand_guidelines_enabled
        mutate_operations.append(camp_mutate)

        for link in asset_links:
            link_mutate = client.get_type("MutateOperation")
            ca = link_mutate.campaign_asset_operation.create
            ca.campaign = temp_campaign_resource
            ca.asset = f"customers/{customer_id}/assets/{link.asset_id}"
            ca.field_type = _ASSET_FIELD_TYPE[link.field_type]
            mutate_operations.append(link_mutate)

        response = ga_service.mutate(
            customer_id=customer_id, mutate_operations=mutate_operations
        )
        camp_resource = response.mutate_operation_responses[
            0
        ].campaign_result.resource_name
        return (
            f"Created P-MAX campaign {camp_resource} "
            f"(PAUSED, budget: {budget_amount_micros / 1_000_000:.2f}/day, "
            f"brand_guidelines={brand_guidelines_enabled}, "
            f"linked {len(asset_links)} CampaignAsset(s))"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
def update_campaign_brand_guidelines(
    customer_id: str,
    campaign_id: str,
    enabled: bool,
) -> str:
    """Toggle Brand Guidelines on a Performance Max campaign.

    When ``enabled`` is True, the campaign will require at least one
    BUSINESS_NAME and one LOGO linked at the campaign level
    (CampaignAsset). Use ``link_assets_to_campaign`` BEFORE enabling if
    those assets are not already attached as CampaignAsset entries.

    When ``enabled`` is False, BUSINESS_NAME and LOGO must instead be
    attached as AssetGroupAsset entries on every asset group.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        campaign_id: The P-MAX campaign ID.
        enabled: True to enable Brand Guidelines, False to disable.
    """
    try:
        client = utils.get_googleads_client()
        campaign_service = utils.get_googleads_service("CampaignService")
        campaign_operation = client.get_type("CampaignOperation")

        campaign = campaign_operation.update
        campaign.resource_name = campaign_service.campaign_path(
            customer_id, campaign_id
        )
        campaign.brand_guidelines_enabled = enabled
        campaign_operation.update_mask = field_mask_pb2.FieldMask(
            paths=["brand_guidelines_enabled"]
        )

        response = campaign_service.mutate_campaigns(
            customer_id=customer_id, operations=[campaign_operation]
        )
        return (
            f"Updated campaign {response.results[0].resource_name} "
            f"brand_guidelines_enabled to {enabled}"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
def create_asset_group(
    customer_id: str,
    campaign_id: str,
    name: str,
    final_url: str,
    assets: list[AssetLink] | None = None,
) -> str:
    """Create a new Performance Max asset group in PAUSED state.

    The asset group is the container that holds all creative assets (images,
    text, logos) for a P-MAX campaign.

    Google Ads requires the asset group and its required assets to be created
    in a single atomic ``mutate`` call. Pass the full set of pre-created assets
    (created via ``upload_image_asset`` and ``create_text_asset``) via the
    ``assets`` parameter so the asset group is created with all required slots
    filled. Additional assets can be attached later via
    ``link_assets_to_asset_group``.

    Minimum required assets for a valid P-MAX asset group:
      - 3 HEADLINE
      - 1 LONG_HEADLINE
      - 2 DESCRIPTION
      - 1 BUSINESS_NAME
      - 1 MARKETING_IMAGE
      - 1 SQUARE_MARKETING_IMAGE
      - 1 LOGO

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        campaign_id: The P-MAX campaign ID.
        name: Asset group name.
        final_url: Landing page URL (e.g., "https://example.com/landing").
        assets: List of {"asset_id": "...", "field_type": "..."} entries to
            link to the asset group at creation time. Optional; if omitted,
            the asset group will be created without any linked assets and
            the API will reject it unless the minimum requirements are met.
    """
    if not final_url:
        return "Error: final_url must not be empty"

    asset_links = (
        [
            AssetLink(**a) if isinstance(a, dict) else a
            for a in _ensure_list(assets)
        ]
        if assets
        else []
    )
    valid_field_types = set(_ASSET_FIELD_TYPE.keys()) | {"YOUTUBE_VIDEO"}
    for i, link in enumerate(asset_links):
        if link.field_type not in valid_field_types:
            return (
                f"Error: assets[{i}].field_type must be one of "
                f"{sorted(valid_field_types)}, got '{link.field_type}'"
            )
        if not link.asset_id:
            return f"Error: assets[{i}].asset_id must not be empty"

    try:
        client = utils.get_googleads_client()
        campaign_service = utils.get_googleads_service("CampaignService")
        asset_group_service = utils.get_googleads_service("AssetGroupService")

        # When no assets to link, use the simple single-mutate path.
        if not asset_links:
            asset_group_operation = client.get_type("AssetGroupOperation")
            asset_group = asset_group_operation.create
            asset_group.name = name
            asset_group.campaign = campaign_service.campaign_path(
                customer_id, campaign_id
            )
            asset_group.status = 3  # PAUSED
            asset_group.final_urls.append(final_url)

            response = asset_group_service.mutate_asset_groups(
                customer_id=customer_id, operations=[asset_group_operation]
            )
            return (
                f"Created asset group {response.results[0].resource_name} "
                f"(PAUSED, final_url: {final_url}, no assets linked)"
            )

        # Atomic mutate: AssetGroup + AssetGroupAssets in one transaction
        # using a temporary resource name (-1) for the asset group.
        ga_service = utils.get_googleads_service("GoogleAdsService")
        temp_asset_group_resource = f"customers/{customer_id}/assetGroups/-1"

        mutate_operations = []

        ag_mutate = client.get_type("MutateOperation")
        asset_group = ag_mutate.asset_group_operation.create
        asset_group.resource_name = temp_asset_group_resource
        asset_group.name = name
        asset_group.campaign = campaign_service.campaign_path(
            customer_id, campaign_id
        )
        asset_group.status = 3  # PAUSED
        asset_group.final_urls.append(final_url)
        mutate_operations.append(ag_mutate)

        for link in asset_links:
            link_mutate = client.get_type("MutateOperation")
            aga = link_mutate.asset_group_asset_operation.create
            aga.asset_group = temp_asset_group_resource
            aga.asset = f"customers/{customer_id}/assets/{link.asset_id}"
            aga.field_type = _ASSET_FIELD_TYPE[link.field_type]
            mutate_operations.append(link_mutate)

        response = ga_service.mutate(
            customer_id=customer_id, mutate_operations=mutate_operations
        )
        # First result is the AssetGroup; remaining are AssetGroupAssets.
        ag_resource = response.mutate_operation_responses[
            0
        ].asset_group_result.resource_name
        return (
            f"Created asset group {ag_resource} "
            f"(PAUSED, final_url: {final_url}, "
            f"linked {len(asset_links)} asset(s))"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
def upload_image_asset(
    customer_id: str,
    name: str,
    image_path: str,
) -> str:
    """Upload a local image file as a Google Ads image asset.

    The returned asset ID can be linked to a P-MAX asset group via
    ``link_assets_to_asset_group`` with an image field type
    (MARKETING_IMAGE / SQUARE_MARKETING_IMAGE / PORTRAIT_MARKETING_IMAGE /
    LOGO / LANDSCAPE_LOGO).

    Recommended dimensions:
      - MARKETING_IMAGE (1.91:1): 1200x628 or larger
      - SQUARE_MARKETING_IMAGE (1:1): 1200x1200 or larger
      - PORTRAIT_MARKETING_IMAGE (4:5): 960x1200 or larger
      - LOGO (1:1): 1200x1200, recommended >= 128x128
      - LANDSCAPE_LOGO (4:1): 1200x300

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        name: Asset display name (used to identify the asset in the UI).
        image_path: Absolute or ``~``-expanded local file path (PNG/JPG).
    """
    if not name:
        return "Error: name must not be empty"
    try:
        image_bytes = _read_image_bytes(image_path)
    except (FileNotFoundError, ValueError) as ex:
        return f"Error: {ex}"

    try:
        client = utils.get_googleads_client()
        asset_service = utils.get_googleads_service("AssetService")
        asset_operation = client.get_type("AssetOperation")

        asset = asset_operation.create
        asset.name = name
        asset.type_ = 4  # IMAGE
        asset.image_asset.data = image_bytes

        response = asset_service.mutate_assets(
            customer_id=customer_id, operations=[asset_operation]
        )
        resource_name = response.results[0].resource_name
        asset_id = resource_name.split("/")[-1]
        return (
            f"Uploaded image asset {resource_name} "
            f"(asset_id: {asset_id}, bytes: {len(image_bytes)})"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
def create_text_asset(
    customer_id: str,
    text: str,
) -> str:
    """Create a reusable text asset (used for HEADLINE / LONG_HEADLINE / DESCRIPTION / BUSINESS_NAME / CALLOUT).

    The returned asset ID can be linked to a P-MAX asset group via
    ``link_assets_to_asset_group`` with the appropriate text field type.
    Length limits depend on field type at link time:
      - HEADLINE: max 30 chars (display width)
      - LONG_HEADLINE: max 90 chars
      - DESCRIPTION: max 90 chars (or 60 for the short slot)
      - BUSINESS_NAME: max 25 chars
      - CALLOUT: max 25 chars

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        text: The asset text.
    """
    if not text:
        return "Error: text must not be empty"

    try:
        client = utils.get_googleads_client()
        asset_service = utils.get_googleads_service("AssetService")
        asset_operation = client.get_type("AssetOperation")

        asset = asset_operation.create
        asset.type_ = 5  # TEXT
        asset.text_asset.text = text

        response = asset_service.mutate_assets(
            customer_id=customer_id, operations=[asset_operation]
        )
        resource_name = response.results[0].resource_name
        asset_id = resource_name.split("/")[-1]
        return (
            f"Created text asset {resource_name} "
            f"(asset_id: {asset_id}, text: {text!r})"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
def link_assets_to_campaign(
    customer_id: str,
    campaign_id: str,
    assets: list[AssetLink],
) -> str:
    """Link existing assets to a campaign with a field type (CampaignAsset).

    Required for Performance Max campaigns with Brand Guidelines enabled,
    which mandate at least one BUSINESS_NAME and one LOGO linked at the
    campaign level (CampaignAsset, not AssetGroupAsset).

    Field type must be one of:
      Image: LOGO, LANDSCAPE_LOGO
      Text:  BUSINESS_NAME

    Other field types are technically accepted by the API, but Brand Guidelines
    only consumes BUSINESS_NAME and LOGO/LANDSCAPE_LOGO at the campaign level.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        campaign_id: The campaign ID to link assets to.
        assets: List of {"asset_id": "...", "field_type": "..."} entries.
    """
    assets = [
        AssetLink(**a) if isinstance(a, dict) else a
        for a in _ensure_list(assets)
    ]
    if not assets:
        return "Error: assets must contain at least one entry"

    valid_field_types = set(_ASSET_FIELD_TYPE.keys()) | {"YOUTUBE_VIDEO"}
    for i, link in enumerate(assets):
        if link.field_type not in valid_field_types:
            return (
                f"Error: field_type must be one of "
                f"{sorted(valid_field_types)}, "
                f"got '{link.field_type}' (index {i})"
            )
        if not link.asset_id:
            return f"Error: asset_id must not be empty (index {i})"

    try:
        client = utils.get_googleads_client()
        service = utils.get_googleads_service("CampaignAssetService")

        operations = []
        for link in assets:
            operation = client.get_type("CampaignAssetOperation")
            campaign_asset = operation.create
            campaign_asset.campaign = (
                f"customers/{customer_id}/campaigns/{campaign_id}"
            )
            campaign_asset.asset = (
                f"customers/{customer_id}/assets/{link.asset_id}"
            )
            campaign_asset.field_type = _ASSET_FIELD_TYPE[link.field_type]
            operations.append(operation)

        response = service.mutate_campaign_assets(
            customer_id=customer_id, operations=operations
        )
        return (
            f"Linked {len(response.results)} asset(s) to campaign "
            f"{campaign_id}"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
def link_assets_to_asset_group(
    customer_id: str,
    asset_group_id: str,
    assets: list[AssetLink],
) -> str:
    """Link existing assets to a Performance Max asset group with a field type.

    Each entry attaches a single asset (created by ``upload_image_asset`` or
    ``create_text_asset``) to the asset group as the given creative slot.

    Field type must be one of:
      Image: MARKETING_IMAGE, SQUARE_MARKETING_IMAGE, PORTRAIT_MARKETING_IMAGE,
             LOGO, LANDSCAPE_LOGO
      Text:  HEADLINE, LONG_HEADLINE, DESCRIPTION, BUSINESS_NAME, CALLOUT
      Video: YOUTUBE_VIDEO

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        asset_group_id: The asset group ID to link assets to.
        assets: List of {"asset_id": "...", "field_type": "..."} entries.
    """
    assets = [
        AssetLink(**a) if isinstance(a, dict) else a
        for a in _ensure_list(assets)
    ]
    if not assets:
        return "Error: assets must contain at least one entry"

    valid_field_types = set(_ASSET_FIELD_TYPE.keys()) | {"YOUTUBE_VIDEO"}
    for i, link in enumerate(assets):
        if link.field_type not in valid_field_types:
            return (
                f"Error: field_type must be one of "
                f"{sorted(valid_field_types)}, "
                f"got '{link.field_type}' (index {i})"
            )
        if not link.asset_id:
            return f"Error: asset_id must not be empty (index {i})"

    try:
        client = utils.get_googleads_client()
        service = utils.get_googleads_service("AssetGroupAssetService")

        operations = []
        for link in assets:
            operation = client.get_type("AssetGroupAssetOperation")
            asset_group_asset = operation.create
            asset_group_asset.asset_group = (
                f"customers/{customer_id}/assetGroups/{asset_group_id}"
            )
            asset_group_asset.asset = (
                f"customers/{customer_id}/assets/{link.asset_id}"
            )
            asset_group_asset.field_type = _ASSET_FIELD_TYPE[link.field_type]
            operations.append(operation)

        response = service.mutate_asset_group_assets(
            customer_id=customer_id, operations=operations
        )
        return (
            f"Linked {len(response.results)} asset(s) to asset group "
            f"{asset_group_id}"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
def add_campaign_language(
    customer_id: str,
    campaign_id: str,
    language_constant_ids: list[str],
) -> str:
    """Add language targeting to a campaign.

    Common language constant IDs:
      - 1000: English
      - 1005: Japanese
      - 1017: Chinese (Simplified)
      - 1018: Chinese (Traditional)
      - 1021: Korean

    Reference: https://developers.google.com/google-ads/api/data/codes-formats#languages

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        campaign_id: The campaign ID to add language targeting to.
        language_constant_ids: List of language constant IDs (e.g., ["1005"] for Japanese).
    """
    language_constant_ids = _ensure_list(language_constant_ids)
    if not language_constant_ids:
        return "Error: language_constant_ids must not be empty"

    try:
        client = utils.get_googleads_client()
        service = utils.get_googleads_service("CampaignCriterionService")

        operations = []
        for lang_id in language_constant_ids:
            operation = client.get_type("CampaignCriterionOperation")
            criterion = operation.create
            criterion.campaign = (
                f"customers/{customer_id}/campaigns/{campaign_id}"
            )
            criterion.language.language_constant = (
                f"languageConstants/{lang_id}"
            )
            operations.append(operation)

        response = service.mutate_campaign_criteria(
            customer_id=customer_id, operations=operations
        )
        return (
            f"Added {len(response.results)} language target(s) to campaign "
            f"{campaign_id}"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
def add_campaign_location(
    customer_id: str,
    campaign_id: str,
    geo_target_constant_ids: list[str],
) -> str:
    """Add location (geo) targeting to a campaign.

    Common geo target constant IDs:
      - 2392: Japan
      - 2840: United States
      - 2826: United Kingdom
      - 2156: China
      - 2410: South Korea

    Reference: https://developers.google.com/google-ads/api/data/geotargets

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        campaign_id: The campaign ID to add location targeting to.
        geo_target_constant_ids: List of geo target constant IDs (e.g., ["2392"] for Japan).
    """
    geo_target_constant_ids = _ensure_list(geo_target_constant_ids)
    if not geo_target_constant_ids:
        return "Error: geo_target_constant_ids must not be empty"

    try:
        client = utils.get_googleads_client()
        service = utils.get_googleads_service("CampaignCriterionService")

        operations = []
        for geo_id in geo_target_constant_ids:
            operation = client.get_type("CampaignCriterionOperation")
            criterion = operation.create
            criterion.campaign = (
                f"customers/{customer_id}/campaigns/{campaign_id}"
            )
            criterion.location.geo_target_constant = (
                f"geoTargetConstants/{geo_id}"
            )
            operations.append(operation)

        response = service.mutate_campaign_criteria(
            customer_id=customer_id, operations=operations
        )
        return (
            f"Added {len(response.results)} location target(s) to campaign "
            f"{campaign_id}"
        )
    except GoogleAdsException as ex:
        return _format_google_ads_error(ex)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"
