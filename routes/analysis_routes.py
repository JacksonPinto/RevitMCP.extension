# -*- coding: utf-8 -*-
"""pyRevit Routes — Analysis and geometry endpoints."""
import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import BoundingBoxXYZ, BoundingBoxIntersectsFilter, ElementId, FilteredElementCollector, Level, Outline, View, XYZ
from Autodesk.Revit.DB.Architecture import RoomFilter
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

    @api.route('/elements/<int:element_id>/bounding_box', methods=['GET'])
    def get_bounding_box(uiapp, element_id):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        elem = doc.GetElement(ElementId(element_id))
        if not elem:
            return Response(status_code=404, data={'error': 'Element not found'})
        bb = elem.get_BoundingBox(None)
        if not bb:
            return Response(data={'element_id': element_id, 'bounding_box': None})
        return Response(data={'min': {'x': bb.Min.X, 'y': bb.Min.Y, 'z': bb.Min.Z}, 'max': {'x': bb.Max.X, 'y': bb.Max.Y, 'z': bb.Max.Z}, 'width': abs(bb.Max.X - bb.Min.X), 'depth': abs(bb.Max.Y - bb.Min.Y), 'height': abs(bb.Max.Z - bb.Min.Z)})

    @api.route('/model/extents', methods=['GET'])
    def get_model_extents(uiapp):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        all_elems = FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements()
        min_x = min_y = min_z = float('inf')
        max_x = max_y = max_z = float('-inf')
        for elem in all_elems:
            try:
                bb = elem.get_BoundingBox(None)
                if bb:
                    min_x = min(min_x, bb.Min.X)
                    min_y = min(min_y, bb.Min.Y)
                    min_z = min(min_z, bb.Min.Z)
                    max_x = max(max_x, bb.Max.X)
                    max_y = max(max_y, bb.Max.Y)
                    max_z = max(max_z, bb.Max.Z)
            except Exception:
                pass
        return Response(data={'min': {'x': min_x, 'y': min_y, 'z': min_z}, 'max': {'x': max_x, 'y': max_y, 'z': max_z}, 'width': abs(max_x - min_x), 'depth': abs(max_y - min_y), 'height': abs(max_z - min_z)})

    @api.route('/analysis/room_areas', methods=['GET'])
    def room_areas(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        level_name = _qp(request).get('level_name')
        level_areas = {}
        for room in FilteredElementCollector(doc).WherePasses(RoomFilter()):
            if room.Area <= 0:
                continue
            lvl = room.Level.Name if room.Level else 'Unknown'
            if level_name and lvl != level_name:
                continue
            if lvl not in level_areas:
                level_areas[lvl] = {'level': lvl, 'total_area': 0, 'room_count': 0}
            level_areas[lvl]['total_area'] += room.Area
            level_areas[lvl]['room_count'] += 1
        result = list(level_areas.values())
        for row in result:
            if row['room_count'] > 0:
                row['avg_area'] = row['total_area'] / row['room_count']
        return Response(data=result)

    @api.route('/analysis/area_by_category', methods=['GET'])
    def area_by_category(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        category_name = _qp(request).get('category', 'Floors')
        level_name = _qp(request).get('level_name')
        total = 0
        breakdown = {}
        for elem in FilteredElementCollector(doc).WhereElementIsNotElementType():
            if not (elem.Category and elem.Category.Name == category_name):
                continue
            if level_name:
                lvl_p = elem.LookupParameter('Level') or elem.LookupParameter('Reference Level')
                if lvl_p and level_name not in (lvl_p.AsValueString() or ''):
                    continue
            area_param = elem.LookupParameter('Area')
            if area_param:
                area_val = area_param.AsDouble()
                total += area_val
                type_elem = doc.GetElement(elem.GetTypeId())
                type_name = type_elem.Name if type_elem else 'Unknown'
                breakdown[type_name] = breakdown.get(type_name, 0) + area_val
        return Response(data={'category': category_name, 'total_area': total, 'element_count': len(breakdown), 'breakdown': [{'type_name': k, 'area': v} for (k, v) in breakdown.items()]})

    @api.route('/elements/<int:element_id>/volume', methods=['GET'])
    def get_volume(uiapp, element_id):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        elem = doc.GetElement(ElementId(element_id))
        if not elem:
            return Response(status_code=404, data={'error': 'Element not found'})
        vol_param = elem.LookupParameter('Volume')
        vol = vol_param.AsDouble() if vol_param else 0
        return Response(data={'element_id': element_id, 'volume': vol, 'category': elem.Category.Name if elem.Category else None})

    @api.route('/analysis/elements_in_box', methods=['POST'])
    def elements_in_box(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        outline = Outline(XYZ(body['min_x'], body['min_y'], body['min_z']), XYZ(body['max_x'], body['max_y'], body['max_z']))
        bb_filter = BoundingBoxIntersectsFilter(outline)
        collector = FilteredElementCollector(doc).WherePasses(bb_filter).WhereElementIsNotElementType()
        category_filter = body.get('category')
        results = []
        for elem in collector:
            if category_filter and (not (elem.Category and elem.Category.Name == category_filter)):
                continue
            results.append({'element_id': _idv(elem.Id), 'category': elem.Category.Name if elem.Category else None})
        return Response(data=results)

    @api.route('/analysis/clash_detection', methods=['POST'])
    def clash_detection(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        cat_a = body.get('category_a')
        cat_b = body.get('category_b')
        tolerance = float(body.get('tolerance', 0))
        elems_a = [e for e in FilteredElementCollector(doc).WhereElementIsNotElementType() if e.Category and e.Category.Name == cat_a]
        elems_b = [e for e in FilteredElementCollector(doc).WhereElementIsNotElementType() if e.Category and e.Category.Name == cat_b]
        clashes = []
        for a in elems_a:
            bb_a = a.get_BoundingBox(None)
            if not bb_a:
                continue
            for b in elems_b:
                if a.Id == b.Id:
                    continue
                bb_b = b.get_BoundingBox(None)
                if not bb_b:
                    continue
                overlap_x = min(bb_a.Max.X, bb_b.Max.X) - max(bb_a.Min.X, bb_b.Min.X)
                overlap_y = min(bb_a.Max.Y, bb_b.Max.Y) - max(bb_a.Min.Y, bb_b.Min.Y)
                overlap_z = min(bb_a.Max.Z, bb_b.Max.Z) - max(bb_a.Min.Z, bb_b.Min.Z)
                if overlap_x > tolerance and overlap_y > tolerance and (overlap_z > tolerance):
                    clashes.append({'element_a_id': _idv(a.Id), 'element_b_id': _idv(b.Id), 'overlap_mm': min(overlap_x, overlap_y, overlap_z) * 304.8})
        return Response(data={'clash_count': len(clashes), 'clashes': clashes})

    @api.route('/analysis/model_summary', methods=['GET'])
    def model_summary(uiapp):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        info = doc.ProjectInformation
        all_elems = list(FilteredElementCollector(doc).WhereElementIsNotElementType())
        cat_counts = {}
        for e in all_elems:
            if e.Category:
                cn = e.Category.Name
                cat_counts[cn] = cat_counts.get(cn, 0) + 1
        top_cats = sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)[:20]
        levels = sorted(FilteredElementCollector(doc).OfClass(Level), key=lambda l: l.Elevation)
        from Autodesk.Revit.DB import ViewSheet
        sheet_count = sum((1 for _ in FilteredElementCollector(doc).OfClass(ViewSheet)))
        from Autodesk.Revit.DB import View
        view_count = sum((1 for v in FilteredElementCollector(doc).OfClass(View) if not v.IsTemplate))
        warnings = doc.GetWarnings()
        return Response(data={'project_name': info.Name, 'project_number': info.Number, 'level_count': len(list(levels)), 'levels': [{'name': l.Name, 'elevation_ft': l.Elevation} for l in levels], 'sheet_count': sheet_count, 'view_count': view_count, 'warning_count': len(list(warnings)), 'top_categories': [{'category': k, 'count': v} for (k, v) in top_cats], 'total_elements': len(all_elems), 'file_path': doc.PathName})
