# Demo Scenario: Dual Breaking Change — Nightly Sync Breaks Two Custom Extensions

## Overview

One nightly upstream sync pulls in 135+ commits including two independent breaking changes:

1. `919bd35` — marshmallow 3→4 bump: breaks `@validates` validator signatures in `TenantProvisioningSchema`
2. `0fd244b` — RLS strict validation: breaks `build_tenant_rls_rule` which passes `tenant_id` as an extra field

Both custom features fail simultaneously. Devin must triage, identify two independent root causes, and fix both in one PR.

## Custom Features

### 1. Tenant Provisioner (`superset/extensions/tenant_provisioner.py`)

This fork extends Apache Superset for a **managed multi-tenant analytics SaaS platform**. Enterprise
customers each get an isolated Superset workspace (separate metadata database, separate
row-level-security context, subdomain routing). When a sales contract is signed, the customer-success
team provisions the new tenant through an internal admin API:

```
POST /api/v1/internal/tenants/provision
{
  "organization_slug": "acme-corp",
  "tier": "enterprise",
  "seats": 200,
  "data_residency_region": "eu-central-1",
  "contract_end_date": "2027-12-31",
  "sso_domain": "acme.com"
}
```

The request is validated by `TenantProvisioningSchema` before any infrastructure is created. Strict
validation matters: a bad slug corrupts DNS routing tables; a bad region violates GDPR/CCPA
data-residency commitments; a duplicate call double-bills the customer.

**Business stakes**: Every failed provisioning call is a blocked enterprise onboarding. At
$50k–$500k ACV per enterprise deal, even a one-day outage of this endpoint is a material revenue
incident.

### 2. Embedded Analytics (`superset/extensions/tenant_embed.py`)

The platform also exposes **white-label embedded dashboards** — customers embed Superset charts
directly in their own product UIs. Access is gated via short-lived Superset guest tokens, each
scoped to a specific tenant through a Row-Level Security (RLS) rule.

The helper `build_tenant_rls_rule` generates the RLS payload sent to:

```
POST /api/v1/security/guest_token/
```

The team added a `tenant_id` field to each RLS rule dict alongside the standard `clause` and
`dataset` fields. This makes the token payload self-describing: audit logs and token introspection
tools can identify the originating tenant without decoding the SQL clause text. It was an intentional
design choice driven by the security team's audit requirements.

**Business stakes**: Broken guest token issuance means embedded dashboards return 401/403 for every
end-customer iframe load. Revenue-generating product features go dark for all customers simultaneously.

## The Upstream Changes

### Change 1: marshmallow 4 bump (`919bd35`)

- **PR title**: `chore(deps): bump marshmallow from 3.26.2 to 4.3.0 (#39751)`
- **Authors**: dependabot[bot], Evan (Preset), Amin Ghadersohi

Marshmallow 4 changed the internal calling convention for `@validates` decorated methods. In
marshmallow 3, the decorator called the method with a single positional argument (the deserialized
field value):

```python
# marshmallow 3 calling convention
validator(value)
```

In marshmallow 4, the decorator passes an additional `data_key=` keyword argument:

```python
# marshmallow 4 calling convention
validator(value, data_key=<str>)
```

Upstream fixed all 7 validators in the core schemas by adding `**kwargs: Any` to each method
signature. The fork's `TenantProvisioningSchema` has four `@validates` methods with the old
marshmallow 3 signature — none of them were updated.

**Why upstream CI passes**: Upstream CI has no visibility into custom extension code in this fork.
All upstream-owned schemas were patched in `919bd35`. The fork's validators silently carry the old
signature and are never exercised by upstream tests.

### Change 2: RLS strict validation (`0fd244b`)

- **PR title**: `fix(security): reject unknown fields in guest-token RLS rules`

Upstream changed `RlsRuleSchema` from a permissive schema (unknown fields silently stripped) to a
strict schema (unknown fields rejected with `ValidationError`):

```python
# Before 0fd244b — PermissiveSchema uses Meta.unknown = EXCLUDE
class RlsRuleSchema(PermissiveSchema):
    dataset = fields.Integer()
    clause = fields.String(required=True)

# After 0fd244b — strict rejection of extra fields
class RlsRuleSchema(Schema):
    dataset = fields.Integer()
    clause = fields.String(required=True)
    # Meta.unknown defaults to RAISE in marshmallow 3/4
```

