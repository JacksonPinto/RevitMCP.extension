# -*- coding: utf-8 -*-
"""
pyRevit Routes — Conduit auto-build from electrical circuit paths.
Runs INSIDE Revit. Registered in startup.py.

Key Revit API classes used:
  Autodesk.Revit.DB.Electrical.Conduit           — conduit segment creation
  Autodesk.Revit.DB.Electrical.ConduitType       — conduit family/type
  Autodesk.Revit.DB.Electrical.ElectricalSystem  — circuit (panel→fixtures)
  Autodesk.Revit.DB.Connector                    — MEP connector (origin, domain)
  Autodesk.Revit.DB.ConnectorManager             — connector set on an element
  Autodesk.Revit.DB.Domain                       — DomainConduit filter
  doc.Create.NewElbowFitting(c1, c2)             — elbow at direction change
"""
import math
import clr
clr.AddReference('RevitAPI')
import Autodesk
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import Domain, ElementId, FamilyInstance, FilteredElementCollector, Level, Transaction, XYZ
from Autodesk.Revit.DB.Electrical import Conduit, ConduitType, ElectricalSystem, ElectricalSystemType
from pyrevit.routes import API, Response
_uidoc = getattr(__revit__, 'ActiveUIDocument', None)
doc = _uidoc.Document if _uidoc else None
app = __revit__.Application
MM_PER_FOOT = 304.8

def _ft(mm):
    """mm → feet (Revit internal units)."""
    return mm / MM_PER_FOOT

def _mm(ft):
    """feet → mm."""
    return ft * MM_PER_FOOT

def _xyz_dict(pt):
    return {'x': pt.X, 'y': pt.Y, 'z': pt.Z}

def _dist(a, b):
    """Euclidean distance in feet."""
    return math.sqrt((a.X - b.X) ** 2 + (a.Y - b.Y) ** 2 + (a.Z - b.Z) ** 2)

def _get_conduit_connectors(element):
    """
    Return all unused conduit-domain connectors from a Revit element.
    Works for FamilyInstances (fixtures, equipment) and MEPCurve elements.
    """
    cm = None
    try:
        if isinstance(element, FamilyInstance):
            mep_model = element.MEPModel
            if mep_model is not None:
                cm = mep_model.ConnectorManager
        else:
            cm = element.ConnectorManager
    except Exception:
        return []
    if cm is None:
        return []
    result = []
    for conn in cm.Connectors:
        try:
            if conn.Domain == Domain.DomainConduit:
                result.append(conn)
        except Exception:
            pass
    return result

def _get_unused_conduit_connector(element):
    """Return the first unconnected conduit connector, or None."""
    for conn in _get_conduit_connectors(element):
        if not conn.IsConnected:
            return conn
    connectors = _get_conduit_connectors(element)
    return connectors[0] if connectors else None

def _get_nearest_level(z_elevation):
    """Return the Level element nearest to a given Z elevation in feet."""
    levels = list(FilteredElementCollector(doc).OfClass(Level))
    if not levels:
        return None
    return min(levels, key=lambda l: abs(l.Elevation - z_elevation))

def _find_level(name):
    for lvl in FilteredElementCollector(doc).OfClass(Level):
        if lvl.Name == name:
            return lvl
    return None

def _elem_summary(elem):
    """Build a concise summary dict for a Revit element."""
    d = {'element_id': elem.Id.IntegerValue, 'category': elem.Category.Name if elem.Category else None, 'name': elem.Name}
    type_elem = doc.GetElement(elem.GetTypeId()) if elem.GetTypeId() != ElementId.InvalidElementId else None
    if type_elem:
        d['family_name'] = getattr(type_elem, 'FamilyName', type_elem.Name)
        d['type_name'] = type_elem.Name
    else:
        d['family_name'] = None
        d['type_name'] = None
    lvl_p = elem.LookupParameter('Level') or elem.LookupParameter('Reference Level')
    d['level'] = lvl_p.AsValueString() if lvl_p else None
    return d

