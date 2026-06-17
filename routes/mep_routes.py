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

def _get_routes(api):

    @api.route('/mep/systems', methods=['GET'])
    def list_systems(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        system_type = request.params.get('system_type')
        results = []
        try:
            for sys in FilteredElementCollector(doc).OfClass(MechanicalSystem):
                if system_type and system_type != 'DuctSystem':
                    continue
                results.append({'type': 'DuctSystem', 'name': sys.Name, 'element_id': sys.Id.IntegerValue})
        except Exception:
            pass
        try:
            for sys in FilteredElementCollector(doc).OfClass(PipingSystem):
                if system_type and system_type != 'PipingSystem':
                    continue
                results.append({'type': 'PipingSystem', 'name': sys.Name, 'element_id': sys.Id.IntegerValue})
        except Exception:
            pass
        return Response(data=results)

    @api.route('/mep/ducts', methods=['GET'])
    def list_ducts(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        level_name = request.params.get('level_name')
        results = []
        try:
            for duct in FilteredElementCollector(doc).OfClass(Duct):
                d = {'element_id': duct.Id.IntegerValue, 'length': duct.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH).AsDouble() if duct.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH) else 0}
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
                results.append({'element_id': pipe.Id.IntegerValue, 'diameter': pipe.Diameter if hasattr(pipe, 'Diameter') else 0})
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
                results.append({'element_id': circuit.Id.IntegerValue, 'name': circuit.Name, 'load_name': circuit.LoadName if hasattr(circuit, 'LoadName') else None})
        except Exception:
            pass
        return Response(data=results)

    @api.route('/mep/mechanical_equipment', methods=['GET'])
    def list_mech_equip(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        level_name = request.params.get('level_name')
        results = []
        for elem in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_MechanicalEquipment).WhereElementIsNotElementType():
            if level_name:
                lvl_p = elem.LookupParameter('Level') or elem.LookupParameter('Reference Level')
                if lvl_p and level_name not in (lvl_p.AsValueString() or ''):
                    continue
            results.append({'element_id': elem.Id.IntegerValue, 'name': elem.Name, 'category': 'Mechanical Equipment'})
        return Response(data=results)

    @api.route('/mep/light_fixtures', methods=['GET'])
    def list_lights(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        results = []
        for elem in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_LightingFixtures).WhereElementIsNotElementType():
            results.append({'element_id': elem.Id.IntegerValue, 'name': elem.Name})
        return Response(data=results)

    @api.route('/mep/plumbing_fixtures', methods=['GET'])
    def list_plumbing(uiapp, request):
        global doc
        _ud = getattr(uiapp, 'ActiveUIDocument', None)
        doc = _ud.Document if _ud else None
        results = []
        for elem in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_PlumbingFixtures).WhereElementIsNotElementType():
            results.append({'element_id': elem.Id.IntegerValue, 'name': elem.Name})
        return Response(data=results)