The fork's `build_tenant_rls_rule` returns a dict with three keys: `dataset`, `clause`, and
`tenant_id`. The first two are valid schema fields; `tenant_id` is an extra key the audit team
added. After `0fd244b`, the schema raises `ValidationError` on the extra key.

**Why upstream CI passes**: Upstream CI tests their own schemas with their own known-good payloads,
none of which include a `tenant_id` field. The breaking change only affects callers who pass extra
fields — i.e., this fork.

## How the Breaks Manifest

### Break 1: Tenant Provisioner

- **Trigger**: Any call to `POST /api/v1/internal/tenants/provision` after the nightly sync merges
  `919bd35`. The endpoint calls `TenantProvisioningSchema().load(request.json)`, which invokes
  `_invoke_field_validators`, which calls each `@validates` method with the new `data_key=`
  keyword — hitting the bug immediately.

- **Error** (exact message):
  ```
  TypeError: TenantProvisioningSchema.validate_contract_end_date() got an unexpected keyword argument 'data_key'
  ```

- **Business impact**: The tenant provisioning endpoint returns HTTP 500 for every request. No new
  enterprise tenant can be onboarded. Existing tenants are unaffected; the failure is invisible to
  end-users but completely blocks the customer-success and sales teams.

- **Why it's subtle**: The error names `data_key`, which does not appear anywhere in the custom
  extension code. The schema imports cleanly, instantiates cleanly, and passes static analysis —
  nothing flags the problem until `.load()` is called with real data at runtime.

### Break 2: Embedded Analytics

- **Trigger**: Any call to `POST /api/v1/security/guest_token/` after the nightly sync merges
  `0fd244b`. Superset validates the RLS rules array through `RlsRuleSchema`, which now rejects the
  extra `tenant_id` field.

- **Error** (exact message):
  ```
  marshmallow.exceptions.ValidationError: {'tenant_id': ['Unknown field.']}
  ```

- **Business impact**: Guest token issuance fails for every tenant embed request. All white-label
  embedded dashboards return 401/403. Customer-facing product features that depend on embedded
  analytics go dark simultaneously across all tenants.

- **Why it's subtle**: The `tenant_id` field was intentionally placed in the RLS rule dict by the
  security/audit team. Developers may not immediately connect a schema `ValidationError` to a
  change in upstream's `RlsRuleSchema` permissiveness. The two breaks surface at different layers
  (Python type error vs. marshmallow validation error) and share no obvious common cause.

## What Devin Needs to Do

### Investigation path

1. **Read the failing test output** in the nightly-sync GitHub issue. Two separate test files are
   failing with two different error types.

2. **Identify that they are independent**: one is a `TypeError` in marshmallow's internal
   `_call_and_store`, the other is a `ValidationError` for an unknown field. Different root causes,
   different files.

3. **For the `TypeError`**:
   - Search for `@validates` in `superset/extensions/tenant_provisioner.py`.
   - Check the diff of `919bd35`: `git show 919bd35 -- superset/reports/schemas.py`.
   - Observe that every `@validates` method gained `**kwargs: Any`.
   - Apply the same pattern to all four validators in `tenant_provisioner.py`.

4. **For the `ValidationError`**:
   - Locate `build_tenant_rls_rule` in `superset/extensions/tenant_embed.py`.
   - Note that it returns a dict with `tenant_id` alongside `dataset` and `clause`.
   - Check the diff of `0fd244b`: `git show 0fd244b -- superset/security/api.py`.
   - Observe that `RlsRuleSchema` no longer accepts unknown fields.
   - Remove `tenant_id` from the returned dict; use structured logging or a request-level
     audit header for tenant correlation instead.

5. **Verify both fixes**:
   ```bash
   pip install "marshmallow>=4.0" pytest
   python -m pytest tests/unit_tests/extensions/ -v \
     --confcutdir=tests/unit_tests/extensions
   # → all tests pass
   ```

6. **Open a single PR** with both fixes.

## The Fixes

### Fix 1: Tenant Provisioner — add `**kwargs` to all `@validates` methods

