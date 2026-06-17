# RevitMCP.extension

pyRevit **Routes** extension that runs inside Autodesk Revit and exposes an HTTP API
(`http://localhost:48884/revit/...`) for the [revit-mcp-server](https://github.com/JacksonPinto/revit-mcp-server).
This is the **in-Revit half** of the system. The Python MCP server is the other half.

Tested target: **Revit 2025 & 2026**, **pyRevit 6.4.0**, Windows 11.

---

## Install directly from this Git URL

In Revit, open **pyRevit tab → Extensions** (Extension Manager). In the **Git information**
box at the bottom, paste:

```
https://github.com/JacksonPinto/RevitMCP.extension.git
```

Leave **Path** as the default (`...\AppData\Roaming\pyRevit\Extensions`), leave **Token**
blank (public repo), and click **Add and install**. pyRevit clones this repo into:

```
%APPDATA%\pyRevit\Extensions\RevitMCP.extension\
```

Then:

1. **pyRevit tab → Settings → Routes**: turn the Routes server **On**, set port **48884**,
   click **Save Settings**.
2. **pyRevit tab → Reload** (or restart Revit). Allow the Windows Firewall prompt.
3. Open any Revit model, then browse to **http://localhost:48884/revit/ping** — you should
   get a JSON response. You can test every GET endpoint straight from a browser or `curl`,
   **without** the Python MCP server running.

---

## LAN access (optional)

By default pyRevit Routes binds to `127.0.0.1` (local only). To reach it from another machine
on the same trusted network, set in pyRevit's config:

```
external_server_host = 0.0.0.0
external_server_port = 48884
```

and open the firewall port. ⚠️ **Security warning:** these routes currently enforce **no
authentication**. On `0.0.0.0`, any machine on the network can drive Revit, including
destructive operations. Keep it on `127.0.0.1` (or use an SSH tunnel) until token auth is
added on the route side.

---

## What's inside

```
RevitMCP.extension/
├── extension.json        # pyRevit extension metadata
├── startup.py            # registers all routes on load (fault-tolerant)
└── routes/               # one module per domain
    ├── project_routes.py     element_routes.py    parameter_routes.py
    ├── family_routes.py      view_routes.py        sheet_routes.py
    ├── workset_routes.py     level_routes.py       room_routes.py
    ├── material_routes.py    mep_routes.py         analysis_routes.py
    └── conduit_routes.py     (electrical-circuit → conduit auto-build)
```

## Known limitations (see the main repo's REVIEW.md)

- Family-document shared-parameter editing is not yet implemented (planned next). The
  plumbing is now in place: handlers run in Revit's API context and receive the live
  document per request, so editing the active family document is feasible.
- `parameter_routes` does not yet implement `/revit/parameters/shared` or
  `/revit/parameters/missing` (the matching MCP tools will 404).
- MEP outputs are not yet unit-converted to mm.
- No authentication on the routes (see LAN warning above).

These are tracked for the next iteration.
