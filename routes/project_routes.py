# -*- coding: utf-8 -*-
"""
pyRevit Routes — Project and document information endpoints.

These functions run INSIDE Revit via the pyRevit Routes API.
They are registered in startup.py using @routes.get / @routes.post decorators.
"""
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import FilteredElementCollector, FailureMessage, BuiltInCategory
import Autodesk.Revit.ApplicationServices as AppServices
from pyrevit.routes import API, Response
app = __revit__.Application
_uidoc = getattr(__revit__, 'ActiveUIDocument', None)
doc = _uidoc.Document if _uidoc else None

def _idv(eid):
    """ElementId integer value. Revit 2024+ uses .Value (Int64); older uses .IntegerValue."""
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue

def _get_routes(api):
    """Register all project-related routes on the provided API object."""

    @api.route('/ping', methods=['GET'])
    def ping(uiapp):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        return Response(data={'status': 'ok', 'revit_version': app.VersionNumber, 'revit_build': app.VersionBuild, 'pyrevit_version': 'pyrevit', 'document_open': doc is not None and (not doc.IsDetached), 'document_title': doc.Title if doc else None})

    @api.route('/application/version', methods=['GET'])
    def get_version(uiapp):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        return Response(data={'version_number': app.VersionNumber, 'version_name': app.VersionName, 'version_build': app.VersionBuild, 'sub_version': app.SubVersionNumber, 'language': str(app.Language)})

    @api.route('/project/info', methods=['GET'])
    def get_project_info(uiapp):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        info = doc.ProjectInformation
        return Response(data={'project_name': info.Name, 'project_number': info.Number, 'client_name': info.ClientName, 'building_name': info.BuildingName, 'address': info.Address, 'issue_date': info.IssueDate, 'status': info.Status, 'author': info.Author, 'file_path': doc.PathName, 'revit_version': app.VersionNumber, 'is_workshared': doc.IsWorkshared, 'is_detached': doc.IsDetached})

    @api.route('/project/info/set', methods=['POST'])
    def set_project_parameter(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        param_name = body.get('param_name')
        value = body.get('value', '')
        info = doc.ProjectInformation
        param = info.LookupParameter(param_name)
        if param is None:
            return Response(status_code=404, data={'error': "Parameter '{}' not found".format(param_name)})
        old_value = param.AsString() or ''
        from Autodesk.Revit.DB import Transaction
        with Transaction(doc, 'Set project parameter: {}'.format(param_name)) as t:
            t.Start()
            param.Set(value)
            t.Commit()
        return Response(data={'param_name': param_name, 'old_value': old_value, 'new_value': value})

    @api.route('/project/stats', methods=['GET'])
    def get_document_stats(uiapp):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        collector = FilteredElementCollector(doc)
        all_elements = collector.WhereElementIsNotElementType().ToElements()
        category_counts = {}
        for elem in all_elements:
            if elem.Category:
                cat_name = elem.Category.Name
                category_counts[cat_name] = category_counts.get(cat_name, 0) + 1
        return Response(data={'total_elements': len(list(all_elements)), 'category_counts': category_counts, 'file_path': doc.PathName})

    @api.route('/project/warnings', methods=['GET'])
    def get_warnings(uiapp):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        warnings = doc.GetWarnings()
        result = []
        for w in warnings:
            result.append({'description': w.GetDescriptionText(), 'element_ids': [_idv(eid) for eid in w.GetFailingElements()]})
        return Response(data=result)

    @api.route('/project/links', methods=['GET'])
    def get_links(uiapp):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        from Autodesk.Revit.DB import RevitLinkInstance
        collector = FilteredElementCollector(doc).OfClass(RevitLinkInstance)
        result = []
        for link in collector:
            link_doc = link.GetLinkDocument()
            result.append({'element_id': _idv(link.Id), 'name': link.Name, 'status': 'loaded' if link_doc is not None else 'unloaded', 'path': link_doc.PathName if link_doc else None})
        return Response(data=result)
