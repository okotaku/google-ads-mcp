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

from ads_mcp.coordinator import mcp
import ads_mcp.utils as utils


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
    if status not in ("ENABLED", "PAUSED"):
        return f"Error: status must be 'ENABLED' or 'PAUSED', got '{status}'"

    client = utils.get_googleads_client()
    campaign_service = client.get_service("CampaignService")
    campaign_operation = client.get_type("CampaignOperation")

    campaign = campaign_operation.update
    campaign.resource_name = campaign_service.campaign_path(
        customer_id, campaign_id
    )
    campaign.status = getattr(
        client.enums.CampaignStatusEnum.CampaignStatus, status
    )

    field_mask = utils.get_field_mask(campaign_operation.update)
    campaign_operation.update_mask.CopyFrom(field_mask)

    response = campaign_service.mutate_campaigns(
        customer_id=customer_id, operations=[campaign_operation]
    )
    return f"Updated campaign {response.results[0].resource_name} to {status}"


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
    if status not in ("ENABLED", "PAUSED"):
        return f"Error: status must be 'ENABLED' or 'PAUSED', got '{status}'"

    client = utils.get_googleads_client()
    ad_group_service = client.get_service("AdGroupService")
    ad_group_operation = client.get_type("AdGroupOperation")

    ad_group = ad_group_operation.update
    ad_group.resource_name = ad_group_service.ad_group_path(
        customer_id, ad_group_id
    )
    ad_group.status = getattr(
        client.enums.AdGroupStatusEnum.AdGroupStatus, status
    )

    field_mask = utils.get_field_mask(ad_group_operation.update)
    ad_group_operation.update_mask.CopyFrom(field_mask)

    response = ad_group_service.mutate_ad_groups(
        customer_id=customer_id, operations=[ad_group_operation]
    )
    return f"Updated ad group {response.results[0].resource_name} to {status}"


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
    if status not in ("ENABLED", "PAUSED"):
        return f"Error: status must be 'ENABLED' or 'PAUSED', got '{status}'"

    client = utils.get_googleads_client()
    ad_group_ad_service = client.get_service("AdGroupAdService")
    ad_group_ad_operation = client.get_type("AdGroupAdOperation")

    ad_group_ad = ad_group_ad_operation.update
    ad_group_ad.resource_name = ad_group_ad_service.ad_group_ad_path(
        customer_id, ad_group_id, ad_id
    )
    ad_group_ad.status = getattr(
        client.enums.AdGroupAdStatusEnum.AdGroupAdStatus, status
    )

    field_mask = utils.get_field_mask(ad_group_ad_operation.update)
    ad_group_ad_operation.update_mask.CopyFrom(field_mask)

    response = ad_group_ad_service.mutate_ad_group_ads(
        customer_id=customer_id, operations=[ad_group_ad_operation]
    )
    return f"Updated ad {response.results[0].resource_name} to {status}"


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
        amount_micros: New budget amount in micros (e.g., 50000000 = $50).
    """
    client = utils.get_googleads_client()
    budget_service = client.get_service("CampaignBudgetService")
    budget_operation = client.get_type("CampaignBudgetOperation")

    budget = budget_operation.update
    budget.resource_name = budget_service.campaign_budget_path(
        customer_id, budget_id
    )
    budget.amount_micros = amount_micros

    field_mask = utils.get_field_mask(budget_operation.update)
    budget_operation.update_mask.CopyFrom(field_mask)

    response = budget_service.mutate_campaign_budgets(
        customer_id=customer_id, operations=[budget_operation]
    )
    return (
        f"Updated budget {response.results[0].resource_name} "
        f"to {amount_micros} micros "
        f"({amount_micros / 1_000_000:.2f} currency units)"
    )


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
        target_value_micros: Target CPA in micros (required for TARGET_CPA, e.g., 5000000 = $5).
        target_roas: Target ROAS as a float (required for TARGET_ROAS, e.g., 4.0 = 400% ROAS).
    """
    valid_strategies = (
        "TARGET_CPA",
        "TARGET_ROAS",
        "MAXIMIZE_CONVERSIONS",
        "MAXIMIZE_CONVERSION_VALUE",
    )
    if strategy_type not in valid_strategies:
        return f"Error: strategy_type must be one of {valid_strategies}, got '{strategy_type}'"

    client = utils.get_googleads_client()
    campaign_service = client.get_service("CampaignService")
    campaign_operation = client.get_type("CampaignOperation")

    campaign = campaign_operation.update
    campaign.resource_name = campaign_service.campaign_path(
        customer_id, campaign_id
    )

    if strategy_type == "TARGET_CPA":
        if target_value_micros is None:
            return "Error: target_value_micros is required for TARGET_CPA"
        campaign.target_cpa.target_cpa_micros = target_value_micros
    elif strategy_type == "TARGET_ROAS":
        if target_roas is None:
            return "Error: target_roas is required for TARGET_ROAS"
        campaign.target_roas.target_roas = target_roas
    elif strategy_type == "MAXIMIZE_CONVERSIONS":
        campaign.maximize_conversions.target_cpa_micros = (
            target_value_micros or 0
        )
    elif strategy_type == "MAXIMIZE_CONVERSION_VALUE":
        campaign.maximize_conversion_value.target_roas = target_roas or 0

    field_mask = utils.get_field_mask(campaign_operation.update)
    campaign_operation.update_mask.CopyFrom(field_mask)

    response = campaign_service.mutate_campaigns(
        customer_id=customer_id, operations=[campaign_operation]
    )
    return f"Updated campaign {response.results[0].resource_name} bidding strategy to {strategy_type}"


