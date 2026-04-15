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

from pydantic import BaseModel

from google.ads.googleads.errors import GoogleAdsException
from google.protobuf import field_mask_pb2

from ads_mcp.coordinator import mcp
import ads_mcp.utils as utils


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
        criterion.keyword.match_type = getattr(
            client.enums.KeywordMatchTypeEnum.KeywordMatchType,
            kw.match_type,
        )
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
        criterion.keyword.match_type = getattr(
            client.enums.KeywordMatchTypeEnum.KeywordMatchType,
            kw.match_type,
        )
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
