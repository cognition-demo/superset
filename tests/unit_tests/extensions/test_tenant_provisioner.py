# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Tests for the tenant provisioning schema."""

from __future__ import annotations

import pytest
from marshmallow import ValidationError

from superset.extensions.tenant_provisioner import (
    TenantProvisioningSchema,
    provision_tenant,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

VALID_PAYLOAD: dict = {
    "organization_slug": "acme-corp",
    "tier": "enterprise",
    "seats": 200,
    "data_residency_region": "us-east-1",
    "contract_end_date": "2027-12-31",
}


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def test_valid_payload_loads_successfully() -> None:
    """A fully valid provisioning request deserialises without error."""
    schema = TenantProvisioningSchema()
    result = schema.load(VALID_PAYLOAD)
    assert result["organization_slug"] == "acme-corp"
    assert result["tier"] == "enterprise"
    assert result["seats"] == 200
    assert result["data_residency_region"] == "us-east-1"
    assert result["contract_end_date"] == "2027-12-31"


def test_provision_tenant_returns_provisioned_status() -> None:
    """provision_tenant() returns a dict with status='provisioned' and tenant metadata."""
    result = provision_tenant(VALID_PAYLOAD)
    assert result["status"] == "provisioned"
    assert result["tenant"]["slug"] == "acme-corp"
    assert result["tenant"]["tier"] == "enterprise"
    assert result["tenant"]["seats"] == 200
    assert result["tenant"]["region"] == "us-east-1"


def test_starter_tier_payload_accepted() -> None:
    payload = {**VALID_PAYLOAD, "tier": "starter", "seats": 5}
    result = TenantProvisioningSchema().load(payload)
    assert result["tier"] == "starter"
    assert result["seats"] == 5


def test_professional_tier_payload_accepted() -> None:
    payload = {**VALID_PAYLOAD, "tier": "professional", "seats": 40}
    result = TenantProvisioningSchema().load(payload)
    assert result["tier"] == "professional"


def test_optional_sso_domain_absent_defaults_to_none() -> None:
    result = TenantProvisioningSchema().load(VALID_PAYLOAD)
    assert result.get("sso_domain") is None


def test_optional_sso_domain_present_is_preserved() -> None:
    payload = {**VALID_PAYLOAD, "sso_domain": "acme.com"}
    result = TenantProvisioningSchema().load(payload)
    assert result["sso_domain"] == "acme.com"


def test_eu_region_accepted() -> None:
    payload = {**VALID_PAYLOAD, "data_residency_region": "eu-central-1"}
    result = TenantProvisioningSchema().load(payload)
    assert result["data_residency_region"] == "eu-central-1"


def test_apac_region_accepted() -> None:
    payload = {**VALID_PAYLOAD, "data_residency_region": "ap-southeast-1"}
    result = TenantProvisioningSchema().load(payload)
    assert result["data_residency_region"] == "ap-southeast-1"


# ---------------------------------------------------------------------------
# Validation-error tests (slug)
# ---------------------------------------------------------------------------


def test_slug_with_uppercase_is_rejected() -> None:
    payload = {**VALID_PAYLOAD, "organization_slug": "AcmeCorp"}
    with pytest.raises(ValidationError) as exc_info:
        TenantProvisioningSchema().load(payload)
    assert "organization_slug" in exc_info.value.messages


def test_slug_starting_with_hyphen_is_rejected() -> None:
    payload = {**VALID_PAYLOAD, "organization_slug": "-acme"}
    with pytest.raises(ValidationError) as exc_info:
        TenantProvisioningSchema().load(payload)
    assert "organization_slug" in exc_info.value.messages


def test_slug_ending_with_hyphen_is_rejected() -> None:
    payload = {**VALID_PAYLOAD, "organization_slug": "acme-"}
    with pytest.raises(ValidationError) as exc_info:
        TenantProvisioningSchema().load(payload)
    assert "organization_slug" in exc_info.value.messages


def test_reserved_slug_admin_is_rejected() -> None:
    payload = {**VALID_PAYLOAD, "organization_slug": "admin"}
    with pytest.raises(ValidationError) as exc_info:
        TenantProvisioningSchema().load(payload)
    assert "organization_slug" in exc_info.value.messages


def test_reserved_slug_api_is_rejected() -> None:
    payload = {**VALID_PAYLOAD, "organization_slug": "api"}
    with pytest.raises(ValidationError) as exc_info:
        TenantProvisioningSchema().load(payload)
    assert "organization_slug" in exc_info.value.messages


# ---------------------------------------------------------------------------
# Validation-error tests (tier)
# ---------------------------------------------------------------------------


def test_unknown_tier_is_rejected() -> None:
    payload = {**VALID_PAYLOAD, "tier": "ultimate"}
    with pytest.raises(ValidationError) as exc_info:
        TenantProvisioningSchema().load(payload)
    assert "tier" in exc_info.value.messages


def test_empty_tier_is_rejected() -> None:
    payload = {**VALID_PAYLOAD, "tier": ""}
    with pytest.raises(ValidationError) as exc_info:
        TenantProvisioningSchema().load(payload)
    assert "tier" in exc_info.value.messages


# ---------------------------------------------------------------------------
# Validation-error tests (region)
# ---------------------------------------------------------------------------


def test_unsupported_region_is_rejected() -> None:
    payload = {**VALID_PAYLOAD, "data_residency_region": "xx-middle-7"}
    with pytest.raises(ValidationError) as exc_info:
        TenantProvisioningSchema().load(payload)
    assert "data_residency_region" in exc_info.value.messages


def test_made_up_region_is_rejected() -> None:
    payload = {**VALID_PAYLOAD, "data_residency_region": "us-east-99"}
    with pytest.raises(ValidationError) as exc_info:
        TenantProvisioningSchema().load(payload)
    assert "data_residency_region" in exc_info.value.messages


# ---------------------------------------------------------------------------
# Validation-error tests (contract_end_date)
# ---------------------------------------------------------------------------


def test_past_contract_date_is_rejected() -> None:
    payload = {**VALID_PAYLOAD, "contract_end_date": "2020-01-01"}
    with pytest.raises(ValidationError) as exc_info:
        TenantProvisioningSchema().load(payload)
    assert "contract_end_date" in exc_info.value.messages


def test_malformed_date_string_is_rejected() -> None:
    payload = {**VALID_PAYLOAD, "contract_end_date": "next-year"}
    with pytest.raises(ValidationError) as exc_info:
        TenantProvisioningSchema().load(payload)
    assert "contract_end_date" in exc_info.value.messages


def test_date_with_time_component_is_rejected() -> None:
    payload = {**VALID_PAYLOAD, "contract_end_date": "2027-12-31T00:00:00"}
    with pytest.raises(ValidationError) as exc_info:
        TenantProvisioningSchema().load(payload)
    assert "contract_end_date" in exc_info.value.messages


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------


def test_missing_slug_is_rejected() -> None:
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "organization_slug"}
    with pytest.raises(ValidationError) as exc_info:
        TenantProvisioningSchema().load(payload)
    assert "organization_slug" in exc_info.value.messages


def test_missing_tier_is_rejected() -> None:
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "tier"}
    with pytest.raises(ValidationError) as exc_info:
        TenantProvisioningSchema().load(payload)
    assert "tier" in exc_info.value.messages
