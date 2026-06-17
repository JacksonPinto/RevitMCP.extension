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
    return {'element_id': room.Id.IntegerValue, 'number': room.Number, 'name': room.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.ROOM_NAME).AsString() if room.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.ROOM_NAME) else room.Name, 'level': room.Level.Name if room.Level else None, 'area': room.Area, 'perimeter': room.Perimeter}

def _get_routes(api):

    @api.route('/rooms', methods=['GET'])
    def list_rooms(request):
        level_name = request.params.get('level_name')
        search = request.params.get('search', '').lower()
        unplaced = request.params.get('unplaced_only', 'false').lower() == 'true'
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
    def get_room(request):
        number = request.params.get('room_number')
        room = next((r for r in FilteredElementCollector(doc).WherePasses(RoomFilter()) if r.Number == number), None)
        if not room:
            return Response(status_code=404, data={'error': "Room '{}' not found".format(number)})
        return Response(data=_room_to_dict(room))

    @api.route('/rooms/create', methods=['POST'])
    def create_room(request):
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
        return Response(data={'element_id': room.Id.IntegerValue, 'number': room.Number, 'name': room.Name})

    @api.route('/rooms/at_point', methods=['GET'])
    def get_room_at_point(request):
        from Autodesk.Revit.DB import XYZ
        x = float(request.params.get('x', 0))
        y = float(request.params.get('y', 0))
        level_name = request.params.get('level_name')
        level = next((l for l in FilteredElementCollector(doc).OfClass(Level) if l.Name == level_name), None)
        if not level:
            return Response(status_code=404, data={'error': 'Level not found'})
        pt = XYZ(x, y, level.Elevation)
        room = doc.GetRoomAtPoint(pt)
        if room:
            return Response(data={'room': _room_to_dict(room)})
        return Response(data={'room': None})

    @api.route('/spaces', methods=['GET'])
    def list_spaces(request):
        level_name = request.params.get('level_name')
        results = []
        try:
            for space in FilteredElementCollector(doc).WherePasses(SpaceFilter()):
                if level_name and space.Level and (space.Level.Name != level_name):
                    continue
                results.append({'element_id': space.Id.IntegerValue, 'number': space.Number, 'name': space.Name, 'level': space.Level.Name if space.Level else None, 'area': space.Area})
        except Exception:
            pass
        return Response(data=results)
