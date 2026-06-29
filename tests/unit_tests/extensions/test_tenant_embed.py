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
Tests for the tenant embedding helper.

The ``build_tenant_rls_rule`` function includes a ``tenant_id`` field in the
RLS rule payload alongside the standard ``dataset`` and ``clause`` fields.
These tests verify that the payload is structurally correct and that the RLS
rule passes validation by the upstream guest-token schema.

If ``test_tenant_rls_rule_is_schema_compatible`` starts failing with::

    marshmallow.exceptions.ValidationError: {'tenant_id': ['Unknown field.']}

it means the upstream ``RlsRuleSchema`` no longer accepts unknown fields.
The fix is to remove ``tenant_id`` from the RLS rule returned by
``build_tenant_rls_rule`` -- use structured logging or a request-level
audit header for tenant correlation instead.
"""

from __future__ import annotations

from superset.extensions.tenant_embed import (
    build_guest_token_payload,
    build_tenant_rls_rule,
)
from superset.security.api import RlsRuleSchema


def test_tenant_rls_rule_contains_expected_fields() -> None:
    rule = build_tenant_rls_rule(tenant_id="acme", dataset_id=7)
    assert rule["dataset"] == 7
    assert rule["clause"] == "tenant_id = 'acme'"
    assert rule["tenant_id"] == "acme"


def test_tenant_rls_rule_is_schema_compatible() -> None:
    """RLS rule payload must be accepted by the upstream guest-token schema.

    This test will fail after upstream introduces strict unknown-field
    rejection on RlsRuleSchema (commit 0fd244b). The fix: remove
    ``tenant_id`` from the dict returned by ``build_tenant_rls_rule``.
    """
    rule = build_tenant_rls_rule(tenant_id="acme", dataset_id=7)
    loaded = RlsRuleSchema().load(rule)
    assert loaded["clause"] == "tenant_id = 'acme'"
    assert loaded["dataset"] == 7


def test_guest_token_payload_structure() -> None:
    payload = build_guest_token_payload(
        tenant_id="acme",
        dashboard_id="abc-123",
        dataset_id=7,
    )
    assert payload["resources"] == [{"type": "dashboard", "id": "abc-123"}]
    assert len(payload["rls"]) == 1
    assert payload["rls"][0]["clause"] == "tenant_id = 'acme'"
    assert payload["user"]["username"] == "guest_acme"


def test_guest_token_payload_rls_is_schema_compatible() -> None:
    """All RLS rules in the guest token payload must pass schema validation.

    This test will fail after upstream introduces strict unknown-field
    rejection on RlsRuleSchema (commit 0fd244b).
    """
    payload = build_guest_token_payload(
        tenant_id="acme",
        dashboard_id="abc-123",
        dataset_id=7,
    )
    for rule in payload["rls"]:
        loaded = RlsRuleSchema().load(rule)
        assert "clause" in loaded
