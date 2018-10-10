# -*- coding: utf-8 -*-
"""CatAtom2Osm command line entry point"""
from __future__ import unicode_literals
from builtins import str, bytes
from argparse import ArgumentParser
import logging
import os
import sys
from zipfile import BadZipfile

import setup
from report import instance as report

log = logging.getLogger(setup.app_name)
fh = logging.FileHandler(setup.log_file)
ch = logging.StreamHandler(sys.stderr)
fh.setLevel(logging.DEBUG)
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter(setup.log_format)
ch.setFormatter(formatter)
fh.setFormatter(formatter)
log.addHandler(ch)
log.addHandler(fh)


def __(msg):
    return str(msg) if sys.stdout.encoding == 'utf-8' else \
        bytes(msg, setup.encoding).decode(sys.stdout.encoding)

usage = __(_("""catatom2osm [OPTION]... [PATH]
The argument path states the directory for input and output files. 
The directory name shall start with 5 digits (GGMMM) matching the Cadastral 
Provincial Office and Municipality Code. If the program don't find the input 
files it will download them for you from the INSPIRE Services of the Spanish 
Cadastre."""))

def process(options):
    a_path = '' if len(options.path) == 0 else options.path[0]
    if options.list:
        from catatom import list_municipalities
        list_municipalities('{:>02}'.format(options.list))
    elif options.download:
        from catatom import Reader
        cat = Reader(a_path)
        cat.download('address')
        cat.download('cadastralzoning')
        cat.download('building')
    else:
        from catatom2osm import CatAtom2Osm
        app = CatAtom2Osm(a_path, options)
        app.run()
        app.exit()

def run():
    parser = ArgumentParser(usage=usage)
    parser.add_argument("path", nargs="*",
        help=__(_("Directory for input and output files")))
    parser.add_argument("-v", "--version", action="version",
        help=_("Show program's version number and exit"),
        version=setup.app_version)
    parser.add_argument("-l", "--list", dest="list", metavar="prov",
        default=False, help=__(_("List available municipalities given the two "
        "digits province code")))
    parser.add_argument("-t", "--tasks", dest="tasks", default=False,
        action="store_true", help=__(_("Splits constructions into tasks files " \
        "(default, implies -z)")))
    parser.add_argument("-z", "--zoning", dest="zoning", default=False,
        action="store_true", help=__(_("Process the cadastral zoning dataset")))
    parser.add_argument("-b", "--building", dest="building", default=False,
        action="store_true", help=__(_("Process buildings to a single file " \
        "instead of tasks")))
    parser.add_argument("-d", "--address", dest="address", default=False,
        action="store_true", help=__(_("Process the address dataset (default)")))
    parser.add_argument("-p", "--parcel", dest="parcel", default=False,
        action="store_true", help=__(_("Process the cadastral parcel dataset")))
    parser.add_argument("-a", "--all", dest="all", default=False,
        action="store_true", help=__(_("Process all datasets (equivalent " \
        "to -bdptz)")))
    parser.add_argument("-m", "--manual", dest="manual", default=False,
        action="store_true", help=__(_("Dissable conflation with OSM data")))
    parser.add_argument("-w", "--download", dest="download", default=False,
        action="store_true", help=__(_("Download only")))
    parser.add_argument("--log", dest="log_level", metavar="log_level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=setup.log_level, help=__(_("Select the log level between " \
        "DEBUG, INFO, WARNING, ERROR or CRITICAL.")))
    options = parser.parse_args()
    report.options = ' '.join(sys.argv[1:])
    if options.all:
        options.building = True
        options.tasks = True
        options.address = True
        options.parcel = True
    if not (options.tasks or options.zoning or options.building or 
            options.address or options.parcel): # default options
        options.tasks = True
        options.address = True
    if options.tasks:
        options.zoning = True
    log_level = getattr(logging, options.log_level.upper())
    log.setLevel(log_level)

    if len(options.path) > 1:
        log.error(_("Too many arguments, supply only a directory path."))
    elif len(options.path) == 0 and not options.list:
        parser.print_help()
    elif log.getEffectiveLevel() == logging.DEBUG:
        process(options)
    else:
        try:
            process(options)
        except (ImportError, IOError, OSError, ValueError, BadZipfile) as e:
            msg = e.message if getattr(e, 'message', '') else str(e)
            log.error(msg)
            if 'qgis' in msg or 'core' in msg or 'osgeo' in msg:
                log.error(_("Please, install QGIS"))

if __name__ == "__main__":
    run()
