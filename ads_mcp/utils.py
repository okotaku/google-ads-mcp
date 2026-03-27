#!/usr/bin/env python

# Copyright 2026 Google LLC.
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

"""Common utilities used by the MCP server."""

from typing import Any
import proto
import logging
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.v23.services.services.google_ads_service import (
    GoogleAdsServiceClient,
)

from google.ads.googleads.util import get_nested_attr
import google.auth
from ads_mcp.mcp_header_interceptor import MCPHeaderInterceptor
import os
import importlib.resources

# filename for generated field information used by search
_GAQL_FILENAME = "gaql_resources.txt"

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Read-only scope for Analytics Admin API and Analytics Data API.
_READ_ONLY_ADS_SCOPE = "https://www.googleapis.com/auth/adwords"


def _create_credentials() -> google.auth.credentials.Credentials:
    """Returns OAuth credentials from YAML file or Application Default Credentials."""
    credentials_path = os.environ.get("GOOGLE_ADS_CREDENTIALS")
    if credentials_path and os.path.isfile(credentials_path):
        client = GoogleAdsClient.load_from_storage(credentials_path)
        return client.credentials
    credentials, _ = google.auth.default(scopes=[_READ_ONLY_ADS_SCOPE])
    return credentials


def _get_developer_token() -> str:
    """Returns the developer token from YAML file or environment variable."""
    credentials_path = os.environ.get("GOOGLE_ADS_CREDENTIALS")
    if credentials_path and os.path.isfile(credentials_path):
        import yaml

        with open(credentials_path) as f:
            config = yaml.safe_load(f)
        token = config.get("developer_token")
        if token:
            return token
    dev_token = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN")
    if dev_token is None:
        raise ValueError(
            "GOOGLE_ADS_DEVELOPER_TOKEN environment variable not set."
        )
    return dev_token


def _get_login_customer_id() -> str | None:
    """Returns login customer id from YAML file or environment variable."""
    credentials_path = os.environ.get("GOOGLE_ADS_CREDENTIALS")
    if credentials_path and os.path.isfile(credentials_path):
        import yaml

        with open(credentials_path) as f:
            config = yaml.safe_load(f)
        login_id = config.get("login_customer_id")
        if login_id:
            return str(login_id)
    return os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")


def _get_googleads_client() -> GoogleAdsClient:
    # If GOOGLE_ADS_CREDENTIALS points to a valid YAML file, load everything
    # from it (refresh_token, client_id, client_secret, developer_token, etc.)
    # This avoids dependency on Application Default Credentials (ADC).
    credentials_path = os.environ.get("GOOGLE_ADS_CREDENTIALS")
    if credentials_path and os.path.isfile(credentials_path):
        return GoogleAdsClient.load_from_storage(credentials_path)

    args = {
        "credentials": _create_credentials(),
        "developer_token": _get_developer_token(),
        "use_proto_plus": True,
    }

    # If the login-customer-id is not set, avoid setting None.
    login_customer_id = _get_login_customer_id()

    if login_customer_id:
        args["login_customer_id"] = login_customer_id

    client = GoogleAdsClient(**args)

    return client


def get_googleads_service(serviceName: str):
    return _get_googleads_client().get_service(
        serviceName, interceptors=[MCPHeaderInterceptor()]
    )


def get_googleads_type(typeName: str):
    return _get_googleads_client().get_type(typeName)


def get_googleads_client():
    return _get_googleads_client()


def format_output_value(value: Any) -> Any:
    if isinstance(value, proto.Enum):
        return value.name
    else:
        return value


def format_output_row(row: proto.Message, attributes):
    return {
        attr: format_output_value(get_nested_attr(row, attr))
        for attr in attributes
    }


def get_gaql_resources_filepath():
    package_root = importlib.resources.files("ads_mcp")
    file_path = package_root.joinpath(_GAQL_FILENAME)
    return file_path
