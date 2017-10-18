# -*- coding: utf-8 -*-
"""
Tool to convert INSPIRE data sets from the Spanish Cadastre ATOM Services to OSM files
"""
import os
import codecs
import logging
from collections import defaultdict, Counter, OrderedDict

from qgis.core import *
import qgis.utils
from osgeo import gdal

import catatom
import csvtools
import layer
import osm
import osmxml
import overpass
import setup
import translate
from compat import etree

log = logging.getLogger(setup.app_name + "." + __name__)
if setup.silence_gdal:
    gdal.PushErrorHandler('CPLQuietErrorHandler')


class QgsSingleton(QgsApplication):
    """Keeps a unique instance of QGIS for the application (and tests)"""
    _qgs = None

    def __new__(cls):
        if QgsSingleton._qgs is None:
            # Init qGis API
            QgsSingleton._qgs = QgsApplication([], False)
            QgsSingleton._qgs.initQgis()
            # sets GDAL to convert xlink references to fields but not resolve
            gdal.SetConfigOption('GML_ATTRIBUTES_TO_OGR_FIELDS', 'YES')
            gdal.SetConfigOption('GML_SKIP_RESOLVE_ELEMS', 'ALL')
        return QgsSingleton._qgs


class CatAtom2Osm:
    """
    Main application class for a tool to convert the data sets from the
    Spanish Cadastre ATOM Services to OSM files.
    """

    def __init__(self, a_path, options):
        """
        Constructor.

        Args:
            a_path (str): Directory where the source files are located.
            options (dict): Dictionary of options.
        """
        self.options = options
        self.cat = catatom.Reader(a_path)
        self.path = self.cat.path
        self.zip_code = self.cat.zip_code
        self.qgs = QgsSingleton()
        self.qgs_version = qgis.utils.QGis.QGIS_VERSION
        self.gdal_version = gdal.__version__
        log.debug(_("Initialized QGIS %s API"), self.qgs_version)
        log.debug(_("Using GDAL %s"), self.gdal_version)
        self.debug = log.getEffectiveLevel() == logging.DEBUG
        self.fixmes = 0
        self.min_level = {}
        self.max_level = {}
        self.is_new = False

    def run(self):
        """Launches the app"""
        log.info(_("Start processing '%s'"), self.zip_code)
        self.get_zoning()
        if self.options.zoning:
            self.process_zoning()
            if not self.options.tasks:
                del self.rustic_zoning
        self.address_osm = osm.Osm()
        self.building_osm = osm.Osm()
        if self.options.address:
            self.read_address()
            if self.is_new:
                self.options.tasks = False
                self.options.building = False
            elif not self.options.manual:
                current_address = self.get_current_ad_osm()
                self.address.conflate(current_address)
        if self.options.building or self.options.tasks:
            self.get_building()
            self.process_building()
            if self.options.address:
                self.address.del_address(self.building)
                self.building.move_address(self.address)
            self.building.reproject()
            if self.options.tasks:
                self.building.set_tasks(self.urban_zoning, self.rustic_zoning)
            if not self.options.manual:
                current_bu_osm = self.get_current_bu_osm()
                if self.building.conflate(current_bu_osm):
                    self.write_osm(current_bu_osm, 'current_building.osm')
                del current_bu_osm
        if self.options.address:
            self.address.reproject()
            self.address_osm = self.address.to_osm()
        if self.options.tasks:
            self.process_tasks(self.building)
            del self.rustic_zoning
            del self.urban_zoning
        if self.options.building:
            self.building_osm = self.building.to_osm()
            self.merge_address(self.building_osm, self.address_osm)
            self.write_building()
        if self.options.address:
            self.write_osm(self.address_osm, 'address.osm')
            del self.address_osm
        if self.options.parcel:
            self.process_parcel()
        self.end_messages()

    def get_building(self):
        """Merge building, parts and pools"""
        building_gml = self.cat.read("building")
        fn = os.path.join(self.path, 'building.shp')
        layer.ConsLayer.create_shp(fn, building_gml.crs())
        self.building = layer.ConsLayer(fn, providerLib='ogr', 
            source_date=building_gml.source_date)
        self.building.append(building_gml)
        del building_gml
        part_gml = self.cat.read("buildingpart")
        self.building.append(part_gml)
        del part_gml
        other_gml = self.cat.read("otherconstruction", True)
        if other_gml:
            self.building.append(other_gml)
        del other_gml

    def process_tasks(self, source):
        self.get_tasks(source)
        for zoning in (self.rustic_zoning, self.urban_zoning):
            for zone in zoning.getFeatures():
                label = zone['label']
                fn = os.path.join(self.path, 'tasks', label + '.shp')
                if os.path.exists(fn):
                    task = layer.ConsLayer(fn, label, 'ogr', source_date=source.source_date)
                    if task.featureCount() > 0:
                        fn = os.path.join('tasks', label + '.osm')
                        task_osm = task.to_osm(upload='yes')
                        self.merge_address(task_osm, self.address_osm)
                        self.write_osm(task_osm, fn)

    def get_tasks(self, source):
        base_path = os.path.join(self.path, 'tasks')
        if not os.path.exists(base_path):
            os.makedirs(base_path)
        else:
            for fn in os.listdir(base_path):
                os.remove(os.path.join(base_path, fn))
        tasks = 0
        last_task = ''
        to_add = []
        for feat in self.building.getFeatures():
            label = feat['task']
            if label:
                f = source.copy_feature(feat, {}, {})
                if last_task == '' or label == last_task:
                    to_add.append(f)
                else:
                    fn = os.path.join(self.path, 'tasks', last_task + '.shp')
                    if not os.path.exists(fn):
                        layer.ConsLayer.create_shp(fn, source.crs())
                        tasks += 1
                    task = layer.ConsLayer(fn, label, 'ogr', source_date=source.source_date)
                    task.keep = True
                    task.writer.addFeatures(to_add)
                    to_add = [f]
                last_task = label
        log.debug(_("Generated %d task files"), tasks)

    def process_zoning(self):
        self.urban_zoning.delete_invalid_geometries()
        self.urban_zoning.simplify()
        self.rustic_zoning.clean()
        self.urban_zoning.reproject()
        self.rustic_zoning.reproject()
        self.export_layer(self.urban_zoning, 'urban_zoning.geojson', 'GeoJSON')
        self.export_layer(self.rustic_zoning, 'rustic_zoning.geojson', 'GeoJSON')

    def process_building(self):
        """Process all buildings dataset"""
        self.building.remove_outside_parts()
        self.building.explode_multi_parts()
        self.building.clean()
        self.building.validate(self.max_level, self.min_level)

    def write_building(self):
        self.write_osm(self.building_osm, 'building.osm')
        for el in self.building_osm.elements:
            if 'fixme' in el.tags:
                self.fixmes += 1
        del self.building_osm

    def process_parcel(self):
        parcel_gml = self.cat.read("cadastralparcel")
        fn = os.path.join(self.path, 'parcel.shp')
        layer.ParcelLayer.create_shp(fn, parcel_gml.crs())
        parcel = layer.ParcelLayer(fn, providerLib='ogr', 
            source_date=parcel_gml.source_date)
        parcel.append(parcel_gml)
        del parcel_gml
        parcel.reproject()
        parcel_osm = parcel.to_osm()
        self.write_osm(parcel_osm, "parcel.osm")

    def end_messages(self):
        if self.options.tasks or self.options.building:
            dlag = ', '.join(["%d: %d" % (l, c) for (l, c) in \
                OrderedDict(Counter(self.max_level.values())).items()])
            dlbg = ', '.join(["%d: %d" % (l, c) for (l, c) in \
                OrderedDict(Counter(self.min_level.values())).items()])
            log.info(_("Distribution of floors above ground %s"), dlag)
            log.info(_("Distribution of floors below ground %s"), dlbg)
        if self.fixmes:
            log.warning(_("Check %d fixme tags"), self.fixmes)
        if self.is_new:
            log.info(_("The translation file '%s' have been writen in "
                "'%s'"), 'highway_names.csv', self.path)
            log.info(_("Please, check it and run again"))
        else:
            log.info(_("Finished!"))
            log.warning(_("Only for testing purposses. Don't upload any result to OSM"))

    def exit(self):
        """Ends properly"""
        for propname in self.__dict__.keys():
            if isinstance(getattr(self, propname), QgsVectorLayer):
                delattr(self, propname)
        if hasattr(self, 'qgs'):
            self.qgs.exitQgis()

    def export_layer(self, layer, filename, driver_name='ESRI Shapefile'):
        """
        Export a vector layer.

        Args:
            layer (QgsVectorLayer): Source layer.
            filename (str): Output filename.
            driver_name (str): Defaults to ESRI Shapefile.
        """
        out_path = os.path.join(self.path, filename)
        if layer.export(out_path, driver_name):
            log.info(_("Generated '%s'"), filename)
        else:
            raise IOError(_("Failed to write layer: '%s'") % filename)

    def read_osm(self, ql, filename):
        """
        Reads a OSM data set from a OSM XML file. If the file not exists,
        downloads data from overpass using ql query

        Args:
            ql (str): Query to put in the url
            filename (str): File to read/write

        Returns
            Osm: OSM data set
        """
        osm_path = os.path.join(self.path, filename)
        if not os.path.exists(osm_path):
            log.info(_("Downloading '%s'") % filename)
            query = overpass.Query(self.cat.boundary_search_area).add(ql)
            query.download(osm_path)
        fo = open(osm_path, 'r')
        data = osmxml.deserialize(fo)
        if len(data.elements) == 0:
            log.warning(_("No OSM data were obtained from '%s'") % filename)
        else:
            log.info(_("Read '%s': %d nodes, %d ways, %d relations"),
                filename, len(data.nodes), len(data.ways), len(data.relations))
        return data

    def write_osm(self, data, filename):
        """
        Generates a OSM XML file for a OSM data set.

        Args:
            data (Osm): OSM data set
            filename (str): output filename
        """
        for e in data.elements:
            if 'ref' in e.tags:
                del e.tags['ref']
        osm_path = os.path.join(self.path, filename)
        data.merge_duplicated()
        with codecs.open(osm_path, "w", "utf-8") as file_obj:
            osmxml.serialize(file_obj, data)
        log.info(_("Generated '%s': %d nodes, %d ways, %d relations"),
            filename, len(data.nodes), len(data.ways), len(data.relations))

    def get_zoning(self):
        """
        Reads cadastralzoning and splits in 'MANZANA' (urban) and 'POLIGONO'
        (rustic)
        """
        zoning_gml = self.cat.read("cadastralzoning")
        fn = os.path.join(self.path, 'rustic_zoning.shp')
        layer.ZoningLayer.create_shp(fn, zoning_gml.crs())
        self.rustic_zoning = layer.ZoningLayer('r{:03}', fn, 'rusticzoning', 'ogr')
        self.rustic_zoning.append(zoning_gml, level='P')
        self.cat.get_boundary(self.rustic_zoning)
        if self.options.tasks or self.options.zoning:
            fn = os.path.join(self.path, 'urban_zoning.shp')
            layer.ZoningLayer.create_shp(fn, zoning_gml.crs())
            self.urban_zoning = layer.ZoningLayer('u{:05}', fn, 'urbanzoning', 'ogr')
            self.urban_zoning.append(zoning_gml, level='M')
            self.urban_zoning.topology()
            self.urban_zoning.clean_duplicated_nodes_in_polygons()
            self.urban_zoning.merge_adjacents()
            self.rustic_zoning.set_tasks()
            self.urban_zoning.set_tasks()
        del zoning_gml

    def read_address(self):
        """Reads Address GML dataset"""
        address_gml = self.cat.read("address")
        if address_gml.fieldNameIndex('component_href') == -1:
            address_gml = self.cat.read("address", force_zip=True)
            if address_gml.fieldNameIndex('component_href') == -1:
                raise IOError(_("Could not resolve joined tables for the "
                    "'%s' layer") % address_gml.name())
        postaldescriptor = self.cat.read("postaldescriptor")
        thoroughfarename = self.cat.read("thoroughfarename")
        fn = os.path.join(self.path, 'address.shp')
        layer.AddressLayer.create_shp(fn, address_gml.crs())
        self.address = layer.AddressLayer(fn, providerLib='ogr', 
            source_date=address_gml.source_date)
        self.address.append(address_gml)
        self.address.join_field(postaldescriptor, 'PD_id', 'gml_id', ['postCode'])
        self.address.join_field(thoroughfarename, 'TN_id', 'gml_id', ['text'], 'TN_')
        highway = self.get_highway()
        (highway_names, self.is_new) = self.get_translations(self.address, highway)
        self.address.translate_field('TN_text', highway_names)

    def merge_address(self, building_osm, address_osm):
        """
        Copy address from address_osm to building_osm using 'ref' tag.

        If there exists one building with the same 'ref' that an address, copy
        the address tags to the building if isn't a 'entrace' type address or
        else to the entrance if there exist a node with the address coordinates
        in the building.

        If there exists many buildings withe the same 'ref' than an address,
        creates a multipolygon relation and copy the address tags to it. Each
        building will be a member with outer role in the relation if it's a way.
        If it's a relation, each outer member of it is aggregated to the address
        relation.

        Args:
            building_osm (Osm): OSM data set with addresses
            address_osm (Osm): OSM data set with buildings
        """
        if 'source:date' in address_osm.tags:
            building_osm.tags['source:date:addr'] = address_osm.tags['source:date']
        address_index = {}
        building_index = {}
        for bu in building_osm.elements:
            if 'ref' in bu.tags:
                building_index[bu.tags['ref']] = bu
        for ad in address_osm.nodes:
            if ad.tags['ref'] in building_index:
                address_index[ad.tags['ref']] = ad
        for (ref, bu) in building_index.items():
            if ref in address_index:
                ad = address_index[ref]
                if 'entrance' in ad.tags:
                    footprint = [bu] if isinstance(bu, osm.Way) \
                        else [m.element for m in bu.members if m.role == 'outer']
                    for w in footprint:
                        entrance = w.search_node(ad.x, ad.y)
                        if entrance:
                            entrance.tags.update(ad.tags)
                            entrance.tags.pop('ref', None)
                            break
                else:
                    bu.tags.update(ad.tags)

    def write_task(self, fn, building, address_osm=None):
        """Generates osm file for a task"""
        task_path = os.path.join('tasks', fn + '.osm')
        task_osm = building.to_osm(upload='yes')
        if address_osm is not None:
            self.merge_address(task_osm, address_osm)
        self.write_osm(task_osm, task_path)

    def get_translations(self, address, highway):
        """
        If there exists the configuration file 'highway_types.csv', read it,
        else write one with default values. If don't exists the translations file
        'highway_names.csv', creates one parsing names_layer, else reads and returns
        it as a dictionary.

        * 'highway_types.csv' List of osm elements in json format located in the
          application path and contains translations from abreviaturs to full
          types of highways.

        * 'highway_names.csv' is located in the outputh folder and contains
          corrections for original highway names.
        """
        highway_types_path = os.path.join(setup.app_path, 'highway_types.csv')
        if not os.path.exists(highway_types_path):
            csvtools.dict2csv(highway_types_path, setup.highway_types)
        else:
            csvtools.csv2dict(highway_types_path, setup.highway_types)
        highway_names_path = os.path.join(self.path, 'highway_names.csv')
        if not os.path.exists(highway_names_path):
            highway.reproject(address.crs())
            highway_names = address.get_highway_names(highway)
            csvtools.dict2csv(highway_names_path, highway_names)
            is_new = True
        else:
            highway_names = csvtools.csv2dict(highway_names_path, {})
            is_new = False
        return (highway_names, is_new)

    def get_highway(self):
        """Gets OSM highways needed for street names conflation"""
        ql = ['way["highway"]["name"]',
              'relation["highway"]["name"]',
              'way["place"="square"]["name"]',
              'relation["place"="square"]["name"]']
        highway_osm = self.read_osm(ql, 'current_highway.osm')
        highway = layer.HighwayLayer()
        highway.read_from_osm(highway_osm)
        del highway_osm
        return highway

    def get_current_ad_osm(self):
        """Gets OSM address for address conflation"""
        ql = ['node["addr:street"]["addr:housenumber"]',
              'way["addr:street"]["addr:housenumber"]',
              'relation["addr:street"]["addr:housenumber"]',
              'node["addr:place"]["addr:housenumber"]',
              'way["addr:place"]["addr:housenumber"]',
              'relation["addr:place"]["addr:housenumber"]']
        address_osm = self.read_osm(ql, 'current_address.osm')
        current_address = set()
        w = 0
        for d in address_osm.elements:
            if 'addr:housenumber' not in d.tags:
                w += 1
            elif 'addr:street' in d.tags:
                current_address.add(d.tags['addr:street'] + d.tags['addr:housenumber'])
            elif 'addr:place' in d.tags:
                current_address.add(d.tags['addr:place'] + d.tags['addr:housenumber'])
        if w > 0:
            log.warning(_("There are %d address without house number in the OSM data"), w)
        return current_address

    def get_current_bu_osm(self):
        """Gets OSM buildings for building conflation"""
        ql = 'way["building"];relation["building"];'
        current_bu_osm = self.read_osm(ql, 'current_building.osm')
        return current_bu_osm

