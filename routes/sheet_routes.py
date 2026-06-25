# -*- coding: utf-8 -*-
"""
pyRevit Routes — Sheet management endpoints.
Runs INSIDE Revit. Registered in startup.py.
"""
import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import ElementId, FamilySymbol, FilteredElementCollector, Transaction, ViewSheet, Viewport, XYZ
from pyrevit.routes import API, Response
_uidoc = getattr(__revit__, 'ActiveUIDocument', None)
doc = _uidoc.Document if _uidoc else None

def _sheet_to_dict(sheet):
    views_on_sheet = [{'viewport_id': _idv(vp.Id), 'view_name': _safe_name(doc.GetElement(vp.ViewId))} for vp in FilteredElementCollector(doc, sheet.Id).OfClass(Viewport)]
    return {'element_id': _idv(sheet.Id), 'sheet_number': sheet.SheetNumber, 'sheet_name': _safe_name(sheet), 'views': views_on_sheet}

def _find_sheet(number):
    for s in FilteredElementCollector(doc).OfClass(ViewSheet):
        if s.SheetNumber == number:
            return s
    return None

def _unq(s):
    """Minimal URL-decode for IronPython 2.7 (handles %XX and +)."""
    try:
        s = s.replace('+', ' ')
        out = []
        i = 0
        while i < len(s):
            if s[i] == '%' and i + 2 < len(s) + 1:
                try:
                    out.append(chr(int(s[i + 1:i + 3], 16)))
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
                if k is None and isinstance(x, (list, tuple)) and (len(x) == 2):
                    (k, v) = (x[0], x[1])
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
                if val and isinstance(val, str) and ('?' in val):
                    qs = val.split('?', 1)[1]
                    break
        if qs:
            for pair in qs.split('&'):
                if '=' in pair:
                    (k, v) = pair.split('=', 1)
                    out[_unq(k)] = _unq(v)
    return out

def _idv(eid):
    """ElementId integer value. Revit 2024+ uses .Value (Int64); older uses .IntegerValue."""
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue

def _safe_name(el):
    try:
        return el.Name
    except Exception:
        return None

