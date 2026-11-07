"""Zone imports must retain CAD arcs through preview, assignment and map output."""
import io
import math

import ezdxf
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings

from core.dxf_utils import parse_dxf_shapes
from core.models import Zone


def drawing(points, kind='LWPOLYLINE', closed=True, extrusion=(0, 0, 1)):
    doc = ezdxf.new()
    attrs = {'layer': 'Zone', 'extrusion': extrusion}
    if kind == 'LWPOLYLINE':
        doc.modelspace().add_lwpolyline(points, format='xyb', close=closed, dxfattribs=attrs)
    else:
        line = doc.modelspace().add_polyline2d([(x, y) for x, y, _ in points],
                                             close=closed, dxfattribs=attrs)
        for vertex, (_, _, bulge) in zip(line.vertices, points):
            vertex.dxf.bulge = bulge
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode()


class ZoneCurveGeometryTests(SimpleTestCase):
    def test_closing_arc_preserves_circle_direction_endpoints_and_area(self):
        for kind in ('LWPOLYLINE', 'POLYLINE'):
            for bulge in (-1, 1):
                with self.subTest(kind=kind, bulge=bulge):
                    shapes = parse_dxf_shapes(io.BytesIO(drawing(
                        [(1000, 1000, 0), (1020, 1000, 0),
                         (1020, 1020, 0), (1000, 1020, bulge)], kind)))
                    vertices = shapes[0]['vertices']
                    self.assertGreater(len(vertices), 20)
                    self.assertEqual(vertices[:4], [(1000, 1000), (1020, 1000),
                                                   (1020, 1020), (1000, 1020)])
                    arc = vertices[4:]
                    for x, y in arc:
                        self.assertAlmostEqual(math.hypot(x - 1000, y - 1010), 10, places=8)
                        self.assertLess((x - 1000) * bulge, 0)
                    area = abs(sum(x * vertices[(i + 1) % len(vertices)][1]
                                   - y * vertices[(i + 1) % len(vertices)][0]
                                   for i, (x, y) in enumerate(vertices))) / 2
                    self.assertAlmostEqual(area, 400 + bulge * math.pi * 50, delta=.3)

    def test_two_vertex_circle_is_not_discarded_as_a_two_point_shape(self):
        for kind in ('LWPOLYLINE', 'POLYLINE'):
            shapes = parse_dxf_shapes(io.BytesIO(drawing([(1000, 1000, 1), (1020, 1000, 1)], kind)))
            self.assertEqual(len(shapes), 1)
            self.assertGreater(shapes[0]['vertex_count'], 60)

    def test_large_radius_major_arc_has_bounded_chord_error(self):
        # A 270 degree closing arc must keep its long sweep, not take the shortcut.
        bulge = math.tan(3 * math.pi / 8)
        vertices = parse_dxf_shapes(io.BytesIO(drawing(
            [(1000, 1000, bulge), (3000, 1000, 0), (3000, 4000, 0)])))[0]['vertices']
        from ezdxf.math import bulge_to_arc
        center, _, _, radius = bulge_to_arc((1000, 1000), (3000, 1000), bulge)
        end = vertices.index((3000, 1000))
        self.assertGreater(end, 100)
        for a, b in zip(vertices[:end], vertices[1:end + 1]):
            midpoint = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            self.assertLessEqual(radius - math.dist(center, midpoint), .050001)

    def test_straight_vertices_keep_full_precision_and_open_lines_are_ignored(self):
        points = [(1000.123456, 1000, 0), (1020, 1000, 0), (1020, 1020, 0)]
        self.assertEqual(parse_dxf_shapes(io.BytesIO(drawing(points)))[0]['vertices'],
                         [(x, y) for x, y, _ in points])
        self.assertEqual(parse_dxf_shapes(io.BytesIO(drawing(points, closed=False))), [])

    def test_nondefault_ocs_applies_to_arc_points_as_well_as_endpoints(self):
        points = [(1000, 1000, 1), (1020, 1000, 0), (1020, 1020, 0)]
        for kind in ('LWPOLYLINE', 'POLYLINE'):
            normal = parse_dxf_shapes(io.BytesIO(drawing(points, kind)))[0]['vertices']
            mirrored = parse_dxf_shapes(io.BytesIO(drawing(points, kind, extrusion=(0, 0, -1))))[0]['vertices']
            self.assertEqual(mirrored, [(-x, y) for x, y in normal])


@override_settings(ALLOWED_HOSTS=['testserver'], CACHES={
    key: {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}
    for key in ('default', 'dxffile')})
class ZoneCurveImportTests(TestCase):
    def test_preview_assigned_boundary_and_homepage_keep_the_same_arc(self):
        self.client.force_login(User.objects.create_superuser('zone-curve', '', 'fixture'))
        zone = Zone.objects.create(code='curve-fixture', name='Curve fixture')
        url = '/settings/zone/dxf-import/'
        content = drawing([(121, 31, 0), (121.002, 31, 1), (121.002, 31.002, 0)])
        response = self.client.post(url, {'action': 'upload_dxf',
            'file': SimpleUploadedFile('curved-zone.dxf', content)})
        self.assertEqual(response.status_code, 200, response.content)
        preview = response.json()['transformed'][0]['vertices_latlng']
        self.assertGreater(len(preview), 20)
        response = self.client.post(url, {'action': 'assign_shape',
            'zone_code': zone.code, 'group_id': 'group_0'})
        self.assertTrue(response.json()['success'], response.content)
        zone.refresh_from_db()
        self.assertEqual(zone.dxf_boundary_points, [preview])
        self.assertEqual(zone.dxf_boundary_source, 'curved-zone.dxf')
        self.assertEqual(zone.active_boundary_points, [preview])
        payload = self.client.get('/api/zones-payload/').json()
        self.assertEqual(next(row for row in payload if row['id'] == zone.id)['boundary_points'], [preview])
