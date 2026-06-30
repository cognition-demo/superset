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

"""
Tenant Provisioning Extension
==============================

Validates and orchestrates the creation of new isolated tenant workspaces on
the managed Superset SaaS platform.

When an enterprise customer signs a contract the customer-success team submits
a provisioning request through the internal admin API:

    POST /api/v1/internal/tenants/provision

This module owns the marshmallow schema that validates every provisioning
request before any infrastructure is created.  Bad data that slips through
validation can corrupt tenant routing tables or double-bill customers, so
validation is strict and a ``ValidationError`` propagates back to the caller
as an HTTP 422 response.

NOTE FOR REVIEWERS
------------------
This schema was written against **marshmallow 3.x**.  The ``@validates``
decorator in marshmallow 3 calls validator methods with a single positional
argument (the field value):

    def validate_foo(self, value: str) -> None: ...

Marshmallow 4 changed the calling convention: it now passes an additional
``data_key=`` keyword argument.  Any validator that does not accept
``**kwargs`` will raise at *runtime* (not at import time) when ``.load()``
is invoked:

    TypeError: validate_contract_end_date() got an unexpected keyword argument 'data_key'

The fix is a one-line change per validator: add ``**kwargs: Any`` to the
signature -- it absorbs the ``data_key`` keyword that marshmallow 4 now passes.
Root cause: the upstream sync bumps marshmallow 3.x -> 4.x in commit ``919bd35``
(``chore(deps): bump marshmallow from 3.26.2 to 4.3.0``, #39751), which also
adds this same ``**kwargs`` pattern across the core schemas
(``superset/reports/schemas.py``, ``superset/charts/schemas.py``, ...).  The
fork's custom validators were never updated.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional

from marshmallow import Schema, ValidationError, fields, validates

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_TIERS = frozenset({"starter", "professional", "enterprise"})

# AWS regions where tenant data can be stored (data-residency commitments).
VALID_REGIONS = frozenset(
    {
        "us-east-1",
        "us-west-2",
        "eu-west-1",
        "eu-central-1",
        "ap-southeast-1",
        "ap-northeast-1",
        "ca-central-1",
        "sa-east-1",
    }
)

# RFC 1123 hostname label rules, restricted to lowercase for URL safety.
# 3–63 chars, starts/ends with alphanumeric, internal hyphens allowed.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,61}[a-z0-9]$")

# Slugs that must not be assigned to any customer tenant.
_RESERVED_SLUGS = frozenset(
    {"admin", "api", "app", "internal", "superset", "system", "billing", "health"}
)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TenantProvisioningSchema(Schema):
    """Validate an incoming tenant provisioning request.

    All fields are required unless noted.  ``sso_domain`` is optional and
    may be supplied later via the tenant settings API.
    """

    # URL-safe identifier used in subdomain routing: <slug>.analytics.example.com
    organization_slug = fields.String(required=True)

    # Subscription tier governs feature flags and resource quotas.
    tier = fields.String(required=True)

    # Number of licensed user seats included in the contract.
    seats = fields.Integer(required=True, strict=True)

    # AWS region that must be honoured for all customer data (GDPR / CCPA).
    data_residency_region = fields.String(required=True)

    # ISO 8601 date on which the contract expires; used for renewal reminders
    # and automated workspace suspension.
    contract_end_date = fields.String(required=True)

    # Optional: primary SSO domain for auto-provisioning accounts via SAML/OIDC.
    sso_domain = fields.String(load_default=None, allow_none=True)

    # -----------------------------------------------------------------------
    # Validators — marshmallow 3 style (no **kwargs)
    # -----------------------------------------------------------------------
    # NOTE: marshmallow 4 passes data_key= as a keyword argument when calling
    # these methods.  Without **kwargs this raises at runtime:
    #   TypeError: validate_<name>() got an unexpected keyword argument 'data_key'
    # -----------------------------------------------------------------------

    @validates("organization_slug")
    def validate_organization_slug(self, value: str, **kwargs: Any) -> None:
        """Enforce RFC 1123 slug rules and block reserved names."""
        if not _SLUG_RE.match(value):
            raise ValidationError(
                "Slug must be 3-63 lowercase alphanumeric characters or hyphens "
                "and must not start or end with a hyphen."
            )
        if value in _RESERVED_SLUGS:
            raise ValidationError(
                f"'{value}' is a reserved organization slug and cannot be assigned "
                "to a customer tenant."
            )

    @validates("tier")
    def validate_tier(self, value: str, **kwargs: Any) -> None:
        """Reject unknown subscription tiers."""
        if value not in VALID_TIERS:
            raise ValidationError(
                f"Invalid tier '{value}'. "
                f"Must be one of: {sorted(VALID_TIERS)}."
            )

    @validates("data_residency_region")
    def validate_data_residency_region(self, value: str, **kwargs: Any) -> None:
        """Reject regions where we do not have a certified data centre."""
        if value not in VALID_REGIONS:
            raise ValidationError(
                f"Unsupported data residency region '{value}'. "
                f"Supported regions: {sorted(VALID_REGIONS)}."
            )

    @validates("contract_end_date")
    def validate_contract_end_date(self, value: str, **kwargs: Any) -> None:
        """Require an ISO 8601 date that is strictly in the future."""
        try:
            end_date = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValidationError(
                "contract_end_date must be an ISO 8601 date string (YYYY-MM-DD)."
            ) from exc
        if end_date <= date.today():
            raise ValidationError(
                "contract_end_date must be a future date; "
                f"received '{value}' which is not after today ({date.today()})."
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def provision_tenant(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate *payload* and return a normalised provisioning config.

    This is the entry point called by the internal REST handler:

        @bp.route("/tenants/provision", methods=["POST"])
        def create_tenant():
            return jsonify(provision_tenant(request.json)), 201

    Raises:
        marshmallow.ValidationError: if *payload* fails schema validation.
    """
    schema = TenantProvisioningSchema()
    # .load() triggers all @validates methods — this is where marshmallow 4
    # breaks if validators lack **kwargs.
    validated = schema.load(payload)

    # In production this would call into the tenant lifecycle manager:
    #   - Create an isolated PostgreSQL schema / RDS instance
    #   - Seed the Superset metadata DB for the new tenant
    #   - Register the tenant in the routing service
    #   - Create the initial admin user
    #   - Emit a TenantProvisioned event for billing
    return {
        "status": "provisioned",
        "tenant": {
            "slug": validated["organization_slug"],
            "tier": validated["tier"],
            "seats": validated["seats"],
            "region": validated["data_residency_region"],
            "contract_ends": validated["contract_end_date"],
            "sso_domain": validated.get("sso_domain"),
        },
    }
