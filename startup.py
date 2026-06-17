#! python3
"""
RevitMCP.extension — pyRevit startup script
============================================

Runs automatically when Revit starts (or when the extension is reloaded).
It registers the pyRevit Routes HTTP handlers that the Revit MCP server calls.

Install (direct from Git, via pyRevit Extension Manager):
    Git URL: https://github.com/JacksonPinto/RevitMCP.extension.git
    pyRevit clones this repo into:
        %APPDATA%\\pyRevit\\Extensions\\RevitMCP.extension\\

Then enable the Routes server in pyRevit Settings -> Routes, set port 48884,
Save Settings, and Reload. Confirm with:  http://localhost:48884/revit/ping

Routes register even if no document is open at load time; open a model before
calling any route. (The document is resolved at load time -- reload the
extension after switching projects until per-request resolution lands.)
"""

from __future__ import annotations

import os
import sys
import traceback

# Ensure this extension folder is importable so `from routes import ...` works
_THIS_DIR = os.path.dirname(__file__)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

try:
    from pyrevit import routes

    # Named API — all routes share this registration
    api = routes.API("revit-mcp")

    from routes import (
        analysis_routes,
        conduit_routes,
        element_routes,
        family_routes,
        level_routes,
        material_routes,
        mep_routes,
        parameter_routes,
        project_routes,
        room_routes,
        sheet_routes,
        view_routes,
        workset_routes,
    )

    _MODULES = [
        project_routes,
        element_routes,
        parameter_routes,
        family_routes,
        view_routes,
        sheet_routes,
        workset_routes,
        level_routes,
        room_routes,
        material_routes,
        mep_routes,
        analysis_routes,
        conduit_routes,
    ]

    _registered = 0
    for _mod in _MODULES:
        try:
            _mod._get_routes(api)
            _registered += 1
        except Exception as _modexc:  # one bad module shouldn't drop the rest
            print("[RevitMCP] WARNING: failed to register %s: %s"
                  % (getattr(_mod, "__name__", _mod), _modexc))

    print("[RevitMCP] Registered %d/%d route modules on http://localhost:48884"
          % (_registered, len(_MODULES)))

except Exception as e:
    print("[RevitMCP] ERROR registering routes: %s" % e)
    traceback.print_exc()
