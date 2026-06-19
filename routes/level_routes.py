# -*- coding: utf-8 -*-
"""pyRevit Routes — Level and grid endpoints."""
import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import ElementId, FilteredElementCollector, Grid, Level, Line, Transaction, XYZ
from pyrevit.routes import API, Response
_uidoc = getattr(__revit__, 'ActiveUIDocument', None)
doc = _uidoc.Document if _uidoc else None

def _qp(request):
    """Normalize pyRevit request.params (list of key/value objects, or dict) to a dict."""
    p = getattr(request, 'params', None)
    if p is None:
        return {}
    if isinstance(p, dict):
        return p
    d = {}
    try:
        for x in p:
            k = getattr(x, 'key', None)
            if k is not None:
                d[k] = getattr(x, 'value', None)
    except Exception:
        pass
    return d

def _get_routes(api):

    @api.route('/levels', methods=['GET'])
    def list_levels(uiapp):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        levels = sorted(FilteredElementCollector(doc).OfClass(Level), key=lambda l: l.Elevation)
        return Response(data=[{'element_id': l.Id.IntegerValue, 'name': l.Name, 'elevation': l.Elevation} for l in levels])

    @api.route('/levels/by_name', methods=['GET'])
    def get_level(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        name = _qp(request).get('level_name')
        lvl = next((l for l in FilteredElementCollector(doc).OfClass(Level) if l.Name == name), None)
        if not lvl:
            return Response(status_code=404, data={'error': "Level '{}' not found".format(name)})
        return Response(data={'element_id': lvl.Id.IntegerValue, 'name': lvl.Name, 'elevation': lvl.Elevation})

    @api.route('/levels/create', methods=['POST'])
    def create_level(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        with Transaction(doc, 'MCP: Create Level') as t:
            t.Start()
            lvl = Level.Create(doc, body['elevation'])
            if body.get('level_name'):
                lvl.Name = body['level_name']
            t.Commit()
        return Response(data={'element_id': lvl.Id.IntegerValue, 'name': lvl.Name, 'elevation': lvl.Elevation})

    @api.route('/levels/set_elevation', methods=['POST'])
    def set_elevation(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        lvl = next((l for l in FilteredElementCollector(doc).OfClass(Level) if l.Name == body['level_name']), None)
        if not lvl:
            return Response(status_code=404, data={'error': 'Level not found'})
        old_elev = lvl.Elevation
        with Transaction(doc, 'MCP: Set Level Elevation') as t:
            t.Start()
            lvl.Elevation = body['elevation']
            t.Commit()
        return Response(data={'level_name': body['level_name'], 'old_elevation': old_elev, 'new_elevation': body['elevation']})

    @api.route('/levels/rename', methods=['POST'])
    def rename_level(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        lvl = next((l for l in FilteredElementCollector(doc).OfClass(Level) if l.Name == body['old_name']), None)
        if not lvl:
            return Response(status_code=404, data={'error': 'Level not found'})
        with Transaction(doc, 'MCP: Rename Level') as t:
            t.Start()
            lvl.Name = body['new_name']
            t.Commit()
        return Response(data={'old_name': body['old_name'], 'new_name': body['new_name']})

    @api.route('/grids', methods=['GET'])
    def list_grids(uiapp):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        results = []
        for g in FilteredElementCollector(doc).OfClass(Grid):
            curve = g.Curve
            s = curve.GetEndPoint(0)
            e = curve.GetEndPoint(1)
            results.append({'element_id': g.Id.IntegerValue, 'name': g.Name, 'start': {'x': s.X, 'y': s.Y, 'z': s.Z}, 'end': {'x': e.X, 'y': e.Y, 'z': e.Z}})
        return Response(data=results)

    @api.route('/grids/create', methods=['POST'])
    def create_grid(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        start = XYZ(body['start_x'], body['start_y'], 0)
        end = XYZ(body['end_x'], body['end_y'], 0)
        line = Line.CreateBound(start, end)
        with Transaction(doc, 'MCP: Create Grid') as t:
            t.Start()
            grid = Grid.Create(doc, line)
            if body.get('grid_name'):
                grid.Name = body['grid_name']
            t.Commit()
        return Response(data={'element_id': grid.Id.IntegerValue, 'name': grid.Name})
