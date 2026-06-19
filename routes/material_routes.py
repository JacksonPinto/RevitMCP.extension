# -*- coding: utf-8 -*-
"""pyRevit Routes — Material endpoints."""
import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import Color, ElementId, FilteredElementCollector, Material, Transaction
from pyrevit.routes import API, Response
_uidoc = getattr(__revit__, 'ActiveUIDocument', None)
doc = _uidoc.Document if _uidoc else None

def _mat_to_dict(m):
    return {'element_id': m.Id.IntegerValue, 'name': m.Name, 'material_class': m.MaterialClass, 'color_r': m.Color.Red if m.Color else 0, 'color_g': m.Color.Green if m.Color else 0, 'color_b': m.Color.Blue if m.Color else 0, 'transparency': m.Transparency, 'shininess': m.Shininess, 'smoothness': m.Smoothness}

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

    @api.route('/materials', methods=['GET'])
    def list_materials(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        search = _qp(request).get('search', '').lower()
        results = []
        for m in FilteredElementCollector(doc).OfClass(Material):
            if search and search not in m.Name.lower():
                continue
            results.append(_mat_to_dict(m))
        return Response(data=results)

    @api.route('/materials/by_name', methods=['GET'])
    def get_material(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        name = _qp(request).get('material_name')
        m = next((m for m in FilteredElementCollector(doc).OfClass(Material) if m.Name == name), None)
        if not m:
            return Response(status_code=404, data={'error': "Material '{}' not found".format(name)})
        return Response(data=_mat_to_dict(m))

    @api.route('/materials/create', methods=['POST'])
    def create_material(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        with Transaction(doc, 'MCP: Create Material') as t:
            t.Start()
            mat_id = Material.Create(doc, body['material_name'])
            mat = doc.GetElement(mat_id)
            mat.MaterialClass = body.get('material_class', 'Generic')
            mat.Color = Color(int(body.get('color_r', 128)), int(body.get('color_g', 128)), int(body.get('color_b', 128)))
            mat.Transparency = int(body.get('transparency', 0))
            t.Commit()
        return Response(data={'element_id': mat_id.IntegerValue, 'name': body['material_name']})

    @api.route('/materials/duplicate', methods=['POST'])
    def duplicate_material(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        src = next((m for m in FilteredElementCollector(doc).OfClass(Material) if m.Name == body['source_name']), None)
        if not src:
            return Response(status_code=404, data={'error': 'Source material not found'})
        with Transaction(doc, 'MCP: Duplicate Material') as t:
            t.Start()
            new_id = src.Duplicate(body['new_name'])
            t.Commit()
        return Response(data={'element_id': new_id.IntegerValue, 'name': body['new_name']})