def _get_routes(api):

    @api.route('/sheets', methods=['GET'])
    def list_sheets(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        search = _qp(request).get('search', '').lower()
        results = []
        for s in FilteredElementCollector(doc).OfClass(ViewSheet):
            if search and search not in s.SheetNumber.lower() and (search not in _safe_name(s).lower()):
                continue
            results.append(_sheet_to_dict(s))
        return Response(data=results)

    @api.route('/sheets/by_number', methods=['GET'])
    def get_sheet(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        number = _qp(request).get('sheet_number')
        sheet = _find_sheet(number)
        if not sheet:
            return Response(status_code=404, data={'error': "Sheet '{}' not found".format(number)})
        return Response(data=_sheet_to_dict(sheet))

    @api.route('/sheets/create', methods=['POST'])
    def create_sheet(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        tb_id = ElementId.InvalidElementId
        tb_family = body.get('titleblock_family')
        if tb_family:
            for sym in FilteredElementCollector(doc).OfClass(FamilySymbol):
                if sym.FamilyName == tb_family:
                    tb_id = sym.Id
                    break
        else:
            tb_types = [s for s in FilteredElementCollector(doc).OfClass(FamilySymbol) if s.Category and 'Title Block' in _safe_name(s.Category)]
            if tb_types:
                tb_id = tb_types[0].Id
        with Transaction(doc, 'MCP: Create Sheet') as t:
            t.Start()
            sheet = ViewSheet.Create(doc, tb_id)
            sheet.SheetNumber = body['sheet_number']
            sheet.Name = body['sheet_name']
            t.Commit()
        return Response(data={'element_id': _idv(sheet.Id), 'sheet_number': sheet.SheetNumber, 'sheet_name': _safe_name(sheet)})

    @api.route('/sheets/create_bulk', methods=['POST'])
    def create_sheets_bulk(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        sheets_data = body.get('sheets', [])
        tb_id = ElementId.InvalidElementId
        tb_family = body.get('titleblock_family')
        if tb_family:
            for sym in FilteredElementCollector(doc).OfClass(FamilySymbol):
                if sym.FamilyName == tb_family:
                    tb_id = sym.Id
                    break
        created = []
        failed = []
        with Transaction(doc, 'MCP: Create Sheets Bulk') as t:
            t.Start()
            for sd in sheets_data:
                try:
                    sheet = ViewSheet.Create(doc, tb_id)
                    sheet.SheetNumber = sd['sheet_number']
                    sheet.Name = sd['sheet_name']
                    created.append({'sheet_number': sd['sheet_number'], 'element_id': _idv(sheet.Id)})
                except Exception as ex:
                    failed.append({'sheet_number': sd.get('sheet_number'), 'reason': str(ex)})
            t.Commit()
        return Response(data={'created_count': len(created), 'created': created, 'failed': failed})

    @api.route('/sheets/place_view', methods=['POST'])
    def place_view(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        view_name = body.get('view_name')
        sheet_number = body.get('sheet_number')
        auto_center = body.get('auto_center', False)
        sheet = _find_sheet(sheet_number)
        if not sheet:
            return Response(status_code=404, data={'error': "Sheet '{}' not found".format(sheet_number)})
        from Autodesk.Revit.DB import View
        view = next((v for v in FilteredElementCollector(doc).OfClass(View) if _safe_name(v) == view_name), None)
        if not view:
            return Response(status_code=404, data={'error': "View '{}' not found".format(view_name)})
        if auto_center:
            bb = sheet.get_BoundingBox(None)
            center = XYZ((bb.Min.X + bb.Max.X) / 2, (bb.Min.Y + bb.Max.Y) / 2, 0)
        else:
            center = XYZ(body.get('x', 0), body.get('y', 0), 0)
        with Transaction(doc, 'MCP: Place View on Sheet') as t:
            t.Start()
            vp = Viewport.Create(doc, sheet.Id, view.Id, center)
            t.Commit()
        return Response(data={'viewport_id': _idv(vp.Id), 'view_name': view_name, 'sheet_number': sheet_number})

    @api.route('/sheets/views', methods=['GET'])
    def list_views_on_sheet(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        number = _qp(request).get('sheet_number')
        sheet = _find_sheet(number)
        if not sheet:
            return Response(status_code=404, data={'error': 'Sheet not found'})
        results = []
        for vp in FilteredElementCollector(doc, sheet.Id).OfClass(Viewport):
            v = doc.GetElement(vp.ViewId)
            results.append({'viewport_id': _idv(vp.Id), 'view_name': _safe_name(v) if v else None, 'view_type': v.ViewType.ToString() if v else None})
        return Response(data=results)

    @api.route('/sheets/remove_view', methods=['DELETE'])
    def remove_view(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        sheet = _find_sheet(body['sheet_number'])
        if not sheet:
            return Response(status_code=404, data={'error': 'Sheet not found'})
        vp = next((v for v in FilteredElementCollector(doc, sheet.Id).OfClass(Viewport) if _safe_name(doc.GetElement(v.ViewId)) == body['view_name']), None)
        if not vp:
            return Response(status_code=404, data={'error': 'Viewport not found on sheet'})
        with Transaction(doc, 'MCP: Remove View from Sheet') as t:
            t.Start()
            doc.Delete(vp.Id)
            t.Commit()
        return Response(data={'removed': body['view_name'], 'from_sheet': body['sheet_number']})

    @api.route('/sheets/set_parameter', methods=['POST'])
    def set_sheet_parameter(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        sheet = _find_sheet(body['sheet_number'])
        if not sheet:
            return Response(status_code=404, data={'error': 'Sheet not found'})
        param = sheet.LookupParameter(body['param_name'])
        if not param:
            return Response(status_code=404, data={'error': "Parameter '{}' not found".format(body['param_name'])})
        old_val = param.AsString() or param.AsValueString()
        with Transaction(doc, 'MCP: Set sheet parameter {}'.format(body['param_name'])) as t:
            t.Start()
            param.Set(str(body['value']))
            t.Commit()
        return Response(data={'param_name': body['param_name'], 'old_value': old_val, 'new_value': body['value']})

    @api.route('/sheets/renumber', methods=['POST'])
    def renumber_sheet(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        sheet = _find_sheet(body['old_number'])
        if not sheet:
            return Response(status_code=404, data={'error': 'Sheet not found'})
        with Transaction(doc, 'MCP: Renumber Sheet') as t:
            t.Start()
            sheet.SheetNumber = body['new_number']
            t.Commit()
        return Response(data={'old_number': body['old_number'], 'new_number': body['new_number']})

    @api.route('/sheets/titleblocks', methods=['GET'])
    def list_titleblocks(uiapp):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        results = []
        for sym in FilteredElementCollector(doc).OfClass(FamilySymbol):
            if sym.Category and 'Title Block' in _safe_name(sym.Category):
                results.append({'family_name': sym.FamilyName, 'type_name': _safe_name(sym), 'element_id': _idv(sym.Id)})
        return Response(data=results)
