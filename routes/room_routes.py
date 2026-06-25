# -*- coding: utf-8 -*-
"""pyRevit Routes — Room and space endpoints."""
import clr
clr.AddReference('RevitAPI')
import Autodesk
from Autodesk.Revit.DB import ElementId, FilteredElementCollector, Level, Transaction, XYZ
from Autodesk.Revit.DB.Architecture import Room, RoomFilter
from Autodesk.Revit.DB.Mechanical import SpaceFilter
from pyrevit.routes import API, Response
_uidoc = getattr(__revit__, 'ActiveUIDocument', None)
doc = _uidoc.Document if _uidoc else None

def _room_to_dict(room):
    return {'element_id': _idv(room.Id), 'number': room.Number, 'name': room.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.ROOM_NAME).AsString() if room.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.ROOM_NAME) else _safe_name(room), 'level': _safe_name(room.Level) if room.Level else None, 'area': room.Area, 'perimeter': room.Perimeter}

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

def _spatial_dict(el):
    """Robust room/space summary (2026-safe): number, name, level, area via params."""
    BIP = Autodesk.Revit.DB.BuiltInParameter

    def _ps(bip):
        try:
            p = el.get_Parameter(bip)
            return p.AsString() if p else None
        except Exception:
            return None
    num = _ps(BIP.ROOM_NUMBER)
    if not num:
        try:
            num = el.Number
        except Exception:
            num = None
    name = _ps(BIP.ROOM_NAME)
    if not name:
        try:
            name = _safe_name(el)
        except Exception:
            name = None
    try:
        lvl = _safe_name(el.Level) if el.Level else None
    except Exception:
        lvl = None
    try:
        area = el.Area
    except Exception:
        area = None
    return {'element_id': _idv(el.Id), 'number': num, 'name': name, 'level': lvl, 'area': area}

def _safe_cat2(elem):
    try:
        return _safe_name(elem.Category) if elem.Category else None
    except Exception:
        return None

def _loc_point(elem):
    """Representative XYZ for an element: location point, curve midpoint, or bbox centre."""
    try:
        loc = elem.Location
        if loc is not None:
            from Autodesk.Revit.DB import LocationPoint, LocationCurve
            if isinstance(loc, LocationPoint):
                return loc.Point
            if isinstance(loc, LocationCurve):
                c = loc.Curve
                a = c.GetEndPoint(0)
                b = c.GetEndPoint(1)
                return XYZ((a.X + b.X) / 2.0, (a.Y + b.Y) / 2.0, (a.Z + b.Z) / 2.0)
    except Exception:
        pass
    try:
        bb = elem.get_BoundingBox(None)
        if bb is not None:
            return XYZ((bb.Min.X + bb.Max.X) / 2.0, (bb.Min.Y + bb.Max.Y) / 2.0, (bb.Min.Z + bb.Max.Z) / 2.0)
    except Exception:
        pass
    return None

def _el_brief(elem):
    nm = None
    try:
        nm = _safe_name(elem)
    except Exception:
        pass
    tnm = None
    try:
        t = doc.GetElement(elem.GetTypeId())
        if t is not None:
            try:
                tnm = _safe_name(t)
            except Exception:
                tnm = None
    except Exception:
        pass
    return {'element_id': _idv(elem.Id), 'category': _safe_cat2(elem), 'name': nm, 'type_name': tnm}

def _near_candidates(spatial):
    """Fast bbox prefilter: elements whose bounding box is near the room/space."""
    coll = FilteredElementCollector(doc).WhereElementIsNotElementType()
    try:
        from Autodesk.Revit.DB import Outline, BoundingBoxIntersectsFilter
        bb = spatial.get_BoundingBox(None)
        if bb is not None:
            coll = coll.WherePasses(BoundingBoxIntersectsFilter(Outline(bb.Min, bb.Max)))
    except Exception:
        pass
    return coll

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

def _mkid(i):
    """Build an ElementId from an int (Revit 2026: force Int64 overload to avoid
    ambiguity with ElementId(BuiltInParameter)/(BuiltInCategory))."""
    import System
    return ElementId(System.Int64(i))

def _safe_name(el):
    try:
        return el.Name
    except Exception:
        return None

