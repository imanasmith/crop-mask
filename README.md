# Crop Map Generation

[![Status](https://github.com/nasaharvest/crop-mask/actions/workflows/main.yml/badge.svg)](https://github.com/nasaharvest/crop-mask/actions)
[![codecov](https://codecov.io/gh/nasaharvest/crop-mask/branch/master/graph/badge.svg?token=MARPAEPZMS)](https://codecov.io/gh/nasaharvest/crop-mask)

This repository contains code and data to generate annual and in-season crop masks. Two models are trained - a multi-headed pixel wise classifier to classify pixels as containing crop or not, and a multi-spectral satellite image forecaster which forecasts a 12 month timeseries given a partial input:

<img src="diagrams/models.png" alt="models" height="200px"/>

These can be used to create annual and in season crop maps.

## Contents

-   [1. Setting up a local environment](#1-setting-up-a-local-environment)
-   [2. Training a new model](#2-training-a-new-model)
-   [3. Running inference locally](#3-running-inference-locally)
-   [4. Running inference at scale (on GCP)](#4-running-inference-at-scale--on-gcp-)
-   [5. Tests](#5-tests)
-   [6. Previously generated crop maps](#6-previously-generated-crop-maps)
-   [7. Acknowledgments](#7-acknowledgments)
-   [8. Reference](#8-reference)

## 1. Setting up a local environment

1. Ensure you have [anaconda](https://www.anaconda.com/download/#macos) installed and run:
    ```bash
    conda config --set channel_priority true # Ensures conda will install environment
    conda env create -f environment-dev.yml   # Creates environment
    conda activate landcover-mapping      # Activates environment
    ```
2. [OPTIONAL] When adding new labeled data, Google Earth Engine is used to export Satellite data. To authenticate Earth Engine run:
    ```bash
    earthengine authenticate                # Authenticates Earth Engine
    python -c "import ee; ee.Initialize()"  # Will raise error if not setup
    ```
3. [OPTIONAL] To access existing data (ie. features, models), ensure you have [gcloud](https://cloud.google.com/sdk/docs/install) CLI installed and run:
    ```bash
    gcloud auth application-default login     # Authenticates gcloud
    dvc pull                                  # All data (will take long time)
    dvc pull data/features data/models        # For retraining or inference
    dvc pull data/processed                   # For labeled data analysis
    ```
    If you get an "invalid grant" error, you may need to run:
    ```bash
    gcloud auth application-default login
    ```

## 2. Adding new labeled data

1. Ensure local environment is set up and all existing data is downloaded.
2. Add the shape file for new labels into [data/raw](data/raw)
3. In [dataset_labeled.py](src/datasets_labeled.py) add a new `LabeledDataset` object into the `labeled_datasets` list and specify the required parameters.
4. To create ML ready features run:

    ```bash
    # To download satellite data
    gsutil -m cp -n -r gs://crop-mask-tifs/tifs data/

    # To create features
    python scripts/create_features
    ```

    If satellite data for the new labels is not available, the satellite data will be downloaded from Google Earth Engine.
    After running the above script, export progress can be viewed here: https://code.earthengine.google.com/
    Once all tasks are complete rerun the above commands and the features will be created.

5. Run `dvc commit` and `dvc push` to upload the new labeled data to remote storage.

<img src="diagrams/data_processing_chart.png" alt="models" height="200px"/>

## 2. Training a new model

Training can be done locally or on grid.ai.

#### Training locally

Add a new entry to [data/models.json](data/models.json), for example:

```json
{
    "model_name": "Ethiopia_Tigray_2021",
    "min_lon": 36.45,
    "max_lon": 40.00,
    "min_lat": 12.25,
    "max_lat": 14.895,
    "eval_datasets": ["Ethiopia_Tigray_2021"],
    "train_datasets": ["geowiki_landcover_2017" "Ethiopia"]
}
```

Then to train and evaluate the model run:

```python
python scripts/train_and_evaluate.py
```

**What do the does the json entry mean?**
`train_datasets` tells the model to train on data found in:

-   `features/geowiki_landcover_2017/training/*.pkl`
-   `features/Ethiopia/training/*.pkl`

`eval_datasets` tells the model to evaluate on data found in:

-   `features/Ethiopia_Tigray_2021/validation/*.pkl`

`min/max_lat/lon` tells the model which items to consider in the local and global head

Any other valid model parameter can be added to this entry.

#### Training on grid.ai

Grid.ai is a platform which allows you to train and evaluate several machine learning models in parallel.

To train models on grid.ai :

```bash
# Install the CLI
pip install lightning-grid

# Login
grid login

# Create datastore
grid datastore create --source /path/to/crop-mask/data/features --name features

# Create a session
grid session create

# Check status of session
grid status

# When session is ready
grid session ssh <session name>

# Clone repository into session
git clone https://github.com/nasaharvest/crop-mask.git

# Navigate to crop-mask directory
cd crop-mask

# Run training script with grid
grid run \
    --name <run name> \
    --instance_type 2_CPU_8gb \
    --datastore_name features \
    --datastore_version 1 \
    --datastore_mount_dir /data/features \
    --framework lightning scripts/train_model.py \
    --data_folder /data \
    --model_dir models \
    --target_bbox_key Kenya \
    --eval_datasets Kenya \
    --train_datasets '["geowiki_landcover_2017,Kenya", "digitalearthafrica,Kenya"]' \
    --do_not_forecast
```

You'll be able to track the runs in the [Grid.ai UI](https://grid.ai/) and once all training runs are complete you can download the artifacts (models, tensorboard logs, etc) to analyze them.

```bash
grid artifacts <run name>

# View tensorboard logs
tensorboard --logdir=<path to tensorboard logs>
```

More details about Grid: https://docs.grid.ai/start-here/typical-workflow-cli-user

## 3. Running inference locally

**Prerequisite: Getting unlabeled data:**

1. Ensure local environment is set up.
2. In [dataset_unlabeled.py](src/datasets_unlabeled.py) add a new `UnlabeledDataset` object into the `unlabeled_datasets` list and specify the required parameters.
3. To begin exporting satellite data from Google Earth Engine, run (from scripts directory):
    ```bash
    python export_for_unlabeled.py --dataset_name <dataset name>
    ```
4. Google Earth Engine will automatically export satellite images to Google Drive.
5. Once the satellite data has been exported, download it from Google Drive into [data/raw](data/raw).

**Actual inference**

```bash
python predict.py --model_name "Kenya" --local_path_to_tif_files "../data/raw/<dataset name>
```

## 4. Running inference at scale (on GCP)

**Deploying**

1. Ensure you have [gcloud](https://cloud.google.com/sdk/docs/install) CLI installed and authenticated.
2. Ensure you have a secret in GCP titled `GOOGLE_APPLICATION_CREDENTIALS`; this will allow Google Earth Engine to be authenticated.
3. Run the following to deploy the project into Google Cloud:

```bash
gsutil mb gs://crop-mask-earthengine
gsutil mb gs://crop-mask-preds
sh deploy_ee_functions.sh
sh deploy_inference.sh
```

**Checking which models are available**
https://crop-mask-management-api-grxg7bzh2a-uc.a.run.app/models

**Actual inference at scale**

```bash

curl -X POST http://us-central1-bsos-geog-harvest1.cloudfunctions.net/export-unlabeled \
    -H "Content-Type:application/json" \
    -d @gcp/<example>.json
```

**Tracking progress**

```bash
# Earth Engine progress
curl https://us-central1-bsos-geog-harvest1.cloudfunctions.net/ee-status?additional=FAILED,COMPLETED | python -mjson.tool

# Amount of files exported
gsutil du gs://crop-mask-earthengine/<model name>/<dataset> | wc -l

# Amount of files predicted
gsutil du gs://crop-mask-preds/<model name>/<dataset> | wc -l
```

**Addressing missed predictions (Not automated)**
When processing 100,000 tif files it is highly likely that crop-mask inference may fail on some files due to issues with not scaling up fast enough. Run the cells in [notebooks/fix-preds-on-gcloud.ipynb](notebooks/fix-preds-on-gcloud.ipynb) to address this problem.

**Putting it all together (Not automated)**
Once an inference run is complete the result is several small `.nc` files. These need to be merged into a single `.tif` file. Currently this operation is not automated and requires the user to:

```bash
export MODEL="Rwanda"
export DATASET="Rwanda_v2"
export START_YEAR=2019
export END_YEAR=2020

# Download appropriate folder
gsutil -m cp -n -r gs://crop-mask-preds/$MODEL/$DATASET/ .

# Run gdal merge script
python gcp/merger/main.py --p <current-dir>/$DATASET

# [OPTIONAL] Upload COG tif output to Google Cloud Storage
gsutil cp <current-dir>/$DATASET/tifs/final.tif gs://crop-mask-preds-merged/$DATASET

# [OPTIONAL] Upload COG to Google Earth Engine
earthengine upload image --asset_id users/izvonkov/$DATASET \
    -ts $START_YEAR-04-01 \
    -te $END_YEAR-04-01 \
    gs://crop-mask-preds-merged/$DATASET
```

## 5. Tests

The following tests can be run against the pipeline:

```bash
flake8 --max-line-length 100 src data scripts test # code formatting
mypy src data scripts  # type checking
python -m unittest # unit tests

# Integration tests
cd test
python -m unittest integration_test_labeled.py
python -m unittest integration_test_predict.py
```

## 6. Previously generated crop maps

Google Earth Engine:

-   [Kenya (post season)](https://code.earthengine.google.com/ea3613a3a45badfd01ce2ec914dfe1ef)
-   [Busia (in season)](https://code.earthengine.google.com/f567cccc28dad7a25e088d56dabfbd4c)

Zenodo

-   [Kenya (post season) and Busia (in season)](https://doi.org/10.5281/zenodo.4271143).

## 7. Acknowledgments

This model requires data from [Plant Village](https://plantvillage.psu.edu/) and [One Acre Fund](https://oneacrefund.org/). We thank those organizations for making these datasets available to us - please contact them if you are interested in accessing the data.

## 8. Reference

If you find this code useful, please cite the following paper:

Gabriel Tseng, Hannah Kerner, Catherine Nakalembe and Inbal Becker-Reshef. 2020. Annual and in-season mapping of cropland at field scale with sparse labels. Tackling Climate Change with Machine Learning workshop at NeurIPS ’20: December 11th, 2020
