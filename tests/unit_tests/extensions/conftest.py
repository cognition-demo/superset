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
Conftest for lightweight tenant-embed tests.

Stubs heavy superset dependencies so that ``superset.security.api`` and
``superset.extensions.tenant_embed`` can be imported with only marshmallow
installed.  This allows the tenant-embed CI workflow to run without
pulling in the full Superset dependency tree.
"""

from __future__ import annotations

import os
import sys
import types
from typing import Any
from unittest.mock import MagicMock


def _identity(*args: Any, **kwargs: Any) -> Any:
    """No-op decorator / function that returns its first arg or a decorator."""
    if len(args) == 1 and callable(args[0]) and not kwargs:
        return args[0]
    return lambda fn: fn


def _stub_module(name: str, path: str | None = None) -> types.ModuleType:
    """Create a stub module with a real __path__ for submodule discovery."""
    mod = types.ModuleType(name)
    mod.__path__ = [path] if path else []
    mod.__spec__ = None
    mod.__loader__ = None
    mod.__package__ = name
    mod.__file__ = None
    return mod


def _set(mod: types.ModuleType, name: str, value: Any) -> None:
    """setattr wrapper to avoid mypy attr-defined errors on ModuleType."""
    object.__setattr__(mod, name, value)


try:
    import flask  # noqa: F401
except ImportError:
    # Running in lightweight CI — stub everything so api.py can be imported.
    cwd = os.getcwd()

    # --- superset namespace packages (need real __path__ for submodules) ---
    sys.modules["superset"] = _stub_module("superset", os.path.join(cwd, "superset"))
    sys.modules["superset.security"] = _stub_module(
        "superset.security", os.path.join(cwd, "superset", "security")
    )
    sys.modules["superset.extensions"] = _stub_module(
        "superset.extensions", os.path.join(cwd, "superset", "extensions")
    )

    # --- flask stubs ---
    _flask = _stub_module("flask")
    _set(_flask, "current_app", MagicMock())
    _set(_flask, "request", MagicMock())
    _set(_flask, "Response", MagicMock())
    sys.modules["flask"] = _flask

    _fab = _stub_module("flask_appbuilder")
    _set(_fab, "expose", _identity)
    sys.modules["flask_appbuilder"] = _fab

    _fab_api = _stub_module("flask_appbuilder.api")
    _set(_fab_api, "rison", _identity)
    _set(_fab_api, "safe", _identity)
    _set(_fab_api, "SQLAInterface", MagicMock())
    sys.modules["flask_appbuilder.api"] = _fab_api

    _fab_schemas = _stub_module("flask_appbuilder.api.schemas")
    _set(_fab_schemas, "get_list_schema", MagicMock())
    sys.modules["flask_appbuilder.api.schemas"] = _fab_schemas

    _fab_sec_dec = _stub_module("flask_appbuilder.security.decorators")
    _set(_fab_sec_dec, "permission_name", _identity)
    _set(_fab_sec_dec, "protect", _identity)
    sys.modules["flask_appbuilder.security.decorators"] = _fab_sec_dec

    _fab_sec_models = _stub_module("flask_appbuilder.security.sqla.models")
    _set(_fab_sec_models, "RegisterUser", MagicMock())
    _set(_fab_sec_models, "Role", MagicMock())
    sys.modules["flask_appbuilder.security.sqla.models"] = _fab_sec_models

    _flask_wtf_csrf = _stub_module("flask_wtf.csrf")
    _set(_flask_wtf_csrf, "generate_csrf", MagicMock())
    sys.modules["flask_wtf.csrf"] = _flask_wtf_csrf

    # --- sqlalchemy stubs ---
    _sa = _stub_module("sqlalchemy")
    _set(_sa, "asc", MagicMock())
    _set(_sa, "desc", MagicMock())
    sys.modules["sqlalchemy"] = _sa

    _sa_orm = _stub_module("sqlalchemy.orm")
    _set(_sa_orm, "selectinload", MagicMock())
    sys.modules["sqlalchemy.orm"] = _sa_orm

    # --- superset internal stubs ---
    _INTERNAL_MODS = (
        "superset.app",
        "superset.commands",
        "superset.commands.dashboard",
        "superset.commands.dashboard.embedded",
        "superset.commands.dashboard.embedded.exceptions",
        "superset.commands.exceptions",
        "superset.exceptions",
        "superset.security.guest_token",
        "superset.utils",
        "superset.utils.core",
        "superset.views",
        "superset.views.base_api",
    )
    for mod_name in _INTERNAL_MODS:
        stub = _stub_module(mod_name)
        for attr in (
            "EmbeddedDashboardNotFoundError",
            "ForbiddenError",
            "SupersetGenericErrorException",
            "db",
            "event_logger",
            "build_guest_token_audit_payload",
            "GuestTokenResourceType",
            "get_user_id",
            "BaseSupersetApi",
            "BaseSupersetModelRestApi",
            "statsd_metrics",
        ):
            _set(stub, attr, MagicMock())
        sys.modules[mod_name] = stub

    # event_logger.log_this must be a no-op decorator
    _el = MagicMock()
    _el.log_this = _identity
    _set(sys.modules["superset.extensions"], "event_logger", _el)
    _set(sys.modules["superset.extensions"], "db", MagicMock())

    # BaseSupersetApi / BaseSupersetModelRestApi need to be real classes
    # so that SecurityRestApi can inherit from them.
    class _FakeBaseApi:
        pass

    _set(sys.modules["superset.views.base_api"], "BaseSupersetApi", _FakeBaseApi)
    _set(
        sys.modules["superset.views.base_api"],
        "BaseSupersetModelRestApi",
        _FakeBaseApi,
    )
    _set(sys.modules["superset.views.base_api"], "statsd_metrics", _identity)

    # GuestTokenResourceType needs to be a real Enum for fields.Enum
    import enum

    class _FakeGuestTokenResourceType(enum.Enum):
        DASHBOARD = "dashboard"

    _set(
        sys.modules["superset.security.guest_token"],
        "GuestTokenResourceType",
        _FakeGuestTokenResourceType,
    )
    _set(
        sys.modules["superset.security.guest_token"],
        "build_guest_token_audit_payload",
        MagicMock(),
    )