```python
# Before (marshmallow 3 — breaks on marshmallow 4)
@validates("organization_slug")
def validate_organization_slug(self, value: str) -> None: ...

@validates("tier")
def validate_tier(self, value: str) -> None: ...

@validates("data_residency_region")
def validate_data_residency_region(self, value: str) -> None: ...

@validates("contract_end_date")
def validate_contract_end_date(self, value: str) -> None: ...

# After (marshmallow 4 compatible)
@validates("organization_slug")
def validate_organization_slug(self, value: str, **kwargs: Any) -> None: ...

@validates("tier")
def validate_tier(self, value: str, **kwargs: Any) -> None: ...

@validates("data_residency_region")
def validate_data_residency_region(self, value: str, **kwargs: Any) -> None: ...

@validates("contract_end_date")
def validate_contract_end_date(self, value: str, **kwargs: Any) -> None: ...
```

The `**kwargs` absorbs the `data_key=` argument marshmallow 4 now passes. The validation logic
itself is unchanged.

### Fix 2: Embedded Analytics — remove `tenant_id` from the RLS rule dict

```python
# Before (extra field breaks strict RlsRuleSchema after 0fd244b)
def build_tenant_rls_rule(tenant_id: str, dataset_id: int) -> dict:
    return {
        "dataset": dataset_id,
        "clause": f"tenant_id = '{tenant_id}'",
        "tenant_id": tenant_id,   # <-- unknown field, now rejected
    }

# After (only the schema-known fields)
def build_tenant_rls_rule(tenant_id: str, dataset_id: int) -> dict:
    return {
        "dataset": dataset_id,
        "clause": f"tenant_id = '{tenant_id}'",
    }
```

Tenant correlation for audit purposes should be handled at the request level (e.g., a structured
log entry or a custom HTTP header on the guest-token request), not embedded in the RLS rule payload.

## Files in This Fork

| File | Purpose |
|------|---------|
| `superset/extensions/tenant_provisioner.py` | Custom marshmallow 3 schema — contains the `@validates` bug |
| `superset/extensions/tenant_embed.py` | Guest token builder — contains the extra `tenant_id` field |
| `tests/unit_tests/extensions/test_tenant_provisioner.py` | 22 tests: pass on marshmallow 3, fail on marshmallow 4 |
| `tests/unit_tests/extensions/test_tenant_embed.py` | 4 tests: pass before 0fd244b, fail after |
| `tests/unit_tests/extensions/conftest.py` | Stubs heavy imports so both test files run with only `pip install marshmallow pytest` |
| `.github/workflows/nightly-upstream-sync.yml` | Nightly rebase onto upstream + CI gate that raises the incident issue |

## Reproducing the Breaks

### Break 1: marshmallow 4 bump

```bash
# On the marshmallow4-scenario branch (marshmallow 3 installed — all pass)
pip install "marshmallow<4" pytest
python -m pytest tests/unit_tests/extensions/test_tenant_provisioner.py -v \
  --confcutdir=tests/unit_tests/extensions
# → 22 passed

# Simulate the nightly sync merging 919bd35 (marshmallow 4 installed — all fail)
pip install "marshmallow>=4.0"
python -m pytest tests/unit_tests/extensions/test_tenant_provisioner.py -v \
  --confcutdir=tests/unit_tests/extensions
# → 22 failed
# TypeError: TenantProvisioningSchema.validate_contract_end_date()
#            got an unexpected keyword argument 'data_key'
```

### Break 2: RLS strict validation

```bash
# Simulate 0fd244b landing: edit conftest.py to change Meta.unknown from EXCLUDE to RAISE
# Then re-run:
python -m pytest tests/unit_tests/extensions/test_tenant_embed.py -v \
  --confcutdir=tests/unit_tests/extensions
# → test_tenant_rls_rule_is_schema_compatible FAILED
#    test_guest_token_payload_rls_is_schema_compatible FAILED
# ValidationError: {'tenant_id': ['Unknown field.']}
```

### Both breaks simultaneously

```bash
# After the nightly sync (marshmallow 4 + strict RLS schema):
python -m pytest tests/unit_tests/extensions/ -v \
  --confcutdir=tests/unit_tests/extensions
# → 22 provisioner tests FAILED (TypeError)
# →  2 embed tests FAILED (ValidationError)
# →  2 embed tests PASSED (structural checks unaffected by schema validation)
```