@mcp.tool()
def add_keywords(
    customer_id: str,
    ad_group_id: str,
    keywords: list[dict],
) -> str:
    """Add keywords to an ad group.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        ad_group_id: The ad group ID to add keywords to.
        keywords: List of keyword dicts, each with "text" (str) and "match_type" ("EXACT", "PHRASE", or "BROAD").
    """
    valid_match_types = ("EXACT", "PHRASE", "BROAD")
    client = utils.get_googleads_client()
    ad_group_criterion_service = client.get_service("AdGroupCriterionService")

    operations = []
    for kw in keywords:
        text = kw.get("text", "")
        match_type = kw.get("match_type", "BROAD")
        if match_type not in valid_match_types:
            return f"Error: match_type must be one of {valid_match_types}, got '{match_type}'"

        operation = client.get_type("AdGroupCriterionOperation")
        criterion = operation.create
        criterion.ad_group = ad_group_criterion_service.ad_group_path(
            customer_id, ad_group_id
        )
        criterion.keyword.text = text
        criterion.keyword.match_type = getattr(
            client.enums.KeywordMatchTypeEnum.KeywordMatchType, match_type
        )
        operations.append(operation)

    response = ad_group_criterion_service.mutate_ad_group_criteria(
        customer_id=customer_id, operations=operations
    )
    return f"Added {len(response.results)} keyword(s) to ad group {ad_group_id}"


@mcp.tool()
def add_negative_keywords(
    customer_id: str,
    campaign_id: str,
    keywords: list[dict],
) -> str:
    """Add negative keywords to a campaign.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        campaign_id: The campaign ID to add negative keywords to.
        keywords: List of keyword dicts, each with "text" (str) and "match_type" ("EXACT", "PHRASE", or "BROAD").
    """
    valid_match_types = ("EXACT", "PHRASE", "BROAD")
    client = utils.get_googleads_client()
    campaign_criterion_service = client.get_service(
        "CampaignCriterionService"
    )

    operations = []
    for kw in keywords:
        text = kw.get("text", "")
        match_type = kw.get("match_type", "BROAD")
        if match_type not in valid_match_types:
            return f"Error: match_type must be one of {valid_match_types}, got '{match_type}'"

        operation = client.get_type("CampaignCriterionOperation")
        criterion = operation.create
        criterion.campaign = campaign_criterion_service.campaign_path(
            customer_id, campaign_id
        )
        criterion.negative = True
        criterion.keyword.text = text
        criterion.keyword.match_type = getattr(
            client.enums.KeywordMatchTypeEnum.KeywordMatchType, match_type
        )
        operations.append(operation)

    response = campaign_criterion_service.mutate_campaign_criteria(
        customer_id=customer_id, operations=operations
    )
    return f"Added {len(response.results)} negative keyword(s) to campaign {campaign_id}"