def _get_element_location_xyz(elem):
    """Return the centroid XYZ of an element (works for point and curve elements)."""
    try:
        loc = elem.Location
        from Autodesk.Revit.DB import LocationPoint, LocationCurve
        if isinstance(loc, LocationPoint):
            return loc.Point
        elif isinstance(loc, LocationCurve):
            curve = loc.Curve
            s = curve.GetEndPoint(0)
            e = curve.GetEndPoint(1)
            return XYZ((s.X + e.X) / 2, (s.Y + e.Y) / 2, (s.Z + e.Z) / 2)
    except Exception:
        pass
    return None

def _traverse_circuit(system):
    """
    Return circuit elements in topological order: panel first, then each
    element in the path outward to the last fixture.

    Strategy:
      1. Start from BaseEquipment (panel).
      2. BFS through connector AllRefs to find the next element.
      3. If BFS fails (no logical connector chain), fall back to
         distance-based ordering from the panel.
    """
    panel = system.BaseEquipment
    elements = list(system.Elements)
    if not elements:
        return []
    circuit_ids = {e.Id.IntegerValue for e in elements}
    if panel:
        circuit_ids.discard(panel.Id.IntegerValue)
    visited = []
    visited_ids = set()
    queue = [panel] if panel else []
    if panel:
        visited_ids.add(panel.Id.IntegerValue)
    while queue:
        current = queue.pop(0)
        if current is not panel:
            visited.append(current)
        for conn in _get_conduit_connectors(current):
            try:
                if conn.IsConnected:
                    for ref in conn.AllRefs:
                        neighbour = doc.GetElement(ref.Owner.Id)
                        if neighbour is not None and neighbour.Id.IntegerValue in circuit_ids and (neighbour.Id.IntegerValue not in visited_ids):
                            visited_ids.add(neighbour.Id.IntegerValue)
                            queue.append(neighbour)
            except Exception:
                pass
    unvisited = [e for e in elements if e.Id.IntegerValue not in visited_ids]
    reference_pt = None
    if panel:
        reference_pt = _get_element_location_xyz(panel)
    elif visited:
        reference_pt = _get_element_location_xyz(visited[-1])
    if reference_pt and unvisited:
        unvisited.sort(key=lambda e: _dist(_get_element_location_xyz(e) or XYZ(0, 0, 0), reference_pt))
    return visited + unvisited

