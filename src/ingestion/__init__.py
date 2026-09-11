"""
Data Ingestion Layer for Data Centre Digital Twin.

Provides modules to normalize raw external datasets (weather, carbon intensity,
water stress) and fetch/normalize solar irradiance from the NREL NSRDB API.
"""

from .base import (
    get_cleaned_data_dir,
    get_project_root,
    get_raw_data_dir,
    get_real_data_dir,
    save_cleaned_dataset,
)

__all__ = [
    "get_project_root",
    "get_real_data_dir",
    "get_raw_data_dir",
    "get_cleaned_data_dir",
    "save_cleaned_dataset",
]
