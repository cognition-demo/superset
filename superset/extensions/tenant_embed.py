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
Tenant-aware guest token generation for embedded analytics.

Builds Superset guest token payloads scoped to a specific tenant. The
``tenant_id`` field is included in each RLS rule alongside the SQL ``clause``
so that the token payload is self-describing: audit systems can correlate
tokens to tenants without decoding the clause text.

Usage::

    payload = build_guest_token_payload(
        tenant_id="acme",
        dashboard_id="abc123",
        dataset_id=42,
    )
    # POST /api/v1/security/guest_token/ with this payload
"""

from __future__ import annotations


def build_tenant_rls_rule(tenant_id: str, dataset_id: int) -> dict:
    """Return an RLS rule restricting a dataset to a single tenant.

    The ``tenant_id`` key is included alongside ``clause`` so that the token
    payload is self-describing: callers and audit systems can identify the
    tenant without decoding the SQL clause.
    """
    return {
        "dataset": dataset_id,
        "clause": f"tenant_id = '{tenant_id}'",
        "tenant_id": tenant_id,
    }


def build_guest_token_payload(
    tenant_id: str,
    dashboard_id: str,
    dataset_id: int,
) -> dict:
    """Build the full guest token request body for a tenant-scoped dashboard."""
    return {
        "user": {
            "username": f"guest_{tenant_id}",
            "first_name": "Guest",
            "last_name": tenant_id.capitalize(),
        },
        "resources": [{"type": "dashboard", "id": dashboard_id}],
        "rls": [build_tenant_rls_rule(tenant_id=tenant_id, dataset_id=dataset_id)],
    }
