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
    return {'element_id': _idv(room.Id), 'number': room.Number, 'name': room.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.ROOM_NAME).AsString() if room.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.ROOM_NAME) else room.Name, 'level': room.Level.Name if room.Level else None, 'area': room.Area, 'perimeter': room.Perimeter}

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
            if level_name and room.Level and (room.Level.Name != level_name):
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
        level = next((l for l in FilteredElementCollector(doc).OfClass(Level) if l.Name == body['level_name']), None)
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
        return Response(data={'element_id': _idv(room.Id), 'number': room.Number, 'name': room.Name})

    @api.route('/rooms/at_point', methods=['GET'])
    def get_room_at_point(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        from Autodesk.Revit.DB import XYZ
        x = float(_qp(request).get('x', 0))
        y = float(_qp(request).get('y', 0))
        level_name = _qp(request).get('level_name')
        level = next((l for l in FilteredElementCollector(doc).OfClass(Level) if l.Name == level_name), None)
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
        level_name = _qp(request).get('level_name')
        results = []
        try:
            for space in FilteredElementCollector(doc).WherePasses(SpaceFilter()):
                if level_name and space.Level and (space.Level.Name != level_name):
                    continue
                results.append({'element_id': _idv(space.Id), 'number': space.Number, 'name': space.Name, 'level': space.Level.Name if space.Level else None, 'area': space.Area})
        except Exception:
            pass
        return Response(data=results)
