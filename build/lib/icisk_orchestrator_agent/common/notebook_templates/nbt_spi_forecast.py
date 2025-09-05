import os
import datetime

import nbformat as nbf

from .nbt_utils import CellMetadata

notebook_template = nbf.v4.new_notebook()
notebook_template.cells.extend([
    nbf.v4.new_code_cell("""
        # Section "install dependencies and import libs"

        %%capture

        import os
        import math
        import datetime
        from dateutil.relativedelta import relativedelta
        import getpass

        import numpy as np
        import pandas as pd
        import xarray as xr

        import scipy.stats as stats
        from scipy.special import gammainc, gamma

        !pip install "cdsapi>=0.7.4"
        import cdsapi
    """, 
    metadata={ CellMetadata.CHECK_IMPORT: True }),
    
    nbf.v4.new_code_cell("""
        # Section "Parameters"

        spi_ts = 1

        area = {area} # min_lon, min_lat, max_lon, max_lat

        reference_period = {reference_period} # start_year, end_year

        init_time = datetime.datetime.strptime('{init_time}', "%Y-%m-%d").replace(day=1)
        
        lead_time = datetime.datetime.strptime('{lead_time}', "%Y-%m-%d").replace(day=1)

        cds_client = cdsapi.Client(url='https://cds.climate.copernicus.eu/api', key=getpass.getpass("YOUR CDS-API-KEY")) # CDS client
    """, 
    metadata={ CellMetadata.NEED_FORMAT: True }),
    
    nbf.v4.new_code_cell("""
        filename = f'era5_land__total_precipitation__{"_".join([str(c) for c in area])}__monthly__{reference_period[0]}_{reference_period[1]:02d}.nc'

        out_dir = 'tmpdir'
        os.makedirs(out_dir, exist_ok=True)

        cds_out_filename = os.path.join(out_dir, filename)

        if not os.path.exists(cds_out_filename):
            cds_dataset = 'reanalysis-era5-land-monthly-means'
            cds_query =  {
                'product_type': 'monthly_averaged_reanalysis',
                'variable': 'total_precipitation',
                'year': [str(year) for year in range(*reference_period)],
                'month': [f'{month:02d}' for month in range(1, 13)],
                'time': '00:00',
                'area': [
                    area[3],  # N
                    area[0],  # W
                    area[1],  # S
                    area[2]   # E
                ],
                "data_format": "netcdf",
                "download_format": "unarchived"
            }

            cds_client.retrieve(cds_dataset, cds_query, cds_out_filename)

        cds_ref_data = xr.open_dataset(cds_out_filename)
    """,
    metadata={ CellMetadata.CHECK_EXISTENCE: True }),
    
    nbf.v4.new_code_cell("""
        # Section "Retrieve period of interest data from CDS"

        # Get (Years, Years-Months) couple for the CDS api query. (We can query just one month at time)
        curr_date = datetime.datetime.now().date()
        if init_time.strftime('%Y-%m') >= curr_date.strftime('%Y-%m'):
            init_date = datetime.datetime.now().replace(day=1).date()
        else:
            init_date = init_time.replace(day=1)

        start_hour = max(24, (init_time.date() - init_date).days*24)
        end_hour = min(5160, (lead_time.date() - init_time.date()).days*24 + start_hour)

        spi_start_date = init_time - relativedelta(months=spi_ts-1)
        spi_years_range = list(range(spi_start_date.year, lead_time.year+1))
        spi_month_range = []
        for iy,year in enumerate(range(spi_years_range[0], spi_years_range[-1]+1)):
            if iy==0 and len(spi_years_range)==1:
                spi_month_range.append([month for month in range(spi_start_date.month, lead_time.month+1)])
            elif iy==0 and len(spi_years_range)>1:
                spi_month_range.append([month for month in range(spi_start_date.month, 13)])
            elif iy>0 and iy==len(spi_years_range)-1:
                spi_month_range.append([month for month in range(1, lead_time.month+1)])
            else:
                spi_month_range.append([month for month in range(1, 13)])

        def build_cds_hourly_data_filepath(start_year, start_month, end_year, end_month):
            dataset_part = 'seasonal_original_single_levels__total_precipitation__daily'
            time_part = f'{start_year}-{start_month:02d}' if start_year==end_year and start_month==end_month else f'{start_year}-{start_month:02d}_{end_year}-{end_month:02d}'
            filename = f'{dataset_part}__{"_".join([str(c) for c in area])}__{time_part}.nc'
            filedir = os.path.join(out_dir, dataset_part)
            if not os.path.exists(filedir):
                os.makedirs(filedir, exist_ok=True)
            filepath = os.path.join(filedir, filename)
            return filepath

        def floor_decimals(number, decimals=0):
            factor = 10 ** decimals
            return math.floor(number * factor) / factor

        def ceil_decimals(number, decimals=0):
            factor = 10 ** decimals
            return math.ceil(number * factor) / factor

        cds_poi_data_filepath = build_cds_hourly_data_filepath(init_time.year, init_time.month, lead_time.year, lead_time.month)

        if not os.path.exists(cds_poi_data_filepath):
            cds_dataset = "seasonal-original-single-levels"
            cds_query = {
                "originating_centre": "ecmwf",
                "system": "51",
                "variable": [
                    "total_precipitation"
                ],
                "year": [str(init_date.year)],
                "month": [f'{init_date.month:02d}'],
                "day": ["01"],
                "leadtime_hour": [str(h) for h in range(start_hour, end_hour+24, 24)],
                "area": [
                    ceil_decimals(area[3], 1),    # N
                    floor_decimals(area[0], 1),   # W
                    floor_decimals(area[1], 1),   # S
                    ceil_decimals(area[2], 1),    # E
                ],
                "data_format": "netcdf",
                "download_format": "unarchived"
            }
            cds_client.retrieve(cds_dataset, cds_query, cds_poi_data_filepath)

        cds_poi_data = xr.open_dataset(cds_poi_data_filepath)
        cds_poi_data = xr.Dataset(
            {
                'tp': (['model', 'time', 'lat', 'lon'], cds_poi_data.tp.values[:,0,:,:,:])
            },
            coords={
                'model': np.arange(0,len(cds_poi_data.number),1),
                'time': cds_poi_data.valid_time.values,
                'lat': cds_poi_data.latitude.values,
                'lon': cds_poi_data.longitude.values
            }
        )
        cds_poi_data = cds_poi_data.sortby(['time', 'lat', 'lon'])
        cds_poi_data = cds_poi_data.sel(time=(cds_poi_data.time.dt.date>=init_time.date()) & (cds_poi_data.time.dt.date<=lead_time.date()))
    """),
    
    nbf.v4.new_code_cell("""
        # Preprocess reference dataset
        cds_ref_data = cds_ref_data.drop_vars(['number', 'expver'])
        cds_ref_data = cds_ref_data.rename({'valid_time': 'time', 'latitude': 'lat', 'longitude': 'lon'})
        cds_ref_data = cds_ref_data * cds_ref_data['time'].dt.days_in_month
        cds_ref_data = cds_ref_data.assign_coords(
            lat=np.round(cds_ref_data.lat.values, 6),
            lon=np.round(cds_ref_data.lon.values, 6),
        )
        cds_ref_data = cds_ref_data.sortby(['time', 'lat', 'lon'])

        # Preprocess period-of-interest dataset
        cds_poi_data = cds_poi_data.resample(time='1ME').mean()                                     # Resample to monthly total data
        cds_poi_data = cds_poi_data.assign_coords(time=cds_poi_data.time.dt.strftime('%Y-%m-01'))   # Set month day to 01
        cds_poi_data = cds_poi_data.assign_coords(time=pd.to_datetime(cds_poi_data.time))
        cds_poi_data['tp'] = cds_poi_data['tp'] / 12                                                # Convert total precipitation to monthly average precipitation
        cds_poi_data = cds_poi_data.assign_coords(
            lat=np.round(cds_poi_data.lat.values, 6),
            lon=np.round(cds_poi_data.lon.values, 6),
        )
        cds_poi_data = cds_poi_data.sortby(['time', 'lat', 'lon'])

        # Get whole dataset
        ts_dataset = xr.concat([cds_ref_data, cds_poi_data], dim='time')
        ts_dataset = ts_dataset.drop_duplicates(dim='time').sortby(['time', 'lat', 'lon'])
    """),
    
    nbf.v4.new_code_cell("""
        # Compute SPI function
        def compute_timeseries_spi(monthly_data, spi_ts, nt_return=1):
            # Compute SPI index for a time series of monthly data
            # REF: https://drought.emergency.copernicus.eu/data/factsheets/factsheet_spi.pdf
            # REF: https://mountainscholar.org/items/842b69e8-a465-4aeb-b7ec-021703baa6af [ page 18 to 24 ]
            
            # SPI calculation needs finite-values and non-zero values
            if all([md<=0 for md in monthly_data]):
                return 0
            if all([np.isnan(md) or md==0 for md in monthly_data]):
                return np.nan
            
            df = pd.DataFrame({'monthly_data': monthly_data})

            # Totalled data over t_scale rolling windows
            if spi_ts > 1:
                t_scaled_monthly_data = df.rolling(spi_ts).sum().monthly_data.iloc[spi_ts:]
            else:
                t_scaled_monthly_data = df.monthly_data
                
            t_scaled_monthly_data = t_scaled_monthly_data.fillna(1e-6)

            # Gamma fitted params
            a, _, b = stats.gamma.fit(t_scaled_monthly_data, floc=0)

            # Cumulative probability distribution
            G = lambda x: stats.gamma.cdf(x, a=a, loc=0, scale=b)

            m = (t_scaled_monthly_data==0).sum()
            n = len(t_scaled_monthly_data)
            q = m / n # zero prob

            H = lambda x: q + (1-q) * G(x) # zero correction

            t = lambda Hx: math.sqrt(
                math.log(1 /
                (math.pow(Hx, 2) if 0<Hx<=0.5 else math.pow(1-Hx, 2))
            ))

            c0, c1, c2 = 2.515517, 0.802853, 0.010328
            d1, d2, d3 = 1.432788, 0.189269, 0.001308

            Hxs = t_scaled_monthly_data[-spi_ts:].apply(H)
            txs = Hxs.apply(t)

            Z = lambda Hx, tx: ( tx - ((c0 + c1*tx + c2*math.pow(tx,2)) / (1 + d1*tx + d2*math.pow(tx,2) + d3*math.pow(tx,3) )) ) * (-1 if 0<Hx<=0.5 else 1)

            spi_t_indexes = pd.DataFrame(zip(Hxs, txs), columns=['H','t']).apply(lambda x: Z(x.H, x.t), axis=1).to_list()

            return np.array(spi_t_indexes[-nt_return]) if nt_return==1 else np.array(spi_t_indexes[-nt_return:])
    """,
    metadata={ CellMetadata.CHECK_EXISTENCE: True }),
    
    nbf.v4.new_code_cell("""
        # Compute SPI over each cell
        month_spi_coverages = []
        for month in cds_poi_data.time:
            month_spi_coverage = xr.apply_ufunc(
                lambda tile_timeseries: compute_timeseries_spi(tile_timeseries, spi_ts=spi_ts, nt_return=1),
                ts_dataset.sel(time=ts_dataset.time<=month).tp.sortby('time'),
                input_core_dims = [['time']],
                vectorize = True
            )
            month_spi_coverages.append((
                month.dt.date.item(),
                month_spi_coverage
            ))

        # Create SPI dataset
        spi_times = [msc[0] for msc in month_spi_coverages]
        spi_grids = [msc[1] for msc in month_spi_coverages]

        dataset_spi_forecast = xr.concat(spi_grids, dim='time').to_dataset()
        dataset_spi_forecast = dataset_spi_forecast.assign_coords({'time': spi_times})
        dataset_spi_forecast = dataset_spi_forecast.rename_vars({'tp': 'spi_fc'})

        dataset_spi_forecast = dataset_spi_forecast.transpose('model', 'time', 'lat', 'lon')
    """),
    
    nbf.v4.new_code_cell("""
        # Section "Describe dataset_spi_forecast"

        \"\"\"
        Object "dataset_spi_forecast" is a xarray.Dataset
        It has four dimensions named:
        - 'model': list of model ids 
        - 'time': forecast timesteps
        - 'lat': list of latitudes, 
        - 'lon': list of longitudes,
        It has 1 variables named spi_fc representing the spi forecast values. It has a shape of [model, time, lat, lon].
        \"\"\"

        # Use the dataset_spi_forecast variable to do next analysis or plots

        display(dataset_spi_forecast)
    """)
])