def _get_routes(api):

    @api.route('/rooms', methods=['GET'])
    def list_rooms(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        level_name = _qp(request).get('level_name')
        search = _qp(request).get('search', '').lower()
        unplaced = _qp(request).get('unplaced_only', 'false').lower() == 'true'
        results = []
        for room in FilteredElementCollector(doc).WherePasses(RoomFilter()):
            if unplaced and room.Area > 0:
                continue
            if level_name and room.Level and (_safe_name(room.Level) != level_name):
                continue
            d = _room_to_dict(room)
            if search and search not in d['number'].lower() and (search not in d['name'].lower()):
                continue
            results.append(d)
        return Response(data=results)

    @api.route('/rooms/by_number', methods=['GET'])
    def get_room(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        number = _qp(request).get('room_number')
        room = next((r for r in FilteredElementCollector(doc).WherePasses(RoomFilter()) if r.Number == number), None)
        if not room:
            return Response(status_code=404, data={'error': "Room '{}' not found".format(number)})
        return Response(data=_room_to_dict(room))

    @api.route('/rooms/create', methods=['POST'])
    def create_room(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        body = request.data
        level = next((l for l in FilteredElementCollector(doc).OfClass(Level) if _safe_name(l) == body['level_name']), None)
        if not level:
            return Response(status_code=404, data={'error': 'Level not found'})
        from Autodesk.Revit.DB import UV
        pt = UV(body['x'], body['y'])
        with Transaction(doc, 'MCP: Create Room') as t:
            t.Start()
            room = doc.Create.NewRoom(level, pt)
            if body.get('room_number'):
                room.Number = body['room_number']
            if body.get('room_name'):
                room.Name = body['room_name']
            t.Commit()
        return Response(data={'element_id': _idv(room.Id), 'number': room.Number, 'name': _safe_name(room)})

    @api.route('/rooms/at_point', methods=['GET'])
    def get_room_at_point(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        from Autodesk.Revit.DB import XYZ
        x = float(_qp(request).get('x', 0))
        y = float(_qp(request).get('y', 0))
        level_name = _qp(request).get('level_name')
        level = next((l for l in FilteredElementCollector(doc).OfClass(Level) if _safe_name(l) == level_name), None)
        if not level:
            return Response(status_code=404, data={'error': 'Level not found'})
        pt = XYZ(x, y, level.Elevation)
        room = doc.GetRoomAtPoint(pt)
        if room:
            return Response(data={'room': _room_to_dict(room)})
        return Response(data={'room': None})

    @api.route('/spaces', methods=['GET'])
    def list_spaces(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        results = []
        for space in FilteredElementCollector(doc).WherePasses(SpaceFilter()):
            try:
                results.append(_spatial_dict(space))
            except Exception:
                pass
        return Response(data={'count': len(results), 'spaces': results})

    @api.route('/spaces/active_view', methods=['GET'])
    def list_spaces_active_view(uiapp):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        av = doc.ActiveView
        results = []
        for space in FilteredElementCollector(doc, av.Id).WherePasses(SpaceFilter()):
            try:
                results.append(_spatial_dict(space))
            except Exception:
                pass
        return Response(data={'active_view': _safe_name(av), 'count': len(results), 'spaces': results})

    @api.route('/rooms/active_view', methods=['GET'])
    def list_rooms_active_view(uiapp):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        av = doc.ActiveView
        results = []
        for room in FilteredElementCollector(doc, av.Id).WherePasses(RoomFilter()):
            try:
                results.append(_spatial_dict(room))
            except Exception:
                pass
        return Response(data={'active_view': _safe_name(av), 'count': len(results), 'rooms': results})

    @api.route('/spaces/<int:space_id>/contents', methods=['GET'])
    def space_contents(uiapp, space_id):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        space = doc.GetElement(_mkid(space_id))
        if space is None:
            return Response(status_code=404, data={'error': 'Space not found'})
        counts = {}
        total = 0
        for elem in _near_candidates(space):
            pt = _loc_point(elem)
            if pt is None:
                continue
            try:
                inside = space.IsPointInSpace(pt)
            except Exception:
                inside = False
            if inside:
                c = _safe_cat2(elem) or 'Unknown'
                counts[c] = counts.get(c, 0) + 1
                total += 1
        cats = [{'category': k, 'count': v} for (k, v) in sorted(counts.items(), key=lambda kv: -kv[1])]
        return Response(data={'space': _spatial_dict(space), 'total': total, 'by_category': cats})

    @api.route('/spaces/<int:space_id>/contents/<category>', methods=['GET'])
    def space_contents_category(uiapp, space_id, category):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        category = _unq(category)
        space = doc.GetElement(_mkid(space_id))
        if space is None:
            return Response(status_code=404, data={'error': 'Space not found'})
        results = []
        for elem in _near_candidates(space):
            if _safe_cat2(elem) != category:
                continue
            pt = _loc_point(elem)
            if pt is None:
                continue
            try:
                if space.IsPointInSpace(pt):
                    results.append(_el_brief(elem))
            except Exception:
                pass
        return Response(data={'space_id': space_id, 'category': category, 'count': len(results), 'elements': results})

    @api.route('/rooms/<int:room_id>/contents', methods=['GET'])
    def room_contents(uiapp, room_id):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        room = doc.GetElement(_mkid(room_id))
        if room is None:
            return Response(status_code=404, data={'error': 'Room not found'})
        counts = {}
        total = 0
        for elem in _near_candidates(room):
            pt = _loc_point(elem)
            if pt is None:
                continue
            try:
                inside = room.IsPointInRoom(pt)
            except Exception:
                inside = False
            if inside:
                c = _safe_cat2(elem) or 'Unknown'
                counts[c] = counts.get(c, 0) + 1
                total += 1
        cats = [{'category': k, 'count': v} for (k, v) in sorted(counts.items(), key=lambda kv: -kv[1])]
        return Response(data={'room': _spatial_dict(room), 'total': total, 'by_category': cats})

    @api.route('/rooms/<int:room_id>/contents/<category>', methods=['GET'])
    def room_contents_category(uiapp, room_id, category):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        category = _unq(category)
        room = doc.GetElement(_mkid(room_id))
        if room is None:
            return Response(status_code=404, data={'error': 'Room not found'})
        results = []
        for elem in _near_candidates(room):
            if _safe_cat2(elem) != category:
                continue
            pt = _loc_point(elem)
            if pt is None:
                continue
            try:
                if room.IsPointInRoom(pt):
                    results.append(_el_brief(elem))
            except Exception:
                pass
        return Response(data={'room_id': room_id, 'category': category, 'count': len(results), 'elements': results})
