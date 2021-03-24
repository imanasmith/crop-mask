from abc import ABC
from datetime import datetime
import geopandas
import pandas as pd
from pathlib import Path
import numpy as np
import logging
import pickle
from tqdm import tqdm
import xarray as xr

from typing import Callable, Dict, Tuple, Optional, Union
from src.band_calculations import process_bands
from src.utils import set_seed, process_filename, load_tif
from .data_instance import CropDataInstance

logger = logging.getLogger(__name__)


class Engineer(ABC):
    r"""Combine earth engine sentinel data
    and geowiki landcover 2017 data to make
    numpy arrays which can be input into the
    machine learning model
    """

    # should be True if the dataset contains data which will
    # only be used for evaluation (e.g. the TogoEvaluation dataset)
    eval_only: bool = False

    data_folder = Path(__file__).parent.parent.parent / "data"

    def __init__(
        self, dataset: str, sentinel_dataset: str, labels_file: str = "data.geojson"
    ) -> None:
        set_seed()
        self.dataset = dataset

        sentinel_files = self.data_folder / "raw" / sentinel_dataset
        self.geospatial_files = list(sentinel_files.glob("*.tif"))

        labels_path = self.data_folder / "processed" / self.dataset / labels_file
        self.labels = self._read_labels(labels_path)

        self.savedir = self.data_folder / "features" / self.dataset
        self.savedir.mkdir(exist_ok=True, parents=True)

        self.normalizing_dict_interim: Dict[str, Union[np.ndarray, int]] = {"n": 0}

    def _read_labels(self, labels_path: Path) -> pd.DataFrame:
        if not labels_path.exists():
            raise FileNotFoundError(
                f"{self.dataset} processor must be run to load labels file: {labels_path}"
            )
        if labels_path.suffix == ".geojson":
            return geopandas.read_file(labels_path)
        elif labels_path.suffix == ".nc":
            return xr.open_dataset(labels_path).to_dataframe().dropna().reset_index()
        else:
            raise ValueError(f"_read_labels is not implemented for suffix {labels_path.suffix}")

    @staticmethod
    def _find_nearest(array, value: float) -> Tuple[float, int]:
        array = np.asarray(array)
        idx = (np.abs(array - value)).argmin()
        return array[idx], idx

    @staticmethod
    def _update_normalizing_values(
        norm_dict: Dict[str, Union[np.ndarray, int]], array: np.ndarray
    ) -> None:
        # given an input array of shape [timesteps, bands]
        # update the normalizing dict
        # https://en.wikipedia.org/wiki/Algorithms_for_calculating_variance
        # https://www.johndcook.com/blog/standard_deviation/
        num_bands = array.shape[1]

        # initialize
        if "mean" not in norm_dict:
            norm_dict["mean"] = np.zeros(num_bands)
            norm_dict["M2"] = np.zeros(num_bands)

        for time_idx in range(array.shape[0]):
            norm_dict["n"] += 1

            x = array[time_idx, :]

            delta = x - norm_dict["mean"]
            norm_dict["mean"] += delta / norm_dict["n"]
            norm_dict["M2"] += delta * (x - norm_dict["mean"])

    def _update_batch_normalizing_values(
        self, norm_dict: Dict[str, Union[np.ndarray, int]], array: np.ndarray
    ) -> None:

        assert len(array.shape) == 3, "Expected array of shape [batch, timesteps, bands]"

        for idx in range(array.shape[0]):
            subarray = array[idx, :, :]
            self._update_normalizing_values(norm_dict, subarray)

    def _calculate_normalizing_dict(
        self, norm_dict: Dict[str, Union[np.ndarray, int]]
    ) -> Optional[Dict[str, np.ndarray]]:

        if "mean" not in norm_dict:
            logger.warning(
                "No normalizing dict calculated! Make sure to call _update_normalizing_values"
            )
            return None

        variance = norm_dict["M2"] / (norm_dict["n"] - 1)
        std = np.sqrt(variance)
        return {"mean": norm_dict["mean"], "std": std}

    def _create_labeled_data_instance(
        self,
        path_to_file: Path,
        crop_probability: Union[float, Callable],
        is_global: bool,
        is_maize: bool,
        crop_type_func: Optional[Callable],
        nan_fill: float,
        max_nan_ratio: float,
        add_ndvi: bool,
        add_ndwi: bool,
        calculate_normalizing_dict: bool,
        start_date: datetime,
        days_per_timestep: int,
        is_test: bool,
    ) -> Optional[CropDataInstance]:
        r"""
        Return a tuple of np.ndarrays of shape [n_timesteps, n_features] for
        1) the anchor (labelled)
        """

        da = load_tif(path_to_file, days_per_timestep=days_per_timestep, start_date=start_date)

        # first, we find the label encompassed within the da

        min_lon, min_lat = float(da.x.min()), float(da.y.min())
        max_lon, max_lat = float(da.x.max()), float(da.y.max())
        overlap = self.labels[
            (
                (self.labels.lon <= max_lon)
                & (self.labels.lon >= min_lon)
                & (self.labels.lat <= max_lat)
                & (self.labels.lat >= min_lat)
            )
        ]
        if len(overlap) == 0:
            return None

        if isinstance(crop_probability, float):
            calculated_crop_probability = crop_probability
        else:
            calculated_crop_probability = crop_probability(overlap.iloc[0])

        if calculated_crop_probability is None:
            return None

        crop_label = None
        if crop_type_func:
            crop_label = crop_type_func(overlap.iloc[0])

        label_lat = overlap.iloc[0].lat
        label_lon = overlap.iloc[0].lon

        closest_lon, _ = self._find_nearest(da.x, label_lon)
        closest_lat, _ = self._find_nearest(da.y, label_lat)

        labelled_np = da.sel(x=closest_lon).sel(y=closest_lat).values
        labelled_array = process_bands(
            labelled_np,
            nan_fill=nan_fill,
            max_nan_ratio=max_nan_ratio,
            add_ndvi=add_ndvi,
            add_ndwi=add_ndwi,
        )

        if (not is_test) and calculate_normalizing_dict:
            self._update_normalizing_values(self.normalizing_dict_interim, labelled_array)

        if labelled_array is not None:
            return CropDataInstance(
                crop_probability=calculated_crop_probability,
                instance_lat=closest_lat,
                instance_lon=closest_lon,
                is_global=is_global,
                is_maize=is_maize,
                label_lat=label_lat,
                label_lon=label_lon,
                labelled_array=labelled_array,
                crop_label=crop_label,
            )
        return None

    def create_pickled_labeled_dataset(
        self,
        crop_probability: Union[float, Callable],
        is_global: bool = False,
        is_maize: bool = False,
        crop_type_func: Optional[Callable] = None,
        val_set_size: float = 0.1,
        test_set_size: float = 0.1,
        nan_fill: float = 0.0,
        max_nan_ratio: float = 0.3,
        checkpoint: bool = True,
        add_ndvi: bool = True,
        add_ndwi: bool = False,
        include_extended_filenames: bool = True,
        calculate_normalizing_dict: bool = True,
        days_per_timestep: int = 30,
    ):
        logger.info(f"{self.dataset}: creating pickled labeled dataset")
        for file_path in tqdm(self.geospatial_files):

            file_info = process_filename(
                file_path.name, include_extended_filenames=include_extended_filenames
            )

            if file_info is None:
                continue

            identifier, start_date, end_date = file_info

            file_name = f"{identifier}_{str(start_date.date())}_{str(end_date.date())}"

            if checkpoint:
                # we check if the file has already been written
                if (
                    (self.savedir / "validation" / f"{file_name}.pkl").exists()
                    or (self.savedir / "training" / f"{file_name}.pkl").exists()
                    or (self.savedir / "testing" / f"{file_name}.pkl").exists()
                ):
                    continue

            if self.eval_only:
                data_subset = "testing"
            else:
                random_float = np.random.uniform()
                # we split into (val, test, train)
                if random_float <= (val_set_size + test_set_size):
                    if random_float <= val_set_size:
                        data_subset = "validation"
                    else:
                        data_subset = "testing"
                else:
                    data_subset = "training"

            instance = self._create_labeled_data_instance(
                file_path,
                crop_probability=crop_probability,
                is_global=is_global,
                is_maize=is_maize,
                crop_type_func=crop_type_func,
                nan_fill=nan_fill,
                max_nan_ratio=max_nan_ratio,
                add_ndvi=add_ndvi,
                add_ndwi=add_ndwi,
                calculate_normalizing_dict=calculate_normalizing_dict,
                start_date=start_date,
                days_per_timestep=days_per_timestep,
                is_test=True if data_subset == "testing" else False,
            )
            if instance is not None:
                subset_path = self.savedir / data_subset
                subset_path.mkdir(exist_ok=True)
                save_path = subset_path / f"{file_name}.pkl"
                with save_path.open("wb") as f:
                    pickle.dump(instance, f)

        if calculate_normalizing_dict:
            normalizing_dict = self._calculate_normalizing_dict(
                norm_dict=self.normalizing_dict_interim
            )

            if normalizing_dict is not None:
                save_path = self.savedir / "normalizing_dict.pkl"
                with save_path.open("wb") as f:
                    pickle.dump(normalizing_dict, f)
            else:
                logger.warning("No normalizing dict calculated!")
