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
        param.Set(ElementId(int(value)))

def _get_routes(api):

    @api.route('/elements/<int:element_id>/parameters', methods=['GET'])
    def get_parameters(element_id, request):
        elem = doc.GetElement(ElementId(element_id))
        if elem is None:
            return Response(status_code=404, data={'error': 'Element not found'})
        include_ro = request.params.get('include_read_only', 'false').lower() == 'true'
        group_filter = request.params.get('group_filter')
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
                    val = param.AsElementId().IntegerValue
                else:
                    val = None
                results.append({'name': param.Definition.Name, 'value': val, 'display_value': param.AsValueString(), 'storage_type': st, 'group': group, 'read_only': param.IsReadOnly})
            except Exception:
                pass
        return Response(data=results)

    @api.route('/elements/<int:element_id>/parameters/<string:param_name>', methods=['GET'])
    def get_single_parameter(element_id, param_name):
        elem = doc.GetElement(ElementId(element_id))
        if elem is None:
            return Response(status_code=404, data={'error': 'Element not found'})
        param = elem.LookupParameter(param_name)
        if param is None:
            return Response(status_code=404, data={'error': "Parameter '{}' not found".format(param_name)})
        st = param.StorageType.ToString()
        val = param.AsString() if st == 'String' else param.AsDouble() if st == 'Double' else param.AsInteger() if st == 'Integer' else param.AsElementId().IntegerValue
        return Response(data={'name': param_name, 'value': val, 'display_value': param.AsValueString(), 'storage_type': st, 'read_only': param.IsReadOnly})

    @api.route('/elements/<int:element_id>/parameters/set', methods=['POST'])
    def set_parameter(element_id, request):
        body = request.data
        elem = doc.GetElement(ElementId(element_id))
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
    def batch_set_parameters(element_id, request):
        elem = doc.GetElement(ElementId(element_id))
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
    def get_type_parameters(type_id):
        elem = doc.GetElement(ElementId(type_id))
        if elem is None:
            return Response(status_code=404, data={'error': 'Type not found'})
        results = []
        for param in elem.Parameters:
            try:
                st = param.StorageType.ToString()
                val = param.AsString() if st == 'String' else param.AsDouble() if st == 'Double' else param.AsInteger() if st == 'Integer' else param.AsElementId().IntegerValue
                results.append({'name': param.Definition.Name, 'value': val, 'display_value': param.AsValueString(), 'storage_type': st, 'read_only': param.IsReadOnly})
            except Exception:
                pass
        return Response(data=results)

    @api.route('/types/<int:type_id>/parameters/set', methods=['POST'])
    def set_type_parameter(type_id, request):
        body = request.data
        elem = doc.GetElement(ElementId(type_id))
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
    def list_project_parameters():
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
    def bulk_update(request):
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
                        failed.append({'element_id': elem.Id.IntegerValue, 'reason': str(ex)})
            t.Commit()
        return Response(data={'updated_count': updated, 'failed': failed})
