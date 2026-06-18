# -*- coding: utf-8 -*-
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

Each handler receives the live active document per request (pyRevit injects
'uiapp' and resolves the current doc) and runs inside Revit's API context, so
transactions work and switching projects needs no reload. Open a model before
calling document-dependent routes.
"""
import os
import sys
import traceback
_THIS_DIR = os.path.dirname(__file__)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
try:
    from pyrevit import routes
    api = routes.API('revit')

    # Import + register each module independently so one bad module
    # cannot prevent the others from registering.
    _MODULE_NAMES = [
        'project_routes', 'element_routes', 'parameter_routes', 'family_routes',
        'view_routes', 'sheet_routes', 'workset_routes', 'level_routes',
        'room_routes', 'material_routes', 'mep_routes', 'analysis_routes',
        'conduit_routes',
    ]
    _registered = 0
    _failed = []
    for _name in _MODULE_NAMES:
        try:
            _mod = __import__('routes.' + _name, fromlist=['_get_routes'])
            _mod._get_routes(api)
            _registered += 1
        except Exception as _modexc:
            _failed.append(_name)
            print('[RevitMCP] WARNING: %s failed: %s' % (_name, _modexc))
    print('[RevitMCP] Registered %d/%d route modules on http://localhost:48884'
          % (_registered, len(_MODULE_NAMES)))
    if _failed:
        print('[RevitMCP] Failed modules: %s' % ', '.join(_failed))
except Exception as e:
    print('[RevitMCP] ERROR registering routes: %s' % e)
    traceback.print_exc()