@mcp.tool()
def create_campaign(
    customer_id: str,
    name: str,
    budget_amount_micros: int,
    advertising_channel_type: str = "SEARCH",
) -> str:
    """Create a new campaign in PAUSED state with a new daily budget.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        name: Campaign name.
        budget_amount_micros: Daily budget in micros (e.g., 50000000 = $50/day).
        advertising_channel_type: Channel type — "SEARCH", "DISPLAY", "SHOPPING", "VIDEO", etc. Defaults to "SEARCH".
    """
    client = utils.get_googleads_client()

    budget_service = client.get_service("CampaignBudgetService")
    budget_operation = client.get_type("CampaignBudgetOperation")
    budget = budget_operation.create
    budget.name = f"{name} Budget"
    budget.amount_micros = budget_amount_micros
    budget.delivery_method = (
        client.enums.BudgetDeliveryMethodEnum.BudgetDeliveryMethod.STANDARD
    )

    budget_response = budget_service.mutate_campaign_budgets(
        customer_id=customer_id, operations=[budget_operation]
    )
    budget_resource_name = budget_response.results[0].resource_name

    campaign_service = client.get_service("CampaignService")
    campaign_operation = client.get_type("CampaignOperation")
    campaign = campaign_operation.create
    campaign.name = name
    campaign.status = (
        client.enums.CampaignStatusEnum.CampaignStatus.PAUSED
    )
    campaign.advertising_channel_type = getattr(
        client.enums.AdvertisingChannelTypeEnum.AdvertisingChannelType,
        advertising_channel_type,
    )
    campaign.campaign_budget = budget_resource_name

    response = campaign_service.mutate_campaigns(
        customer_id=customer_id, operations=[campaign_operation]
    )
    return (
        f"Created campaign {response.results[0].resource_name} "
        f"(PAUSED, budget: {budget_amount_micros / 1_000_000:.2f}/day)"
    )


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
        cpc_bid_micros: CPC bid in micros (e.g., 1000000 = $1.00 CPC).
    """
    client = utils.get_googleads_client()
    campaign_service = client.get_service("CampaignService")
    ad_group_service = client.get_service("AdGroupService")
    ad_group_operation = client.get_type("AdGroupOperation")

    ad_group = ad_group_operation.create
    ad_group.name = name
    ad_group.campaign = campaign_service.campaign_path(
        customer_id, campaign_id
    )
    ad_group.status = (
        client.enums.AdGroupStatusEnum.AdGroupStatus.PAUSED
    )
    ad_group.cpc_bid_micros = cpc_bid_micros

    response = ad_group_service.mutate_ad_groups(
        customer_id=customer_id, operations=[ad_group_operation]
    )
    return (
        f"Created ad group {response.results[0].resource_name} "
        f"(PAUSED, CPC bid: {cpc_bid_micros / 1_000_000:.2f})"
    )


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
        cpc_bid_micros: New CPC bid in micros (e.g., 1500000 = $1.50 CPC).
    """
    client = utils.get_googleads_client()
    ad_group_service = client.get_service("AdGroupService")
    ad_group_operation = client.get_type("AdGroupOperation")

    ad_group = ad_group_operation.update
    ad_group.resource_name = ad_group_service.ad_group_path(
        customer_id, ad_group_id
    )
    ad_group.cpc_bid_micros = cpc_bid_micros

    field_mask = utils.get_field_mask(ad_group_operation.update)
    ad_group_operation.update_mask.CopyFrom(field_mask)

    response = ad_group_service.mutate_ad_groups(
        customer_id=customer_id, operations=[ad_group_operation]
    )
    return (
        f"Updated ad group {response.results[0].resource_name} "
        f"CPC bid to {cpc_bid_micros / 1_000_000:.2f}"
    )
