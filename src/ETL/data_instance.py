import numpy as np
from dataclasses import dataclass
from typing import Union
from .ee_boundingbox import BoundingBox


@dataclass
class CropDataInstance:
    crop_probability: float
    instance_lat: float
    instance_lon: float
    is_global: bool
    label_lat: float
    label_lon: float
    labelled_array: Union[float, np.ndarray]
    data_subset: str
    source_file: str
    start_date_str: str
    end_date_str: str

    def isin(self, bounding_box: BoundingBox) -> bool:
        return (
            (self.instance_lon <= bounding_box.max_lon)
            & (self.instance_lon >= bounding_box.min_lon)
            & (self.instance_lat <= bounding_box.max_lat)
            & (self.instance_lat >= bounding_box.min_lat)
        )