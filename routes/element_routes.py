# -*- coding: utf-8 -*-
"""
pyRevit Routes — Element CRUD and transform endpoints.
Runs INSIDE Revit. Registered in startup.py.
"""
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import BuiltInCategory, ElementId, ElementTransformUtils, FilteredElementCollector, LocationCurve, LocationPoint, ParameterFilterRuleFactory, Transaction, Transform, XYZ, BuiltInParameter
from pyrevit.routes import API, Response
_uidoc = getattr(__revit__, 'ActiveUIDocument', None)
doc = _uidoc.Document if _uidoc else None
uidoc = __revit__.ActiveUIDocument

def _elem_to_dict(elem):
    """Convert a Revit element to a summary dict."""
    d = {'element_id': _idv(elem.Id), 'category': elem.Category.Name if elem.Category else None, 'name': elem.Name}
    type_elem = doc.GetElement(elem.GetTypeId()) if elem.GetTypeId() != ElementId.InvalidElementId else None
    if type_elem:
        d['type_name'] = type_elem.Name
        d['family_name'] = getattr(type_elem, 'FamilyName', None) or (type_elem.LookupParameter('Family Name').AsString() if type_elem.LookupParameter('Family Name') else None)
    level_param = elem.LookupParameter('Level') or elem.LookupParameter('Reference Level')
    if level_param:
        d['level'] = level_param.AsValueString()
    return d

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

    @api.route('/elements/<int:element_id>', methods=['GET'])
    def get_element(uiapp, element_id):
        global doc, uidoc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        uidoc = _ud
        elem_id = ElementId(element_id)
        elem = doc.GetElement(elem_id)
        if elem is None:
            return Response(status_code=404, data={'error': 'Element {} not found'.format(element_id)})
        d = _elem_to_dict(elem)
        params_list = []
        for param in elem.Parameters:
            try:
                val = None
                if param.StorageType.ToString() == 'String':
                    val = param.AsString()
                elif param.StorageType.ToString() == 'Double':
                    val = param.AsDouble()
                elif param.StorageType.ToString() == 'Integer':
                    val = param.AsInteger()
                elif param.StorageType.ToString() == 'ElementId':
                    val = _idv(param.AsElementId())
                params_list.append({'name': param.Definition.Name, 'value': val, 'storage_type': param.StorageType.ToString(), 'read_only': param.IsReadOnly, 'group': param.Definition.ParameterGroup.ToString() if hasattr(param.Definition, 'ParameterGroup') else None})
            except Exception:
                pass
        d['parameters'] = params_list
        return Response(data=d)

    @api.route('/elements/by_category', methods=['GET'])
    def get_elements_by_category(uiapp, request):
        global doc, uidoc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        uidoc = _ud
        category_name = _qp(request).get('category')
        level_name = _qp(request).get('level_name')
        include_types = _qp(request).get('include_type_elements', 'false').lower() == 'true'
        collector = FilteredElementCollector(doc).WhereElementIsNotElementType()
        results = []
        for elem in collector:
            if elem.Category and elem.Category.Name == category_name:
                d = _elem_to_dict(elem)
                if level_name:
                    lvl = d.get('level')
                    if lvl and level_name.lower() not in lvl.lower():
                        continue
                results.append(d)
        if include_types:
            type_collector = FilteredElementCollector(doc).WhereElementIsElementType()
            for elem in type_collector:
                if elem.Category and elem.Category.Name == category_name:
                    results.append(_elem_to_dict(elem))
        return Response(data=results)

    @api.route('/elements/by_category_path/<category>', methods=['GET'])
    def get_elements_by_category_path(uiapp, category):
        global doc, uidoc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        uidoc = _ud
        category = _unq(category)
        results = []
        for elem in FilteredElementCollector(doc).WhereElementIsNotElementType():
            if elem.Category and elem.Category.Name == category:
                results.append(_elem_to_dict(elem))
        return Response(data={'category': category, 'count': len(results), 'elements': results})

    @api.route('/active_view/categories', methods=['GET'])
    def get_active_view_categories(uiapp):
        global doc, uidoc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        uidoc = _ud
        av = doc.ActiveView
        counts = {}
        for elem in FilteredElementCollector(doc, av.Id).WhereElementIsNotElementType():
            if elem.Category:
                n = elem.Category.Name
                counts[n] = counts.get(n, 0) + 1
        cats = [{'category': k, 'count': v} for (k, v) in sorted(counts.items(), key=lambda kv: -kv[1])]
        return Response(data={'active_view': av.Name, 'view_id': _idv(av.Id), 'category_count': len(cats), 'categories': cats})

    @api.route('/active_view/category/<category>', methods=['GET'])
    def get_active_view_category(uiapp, category):
        global doc, uidoc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        uidoc = _ud
        category = _unq(category)
        av = doc.ActiveView
        results = []
        for elem in FilteredElementCollector(doc, av.Id).WhereElementIsNotElementType():
            if elem.Category and elem.Category.Name == category:
                results.append(_elem_to_dict(elem))
        return Response(data={'active_view': av.Name, 'category': category, 'count': len(results), 'elements': results})

    @api.route('/elements/by_type/<int:type_id>', methods=['GET'])
    def get_elements_by_type(uiapp, type_id):
        global doc, uidoc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        uidoc = _ud
        from Autodesk.Revit.DB import FamilyInstanceFilter
        target_id = ElementId(type_id)
        results = []
        collector = FilteredElementCollector(doc).WhereElementIsNotElementType()
        for elem in collector:
            if elem.GetTypeId() == target_id:
                results.append(_elem_to_dict(elem))
        return Response(data=results)

    @api.route('/elements/find_by_parameter', methods=['POST'])
    def find_by_parameter(uiapp, request):
        global doc, uidoc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        uidoc = _ud
        body = request.data
        category_name = body.get('category')
        param_name = body.get('param_name')
        param_value = str(body.get('param_value', ''))
        operator = body.get('operator', 'equals')
        results = []
        collector = FilteredElementCollector(doc).WhereElementIsNotElementType()
        for elem in collector:
            if not (elem.Category and elem.Category.Name == category_name):
                continue
            param = elem.LookupParameter(param_name)
            if param is None:
                continue
            val_str = param.AsValueString() or param.AsString() or ''
            if operator == 'equals' and val_str.lower() == param_value.lower():
                results.append(_elem_to_dict(elem))
            elif operator == 'contains' and param_value.lower() in val_str.lower():
                results.append(_elem_to_dict(elem))
            elif operator == 'starts_with' and val_str.lower().startswith(param_value.lower()):
                results.append(_elem_to_dict(elem))
            elif operator == 'ends_with' and val_str.lower().endswith(param_value.lower()):
                results.append(_elem_to_dict(elem))
        return Response(data=results)

    @api.route('/selection', methods=['GET'])
    def get_selection(uiapp):
        global doc, uidoc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        uidoc = _ud
        sel = uidoc.Selection.GetElementIds()
        results = []
        for eid in sel:
            elem = doc.GetElement(eid)
            if elem:
                results.append(_elem_to_dict(elem))
        return Response(data=results)

    @api.route('/selection', methods=['POST'])
    def set_selection(uiapp, request):
        global doc, uidoc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        uidoc = _ud
        ids = [ElementId(i) for i in request.data.get('element_ids', [])]
        from System.Collections.Generic import List as NetList
        id_list = NetList[ElementId](ids)
        uidoc.Selection.SetElementIds(id_list)
        return Response(data={'selected_count': len(ids)})

    @api.route('/elements/count', methods=['GET'])
    def count_by_category(uiapp, request):
        global doc, uidoc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        uidoc = _ud
        category_name = _qp(request).get('category')
        instance_count = sum((1 for e in FilteredElementCollector(doc).WhereElementIsNotElementType() if e.Category and e.Category.Name == category_name))
        type_count = sum((1 for e in FilteredElementCollector(doc).WhereElementIsElementType() if e.Category and e.Category.Name == category_name))
        return Response(data={'category': category_name, 'instance_count': instance_count, 'type_count': type_count})

    @api.route('/elements', methods=['DELETE'])
    def delete_elements(uiapp, request):
        global doc, uidoc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        uidoc = _ud
        ids = [ElementId(i) for i in request.data.get('element_ids', [])]
        deleted = []
        failed = []
        with Transaction(doc, 'MCP: Delete Elements') as t:
            t.Start()
            for eid in ids:
                elem = doc.GetElement(eid)
                if elem and (not elem.Pinned):
                    try:
                        doc.Delete(eid)
                        deleted.append(_idv(eid))
                    except Exception as ex:
                        failed.append({'element_id': _idv(eid), 'reason': str(ex)})
                elif elem and elem.Pinned:
                    failed.append({'element_id': _idv(eid), 'reason': 'Element is pinned'})
            t.Commit()
        return Response(data={'deleted_count': len(deleted), 'deleted': deleted, 'failed': failed})

    @api.route('/elements/move', methods=['POST'])
    def move_elements(uiapp, request):
        global doc, uidoc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        uidoc = _ud
        body = request.data
        ids = [ElementId(i) for i in body.get('element_ids', [])]
        delta = XYZ(body.get('delta_x', 0), body.get('delta_y', 0), body.get('delta_z', 0))
        moved = []
        with Transaction(doc, 'MCP: Move Elements') as t:
            t.Start()
            for eid in ids:
                try:
                    ElementTransformUtils.MoveElement(doc, eid, delta)
                    moved.append(_idv(eid))
                except Exception:
                    pass
            t.Commit()
        return Response(data={'moved_count': len(moved), 'element_ids': moved})

    @api.route('/elements/copy', methods=['POST'])
    def copy_elements(uiapp, request):
        global doc, uidoc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        uidoc = _ud
        body = request.data
        ids = [ElementId(i) for i in body.get('element_ids', [])]
        delta = XYZ(body.get('delta_x', 0), body.get('delta_y', 0), body.get('delta_z', 0))
        from System.Collections.Generic import List as NetList
        id_list = NetList[ElementId](ids)
        new_ids = []
        with Transaction(doc, 'MCP: Copy Elements') as t:
            t.Start()
            copied = ElementTransformUtils.CopyElements(doc, id_list, delta)
            new_ids = [_idv(eid) for eid in copied]
            t.Commit()
        return Response(data={'new_element_ids': new_ids, 'count': len(new_ids)})

    @api.route('/elements/pin', methods=['POST'])
    def pin_elements(uiapp, request):
        global doc, uidoc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        uidoc = _ud
        body = request.data
        ids = [ElementId(i) for i in body.get('element_ids', [])]
        pinned = body.get('pinned', True)
        changed = 0
        with Transaction(doc, 'MCP: Pin/Unpin Elements') as t:
            t.Start()
            for eid in ids:
                elem = doc.GetElement(eid)
                if elem:
                    elem.Pinned = pinned
                    changed += 1
            t.Commit()
        return Response(data={'changed_count': changed, 'pinned': pinned})

    @api.route('/elements/<int:element_id>/location', methods=['GET'])
    def get_location(uiapp, element_id):
        global doc, uidoc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        uidoc = _ud
        elem = doc.GetElement(ElementId(element_id))
        if elem is None:
            return Response(status_code=404, data={'error': 'Element not found'})
        loc = elem.Location
        if isinstance(loc, LocationPoint):
            pt = loc.Point
            return Response(data={'type': 'point', 'x': pt.X, 'y': pt.Y, 'z': pt.Z, 'rotation': loc.Rotation})
        elif isinstance(loc, LocationCurve):
            curve = loc.Curve
            s = curve.GetEndPoint(0)
            e = curve.GetEndPoint(1)
            return Response(data={'type': 'curve', 'start': {'x': s.X, 'y': s.Y, 'z': s.Z}, 'end': {'x': e.X, 'y': e.Y, 'z': e.Z}, 'length': curve.Length})
        return Response(data={'type': 'unknown'})

    @api.route('/elements/<int:element_id>/dependencies', methods=['GET'])
    def get_dependencies(uiapp, element_id):
        global doc, uidoc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        uidoc = _ud
        elem = doc.GetElement(ElementId(element_id))
        if elem is None:
            return Response(status_code=404, data={'error': 'Element not found'})
        dep_ids = elem.GetDependentElements(None)
        return Response(data={'element_id': element_id, 'dependent_element_ids': [_idv(i) for i in dep_ids], 'count': len(list(dep_ids))})
