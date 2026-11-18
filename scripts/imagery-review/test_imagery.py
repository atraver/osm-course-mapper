"""Regression checks independent of model downloads or live imagery."""

import unittest

import numpy as np
from shapely.geometry import Polygon, mapping

from propose import Mosaic, polygon, snap_guide
from screen import screen


class ImageryTests(unittest.TestCase):
    def setUp(self):
        self.m = Mosaic.__new__(Mosaic)
        self.m.grid = {"z": 18, "x0": 230000, "y0": 97000}
        self.m.scale = 256 * 2**18
        self.m.image = np.zeros((65, 65, 3), np.uint8)

    def test_pixel_center_round_trip(self):
        for x, y in [(0, 0), (33, 62), (251, 309)]:
            lon, lat = self.m.lonlat(x, y)
            u, v = self.m.pixel(lon, lat)
            self.assertAlmostEqual(x, u, places=2)
            self.assertAlmostEqual(y, v, places=2)

    def test_vectorized_feature_keeps_holes(self):
        mask = np.zeros((65, 65), np.uint8)
        mask[5:55, 5:57] = 1
        mask[24:36, 24:36] = 0
        area = polygon(mask, (0, 0), self.m.lonlat)
        self.assertTrue(area.is_valid)
        self.assertEqual(len(area.interiors), 1)

    def test_duplicate_shared_green_keeps_both_hole_hints(self):
        area = Polygon(
            [self.m.lonlat(x, y) for x, y in [(5, 5), (30, 5), (30, 30), (5, 30)]]
        )
        features = [
            {
                "type": "Feature",
                "id": f"green-{h}",
                "properties": {"kind": "green", "hole": h},
                "geometry": mapping(area),
            }
            for h in [2, 16]
        ]
        kept = screen(self.m, {"features": features})["features"]
        self.assertEqual(len(kept), 1)
        self.assertIsNone(kept[0]["properties"]["hole"])
        self.assertEqual(kept[0]["properties"]["hole_hints"], [2, 16])

    def test_edge_guide_abutting_crop_is_rejected(self):
        mask = snap_guide(self.m.image, [(1, 1), (45, 1), (45, 45), (1, 45)], 5)
        self.assertIsNone(mask)


if __name__ == "__main__":
    unittest.main()
