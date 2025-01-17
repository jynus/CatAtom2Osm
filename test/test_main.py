import logging
import os
import unittest
from argparse import Namespace
from test.tools import capture

import mock

from catatom2osm import __main__, config
from catatom2osm.exceptions import CatIOError

logging.disable(logging.WARNING)
os.environ["LANGUAGE"] = "C"
config.install_gettext("catato2osm", "")


def raiseIOError(*args, **kwargs):
    raise CatIOError("bartaz")


def raiseImportError(*args, **kwargs):
    raise ImportError("qgis")


class TestMain(unittest.TestCase):
    def setUp(self):
        self.options = Namespace(
            parcel=[],
            zoning=False,
            building=True,
            address=True,
            comment=False,
            download=False,
            list="",
            log_level="INFO",
            manual=False,
            path=["33333"],
            split=None,
            args="33333",
        )

    def compareOptions(self, options):
        for (k, v2) in self.options.__dict__.items():
            v1 = getattr(options, k)
            self.assertEqual(v1, v2, msg="%s != %s in option %s" % (v1, v2, k))

    @mock.patch("catatom2osm.__main__.sys.argv", ["catatom2osm.py"])
    def test_no_args(self):
        with capture(__main__.run) as output:
            self.assertIn("usage: catatom2osm", str(output))

    @mock.patch(
        "catatom2osm.__main__.sys.argv", ["catatom2osm.py", "foo", "bar", "-s", "taz"]
    )
    @mock.patch("catatom2osm.__main__.log.error")
    def test_too_many_args(self, mocklog):
        __main__.run()
        output = mocklog.call_args_list[0][0][0]
        self.assertIn("Can't use split file", output)

    @mock.patch("catatom2osm.__main__.sys.argv", ["catatom2osm.py", "33333"])
    @mock.patch("catatom2osm.__main__.QgsSingleton", mock.MagicMock)
    @mock.patch("catatom2osm.__main__.CatAtom2Osm.create_and_run")
    def test_default(self, mockcat):
        __main__.run()
        self.assertTrue(mockcat.called)
        self.assertEqual(mockcat.call_args_list[0][0][0], "33333")
        options = mockcat.call_args_list[0][0][1]
        self.compareOptions(options)

    @mock.patch("catatom2osm.__main__.sys.argv", ["catatom2osm.py", "33333", "-b"])
    @mock.patch("catatom2osm.__main__.QgsSingleton", mock.MagicMock)
    @mock.patch("catatom2osm.__main__.CatAtom2Osm.create_and_run")
    def test_building(self, mockcat):
        __main__.run()
        self.options.args = "33333 -b"
        self.assertTrue(mockcat.called)
        options = mockcat.call_args_list[0][0][1]
        self.options.address = False
        self.compareOptions(options)

    @mock.patch("catatom2osm.__main__.sys.argv", ["catatom2osm.py", "-w", "33333"])
    @mock.patch("catatom2osm.__main__.Reader")
    def test_download(self, mockcat):
        cat = mock.MagicMock()
        mockcat.return_value = cat
        __main__.run()
        self.options.args = "-w 33333"
        mockcat.assert_called_once_with("33333")
        cat.download.assert_has_calls(
            [
                mock.call("address"),
                mock.call("cadastralzoning"),
                mock.call("building"),
            ]
        )

    @mock.patch("catatom2osm.__main__.sys.argv", ["catatom2osm.py", "-l", "01"])
    @mock.patch("catatom2osm.__main__.log.error")
    def test_list_error(self, mocklog):
        __main__.run()
        self.assertTrue(mocklog.called)
