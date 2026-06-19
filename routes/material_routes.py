# -*- coding: utf-8 -*-
"""pyRevit Routes — Material endpoints."""
import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import Color, ElementId, FilteredElementCollector, Material, Transaction
from pyrevit.routes import API, Response
_uidoc = getattr(__revit__, 'ActiveUIDocument', None)
doc = _uidoc.Document if _uidoc else None

def _mat_to_dict(m):
    return {'element_id': _idv(m.Id), 'name': m.Name, 'material_class': m.MaterialClass, 'color_r': m.Color.Red if m.Color else 0, 'color_g': m.Color.Green if m.Color else 0, 'color_b': m.Color.Blue if m.Color else 0, 'transparency': m.Transparency, 'shininess': m.Shininess, 'smoothness': m.Smoothness}

def _unq(s):
    """Minimal URL-decode for IronPython 2.7 (handles %XX and +)."""
    try:
        s = s.replace('+', ' ')
        out = []
        i = 0
        while i < len(s):
            if s[i] == '%' and i + 2 < len(s) + 1:
                try:
                    out.append(chr(int(s[i+1:i+3], 16)))
                    i += 3
                    continue
                except Exception:
                    pass
            out.append(s[i])
            i += 1
        return ''.join(out)
    except Exception:
        return s

def _qp(request):
    """Best-effort query/route params as a dict. Handles: dict; list of objects
    with .key/.value or .name/.value; list of (key,value) pairs; or a raw query
    string found on the request (query_string/query/path/uri/url)."""
    out = {}
    p = getattr(request, 'params', None)
    if isinstance(p, dict):
        out.update(p)
    elif p:
        try:
            for x in p:
                k = getattr(x, 'key', None)
                v = getattr(x, 'value', None)
                if k is None and getattr(x, 'name', None) is not None:
                    k = x.name
                    v = getattr(x, 'value', None)
                if k is None and isinstance(x, (list, tuple)) and len(x) == 2:
                    k, v = x[0], x[1]
                if k is not None:
                    out[str(k)] = v
        except Exception:
            pass
    if not out:
        qs = None
        for attr in ('query_string', 'query'):
            val = getattr(request, attr, None)
            if val and isinstance(val, str):
                qs = val
                break
        if qs is None:
            for attr in ('uri', 'url', 'path'):
                val = getattr(request, attr, None)
                if val and isinstance(val, str) and '?' in val:
                    qs = val.split('?', 1)[1]
                    break
        if qs:
            for pair in qs.split('&'):
                if '=' in pair:
                    k, v = pair.split('=', 1)
                    out[_unq(k)] = _unq(v)
    return out

def _idv(eid):
    """ElementId integer value. Revit 2024+ uses .Value (Int64); older uses .IntegerValue."""
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue

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
        return Response(data={'element_id': _idv(mat_id), 'name': body['material_name']})

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
        return Response(data={'element_id': _idv(new_id), 'name': body['new_name']})
