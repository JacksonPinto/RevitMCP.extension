# -*- coding: utf-8 -*-
"""
pyRevit Routes — Family and type endpoints.
Runs INSIDE Revit. Registered in startup.py.
"""
import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import ElementId, ElementTransformUtils, Family, FamilyInstance, FamilySymbol, FilteredElementCollector, Level, Line, Transaction, XYZ
from Autodesk.Revit.DB.Structure import StructuralType
import math
from pyrevit.routes import API, Response
_uidoc = getattr(__revit__, 'ActiveUIDocument', None)
doc = _uidoc.Document if _uidoc else None

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

    @api.route('/families/categories', methods=['GET'])
    def list_family_categories(uiapp):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        families = FilteredElementCollector(doc).OfClass(Family).ToElements()
        cats = {}
        for fam in families:
            cat = fam.FamilyCategory
            cat_name = cat.Name if cat else 'Unknown'
            cats[cat_name] = cats.get(cat_name, 0) + 1
        return Response(data=[{'category': k, 'family_count': v} for (k, v) in sorted(cats.items())])

    @api.route('/families', methods=['GET'])
    def list_families(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        category_filter = _qp(request).get('category')
        search = _qp(request).get('search', '').lower()
        families = FilteredElementCollector(doc).OfClass(Family).ToElements()
        results = []
        for fam in families:
            if category_filter:
                cat = fam.FamilyCategory
                if not cat or cat.Name != category_filter:
                    continue
            if search and search not in fam.Name.lower():
                continue
            type_count = fam.GetFamilySymbolIds().Count
            results.append({'family_name': fam.Name, 'category': fam.FamilyCategory.Name if fam.FamilyCategory else None, 'is_system_family': fam.IsSystemFamily, 'is_in_place': fam.IsInPlace, 'type_count': type_count, 'element_id': _idv(fam.Id)})
        return Response(data=results)

    @api.route('/families/types', methods=['GET'])
    def list_family_types(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        family_name = _qp(request).get('family_name')
        families = FilteredElementCollector(doc).OfClass(Family).ToElements()
        target = next((f for f in families if f.Name == family_name), None)
        if target is None:
            return Response(status_code=404, data={'error': "Family '{}' not found".format(family_name)})
        results = []
        for type_id in target.GetFamilySymbolIds():
            sym = doc.GetElement(type_id)
            if sym:
                results.append({'type_name': sym.Name, 'element_id': _idv(sym.Id), 'is_active': sym.IsActive})
        return Response(data=results)

    @api.route('/families/place', methods=['POST'])
    def place_family(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        family_name = body.get('family_name')
        type_name = body.get('type_name')
        x = body.get('x', 0)
        y = body.get('y', 0)
        z = body.get('z', 0)
        rotation = body.get('rotation_degrees', 0)
        level_name = body.get('level_name')
        host_id = body.get('host_element_id')
        symbols = FilteredElementCollector(doc).OfClass(FamilySymbol).ToElements()
        symbol = next((s for s in symbols if s.FamilyName == family_name and s.Name == type_name), None)
        if symbol is None:
            return Response(status_code=404, data={'error': "Type '{} : {}' not found".format(family_name, type_name)})
        level = None
        if level_name:
            for elem in FilteredElementCollector(doc).OfClass(Level):
                if elem.Name == level_name:
                    level = elem
                    break
        location = XYZ(x, y, z)
        with Transaction(doc, 'MCP: Place Family Instance') as t:
            t.Start()
            if not symbol.IsActive:
                symbol.Activate()
                doc.Regenerate()
            if host_id:
                host = doc.GetElement(ElementId(host_id))
                instance = doc.Create.NewFamilyInstance(location, symbol, host, None)
            elif level:
                from Autodesk.Revit.DB.Structure import StructuralType
                instance = doc.Create.NewFamilyInstance(location, symbol, level, StructuralType.NonStructural)
            else:
                from Autodesk.Revit.DB.Structure import StructuralType
                instance = doc.Create.NewFamilyInstance(location, symbol, StructuralType.NonStructural)
            if rotation != 0:
                import math
                from Autodesk.Revit.DB import Line
                axis = Line.CreateBound(location, XYZ(location.X, location.Y, location.Z + 1))
                ElementTransformUtils.RotateElement(doc, instance.Id, axis, math.radians(rotation))
            t.Commit()
        return Response(data={'element_id': _idv(instance.Id), 'family': family_name, 'type': type_name})

    @api.route('/families/load', methods=['POST'])
    def load_family(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        rfa_path = request.data.get('rfa_path')
        family = clr.Reference[Family]()
        with Transaction(doc, 'MCP: Load Family') as t:
            t.Start()
            success = doc.LoadFamily(rfa_path, family)
            t.Commit()
        if not success:
            return Response(status_code=400, data={'error': "Failed to load family from '{}'".format(rfa_path)})
        fam = family.Value
        return Response(data={'family_name': fam.Name, 'category': fam.FamilyCategory.Name if fam.FamilyCategory else None, 'type_count': fam.GetFamilySymbolIds().Count})
