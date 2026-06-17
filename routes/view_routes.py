# -*- coding: utf-8 -*-
"""
pyRevit Routes — View creation and management endpoints.
Runs INSIDE Revit. Registered in startup.py.
"""
import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import BoundingBoxXYZ, ElementId, FilteredElementCollector, Level, Transaction, View, ViewDuplicateOption, ViewFamilyType, ViewPlan, ViewSection, ViewType, XYZ
from pyrevit.routes import API, Response
_uidoc = getattr(__revit__, 'ActiveUIDocument', None)
doc = _uidoc.Document if _uidoc else None

def _view_to_dict(v):
    return {'element_id': v.Id.IntegerValue, 'name': v.Name, 'view_type': v.ViewType.ToString(), 'scale': v.Scale, 'detail_level': v.DetailLevel.ToString(), 'discipline': v.Discipline.ToString() if hasattr(v, 'Discipline') else None, 'is_template': v.IsTemplate, 'associated_level': v.GenLevel.Name if v.GenLevel else None}

def _find_level(level_name):
    for lvl in FilteredElementCollector(doc).OfClass(Level):
        if lvl.Name == level_name:
            return lvl
    return None

def _get_routes(api):

    @api.route('/views', methods=['GET'])
    def list_views(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        vtype = request.params.get('view_type')
        search = request.params.get('search', '').lower()
        excl_templates = request.params.get('exclude_template_views', 'true').lower() == 'true'
        results = []
        for v in FilteredElementCollector(doc).OfClass(View):
            if excl_templates and v.IsTemplate:
                continue
            if vtype and v.ViewType.ToString() != vtype:
                continue
            if search and search not in v.Name.lower():
                continue
            results.append(_view_to_dict(v))
        return Response(data=results)

    @api.route('/views/by_name', methods=['GET'])
    def get_view_by_name(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        name = request.params.get('view_name')
        for v in FilteredElementCollector(doc).OfClass(View):
            if v.Name == name:
                return Response(data=_view_to_dict(v))
        return Response(status_code=404, data={'error': "View '{}' not found".format(name)})

    @api.route('/views/templates', methods=['GET'])
    def list_templates(uiapp):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        results = [_view_to_dict(v) for v in FilteredElementCollector(doc).OfClass(View) if v.IsTemplate]
        return Response(data=results)

    @api.route('/views/create/floor_plan', methods=['POST'])
    def create_floor_plan(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        level = _find_level(body['level_name'])
        if level is None:
            return Response(status_code=404, data={'error': "Level '{}' not found".format(body['level_name'])})
        vft = next((t for t in FilteredElementCollector(doc).OfClass(ViewFamilyType) if t.ViewFamily.ToString() == 'FloorPlan'), None)
        if vft is None:
            return Response(status_code=404, data={'error': 'No FloorPlan view family type found'})
        with Transaction(doc, 'MCP: Create Floor Plan') as t:
            t.Start()
            view = ViewPlan.Create(doc, vft.Id, level.Id)
            view_name = body.get('view_name') or '{} - Floor Plan'.format(level.Name)
            try:
                view.Name = view_name
            except Exception:
                pass
            t.Commit()
        return Response(data={'element_id': view.Id.IntegerValue, 'name': view.Name})

    @api.route('/views/duplicate', methods=['POST'])
    def duplicate_view(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        src_name = body.get('source_view_name')
        new_name = body.get('new_view_name')
        with_detailing = body.get('with_detailing', False)
        src_view = next((v for v in FilteredElementCollector(doc).OfClass(View) if v.Name == src_name), None)
        if src_view is None:
            return Response(status_code=404, data={'error': "View '{}' not found".format(src_name)})
        option = ViewDuplicateOption.WithDetailing if with_detailing else ViewDuplicateOption.Duplicate
        with Transaction(doc, 'MCP: Duplicate View') as t:
            t.Start()
            new_id = src_view.Duplicate(option)
            new_view = doc.GetElement(new_id)
            try:
                new_view.Name = new_name
            except Exception:
                pass
            t.Commit()
        return Response(data={'element_id': new_id.IntegerValue, 'name': new_name})

    @api.route('/views/apply_template', methods=['POST'])
    def apply_template(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        view = next((v for v in FilteredElementCollector(doc).OfClass(View) if v.Name == body['view_name']), None)
        template = next((v for v in FilteredElementCollector(doc).OfClass(View) if v.IsTemplate and v.Name == body['template_name']), None)
        if not view:
            return Response(status_code=404, data={'error': "View '{}' not found".format(body['view_name'])})
        if not template:
            return Response(status_code=404, data={'error': "Template '{}' not found".format(body['template_name'])})
        with Transaction(doc, 'MCP: Apply View Template') as t:
            t.Start()
            view.ViewTemplateId = template.Id
            t.Commit()
        return Response(data={'view_name': body['view_name'], 'template_applied': body['template_name']})

    @api.route('/views/set_scale', methods=['POST'])
    def set_scale(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        view = next((v for v in FilteredElementCollector(doc).OfClass(View) if v.Name == body['view_name']), None)
        if not view:
            return Response(status_code=404, data={'error': "View '{}' not found".format(body['view_name'])})
        old_scale = view.Scale
        with Transaction(doc, 'MCP: Set View Scale') as t:
            t.Start()
            view.Scale = int(body['scale_denominator'])
            t.Commit()
        return Response(data={'view_name': body['view_name'], 'old_scale': old_scale, 'new_scale': view.Scale})

    @api.route('/views/set_detail_level', methods=['POST'])
    def set_detail_level(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        from Autodesk.Revit.DB import ViewDetailLevel
        body = request.data
        view = next((v for v in FilteredElementCollector(doc).OfClass(View) if v.Name == body['view_name']), None)
        if not view:
            return Response(status_code=404, data={'error': 'View not found'})
        level_map = {'Coarse': ViewDetailLevel.Coarse, 'Medium': ViewDetailLevel.Medium, 'Fine': ViewDetailLevel.Fine}
        with Transaction(doc, 'MCP: Set Detail Level') as t:
            t.Start()
            view.DetailLevel = level_map.get(body['detail_level'], ViewDetailLevel.Medium)
            t.Commit()
        return Response(data={'view_name': body['view_name'], 'detail_level': body['detail_level']})

    @api.route('/views/rename', methods=['POST'])
    def rename_view(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        view = next((v for v in FilteredElementCollector(doc).OfClass(View) if v.Name == body['old_name']), None)
        if not view:
            return Response(status_code=404, data={'error': 'View not found'})
        with Transaction(doc, 'MCP: Rename View') as t:
            t.Start()
            view.Name = body['new_name']
            t.Commit()
        return Response(data={'old_name': body['old_name'], 'new_name': body['new_name']})

    @api.route('/views', methods=['DELETE'])
    def delete_view(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        view_name = request.data.get('view_name')
        view = next((v for v in FilteredElementCollector(doc).OfClass(View) if v.Name == view_name), None)
        if not view:
            return Response(status_code=404, data={'error': 'View not found'})
        with Transaction(doc, 'MCP: Delete View') as t:
            t.Start()
            doc.Delete(view.Id)
            t.Commit()
        return Response(data={'deleted': view_name})
