import os
import datetime

import nbformat as nbf

from .nbt_utils import CellMetadata

notebook_template = nbf.v4.new_notebook()
notebook_template.cells.extend([
    nbf.v4.new_code_cell("""
        # Section "Dependencies"

        %%capture

        import os
        import json
        import time
        import datetime
        import requests
        import getpass
        import pprint
        from calendar import monthrange

        import numpy as np
        import pandas as pd

        !pip install zarr xarray
        import xarray as xr

        !pip install s3fs
        import s3fs

        !pip install "cdsapi>=0.7.4"
        import cdsapi
        
        !pip install cartopy
        import cartopy.crs as ccrs
        import cartopy.feature as cfeature
    """, metadata={ CellMetadata.CHECK_IMPORT: True }),
    
    nbf.v4.new_code_cell("""
        # Section "Define constant"
        
        # CDS Dataset name
        dataset_name = '{historic_dataset}'

        # Forcast variables
        historic_variables = {historic_variables}
        
        # Bouning box of interest in format [min_lon, min_lat, max_lon, max_lat]
        region = {area}

        # init forecast datetime
        start_time = datetime.datetime.strptime('{start_time}', "%Y-%m-%d").replace(day=1)

        # lead forecast datetime
        end_time = datetime.datetime.strptime('{end_time}', "%Y-%m-%d").replace(day=1)

        # ingested data ouput zarr file
        zarr_output = '{zarr_output}'
    """, metadata={ CellMetadata.NEED_FORMAT: True }),
    
    nbf.v4.new_code_cell("""
        # Section "Call I-Cisk cds-ingestor-process API" from reanalysis-era5-land-monthly-means dataset [ https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land-monthly-means?tab=overview ]

        job_responses = { hist_var: { 'job_id': None, 'result': None } for hist_var in historic_variables }

        for hist_var in historic_variables:

            # Prepare payload
            icisk_api_payload = {
                "inputs": {
                    "dataset": dataset_name,
                    "file_out": f"/tmp/{zarr_output.replace('.zarr', f'-{hist_var}')}.nc",
                    "query": {
                        "product_type": ["monthly_averaged_reanalysis"],
                        "variable": [hist_var],
                        "year": [str(year) for year in range(start_time.year, end_time.year+1)],
                        "month": pd.date_range(start=start_time, end=end_time, freq='MS').strftime('%m').unique().to_list(),
                        "time": ["00:00"],
                        "area": [
                            region[3],
                            region[0],
                            region[1],
                            region[2]
                        ],
                        "data_format": "netcdf",
                        "download_format": "unarchived"
                    },
                    "token": "YOUR-ICISK-API-TOKEN",
                    "zarr_out": f"s3://saferplaces.co/test/icisk/ai-agent/{zarr_output.replace('.zarr', f'-{hist_var}')}.zarr",
                }
            }

            print(); print('###################################################################'); print();

            print('• Payload')
            pprint.pprint(icisk_api_payload)

            print(); print('-------------------------------------------------------------------'); print();

            icisk_api_token = 'token' # getpass.getpass("YOUR ICISK-API-TOKEN: ")

            icisk_api_payload['inputs']['token'] = icisk_api_token

            # Call API
            root_url = 'https://i-cisk.dev.52north.org/ingest'
            icisk_api_response = requests.post(
                url = f'{root_url}/processes/ingestor-cds-process/execution',
                headers = { 'Prefer': 'respond-async' },
                json = icisk_api_payload
            )

            # Get job id
            job_id = icisk_api_response.headers['Location'].split("/")[-1]
            job_responses[hist_var]['job_id'] = job_id

            # Display response
            print('• Response')
            pprint.pprint({
                'job_id': job_id,
                'status_code': icisk_api_response.status_code,
            })

            print(); print('###################################################################'); print();
    """,
    metadata = { CellMetadata.MODE: 'reanalysis-era5-land-monthly-means' }), 
    
    nbf.v4.new_code_cell("""
        # Section "Call I-Cisk cds-ingestor-process API" from reanalysis-era5-land [ https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land?tab=overview ]

        job_responses = dict() 

        for year_month in pd.date_range(start=start_time, end=end_time, freq='MS').to_list():
            
            for hist_var in historic_variables:

                job_responses[f'{year_month.strftime("%Y%m")}-{hist_var}'] = { 'job_id': None, 'result': None }

                zarr_output = zarr_output.replace('.zarr', f'{year_month.strftime("%Y%m")}-{hist_var}.zarr')

                # Prepare payload
                icisk_api_payload = {
                    "inputs": {
                        "dataset": dataset_name,
                        "file_out": f"/tmp/{zarr_output.replace('.zarr', f'-{hist_var}')}.nc",
                        "query": {
                            "variable": [hist_var],
                            "year": str(year_month.year),
                            "month": f'{year_month.month:02d}',
                            "day": [f'{d:02d}' for d in range(1,monthrange(year_month.year, year_month.month)[1])],
                            "time": [f'{h:02d}:00' for h in range(0,24)],
                            "area": [
                                region[3],
                                region[0],
                                region[1],
                                region[2]
                            ],
                            "data_format": "netcdf",
                            "download_format": "unarchived"
                        },
                        "token": "YOUR-ICISK-API-TOKEN",
                        "zarr_out": f"s3://saferplaces.co/test/icisk/ai-agent/{zarr_output.replace('.zarr', f'-{hist_var}')}.zarr",
                    }
                }

                print(); print('###################################################################'); print();

                print('• Payload')
                pprint.pprint(icisk_api_payload)

                print(); print('-------------------------------------------------------------------'); print();

                icisk_api_token = 'token' # getpass.getpass("YOUR ICISK-API-TOKEN: ")

                icisk_api_payload['inputs']['token'] = icisk_api_token

                # Call API
                root_url = 'https://i-cisk.dev.52north.org/ingest'
                icisk_api_response = requests.post(
                    url = f'{root_url}/processes/ingestor-cds-process/execution',
                    headers = { 'Prefer': 'respond-async' },
                    json = icisk_api_payload
                )

                # Get job id
                job_id = icisk_api_response.headers['Location'].split("/")[-1]
                job_responses[f'{year_month.strftime("%Y%m")}-{hist_var}']['job_id'] = job_id

                # Display response
                print('• Response')
                pprint.pprint({
                    'job_id': job_id,
                    'status_code': icisk_api_response.status_code,
                })

                print(); print('###################################################################'); print();
    """,
    metadata = { CellMetadata.MODE: 'reanalysis-era5-land' }), 
    
    nbf.v4.new_code_cell("""
        timesleep = 30

        while any([job_response['result']==None for job_response in job_responses.values()]):
            for hist_var,job_response in job_responses.items():
                if job_response['result'] is None:
                    job_status = requests.get(f'{root_url}/jobs/{job_response["job_id"]}?f=json').json()['status']
                    if job_status in ["failed", "successful", "dismissed"]:
                        job_response['result'] = requests.get(f'{root_url}/jobs/{job_response["job_id"]}/results?f=json').json()
                        print(f'> {datetime.datetime.now().strftime("%H:%M:%S")} - {hist_var} is {job_status}')
                    else:
                        print(f'> {datetime.datetime.now().strftime("%H:%M:%S")} - {hist_var} status is "{job_status}" - retring in {timesleep} seconds')
            if any([job_response['result']==None for job_response in job_responses.values()]):
                time.sleep(timesleep)
    """),
    
    nbf.v4.new_code_cell("""
        # Section "Get data from I-Cisk collection"

        dataset_list = []

        for var in {historic_variables_icisk}:

            living_lab = None
            collection_name = f"{{dataset_name}}_{{start_time.strftime('%Y%m')}}_{{living_lab}}_{{var}}"

            # Query collection
            collection_response = requests.get(
                f'{{root_url}}/collections/{{collection_name}}/cube',
                params = {{
                    'bbox': ','.join(map(str, region)),
                    'f': 'json'
                }}
            )

            # Get response
            if collection_response.status_code == 200:
                collection_data = json.loads(collection_response.content)
            else:
                print(f'Error {{collection_response.status_code}}: {{collection_response.json()}}')

            # Parse collection output data
            axes = collection_data['domain']['axes']
            params = collection_data['parameters']
            ranges = collection_data['ranges']

            dims = {{
                'time': pd.date_range(axes['valid_time']['start'], axes['valid_time']['stop'], axes['valid_time']['num']),
                'lon': np.linspace(axes['x']['start'], axes['x']['stop'], axes['x']['num'], endpoint=True),
                'lat': np.linspace(axes['y']['start'], axes['y']['stop'], axes['y']['num'], endpoint=True)
            }}
            vars = {{
                var: (tuple(dims.keys()), np.array(ranges[var]['values']).reshape((len(dims['time']), len(dims['lon']), len(dims['lat'])))) 
            }}

            # Build xarray dataset
            dataset = xr.Dataset(
                data_vars = vars,
                coords = dims
            )
            dataset_list.append(dataset)

        {dataset_var_name} = xr.merge(dataset_list).sortby(['time', 'lat', 'lon'])
    """,
    metadata = { CellMetadata.NEED_FORMAT: True }),
    
    nbf.v4.new_code_cell("""
        # Section "Describe {dataset_var_name}"

        {dataset_var_description}

        # Use the {dataset_var_name} variable to do next analysis or plots

        display({dataset_var_name})
    """, 
    metadata={ CellMetadata.NEED_FORMAT: True })
    
])