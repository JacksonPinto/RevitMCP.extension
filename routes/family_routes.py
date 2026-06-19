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
            results.append({'family_name': fam.Name, 'category': fam.FamilyCategory.Name if fam.FamilyCategory else None, 'is_system_family': fam.IsSystemFamily, 'is_in_place': fam.IsInPlace, 'type_count': type_count, 'element_id': fam.Id.IntegerValue})
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
                results.append({'type_name': sym.Name, 'element_id': sym.Id.IntegerValue, 'is_active': sym.IsActive})
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
        return Response(data={'element_id': instance.Id.IntegerValue, 'family': family_name, 'type': type_name})

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