def _get_routes(api):

    @api.route('/conduit/circuits', methods=['GET'])
    def list_circuits(request):
        panel_filter = request.params.get('panel_name', '').lower()
        type_filter = request.params.get('circuit_type', '').lower()
        results = []
        for sys in FilteredElementCollector(doc).OfClass(ElectricalSystem):
            try:
                ct = sys.CircuitType.ToString()
                if type_filter and type_filter not in ct.lower():
                    continue
                panel = sys.BaseEquipment
                panel_name = panel.Name if panel else None
                if panel_filter and panel_name and (panel_filter not in panel_name.lower()):
                    continue
                elem_count = sum((1 for _ in sys.Elements))
                results.append({'circuit_id': sys.Id.IntegerValue, 'circuit_name': sys.Name, 'circuit_number': sys.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.RBS_ELEC_CIRCUIT_NUMBER).AsString() if sys.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.RBS_ELEC_CIRCUIT_NUMBER) else None, 'circuit_type': ct, 'panel_name': panel_name, 'panel_id': panel.Id.IntegerValue if panel else None, 'load_name': sys.LoadName if hasattr(sys, 'LoadName') else None, 'element_count': elem_count, 'amperage': sys.ApparentCurrent if hasattr(sys, 'ApparentCurrent') else None, 'voltage': sys.Voltage if hasattr(sys, 'Voltage') else None})
            except Exception as e:
                pass
        return Response(data=results)

    @api.route('/conduit/circuits/<int:circuit_id>/analyze_connectors', methods=['GET'])
    def analyze_connectors(circuit_id):
        system = doc.GetElement(ElementId(circuit_id))
        if not isinstance(system, ElectricalSystem):
            return Response(status_code=404, data={'error': 'Circuit not found'})
        panel = system.BaseEquipment
        ready = []
        problems = []
        panel_has_conduit = False
        if panel:
            panel_connectors = _get_conduit_connectors(panel)
            panel_has_conduit = len(panel_connectors) > 0
        for elem in system.Elements:
            s = _elem_summary(elem)
            conduit_conns = _get_conduit_connectors(elem)
            if conduit_conns:
                s['conduit_connector_count'] = len(conduit_conns)
                s['connector_origins'] = [_xyz_dict(c.Origin) for c in conduit_conns]
                s['connector_connected'] = [c.IsConnected for c in conduit_conns]
                ready.append(s)
            else:
                s['fix_instruction'] = "Open family '{}' in the Family Editor. Add a Connector: Manage → MEP Settings → Connectors → New Connector. Set Domain = Electrical, Connector Type = Conduit. Place it at the conduit entry/exit point of the fixture. Save and reload the family into the project.".format(s.get('family_name', elem.Name))
                problems.append(s)
        return Response(data={'circuit_id': circuit_id, 'circuit_name': system.Name, 'panel_name': panel.Name if panel else None, 'panel_id': panel.Id.IntegerValue if panel else None, 'panel_has_conduit_connector': panel_has_conduit, 'element_count': len(ready) + len(problems), 'ready_elements': ready, 'problem_elements': problems, 'can_build': len(problems) == 0 and panel_has_conduit})

    @api.route('/conduit/types', methods=['GET'])
    def list_conduit_types():
        results = []
        for ct in FilteredElementCollector(doc).OfClass(ConduitType):
            results.append({'element_id': ct.Id.IntegerValue, 'name': ct.Name, 'family_name': ct.FamilyName if hasattr(ct, 'FamilyName') else ct.Name})
        return Response(data=results)

    @api.route('/conduit/types/<int:type_id>/sizes', methods=['GET'])
    def get_conduit_sizes(type_id):
        ct = doc.GetElement(ElementId(type_id))
        if ct is None:
            return Response(status_code=404, data={'error': 'ConduitType not found'})
        standard_sizes_mm = [12, 16, 20, 25, 32, 40, 50, 63, 75, 100]
        results = []
        for sz in standard_sizes_mm:
            results.append({'trade_size': sz / MM_PER_FOOT, 'trade_size_label': '{}mm'.format(sz), 'inside_diameter': sz * 0.85 / MM_PER_FOOT, 'outside_diameter': sz * 1.05 / MM_PER_FOOT})
        return Response(data=results)

    @api.route('/conduit/circuits/<int:circuit_id>/sequence', methods=['GET'])
    def get_sequence(circuit_id):
        system = doc.GetElement(ElementId(circuit_id))
        if not isinstance(system, ElectricalSystem):
            return Response(status_code=404, data={'error': 'Circuit not found'})
        panel = system.BaseEquipment
        ordered = _traverse_circuit(system)
        sequence = []
        total_length = 0.0
        prev_connector = None
        if panel:
            panel_conn = _get_unused_conduit_connector(panel)
            prev_connector = panel_conn
        for (step, elem) in enumerate(ordered, start=1):
            conn = _get_unused_conduit_connector(elem)
            loc = _get_element_location_xyz(elem)
            s = _elem_summary(elem)
            s['step'] = step
            s['location'] = _xyz_dict(loc) if loc else None
            s['conduit_connector_origin'] = _xyz_dict(conn.Origin) if conn else None
            s['has_conduit_connector'] = conn is not None
            if prev_connector and conn:
                seg_length = _dist(prev_connector.Origin, conn.Origin)
                total_length += seg_length
                s['segment_length_from_previous'] = seg_length
            sequence.append(s)
            if conn:
                prev_connector = conn
        panel_info = None
        if panel:
            p_conn = _get_unused_conduit_connector(panel)
            panel_info = {'element_id': panel.Id.IntegerValue, 'name': panel.Name, 'connector_origin': _xyz_dict(p_conn.Origin) if p_conn else None, 'has_conduit_connector': p_conn is not None}
        return Response(data={'circuit_id': circuit_id, 'circuit_name': system.Name, 'panel': panel_info, 'sequence': sequence, 'segment_count': max(0, len(ordered) - 1) + (1 if panel else 0), 'total_run_length': total_length})

    @api.route('/conduit/circuits/<int:circuit_id>/build_plan', methods=['GET'])
    def build_plan(circuit_id):
        system = doc.GetElement(ElementId(circuit_id))
        if not isinstance(system, ElectricalSystem):
            return Response(status_code=404, data={'error': 'Circuit not found'})
        panel = system.BaseEquipment
        ordered = _traverse_circuit(system)
        problem_families = []
        steps = []
        total_length = 0.0
        all_elements = ([panel] if panel else []) + ordered
        for i in range(len(all_elements) - 1):
            a = all_elements[i]
            b = all_elements[i + 1]
            a_name = a.Name if a else '?'
            b_name = b.Name
            a_conn = _get_unused_conduit_connector(a)
            b_conn = _get_unused_conduit_connector(b)
            if b_conn is None:
                type_elem = doc.GetElement(b.GetTypeId())
                fam_name = type_elem.FamilyName if type_elem and hasattr(type_elem, 'FamilyName') else b.Name
                if fam_name not in problem_families:
                    problem_families.append(fam_name)
                steps.append({'step': i + 1, 'description': "⚠️  BLOCKED — '{}' has no conduit connector. Family '{}' must be modified first.".format(b_name, fam_name), 'status': 'blocked', 'from_element': a_name, 'to_element': b_name})
            else:
                seg_len = _dist(a_conn.Origin if a_conn else XYZ(0, 0, 0), b_conn.Origin)
                total_length += seg_len
                steps.append({'step': i + 1, 'description': "Create conduit from '{}' → '{}' (~{:.0f} mm)".format(a_name, b_name, seg_len * MM_PER_FOOT), 'status': 'ready', 'from_element': a_name, 'to_element': b_name, 'estimated_length': seg_len})
        try:
            amps = system.ApparentCurrent if hasattr(system, 'ApparentCurrent') else 0
            if amps <= 20:
                recommended_mm = 16
            elif amps <= 30:
                recommended_mm = 20
            elif amps <= 60:
                recommended_mm = 25
            elif amps <= 100:
                recommended_mm = 32
            else:
                recommended_mm = 40
        except Exception:
            recommended_mm = 20
        return Response(data={'circuit_id': circuit_id, 'circuit_name': system.Name, 'panel_name': panel.Name if panel else None, 'pre_flight_status': 'needs_family_edits' if problem_families else 'ready', 'steps': steps, 'problem_families': problem_families, 'estimated_total_length': total_length, 'recommended_diameter_mm': recommended_mm})

    @api.route('/conduit/build', methods=['POST'])
    def build_conduit(request):
        body = request.data
        circuit_id = int(body.get('circuit_id'))
        conduit_type_id = int(body.get('conduit_type_id'))
        diameter = float(body.get('diameter', _ft(20)))
        routing_strategy = body.get('routing_strategy', 'direct')
        offset_z = float(body.get('offset_z', 0.0))
        connect_to_panel = bool(body.get('connect_to_panel', True))
        create_fittings = bool(body.get('create_fittings', True))
        level_name = body.get('level_name')
        system = doc.GetElement(ElementId(circuit_id))
        if not isinstance(system, ElectricalSystem):
            return Response(status_code=404, data={'error': 'Circuit not found'})
        conduit_type = doc.GetElement(ElementId(conduit_type_id))
        if conduit_type is None or not isinstance(conduit_type, ConduitType):
            return Response(status_code=404, data={'error': 'ConduitType not found'})
        panel = system.BaseEquipment
        ordered = _traverse_circuit(system)
        if not ordered:
            return Response(status_code=400, data={'error': 'Circuit has no elements'})
        chain = []
        if connect_to_panel and panel:
            chain.append(panel)
        chain.extend(ordered)
        segments_created = []
        fittings_created = []
        skipped_connections = []
        warnings = []
        total_length = 0.0
        override_level = _find_level(level_name) if level_name else None
        with Transaction(doc, 'MCP: Build Conduit from Circuit') as t:
            t.Start()
            try:
                prev_conduit_end_connector = None
                for i in range(len(chain) - 1):
                    elem_a = chain[i]
                    elem_b = chain[i + 1]
                    conn_a = _get_unused_conduit_connector(elem_a)
                    conn_b = _get_unused_conduit_connector(elem_b)
                    if conn_a is None:
                        skipped_connections.append({'from_element_id': elem_a.Id.IntegerValue, 'to_element_id': elem_b.Id.IntegerValue, 'reason': "Element '{}' (ID {}) has no available conduit connector.".format(elem_a.Name, elem_a.Id.IntegerValue)})
                        prev_conduit_end_connector = None
                        continue
                    if conn_b is None:
                        type_elem = doc.GetElement(elem_b.GetTypeId())
                        fam = type_elem.FamilyName if type_elem and hasattr(type_elem, 'FamilyName') else elem_b.Name
                        skipped_connections.append({'from_element_id': elem_a.Id.IntegerValue, 'to_element_id': elem_b.Id.IntegerValue, 'reason': "Element '{}' (ID {}) from family '{}' has no conduit connector. Open the family in the Family Editor, add a Connector (Manage → MEP Settings → Connectors → New Connector), set Domain = Electrical, Connector Type = Conduit, and reload the family.".format(elem_b.Name, elem_b.Id.IntegerValue, fam)})
                        prev_conduit_end_connector = None
                        continue
                    start_pt = conn_a.Origin
                    end_pt = conn_b.Origin
                    if offset_z != 0.0:
                        start_pt = XYZ(start_pt.X, start_pt.Y, start_pt.Z + offset_z)
                        end_pt = XYZ(end_pt.X, end_pt.Y, end_pt.Z + offset_z)
                    segments_to_create = []
                    if routing_strategy == 'orthogonal':
                        mid_pt = XYZ(end_pt.X, end_pt.Y, start_pt.Z)
                        if _dist(start_pt, mid_pt) > 0.001:
                            segments_to_create.append((start_pt, mid_pt))
                        if _dist(mid_pt, end_pt) > 0.001:
                            segments_to_create.append((mid_pt, end_pt))
                    else:
                        segments_to_create.append((start_pt, end_pt))
                    segments_to_create = [(s, e) for (s, e) in segments_to_create if _dist(s, e) > 0.001]
                    if not segments_to_create:
                        warnings.append('Segment {}: start and end points are identical — skipped.'.format(i + 1))
                        continue
                    created_in_step = []
                    for (seg_start, seg_end) in segments_to_create:
                        level = override_level or _get_nearest_level((seg_start.Z + seg_end.Z) / 2)
                        level_id = level.Id if level else ElementId.InvalidElementId
                        try:
                            conduit = Conduit.Create(doc, conduit_type.Id, seg_start, seg_end, level_id)
                            try:
                                from Autodesk.Revit.DB import BuiltInParameter
                                diam_param = conduit.get_Parameter(BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM)
                                if diam_param and (not diam_param.IsReadOnly):
                                    diam_param.Set(diameter)
                            except Exception:
                                pass
                            seg_len = _dist(seg_start, seg_end)
                            total_length += seg_len
                            created_in_step.append(conduit)
                            segments_created.append({'segment_index': len(segments_created) + 1, 'conduit_id': conduit.Id.IntegerValue, 'from_element': elem_a.Name, 'to_element': elem_b.Name, 'from_element_id': elem_a.Id.IntegerValue, 'to_element_id': elem_b.Id.IntegerValue, 'length': seg_len, 'start': _xyz_dict(seg_start), 'end': _xyz_dict(seg_end), 'level': level.Name if level else None})
                        except Exception as ex:
                            skipped_connections.append({'from_element_id': elem_a.Id.IntegerValue, 'to_element_id': elem_b.Id.IntegerValue, 'reason': 'Conduit.Create failed: {}'.format(ex)})
                            created_in_step = []
                            break
                    if not created_in_step:
                        prev_conduit_end_connector = None
                        continue
                    first_conduit = created_in_step[0]
                    last_conduit = created_in_step[-1]
                    try:
                        first_cm = first_conduit.ConnectorManager
                        first_end_connectors = [c for c in first_cm.Connectors if c.Domain == Domain.DomainConduit]
                        first_end_connectors.sort(key=lambda c: _dist(c.Origin, conn_a.Origin))
                        if first_end_connectors:
                            try:
                                first_end_connectors[0].ConnectTo(conn_a)
                            except Exception:
                                pass
                        last_cm = last_conduit.ConnectorManager
                        last_end_connectors = [c for c in last_cm.Connectors if c.Domain == Domain.DomainConduit]
                        last_end_connectors.sort(key=lambda c: _dist(c.Origin, conn_b.Origin))
                        if last_end_connectors:
                            try:
                                last_end_connectors[-1].ConnectTo(conn_b)
                            except Exception:
                                pass
                    except Exception as conn_err:
                        warnings.append('Connector attachment warning on segment {}: {}'.format(i + 1, conn_err))
                    if create_fittings and prev_conduit_end_connector and created_in_step:
                        cur_start_cm = created_in_step[0].ConnectorManager
                        cur_start_connectors = [c for c in cur_start_cm.Connectors if c.Domain == Domain.DomainConduit]
                        cur_start_connectors.sort(key=lambda c: _dist(c.Origin, conn_a.Origin))
                        if cur_start_connectors:
                            try:
                                fitting = doc.Create.NewElbowFitting(prev_conduit_end_connector, cur_start_connectors[0])
                                fittings_created.append(fitting.Id.IntegerValue)
                            except Exception as fit_ex:
                                warnings.append('Elbow fitting at segment {} failed: {}. You may need to manually add fittings at direction changes.'.format(i + 1, fit_ex))
                    if last_conduit:
                        last_cm2 = last_conduit.ConnectorManager
                        far_connectors = [c for c in last_cm2.Connectors if c.Domain == Domain.DomainConduit]
                        far_connectors.sort(key=lambda c: _dist(c.Origin, conn_b.Origin))
                        prev_conduit_end_connector = far_connectors[-1] if far_connectors else None
                    else:
                        prev_conduit_end_connector = None
                t.Commit()
            except Exception as tx_err:
                t.RollBack()
                return Response(status_code=500, data={'error': 'Transaction failed and was rolled back: {}'.format(tx_err), 'segments_created_before_error': segments_created})
        return Response(data={'circuit_id': circuit_id, 'circuit_name': system.Name, 'conduit_type_name': conduit_type.Name, 'diameter': diameter, 'routing_strategy': routing_strategy, 'segments_created': segments_created, 'fittings_created': fittings_created, 'skipped_connections': skipped_connections, 'total_length': total_length, 'success': len(skipped_connections) == 0, 'warnings': warnings})

    @api.route('/conduit/list', methods=['GET'])
    def list_conduits(request):
        level_name = request.params.get('level_name')
        type_name = request.params.get('conduit_type_name')
        results = []
        for conduit in FilteredElementCollector(doc).OfClass(Conduit):
            c = conduit
            level = None
            try:
                level = doc.GetElement(c.ReferenceLevel.Id).Name if c.ReferenceLevel else None
            except Exception:
                pass
            if level_name and level and (level != level_name):
                continue
            ctype = doc.GetElement(c.GetTypeId())
            ctype_name = ctype.Name if ctype else None
            if type_name and ctype_name and (type_name.lower() not in ctype_name.lower()):
                continue
            cm = c.ConnectorManager
            connectors = list(cm.Connectors) if cm else []
            start = _xyz_dict(connectors[0].Origin) if len(connectors) > 0 else None
            end = _xyz_dict(connectors[1].Origin) if len(connectors) > 1 else None
            diam = 0.0
            try:
                from Autodesk.Revit.DB import BuiltInParameter
                dp = c.get_Parameter(BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM)
                if dp:
                    diam = dp.AsDouble()
            except Exception:
                pass
            results.append({'element_id': c.Id.IntegerValue, 'conduit_type': ctype_name, 'diameter': diam, 'length': c.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.CURVE_ELEM_LENGTH).AsDouble() if c.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.CURVE_ELEM_LENGTH) else 0.0, 'level': level, 'start': start, 'end': end})
        return Response(data=results)

    @api.route('/conduit/element/<int:element_id>/connectors', methods=['GET'])
    def get_element_connectors(element_id):
        elem = doc.GetElement(ElementId(element_id))
        if elem is None:
            return Response(status_code=404, data={'error': 'Element not found'})
        s = _elem_summary(elem)
        conduit_conns = _get_conduit_connectors(elem)
        connector_list = []
        for (idx, conn) in enumerate(conduit_conns):
            connected_to = None
            if conn.IsConnected:
                try:
                    for ref in conn.AllRefs:
                        connected_to = ref.Owner.Id.IntegerValue
                        break
                except Exception:
                    pass
            connector_list.append({'index': idx, 'origin': _xyz_dict(conn.Origin), 'direction': _xyz_dict(conn.CoordinateSystem.BasisZ) if hasattr(conn, 'CoordinateSystem') else None, 'is_connected': conn.IsConnected, 'connected_to_id': connected_to})
        fix_instruction = None
        if not conduit_conns:
            fam = s.get('family_name', elem.Name)
            fix_instruction = "Family '{}' has no conduit connector. To add one:\n1. Select the element → Edit Family (opens family editor).\n2. In the family editor: Manage tab → MEP Settings → Connectors → Add Connector.\n3. Set: System Classification = Conduit (Electrical), Connector Type = End, Flow Direction = Bidirectional.\n4. Place the connector at the entry/exit point where conduit attaches.\n5. Finish the family and reload it into the project (overwrite existing).\n6. Re-run analyze_circuit_connectors to confirm the fix.".format(fam)
        return Response(data={**s, 'has_conduit_connectors': len(conduit_conns) > 0, 'connectors': connector_list, 'fix_instruction': fix_instruction})

    @api.route('/conduit/by_circuit', methods=['DELETE'])
    def delete_circuit_conduits(request):
        circuit_id = int(request.data.get('circuit_id'))
        system = doc.GetElement(ElementId(circuit_id))
        if not isinstance(system, ElectricalSystem):
            return Response(status_code=404, data={'error': 'Circuit not found'})
        circuit_elem_ids = {e.Id.IntegerValue for e in system.Elements}
        if system.BaseEquipment:
            circuit_elem_ids.add(system.BaseEquipment.Id.IntegerValue)
        to_delete = []
        for conduit in FilteredElementCollector(doc).OfClass(Conduit):
            cm = conduit.ConnectorManager
            if cm is None:
                continue
            for conn in cm.Connectors:
                if conn.IsConnected:
                    try:
                        for ref in conn.AllRefs:
                            if ref.Owner.Id.IntegerValue in circuit_elem_ids:
                                to_delete.append(conduit.Id)
                                break
                    except Exception:
                        pass
        deleted_conduits = 0
        with Transaction(doc, 'MCP: Delete Circuit Conduits') as t:
            t.Start()
            for eid in set(to_delete):
                try:
                    doc.Delete(eid)
                    deleted_conduits += 1
                except Exception:
                    pass
            t.Commit()
        return Response(data={'circuit_id': circuit_id, 'deleted_conduit_segments': deleted_conduits})
