from unittest import TestCase
from unittest.mock import patch, call
from pathlib import Path
from datetime import date
from typing import Dict
import pandas as pd
import tempfile
import shutil

from src.ETL.ee_boundingbox import BoundingBox

from src.ETL.ee_exporter import (
    LabelExporter,
    RegionExporter,
    EarthEngineExporter,
    get_cloud_tif_list,
)
from src.ETL.constants import LAT, LON, START, END

module = "src.ETL.ee_exporter"


class TestEEExporters(TestCase):

    temp_data_dir: Path
    exporters: Dict[str, EarthEngineExporter]

    @classmethod
    def setUpClass(cls):
        cls.temp_data_dir = Path(tempfile.mkdtemp())
        cls.label_exporter = LabelExporter(check_gcp=False, check_ee=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_data_dir)

    @patch(f"{module}.ee.Geometry.Polygon")
    @patch(f"{module}.EarthEngineExporter._export_for_polygon")
    def test_export_using_point_and_dates(self, mock_export_for_polygon, mock_Polygon):
        mock_poly_return = "mock_poly"
        mock_Polygon.return_value = mock_poly_return
        self.label_exporter._export_using_point_and_dates(
            lat=1, lon=1, start_date=date(2019, 4, 22), end_date=date(2020, 4, 16)
        )
        pref = (
            "tifs/min_lat=0.9993_min_lon=0.9993_max_lat=1.0007_"
            + "max_lon=1.0007_dates=2019-04-22_2020-04-16"
        )
        description = (
            "min_lat-0-9993_min_lon-0-9993_max_lat-1-0007_"
            + "max_lon-1-0007_dates-2019-04-22_2020-04-16"
        )
        mock_export_for_polygon.assert_called_with(
            dest_bucket="crop-mask-tifs",
            file_name_prefix=pref,
            description=description,
            polygon=mock_poly_return,
            start_date=date(2019, 4, 22),
            end_date=date(2020, 4, 16),
        )
        mock_export_for_polygon.reset_mock()

    @patch(f"{module}.LabelExporter._export_using_point_and_dates")
    def test_export_for_labels(self, mock_export_using_point_and_dates):
        mock_labels = pd.DataFrame(
            {
                LAT: [1, 2],
                LON: [1, 2],
                END: ["2020-04-16", "2020-04-16"],
                START: ["2019-04-22", "2019-04-22"],
            }
        )
        self.label_exporter.export(labels=mock_labels)
        self.assertEqual(mock_export_using_point_and_dates.call_count, 2)
        mock_export_using_point_and_dates.assert_has_calls(
            [
                call(lat=1, lon=1, start_date=date(2019, 4, 22), end_date=date(2020, 4, 16)),
                call(lat=2, lon=2, start_date=date(2019, 4, 22), end_date=date(2020, 4, 16)),
            ],
            any_order=True,
        )

    def test_generate_filename(self):
        bbox = BoundingBox(0, 0, 1, 1)
        generated, desc = self.label_exporter._generate_filename_and_desc(
            bbox=bbox, start_date=date(2019, 4, 22), end_date=date(2020, 4, 16)
        )
        self.assertEqual(
            generated, "min_lat=1_min_lon=0_max_lat=1_max_lon=0_dates=2019-04-22_2020-04-16"
        )
        self.assertEqual(
            desc, "min_lat-1_min_lon-0_max_lat-1_max_lon-0_dates-2019-04-22_2020-04-16"
        )

    def test_generate_filename_decimals(self):
        bbox = BoundingBox(0, 0, 0.0008123, 0.0009432)
        generated, desc = self.label_exporter._generate_filename_and_desc(
            bbox=bbox, start_date=date(2019, 4, 22), end_date=date(2020, 4, 16)
        )
        self.assertEqual(
            generated,
            "min_lat=0.0008_min_lon=0_max_lat=0.0009_max_lon=0_dates=2019-04-22_2020-04-16",
        )
        self.assertEqual(
            desc, "min_lat-0-0008_min_lon-0_max_lat-0-0009_max_lon-0_dates-2019-04-22_2020-04-16"
        )

    @patch(f"{module}.storage")
    def test_get_cloud_tif_list(self, mock_storage):
        mock_storage.Client().list_blobs("mock_bucket").return_value = []
        tif_list = get_cloud_tif_list("mock_bucket")
        self.assertEqual(tif_list, [])

    @patch(f"{module}.ee")
    @patch(f"{module}.ee.Geometry.Polygon")
    @patch("src.ETL.cloudfree.fast.ee")
    @patch("src.ETL.cloudfree.utils.ee.batch.Export.image.toDrive")
    def test_export_for_region_metres_per_polygon_none(
        self, mock_export_image, mock_cloudfree_ee, mock_ee_polygon, mock_base_ee
    ):
        RegionExporter().export(
            end_date=date(2020, 4, 16),
            dest_path="Togo",
            metres_per_polygon=None,
            region_bbox=BoundingBox(
                min_lon=-0.1501, max_lon=1.7779296875, min_lat=6.08940429687, max_lat=11.115625
            ),
        )
        mock_base_ee.Initialize.assert_called()

        expected_polygon_count = 1
        expected_image_colls_to_export = 12 * expected_polygon_count
        self.assertEqual(mock_ee_polygon.call_count, expected_polygon_count)
        self.assertEqual(mock_cloudfree_ee.DateRange.call_count, expected_image_colls_to_export * 3)
        self.assertEqual(
            mock_cloudfree_ee.ImageCollection.call_count, expected_image_colls_to_export
        )
        self.assertEqual(mock_export_image.call_count, expected_polygon_count)

    @patch(f"{module}.ee")
    @patch(f"{module}.ee.Geometry.Polygon")
    @patch("src.ETL.cloudfree.fast.ee")
    @patch("src.ETL.cloudfree.utils.ee.batch.Export.image.toDrive")
    def test_export_for_region_metres_per_polygon_set(
        self, mock_export_image, mock_cloudfree_ee, mock_ee_polygon, mock_base_ee
    ):
        RegionExporter().export(
            end_date=date(2020, 4, 16),
            dest_path="Togo",
            metres_per_polygon=10000,
            region_bbox=BoundingBox(
                min_lon=-0.1501, max_lon=1.7779296875, min_lat=6.08940429687, max_lat=11.115625
            ),
        )
        mock_base_ee.Initialize.assert_called()
        expected_polygon_count = 1155
        expected_image_colls_to_export = 12 * expected_polygon_count
        self.assertEqual(mock_ee_polygon.call_count, expected_polygon_count)
        self.assertEqual(mock_cloudfree_ee.DateRange.call_count, expected_image_colls_to_export * 3)
        self.assertEqual(
            mock_cloudfree_ee.ImageCollection.call_count, expected_image_colls_to_export
        )
        self.assertEqual(mock_export_image.call_count, expected_polygon_count)
