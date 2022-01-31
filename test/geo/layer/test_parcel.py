import logging
import mock
import unittest

from qgis.core import QgsFeature, QgsVectorLayer

from catatom2osm.app import QgsSingleton
from catatom2osm.geo.geometry import Geometry
from catatom2osm.geo.layer.cons import ConsLayer
from catatom2osm.geo.layer.parcel import ParcelLayer

qgs = QgsSingleton()
m_log = mock.MagicMock()
m_log.app_level = logging.INFO


class TestParcelLayer(unittest.TestCase):

    @mock.patch('catatom2osm.geo.layer.base.tqdm', mock.MagicMock())
    @mock.patch('catatom2osm.geo.layer.base.log', m_log)
    def setUp(self):
        fn = 'test/fixtures/parcel.gpkg|layername=parcel'
        self.parcel = ParcelLayer('MultiPolygon', 'parcel', 'memory')
        fixture = QgsVectorLayer(fn, 'parcel', 'ogr')
        self.assertTrue(fixture.isValid(), "Loading fixture")
        self.parcel.append(fixture)
        self.assertEqual(self.parcel.featureCount(), 186)
        fn = 'test/fixtures/cons.gpkg|layername=cons'
        fixture2 = QgsVectorLayer(fn, 'cons', 'ogr')
        self.building = ConsLayer('MultiPolygon', 'cons', 'memory')
        self.building.append(fixture2)
        self.assertTrue(self.building.isValid(), "Loading fixture")

    def test_init(self):
        layer = ParcelLayer()
        self.assertEqual(layer.fields()[0].name(), 'localId')
        self.assertEqual(layer.fields()[1].name(), 'label')
        self.assertEqual(layer.rename['localId'], 'inspireId_localId')

    def test_not_empty(self):
        layer = ParcelLayer()
        self.assertEqual(len(layer.fields().toList()), 2)

    def test_delete_void_parcels(self):
        self.parcel.delete_void_parcels(self.building)
        self.assertEqual(self.parcel.featureCount(), 111)

    def test_create_missing_parcels(self):
        self.parcel.create_missing_parcels(self.building)
        self.assertEqual(self.parcel.featureCount(), 188)
        p = next(self.parcel.search("localId = '8642317CS5284S'"))
        self.assertEqual(len(Geometry.get_multipolygon(p)[0]), 1)

    def test_get_groups_by_adjacent_buildings(self):
        self.parcel.create_missing_parcels(self.building)
        pa_groups, __, __ = self.parcel.get_groups_by_adjacent_buildings(
            self.building
        )
        expected = [
            {48, 9, 10}, {14, 15}, {16, 17}, {18, 19, 20, 22, 23},
            {27, 40, 41, 42, 43, 44, 45, 24, 25, 26, 187, 28, 29, 30, 31},
            {34, 35, 55}, {56, 36, 37}, {32, 33, 38, 39}, {11, 12, 46, 47},
            {8, 49, 50, 7}, {51, 52, 5, 6}, {3, 4, 53, 54}, {57, 58},
            {64, 65, 66, 71, 59, 60, 61, 62, 63}, {81, 77, 78}, {80, 79},
            {84, 85}, {86, 87}, {91, 92}, {107, 99, 100},
        ]
        self.assertEqual(pa_groups, expected)

    @mock.patch('catatom2osm.geo.layer.base.tqdm', mock.MagicMock())
    @mock.patch('catatom2osm.geo.layer.base.log', m_log)
    @mock.patch('catatom2osm.geo.layer.polygon.log', m_log)
    def test_merge_by_adjacent_buildings(self):
        self.building.remove_outside_parts()
        self.building.explode_multi_parts()
        self.building.clean()
        self.parcel.delete_void_parcels(self.building)
        self.parcel.create_missing_parcels(self.building)
        tasks = self.parcel.merge_by_adjacent_buildings(self.building)
        pa_refs = [f['localId'] for f in self.parcel.getFeatures()]
        expected = [
            '001000300CS52D', '001000400CS52D', '8641608CS5284S',
            '8641612CS5284S', '8641613CS5284S', '8641616CS5284S',
            '8641620CS5284S', '8641621CS5284S', '8641632CS5284S',
            '8641636CS5284S', '8641638CS5284S', '8641649CS5284S',
            '8641653CS5284S', '8641658CS5284S', '8641660CS5284S',
            '8642302CS5284S', '8642310CS5284S', '8642312CS5284S',
            '8642313CS5284S', '8642314CS5284S', '8642317CS5284S',
            '8642321CS5284S', '8642325CS5484N', '8642701CS5284S',
            '8742701CS5284S', '8742707CS5284S', '8742711CS5284S',
            '8742721CS5284S', '8839301CS5283N', '8840501CS5284S',
            '8841602CS5284S', '8841603CS5284S', '8844121CS5284S',
            '8940301CS5284S', '8940302CS5284S', '8940305CS5284S',
            '8940306CS5284S', '8940307CS5284S', '8940309CS5284S',
            '8941505CS5284S', '9041703CS5294S', '9041704CS5294S',
            '9041705CS5294S', '9041716CS5294S', '9041719CS5294S',
            '9042401CS5294S', '9042402CS5294S', '9042404CS5294S',
        ]
        self.assertEqual(pa_refs, expected)
        merged = []
        for bu in self.building.getFeatures():
            if self.building.is_building(bu):
                ref = self.building.get_id(bu)
                if ref not in pa_refs:
                    merged.append(ref)
        self.assertEqual(len(merged), 71)
        self.assertTrue(all([tasks[ref] != ref for ref in merged]))

    @mock.patch('catatom2osm.geo.layer.base.tqdm', mock.MagicMock())
    @mock.patch('catatom2osm.geo.layer.base.log', m_log)
    @mock.patch('catatom2osm.geo.layer.polygon.log', m_log)
    def test_count_parts(self):
        self.building.remove_outside_parts()
        self.building.explode_multi_parts()
        self.building.clean()
        self.parcel.delete_void_parcels(self.building)
        self.parcel.create_missing_parcels(self.building)
        parts_count = self.parcel.count_parts(self.building)
        self.assertEqual(sum(parts_count.values()), 255)
        self.assertEqual(len(parts_count), self.parcel.featureCount())
        f = next(self.parcel.search("localId = '8840501CS5284S'"))
        self.assertEqual(f['parts'], 7)
        f = next(self.parcel.search("localId = '8840502CS5284S'"))
        self.assertEqual(f['parts'], 3)
        self.parcel.reproject()
        self.parcel.export('parcel.geojson', 'GeoJSON')
