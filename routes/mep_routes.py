# -*- coding: utf-8 -*-
"""pyRevit Routes — MEP endpoints."""
import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import BuiltInCategory, BuiltInParameter, FilteredElementCollector
from Autodesk.Revit.DB.Mechanical import Duct, MechanicalSystem, Space
from Autodesk.Revit.DB.Plumbing import Pipe, PipingSystem
from Autodesk.Revit.DB.Electrical import ElectricalSystem
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

    @api.route('/mep/systems', methods=['GET'])
    def list_systems(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        system_type = _qp(request).get('system_type')
        results = []
        try:
            for sys in FilteredElementCollector(doc).OfClass(MechanicalSystem):
                if system_type and system_type != 'DuctSystem':
                    continue
                results.append({'type': 'DuctSystem', 'name': sys.Name, 'element_id': _idv(sys.Id)})
        except Exception:
            pass
        try:
            for sys in FilteredElementCollector(doc).OfClass(PipingSystem):
                if system_type and system_type != 'PipingSystem':
                    continue
                results.append({'type': 'PipingSystem', 'name': sys.Name, 'element_id': _idv(sys.Id)})
        except Exception:
            pass
        return Response(data=results)

    @api.route('/mep/ducts', methods=['GET'])
    def list_ducts(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        level_name = _qp(request).get('level_name')
        results = []
        try:
            for duct in FilteredElementCollector(doc).OfClass(Duct):
                d = {'element_id': _idv(duct.Id), 'length': duct.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH).AsDouble() if duct.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH) else 0}
                results.append(d)
        except Exception:
            pass
        return Response(data=results)

    @api.route('/mep/pipes', methods=['GET'])
    def list_pipes(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        results = []
        try:
            for pipe in FilteredElementCollector(doc).OfClass(Pipe):
                results.append({'element_id': _idv(pipe.Id), 'diameter': pipe.Diameter if hasattr(pipe, 'Diameter') else 0})
        except Exception:
            pass
        return Response(data=results)

    @api.route('/mep/circuits', methods=['GET'])
    def list_circuits(uiapp):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        results = []
        try:
            for circuit in FilteredElementCollector(doc).OfClass(ElectricalSystem):
                results.append({'element_id': _idv(circuit.Id), 'name': circuit.Name, 'load_name': circuit.LoadName if hasattr(circuit, 'LoadName') else None})
        except Exception:
            pass
        return Response(data=results)

    @api.route('/mep/mechanical_equipment', methods=['GET'])
    def list_mech_equip(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        level_name = _qp(request).get('level_name')
        results = []
        for elem in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_MechanicalEquipment).WhereElementIsNotElementType():
            if level_name:
                lvl_p = elem.LookupParameter('Level') or elem.LookupParameter('Reference Level')
                if lvl_p and level_name not in (lvl_p.AsValueString() or ''):
                    continue
            results.append({'element_id': _idv(elem.Id), 'name': elem.Name, 'category': 'Mechanical Equipment'})
        return Response(data=results)

    @api.route('/mep/light_fixtures', methods=['GET'])
    def list_lights(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        results = []
        for elem in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_LightingFixtures).WhereElementIsNotElementType():
            results.append({'element_id': _idv(elem.Id), 'name': elem.Name})
        return Response(data=results)

    @api.route('/mep/plumbing_fixtures', methods=['GET'])
    def list_plumbing(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        results = []
        for elem in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_PlumbingFixtures).WhereElementIsNotElementType():
            results.append({'element_id': _idv(elem.Id), 'name': elem.Name})
        return Response(data=results)
