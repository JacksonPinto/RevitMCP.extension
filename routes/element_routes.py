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
