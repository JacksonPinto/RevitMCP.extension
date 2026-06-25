# -*- coding: utf-8 -*-
"""
pyRevit Routes — Parameter read/write endpoints.
Runs INSIDE Revit. Registered in startup.py.
"""
import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import ElementId, FilteredElementCollector, Transaction
from pyrevit.routes import API, Response
_uidoc = getattr(__revit__, 'ActiveUIDocument', None)
doc = _uidoc.Document if _uidoc else None

def _set_param(param, value):
    """Set a parameter value using the correct storage type."""
    st = param.StorageType.ToString()
    if st == 'String':
        param.Set(str(value))
    elif st == 'Double':
        param.Set(float(value))
    elif st == 'Integer':
        param.Set(int(value))
    elif st == 'ElementId':
        param.Set(_mkid(int(value)))

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

def _mkid(i):
    """Build an ElementId from an int (Revit 2026: force Int64 overload to avoid
    ambiguity with ElementId(BuiltInParameter)/(BuiltInCategory))."""
    import System
    return ElementId(System.Int64(i))

def _get_routes(api):

    @api.route('/elements/<int:element_id>/parameters', methods=['GET'])
    def get_parameters(uiapp, element_id, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        elem = doc.GetElement(_mkid(element_id))
        if elem is None:
            return Response(status_code=404, data={'error': 'Element not found'})
        include_ro = _qp(request).get('include_read_only', 'false').lower() == 'true'
        group_filter = _qp(request).get('group_filter')
        results = []
        for param in elem.Parameters:
            if param.IsReadOnly and (not include_ro):
                continue
            group = None
            try:
                group = param.Definition.ParameterGroup.ToString()
            except Exception:
                pass
            if group_filter and group and (group_filter.lower() not in group.lower()):
                continue
            try:
                st = param.StorageType.ToString()
                if st == 'String':
                    val = param.AsString()
                elif st == 'Double':
                    val = param.AsDouble()
                elif st == 'Integer':
                    val = param.AsInteger()
                elif st == 'ElementId':
                    val = _idv(param.AsElementId())
                else:
                    val = None
                results.append({'name': param.Definition.Name, 'value': val, 'display_value': param.AsValueString(), 'storage_type': st, 'group': group, 'read_only': param.IsReadOnly})
            except Exception:
                pass
        return Response(data=results)

    @api.route('/elements/<int:element_id>/parameters/<string:param_name>', methods=['GET'])
    def get_single_parameter(uiapp, element_id, param_name):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        elem = doc.GetElement(_mkid(element_id))
        if elem is None:
            return Response(status_code=404, data={'error': 'Element not found'})
        param = elem.LookupParameter(param_name)
        if param is None:
            return Response(status_code=404, data={'error': "Parameter '{}' not found".format(param_name)})
        st = param.StorageType.ToString()
        val = param.AsString() if st == 'String' else param.AsDouble() if st == 'Double' else param.AsInteger() if st == 'Integer' else _idv(param.AsElementId())
        return Response(data={'name': param_name, 'value': val, 'display_value': param.AsValueString(), 'storage_type': st, 'read_only': param.IsReadOnly})

    @api.route('/elements/<int:element_id>/parameters/set', methods=['POST'])
    def set_parameter(uiapp, element_id, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        elem = doc.GetElement(_mkid(element_id))
        if elem is None:
            return Response(status_code=404, data={'error': 'Element not found'})
        param = elem.LookupParameter(body['param_name'])
        if param is None:
            return Response(status_code=404, data={'error': "Parameter '{}' not found".format(body['param_name'])})
        if param.IsReadOnly:
            return Response(status_code=400, data={'error': 'Parameter is read-only'})
        old_val = param.AsValueString() or param.AsString()
        with Transaction(doc, 'MCP: Set parameter {}'.format(body['param_name'])) as t:
            t.Start()
            _set_param(param, body['value'])
            t.Commit()
        return Response(data={'param_name': body['param_name'], 'old_value': old_val, 'new_value': body['value']})

    @api.route('/elements/<int:element_id>/parameters/batch', methods=['POST'])
    def batch_set_parameters(uiapp, element_id, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        elem = doc.GetElement(_mkid(element_id))
        if elem is None:
            return Response(status_code=404, data={'error': 'Element not found'})
        results = {}
        with Transaction(doc, 'MCP: Batch Set Parameters') as t:
            t.Start()
            for (name, value) in request.data.get('parameters', {}).items():
                param = elem.LookupParameter(name)
                if param is None:
                    results[name] = {'status': 'not_found'}
                elif param.IsReadOnly:
                    results[name] = {'status': 'read_only'}
                else:
                    try:
                        _set_param(param, value)
                        results[name] = {'status': 'ok', 'value': value}
                    except Exception as ex:
                        results[name] = {'status': 'error', 'message': str(ex)}
            t.Commit()
        return Response(data={'element_id': element_id, 'results': results})

    @api.route('/types/<int:type_id>/parameters', methods=['GET'])
    def get_type_parameters(uiapp, type_id):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        elem = doc.GetElement(_mkid(type_id))
        if elem is None:
            return Response(status_code=404, data={'error': 'Type not found'})
        results = []
        for param in elem.Parameters:
            try:
                st = param.StorageType.ToString()
                val = param.AsString() if st == 'String' else param.AsDouble() if st == 'Double' else param.AsInteger() if st == 'Integer' else _idv(param.AsElementId())
                results.append({'name': param.Definition.Name, 'value': val, 'display_value': param.AsValueString(), 'storage_type': st, 'read_only': param.IsReadOnly})
            except Exception:
                pass
        return Response(data=results)

    @api.route('/types/<int:type_id>/parameters/set', methods=['POST'])
    def set_type_parameter(uiapp, type_id, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        elem = doc.GetElement(_mkid(type_id))
        if elem is None:
            return Response(status_code=404, data={'error': 'Type not found'})
        param = elem.LookupParameter(body['param_name'])
        if param is None:
            return Response(status_code=404, data={'error': "Parameter '{}' not found".format(body['param_name'])})
        old_val = param.AsValueString()
        with Transaction(doc, 'MCP: Set type parameter {}'.format(body['param_name'])) as t:
            t.Start()
            _set_param(param, body['value'])
            t.Commit()
        return Response(data={'type_id': type_id, 'param_name': body['param_name'], 'old_value': old_val, 'new_value': body['value']})

    @api.route('/parameters/project', methods=['GET'])
    def list_project_parameters(uiapp):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        binding_map = doc.ParameterBindings
        it = binding_map.ForwardIterator()
        results = []
        while it.MoveNext():
            defn = it.Key
            binding = it.Current
            cats = []
            try:
                cats = [c.Name for c in binding.Categories]
            except Exception:
                pass
            results.append({'name': defn.Name, 'binding_type': binding.GetType().Name, 'data_type': str(defn.ParameterType) if hasattr(defn, 'ParameterType') else 'Unknown', 'categories': cats})
        return Response(data=results)

    @api.route('/parameters/bulk_update', methods=['POST'])
    def bulk_update(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        category_name = body.get('category')
        param_name = body.get('param_name')
        value = body.get('value')
        level_name = body.get('level_name')
        updated = 0
        failed = []
        with Transaction(doc, 'MCP: Bulk update {}'.format(param_name)) as t:
            t.Start()
            for elem in FilteredElementCollector(doc).WhereElementIsNotElementType():
                if not (elem.Category and elem.Category.Name == category_name):
                    continue
                if level_name:
                    lvl_param = elem.LookupParameter('Level') or elem.LookupParameter('Reference Level')
                    if lvl_param and level_name.lower() not in (lvl_param.AsValueString() or '').lower():
                        continue
                param = elem.LookupParameter(param_name)
                if param and (not param.IsReadOnly):
                    try:
                        _set_param(param, value)
                        updated += 1
                    except Exception as ex:
                        failed.append({'element_id': _idv(elem.Id), 'reason': str(ex)})
            t.Commit()
        return Response(data={'updated_count': updated, 'failed': failed})
