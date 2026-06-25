# -*- coding: utf-8 -*-
"""pyRevit Routes — Workset endpoints."""
import clr
clr.AddReference('RevitAPI')
import Autodesk
from Autodesk.Revit.DB import ElementId, FilteredElementCollector, FilteredWorksetCollector, Transaction, WorksetKind
from pyrevit.routes import API, Response
_uidoc = getattr(__revit__, 'ActiveUIDocument', None)
doc = _uidoc.Document if _uidoc else None

def _idv(eid):
    """ElementId integer value. Revit 2024+ uses .Value (Int64); older uses .IntegerValue."""
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue

def _mkid(i):
    """Build an ElementId from an int (Revit 2026: force Int64 overload to avoid
    ambiguity with ElementId(BuiltInParameter)/(BuiltInCategory))."""
    import System
    return ElementId(System.Int64(i))

def _get_routes(api):

    @api.route('/worksets/status', methods=['GET'])
    def workset_status(uiapp):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        return Response(data={'workshared': doc.IsWorkshared, 'path': doc.PathName if doc.IsWorkshared else None})

    @api.route('/worksets', methods=['GET'])
    def list_worksets(uiapp):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        if not doc.IsWorkshared:
            return Response(status_code=400, data={'error': 'Model is not workshared'})
        results = []
        for ws in FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset):
            results.append({'name': ws.Name, 'workset_id': _idv(ws.Id), 'is_open': ws.IsOpen, 'owner': ws.Owner or None})
        return Response(data=results)

    @api.route('/worksets/create', methods=['POST'])
    def create_workset(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        name = request.data.get('name')
        with Transaction(doc, 'MCP: Create Workset') as t:
            t.Start()
            from Autodesk.Revit.DB import Workset
            ws = Workset.Create(doc, name)
            t.Commit()
        return Response(data={'name': name, 'workset_id': _idv(ws.Id)})

    @api.route('/elements/<int:element_id>/workset', methods=['GET'])
    def get_element_workset(uiapp, element_id):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        elem = doc.GetElement(_mkid(element_id))
        if not elem:
            return Response(status_code=404, data={'error': 'Element not found'})
        ws_param = elem.get_Parameter(clr.GetClrType(Autodesk.Revit.DB.BuiltInParameter).WorksetId)
        ws_id = elem.WorksetId
        ws = doc.GetWorksetTable().GetWorkset(ws_id)
        return Response(data={'element_id': element_id, 'workset_name': ws.Name, 'workset_id': _idv(ws_id)})

    @api.route('/worksets/set_elements', methods=['POST'])
    def set_element_workset(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        ws_name = body.get('workset_name')
        ids = body.get('element_ids', [])
        table = doc.GetWorksetTable()
        target_ws = next((ws for ws in FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset) if ws.Name == ws_name), None)
        if not target_ws:
            return Response(status_code=404, data={'error': "Workset '{}' not found".format(ws_name)})
        moved = 0
        with Transaction(doc, 'MCP: Set Element Workset') as t:
            t.Start()
            for eid in ids:
                elem = doc.GetElement(_mkid(eid))
                if elem:
                    from Autodesk.Revit.DB import WorksetId
                    ws_param = elem.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.ELEM_PARTITION_PARAM)
                    if ws_param and (not ws_param.IsReadOnly):
                        ws_param.Set(_idv(target_ws.Id))
                        moved += 1
            t.Commit()
        return Response(data={'moved_count': moved, 'workset_name': ws_name})

    @api.route('/worksets/set_active', methods=['POST'])
    def set_active_workset(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        ws_name = request.data.get('workset_name')
        target_ws = next((ws for ws in FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset) if ws.Name == ws_name), None)
        if not target_ws:
            return Response(status_code=404, data={'error': "Workset '{}' not found".format(ws_name)})
        table = doc.GetWorksetTable()
        old_active = table.GetWorkset(table.GetActiveWorksetId()).Name
        with Transaction(doc, 'MCP: Set Active Workset') as t:
            t.Start()
            table.SetActiveWorksetId(target_ws.Id)
            t.Commit()
        return Response(data={'previous_active': old_active, 'new_active': ws_name})
