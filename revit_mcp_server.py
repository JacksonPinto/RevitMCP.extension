#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Revit MCP server (stdio bridge)  —  runs on the machine where Claude Desktop lives
==================================================================================
This is the MCP server that Claude Desktop launches. It exposes Revit "tools"
to Claude and forwards each call as an HTTP request to the pyRevit Routes API
(RevitMCP.extension) running inside Revit on your Windows PC.

    Claude Desktop  --stdio-->  THIS server  --HTTP/LAN-->  pyRevit Routes (Revit)

It uses only the official `mcp` package plus the Python standard library
(no httpx, no extra deps).

Install (on the Mac that runs Claude Desktop):
    python3 -m pip install --upgrade "mcp>=1.2.0"

Configure (point it at the Revit PC):
    REVIT_HOST   default 192.168.0.171
    REVIT_PORT   default 48884
    REVIT_TOKEN  optional bearer token (only if the Routes side checks one)

Run standalone to smoke-test the connection (not via Claude):
    REVIT_HOST=192.168.0.171 python3 revit_mcp_server.py --selftest
"""
import json
import os
import sys
from urllib import request, error, parse

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # pragma: no cover
    sys.stderr.write(
        "ERROR: the 'mcp' package is not installed.\n"
        "Run:  python3 -m pip install --upgrade 'mcp>=1.2.0'\n"
    )
    raise

REVIT_HOST = os.environ.get("REVIT_HOST", "192.168.0.171")
REVIT_PORT = os.environ.get("REVIT_PORT", "48884")
REVIT_TOKEN = os.environ.get("REVIT_TOKEN", "")
BASE_URL = "http://%s:%s" % (REVIT_HOST, REVIT_PORT)
TIMEOUT = float(os.environ.get("REVIT_TIMEOUT", "30"))

mcp = FastMCP("revit")


# ------------------------------------------------------------------ transport
def _http(method, path, params=None, body=None):
    """Call the pyRevit Routes API. Returns a Python object or an {'error': ...} dict."""
    url = BASE_URL + path
    if params:
        url += "?" + parse.urlencode({k: v for k, v in params.items() if v is not None})
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if REVIT_TOKEN:
        headers["Authorization"] = "Bearer " + REVIT_TOKEN
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read().decode("utf-8", "replace")
    except error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return {"error": "HTTP %s" % e.code, "details": json.loads(raw)}
        except Exception:
            return {"error": "HTTP %s" % e.code, "details": raw}
    except Exception as e:
        return {"error": "Cannot reach Revit at %s. Is Revit open with the Routes "
                         "server ON and the firewall allowing port %s? (%s)"
                         % (BASE_URL, REVIT_PORT, e)}
    try:
        return json.loads(raw)
    except Exception:
        return {"raw": raw}


# ------------------------------------------------------------------ tools
@mcp.tool()
def revit_ping() -> dict:
    """Check the connection to Revit and report its version and the open model."""
    return _http("GET", "/revit/ping")


@mcp.tool()
def get_project_info() -> dict:
    """Get the active Revit project's name, number, client, address and status."""
    return _http("GET", "/revit/project/info")


@mcp.tool()
def get_model_summary() -> dict:
    """Get a high-level summary of the model (good first call for context)."""
    return _http("GET", "/revit/analysis/model_summary")


@mcp.tool()
def list_levels() -> list:
    """List all levels in the model with their elevations."""
    return _http("GET", "/revit/levels")


@mcp.tool()
def list_elements_by_category(category: str) -> list:
    """List element instances in a Revit category.

    Args:
        category: e.g. 'Walls', 'Doors', 'Ducts', 'Pipes', 'Mechanical Equipment'.
    """
    return _http("GET", "/revit/elements/by_category", params={"category": category})


@mcp.tool()
def get_element_parameters(element_id: int, include_read_only: bool = False) -> list:
    """Get all parameters of a Revit element by its integer ElementId."""
    return _http("GET", "/revit/elements/%d/parameters" % element_id,
                 params={"include_read_only": str(include_read_only).lower()})


@mcp.tool()
def get_parameter_value(element_id: int, param_name: str) -> dict:
    """Get a single parameter value from an element."""
    return _http("GET", "/revit/elements/%d/parameters/%s"
                 % (element_id, parse.quote(param_name)))


@mcp.tool()
def set_element_parameter(element_id: int, param_name: str, value) -> dict:
    """Set a parameter on an element (writes inside a Revit transaction).

    Args:
        element_id: integer ElementId.
        param_name: parameter name to set.
        value: new value (use millimetres for length parameters).
    """
    return _http("POST", "/revit/elements/%d/parameters/set" % element_id,
                 body={"param_name": param_name, "value": value})


@mcp.tool()
def list_mep_systems() -> list:
    """List MEP systems (duct and piping) in the model."""
    return _http("GET", "/revit/mep/systems")


@mcp.tool()
def list_ducts() -> list:
    """List duct elements."""
    return _http("GET", "/revit/mep/ducts")


@mcp.tool()
def list_pipes() -> list:
    """List pipe elements."""
    return _http("GET", "/revit/mep/pipes")


@mcp.tool()
def list_families(category: str = None, search: str = None) -> list:
    """List loaded families, optionally filtered by category or name search."""
    return _http("GET", "/revit/families", params={"category": category, "search": search})


@mcp.tool()
def revit_api_get(path: str) -> dict:
    """Power tool: GET any Routes endpoint directly. Path must start with '/revit/'.

    Use this to reach endpoints that don't have a dedicated tool yet,
    e.g. '/revit/grids', '/revit/sheets', '/revit/worksets'.
    """
    if not path.startswith("/revit/"):
        return {"error": "path must start with /revit/"}
    return _http("GET", path)


# ------------------------------------------------------------------ entry
def _selftest():
    sys.stderr.write("Self-test against %s ...\n" % BASE_URL)
    print(json.dumps(_http("GET", "/revit/ping"), indent=2))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        mcp.run(transport="stdio")
