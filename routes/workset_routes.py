#! python3
"""pyRevit Routes — Workset endpoints."""
from __future__ import annotations
import clr
clr.AddReference("RevitAPI")
import Autodesk  # expose Autodesk.Revit.DB.* namespace for runtime refs
from Autodesk.Revit.DB import ElementId, FilteredElementCollector, FilteredWorksetCollector, Transaction, WorksetKind
from pyrevit.routes import API, Response
_uidoc = getattr(__revit__, "ActiveUIDocument", None)
doc = _uidoc.Document if _uidoc else None  # resolved at load; reload extension with your model open

def _get_routes(api: API) -> None:

    @api.route("/revit/worksets/status", methods=["GET"])
    def workset_status():
        return Response(data={"workshared": doc.IsWorkshared,
                               "path": doc.PathName if doc.IsWorkshared else None})

    @api.route("/revit/worksets", methods=["GET"])
    def list_worksets():
        if not doc.IsWorkshared:
            return Response(status_code=400, data={"error": "Model is not workshared"})
        results = []
        for ws in FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset):
            results.append({"name": ws.Name, "workset_id": ws.Id.IntegerValue,
                             "is_open": ws.IsOpen, "owner": ws.Owner or None})
        return Response(data=results)

    @api.route("/revit/worksets/create", methods=["POST"])
    def create_workset(request):
        name = request.data.get("name")
        with Transaction(doc, "MCP: Create Workset") as t:
            t.Start()
            from Autodesk.Revit.DB import Workset
            ws = Workset.Create(doc, name)
            t.Commit()
        return Response(data={"name": name, "workset_id": ws.Id.IntegerValue})

    @api.route("/revit/elements/<int:element_id>/workset", methods=["GET"])
    def get_element_workset(element_id: int):
        elem = doc.GetElement(ElementId(element_id))
        if not elem:
            return Response(status_code=404, data={"error": "Element not found"})
        ws_param = elem.get_Parameter(clr.GetClrType(Autodesk.Revit.DB.BuiltInParameter).WorksetId)
        ws_id = elem.WorksetId
        ws = doc.GetWorksetTable().GetWorkset(ws_id)
        return Response(data={"element_id": element_id, "workset_name": ws.Name, "workset_id": ws_id.IntegerValue})

    @api.route("/revit/worksets/set_elements", methods=["POST"])
    def set_element_workset(request):
        body = request.data
        ws_name = body.get("workset_name")
        ids = body.get("element_ids", [])
        table = doc.GetWorksetTable()
        target_ws = next((ws for ws in FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset)
                          if ws.Name == ws_name), None)
        if not target_ws:
            return Response(status_code=404, data={"error": f"Workset '{ws_name}' not found"})
        moved = 0
        with Transaction(doc, "MCP: Set Element Workset") as t:
            t.Start()
            for eid in ids:
                elem = doc.GetElement(ElementId(eid))
                if elem:
                    from Autodesk.Revit.DB import WorksetId
                    ws_param = elem.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.ELEM_PARTITION_PARAM)
                    if ws_param and not ws_param.IsReadOnly:
                        ws_param.Set(target_ws.Id.IntegerValue)
                        moved += 1
            t.Commit()
        return Response(data={"moved_count": moved, "workset_name": ws_name})

    @api.route("/revit/worksets/set_active", methods=["POST"])
    def set_active_workset(request):
        ws_name = request.data.get("workset_name")
        target_ws = next((ws for ws in FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset)
                          if ws.Name == ws_name), None)
        if not target_ws:
            return Response(status_code=404, data={"error": f"Workset '{ws_name}' not found"})
        table = doc.GetWorksetTable()
        old_active = table.GetWorkset(table.GetActiveWorksetId()).Name
        with Transaction(doc, "MCP: Set Active Workset") as t:
            t.Start()
            table.SetActiveWorksetId(target_ws.Id)
            t.Commit()
        return Response(data={"previous_active": old_active, "new_active": ws_name})
