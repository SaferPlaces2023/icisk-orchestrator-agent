import os
import datetime
from dateutil import relativedelta
from enum import Enum

import nbformat as nbf

from typing import Optional
from pydantic import BaseModel, Field
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)

from icisk_orchestrator_agent import utils
from icisk_orchestrator_agent import names as N
from icisk_orchestrator_agent.nodes.base import BaseAgentTool
from icisk_orchestrator_agent.common.notebook_templates import nbt_utils
from icisk_orchestrator_agent.common.notebook_templates.nbt_cds_historic import notebook_template as nbt_cds_historic
from icisk_orchestrator_db import DBI, DBS

# DOC: This is a tool that exploits I-Cisk API to ingests historic data from the Climate Data Store (CDS) API and saves it in a zarr format. It build a jupyter notebook to do that.
class CDSHistoricNotebookTool(BaseAgentTool):
    
    class InputHistoricCDSDataset(str, Enum):
        reanalysis_era5_land_monthly_means = "reanalysis-era5-land-monthly-means"
        reanalysis_era5_land = "reanalysis-era5-land"
        
        @property
        def as_str(self) -> str:
            return self.value.replace('_', '-')
        
        @classmethod
        def from_str(cls, alias, raise_error=False):
            if alias in cls.__members__:
                return cls[alias]
            if alias.replace('-', '_') in cls.__members__:
                return cls[alias.replace('-', '_')]
            if alias == f'{cls.__name__}.reanalysis_era5_land_monthly_means':
                return cls.reanalysis_era5_land_monthly_means
            if 'month' in alias:
                return cls.reanalysis_era5_land_monthly_means
            if alias == f'{cls.__name__}.reanalysis_era5_land':
                return cls.reanalysis_era5_land
            if 'hour' in alias:
                return cls.reanalysis_era5_land
            if raise_error:
                raise ValueError(f"{alias} is not a valid {cls.__name__} member")
            return None
        
    class InputHistoricVariable(str, Enum):
    
        total_precipitation = "total_precipitation"
        temperature = "temperature"
        
        @property
        def as_cds(self) -> str:
            return {
                'total_precipitation': 'total_precipitation',
                'temperature': '2m_temperature',
            }.get(self.value)
            
        @property
        def as_icisk(self) -> str:
            return {
                'total_precipitation': 'tp',
                'temperature': 't2m',
            }.get(self.value)
            
        @property
        def as_str(self) -> str:
            return self.value
            
        @classmethod
        def from_str(cls, alias, raise_error=False):
            if alias in cls.__members__:
                return cls[alias]
            if 'prec' in alias:
                return cls.total_precipitation
            if 'temp' in alias:
                return cls.temperature
            if raise_error:
                raise ValueError(f"{alias} is not a valid {cls.__name__} member")
            return None
    
    class InputSchema(BaseModel):
        
        historic_dataset: None | str = Field(
            title = "Historic Dataset",
            description = """The historic dataset to be used for the data retrieval. If not specified use None as default.
            It could be one of the following: 
            - 'reanalysis-era5-land-monthly-means': to get monthly means data from the Climate Data Store (CDS) API.
            - 'reanalysis-era5-land': to get hourly data from the Climate Data Store (CDS) API.""",
            examples=[
                None,
                "reanalysis-era5-land-monthly-means",
                "reanalysis-era5-land",
            ]
        )
        historic_variables: None | list[str] = Field(
            title = "Historic Variables",
            description = "List of historic variables to be retrieved from the CDS API. If not specified use None as default.", 
            examples = [
                None,
                ['total_precipitation'],
                ['temperature']
            ]
        )
        area: None | str | list[float] = Field(
            title = "Area",
            description = """The area of interest for the historic data. If not specified use None as default.
            It could be a bouning-box defined by [min_x, min_y, max_x, max_y] coordinates provided in EPSG:4326 Coordinate Reference System.
            Otherwise it can be the name of a country, continent, or specific geographic area.""",
            examples=[
                None,
                "Italy",
                "Paris",
                "Continental Spain",
                "Alps",
                [12, 52, 14, 53],
                [-5.5, 35.2, 5.58, 45.10],
            ]
        )
        start_time: None | str = Field(
            title = "Start Time",
            description = f"The start datetime provided in UTC-0 YYYY-MM-DD. If not specified use {(datetime.datetime.now() - relativedelta.relativedelta(months=2)).strftime('%Y-%m-01')} as default.",
            examples = [
                None,
                f"{(datetime.datetime.now() - relativedelta.relativedelta(months=2)).strftime('%Y-%m-01')}"
            ],
            default = None
        )
        end_time: None | str = Field(
            title = "End Time",
            description = f"The end date provided in UTC-0 YYYY-MM-DD. It must be after the start_time arg. If not specified use: {(datetime.datetime.now() - relativedelta.relativedelta(months=1)).strftime('%Y-%m-01')} as default.",
            examples = [
                None,
                f"{(datetime.datetime.now() - relativedelta.relativedelta(months=1)).strftime('%Y-%m-01')}"
            ],
            default = None
        )
        zarr_output: None | str = Field(
            title = "Output Zarr File",
            description = f"The path to the output zarr file with the historic data. In could be a local path or a remote path. If not specified is None",
            examples = [
                None,
                "C:/Users/username/appdata/local/temp/output-<variable>.zarr",
                "/path/to/output-<variable>-<date>.zarr",
                "S3://bucket-name/path/to/<location>-<varibale>-data.zarr",
            ],
            default = None
        )
        jupyter_notebook: None | str = Field(
            title = "Jupyter Notebook",
            description = f"The path to the jupyter notebook that was used to build the data ingest procedure. If not specified is None",
            examples = [
                None,
                "C:/Users/username/appdata/local/temp/output-<variable>.ipynb",
                "/path/to/output-<variable>-<date>.ipynb",
                "S3://bucket-name/path/to/<location>-<varibale>-data.ipynb",
            ],
            default = None
        )
        
    
    # DOC: Additional tool args
    notebook: DBS.Notebook = None

    
    # DOC: Initialize the tool with a name, description and args_schema
    def __init__(self, **kwargs):
        super().__init__(
            name = N.CDS_HISTORIC_NOTEBOOK_TOOL,
            description = """Useful when user want to get historic data from the Climate Data Store (CDS) API.
            This tool builds a jupityer notebook to ingests historic data for a specific region and time period, and saves it in a zarr format.
            This tool returns the path to the output zarr file with the retireved historic data and an editable jupyter notebook that was used to build the data ingest procedure.
            If not provided by the user, assign the specified default values to the arguments.
            """,
            args_schema = CDSHistoricNotebookTool.InputSchema,
            **kwargs
        )
        self.output_confirmed = True    # INFO: There is already the execution_confirmed:True
        
        
    # DOC: Validation rules ( i.e.: valid init and lead time ... ) 
    def _set_args_validation_rules(self) -> dict:
        
        return {
            'historic_dataset': [
                lambda **ka: f"Invalid historic dataset: {ka['historic_dataset']}. It should be a list of valid CDS historic dataset: {[self.InputHistoricCDSDataset._member_names_]}."
                    if self.InputHistoricCDSDataset.from_str(ka['historic_dataset']) is None else None   
            ],                
            'historic_variables' : [
                lambda **ka: f"Invalid historic variables: {[v for v in ka['historic_variables'] if self.InputHistoricVariable.from_str(v) is None]}. It should be a list of valid CDS historic variables: {[self.InputHistoricVariable._member_names_]}."
                    if len([v for v in ka['historic_variables'] if self.InputHistoricVariable.from_str(v) is None]) > 0 else None 
            ],
            'area': [
                lambda **ka: f"Invalid area coordinates: {ka['area']}. It should be a list of 4 float values representing the bounding box [min_x, min_y, max_x, max_y]." 
                    if isinstance(ka['area'], list) and len(ka['area']) != 4 else None  
            ],
            'start_time': [
                lambda **ka: f"Invalid start time: {ka['start_time']}. It should be in the format YYYY-MM-DD."
                    if ka['start_time'] is not None and utils.try_default(lambda: datetime.datetime.strptime(ka['start_time'], "%Y-%m-%d"), None) is None else None,
                lambda **ka: f"Invalid start time: {ka['start_time']}. It should be in the past, at least in the previous month."
                    if ka['start_time'] is not None and datetime.datetime.strptime(ka['start_time'], '%Y-%m-%d') > datetime.datetime.now().replace(day=1) else None
            ],
            'end_time': [
                lambda **ka: f"Invalid end time: {ka['end_time']}. It should be in the format YYYY-MM-DD."
                    if ka['end_time'] is not None and utils.try_default(lambda: datetime.datetime.strptime(ka['end_time'], "%Y-%m-%d"), None) is None else None,
                lambda **ka: f"Invalid end time: {ka['end_time']}. It should be at least one month after the init time."
                    if ka['start_time'] is not None and ka['end_time'] is not None and utils.try_default(lambda: datetime.datetime.strptime(ka['end_time'], '%Y-%m') <= datetime.datetime.strptime(ka['start_time'], '%Y-%m'), False) else None,
                lambda **ka: f"Invalid end time: {ka['end_time']}. It should be at least in the previous month with respect to the current date"
                    if ka['end_time'] is not None and datetime.datetime.strptime(ka['end_time'], '%Y-%m-%d') >= datetime.datetime.now().replace(day=1) else None
            ]
        }
        
        
    # DOC: Inference rules ( i.e.: from location name to bbox ... )
    def _set_args_inference_rules(self) -> dict:
        
        def infer_historic_dataset(**ka):
            def alias_to_enum(historic_dataset):
                return self.InputHistoricCDSDataset.from_str(historic_dataset, raise_error=True)
            return alias_to_enum(ka['historic_dataset'])
        
        def infer_historic_variables(**ka):
            def alias_to_enum(historic_variables):
                return [self.InputHistoricVariable.from_str(hc_var, raise_error=True) for hc_var in historic_variables]
            def unique_variables(historic_variables):
                return list(set(historic_variables))
            historic_variables = alias_to_enum(ka['historic_variables'])
            historic_variables = unique_variables(historic_variables)
            return alias_to_enum(ka['historic_variables'])
        
        def infer_area(**ka):
            def bounding_box_from_location_name(area):
                if type(area) is str:
                    area = utils.ask_llm(
                        role = 'system',
                        message = f"""Please provide the bounding box coordinates for the area: {area} with format [min_x, min_y, max_x, max_y] in EPSG:4326 Coordinate Reference System. 
                        Provide only the coordinates list without any additional text or explanation.""",
                        eval_output = True
                    )
                    self.execution_confirmed = False
                return area
            def round_bounding_box(area):
                if type(area) is list:
                    area = [
                        utils.floor_decimals(area[0], 1),
                        utils.floor_decimals(area[1], 1),
                        utils.ceil_decimals(area[2], 1),
                        utils.ceil_decimals(area[3], 1)
                    ]
                return area
            area = bounding_box_from_location_name(ka['area'])
            area = round_bounding_box(area)
            return area
        
        def infer_start_time(**ka):
            if ka['start_time'] is None:
                return (datetime.datetime.now().date() - relativedelta.relativedelta(month=2)).strftime('%Y-%m-01')
            elif ka['end_time'] is not None and ka['start_time'] > ka['end_time']:
                ka['start_time'] = ka['end_time']
            return ka['start_time']
        
        def infer_end_time(**ka):
            if ka['end_time'] is None:
                return (datetime.datetime.now().date() - relativedelta.relativedelta(month=1)).strftime('%Y-%m-01')
            elif ka['start_time'] is not None and ka['end_time'] < ka['start_time']:
                ka['end_time'] = ka['start_time']
            return ka['end_time']
        
        def infer_zarr_output(**ka):
            if ka['zarr_output'] is None:
                return f"icisk-ai_cds-historic-{'-'.join([v.as_icisk for v in ka['historic_variables']])}_{datetime.datetime.now().isoformat(timespec='seconds').replace(':','-')}.zarr"
            if not ka['zarr_output'].endswith('.zarr'):
                return f"{ka['zarr_output']}.zarr"
            return ka['zarr_output']
        
        def infer_jupyter_notebook(**ka):
            if ka['jupyter_notebook'] is None:
                return f"icisk-ai_cds-historic-{'-'.join([v.as_icisk for v in ka['historic_variables']])}_{datetime.datetime.now().isoformat(timespec='seconds').replace(':','-')}.ipynb"
            if not ka['jupyter_notebook'].endswith('.ipynb'):
                return f"{ka['jupyter_notebook']}.ipynb"
            return ka['jupyter_notebook']
        
        return {
            'historic_dataset': infer_historic_dataset,
            'historic_variables': infer_historic_variables,
            'area': infer_area,
            'start_time': infer_start_time,
            'end_time': infer_end_time,
            'zarr_output': infer_zarr_output,
            'jupyter_notebook': infer_jupyter_notebook
        }
       
        
    # DOC: Preapre notebook cell code template
    def prepare_notebook(self, jupyter_notebook):
        self.notebook = DBI.notebook_by_name(author=self.graph_state.get('user_id'), notebook_name=jupyter_notebook, retrieve_source=True)
        if self.notebook is None:
            self.notebook = DBS.Notebook(
                name = jupyter_notebook,
                authors = self.graph_state.get('user_id'),
                source = nbf.v4.new_notebook()
            )
        self.notebook.source.cells.extend(nbt_utils.notebook_copy(nbt_cds_historic).cells)
        
        
    # DOC: Execute the tool → Build notebook, write it to a file and return the path to the notebook and the zarr output file
    def _execute(
        self,
        historic_dataset: str,
        historic_variables: list[str],
        area: str | list[float],
        start_time: str,
        end_time: str,
        zarr_output: str,
        jupyter_notebook: str
    ): 
        self.prepare_notebook(jupyter_notebook)    
        nb_values = {
            'historic_dataset': self.InputHistoricCDSDataset(historic_dataset).as_str,
            'historic_variables': [self.InputHistoricVariable(var).as_cds for var in historic_variables],
            'area': area,
            'start_time': start_time,
            'end_time': end_time,
            'zarr_output': zarr_output,
            
            'historic_variables_icisk': [self.InputHistoricVariable(var).as_icisk for var in historic_variables],
            
            'dataset_var_name': f"dataset_cds_historic_{'_'.join([self.InputHistoricVariable(var).as_icisk for var in historic_variables])}",
        }
        nb_values['dataset_var_description'] = utils.dedent(f"""
             \"\"\"
            Object "{nb_values['dataset_var_name']}" is a xarray.Dataset containing historic values from {start_time} to {end_time} for this bounding-box: {area}.
            It has four dimensions named:
            - 'time': historic timesteps
            - 'lat': list of latitudes, 
            - 'lon': list of longitudes,
            It has these variables: {[self.InputHistoricVariable(var).as_icisk for var in historic_variables]} representing the {[self.InputHistoricVariable(var).as_cds for var in historic_variables]} historic data values. Variables have a shape of [time, lat, lon].
            \"\"\"
        """, add_tab=2, tab_first=False)
        self.notebook.source = nbt_utils.write_notebook_template(self.notebook.source, values_dict=nb_values, mode=nb_values['historic_dataset'])   # DOC: We write different code section based on dataset  
        DBI.save_notebook(self.notebook)
        
        # DOC: Back to a consisent state
        self.execution_confirmed = False
        
        return {
            "data_source": zarr_output,
            "notebook": jupyter_notebook,
        }
        
    
    # DOC: Back to a consisent state
    def _on_tool_end(self):
        self.execution_confirmed = False
        self.output_confirmed = True   
        
        
    # DOC: Try running AgentTool → Will check required, validity and inference over arguments thatn call and return _execute()
    def _run(
        self, 
        historic_dataset: str,
        historic_variables: list[str],
        area: str | list[float],
        start_time: str = None,
        end_time: str = None,
        zarr_output: str = None,
        jupyter_notebook: str = None,
        run_manager: None | Optional[CallbackManagerForToolRun] = None
    ) -> dict:
        
        return super()._run(
            tool_args = {
                "historic_dataset": historic_dataset,
                "historic_variables": historic_variables,
                "area": area,
                "start_time": start_time,
                "end_time": end_time,
                "zarr_output": zarr_output,
                "jupyter_notebook": jupyter_notebook,
            },
            run_manager=run_manager,
        )