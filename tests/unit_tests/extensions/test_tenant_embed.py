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

The ``build_tenant_rls_rule`` function returns only schema-compliant fields
(``dataset`` and ``clause``).  Tenant correlation is handled via Python
logging rather than embedding extra fields in the RLS rule dict.  These tests
verify structural correctness and schema compatibility with the upstream
strict ``RlsRuleSchema``.
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
    assert "tenant_id" not in rule


def test_tenant_rls_rule_is_schema_compatible() -> None:
    """RLS rule payload must be accepted by the strict upstream schema."""
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
    """All RLS rules in the guest token payload must pass strict schema validation."""
    payload = build_guest_token_payload(
        tenant_id="acme",
        dashboard_id="abc-123",
        dataset_id=7,
    )
    for rule in payload["rls"]:
        loaded = RlsRuleSchema().load(rule)
        assert "clause" in loaded
