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
Lightweight conftest for the extensions unit-test suite.

Goal: let the tests in this directory run with only::

    pip install marshmallow pytest

without pulling in Flask, SQLAlchemy, Celery, or any other Superset
runtime dependency.

How it works
------------
``superset/__init__.py`` imports Flask, Celery and dozens of other packages
at module level.  ``superset/extensions/__init__.py`` does the same.
``superset/security/api.py`` imports Flask, Flask-AppBuilder, and SQLAlchemy.
If any of these files executes during import, the test run fails with
ImportError.

This conftest pre-populates ``sys.modules`` with thin stub packages for
``superset``, ``superset.extensions``, ``superset.security``, and
``superset.security.api`` *before* any test module is collected.  Because
Python's import machinery checks ``sys.modules`` first, the real
``__init__.py`` files are never executed.

Critically, we still point each stub's ``__path__`` at the real directory on
disk so that ``from superset.extensions.tenant_provisioner import ...`` and
``from superset.extensions.tenant_embed import ...`` resolve correctly:
Python will find those files on the filesystem and execute only *that* file
(which has no heavy imports).

For ``superset.security.api`` we provide a self-contained stub that defines
``RlsRuleSchema`` directly using marshmallow.  Rather than hardcoding its
unknown-field policy, the stub reads the *synced* ``superset/security/api.py``
off disk and mirrors whatever policy it declares:

- before commit 0fd244b  -> ``class RlsRuleSchema(PermissiveSchema)`` -> EXCLUDE
  (the custom ``tenant_id`` field is silently stripped; ``.load()`` succeeds)
- after commit 0fd244b   -> ``class RlsRuleSchema(Schema)``           -> RAISE
  (the extra field is rejected)

So once the nightly sync rebases the fork onto upstream, the synced api.py is
strict, the stub becomes strict to match, and
``test_tenant_rls_rule_is_schema_compatible`` fails with::

    ValidationError: {'tenant_id': ['Unknown field.']}

That failure is the intended demo signal.  Devin's fix: remove ``tenant_id``
from the dict returned by ``build_tenant_rls_rule``.
"""

from __future__ import annotations

import os
import re
import sys
import types

from marshmallow import EXCLUDE, fields, RAISE, Schema

# ---------------------------------------------------------------------------
# Locate the repository root so we can build absolute paths.
# ---------------------------------------------------------------------------
# This file lives at:
#   tests/unit_tests/extensions/conftest.py
# The repo root is three levels up.
_here = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.abspath(os.path.join(_here, "..", "..", ".."))

if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

_superset_src = os.path.join(_repo_root, "superset")
_ext_src = os.path.join(_superset_src, "extensions")
_security_src = os.path.join(_superset_src, "security")


# ---------------------------------------------------------------------------
# Helper: create a lightweight package stub.
# ---------------------------------------------------------------------------

def _stub_package(fqname: str, real_path: str) -> types.ModuleType:
    """Return (and register) a stub module for *fqname* if not already present.

    Sets ``__path__`` to *real_path* so that sub-module imports still resolve
    against the actual source tree.
    """
    if fqname in sys.modules:
        return sys.modules[fqname]
    mod = types.ModuleType(fqname)
    mod.__path__ = [real_path]  # type: ignore[assignment]
    mod.__package__ = fqname
    sys.modules[fqname] = mod
    return mod


# ---------------------------------------------------------------------------
# Stub RlsRuleSchema — tracks the *synced* upstream schema's unknown-field
# policy instead of hardcoding it.
#
# We can't import the real superset/security/api.py (it pulls in Flask), but we
# can read it off disk and mirror its policy:
#   - class RlsRuleSchema(PermissiveSchema)  -> unknown = EXCLUDE  (pre-0fd244b:
#       the custom ``tenant_id`` field is silently stripped, .load() succeeds)
#   - class RlsRuleSchema(Schema)            -> unknown = RAISE    (post-0fd244b:
#       the extra field is rejected with ValidationError)
#
# This way the nightly rebase onto upstream genuinely drives the RLS break: the
# stub is strict exactly when the synced source is strict, not because a test
# fixture was hand-edited.
# ---------------------------------------------------------------------------

def _synced_rls_unknown_policy(api_path: str) -> str:
    """Return the marshmallow unknown-field policy of the synced RlsRuleSchema.

    Reads ``superset/security/api.py`` from disk and inspects the base class of
    ``RlsRuleSchema``.  Defaults to EXCLUDE (legacy permissive behaviour) if the
    file or class can't be found.
    """
    try:
        with open(api_path, encoding="utf-8") as fh:
            source = fh.read()
    except OSError:
        return EXCLUDE
    match = re.search(r"class\s+RlsRuleSchema\s*\(\s*([\w.]+)\s*\)", source)
    base = match.group(1) if match else ""
    return EXCLUDE if base == "PermissiveSchema" else RAISE


_RLS_UNKNOWN = _synced_rls_unknown_policy(os.path.join(_security_src, "api.py"))


class RlsRuleSchema(Schema):
    """Lightweight replica of the upstream RlsRuleSchema.

    ``Meta.unknown`` is set to match the *synced* upstream schema (read from
    ``superset/security/api.py`` on disk): EXCLUDE before commit 0fd244b,
    RAISE after it.  When strict, extra fields such as the fork's custom
    ``tenant_id`` raise ``ValidationError`` on ``.load()``.
    """

    dataset = fields.Integer()
    clause = fields.String(required=True)

    class Meta:
        unknown = _RLS_UNKNOWN


# ---------------------------------------------------------------------------
# Install stubs before pytest collects any test module.
# ---------------------------------------------------------------------------

_superset_mod = _stub_package("superset", _superset_src)
_ext_mod = _stub_package("superset.extensions", _ext_src)

# Wire the attribute so `import superset; superset.extensions` also works.
setattr(_superset_mod, "extensions", _ext_mod)

# Stub superset.security as a package (real path on disk, but __init__.py
# never executed).
_security_mod = _stub_package("superset.security", _security_src)
setattr(_superset_mod, "security", _security_mod)

# Stub superset.security.api as a plain module with our thin RlsRuleSchema.
_security_api_mod = types.ModuleType("superset.security.api")
_security_api_mod.RlsRuleSchema = RlsRuleSchema  # type: ignore[attr-defined]
sys.modules["superset.security.api"] = _security_api_mod
setattr(_security_mod, "api", _security_api_mod)
