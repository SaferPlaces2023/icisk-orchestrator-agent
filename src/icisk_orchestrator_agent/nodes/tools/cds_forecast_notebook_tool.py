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
from icisk_orchestrator_agent.common.notebook_templates.nbt_cds_forecast import notebook_template as nbt_cds_forecast
from icisk_orchestrator_db import DBI, DBS



# DOC: This is a tool that exploits I-Cisk API to ingests forecast data from the Climate Data Store (CDS) API and saves it in a zarr format. It build a jupyter notebook to do that.
class CDSForecastNotebookTool(BaseAgentTool):
    
    
    # DOC: CDS Variable names
    class InputForecastVariable(str, Enum):
    
        total_precipitation = "total_precipitation"
        temperature = "temperature"
        glofas = "glofas"
        
        @property
        def as_cds(self) -> str:
            return {
                'total_precipitation': 'total_precipitation',
                'temperature': '2m_temperature',
                'glofas': 'river_discharge_in_the_last_24_hours',
            }.get(self.value)
            
        @property
        def as_icisk(self) -> str:
            return {
                'total_precipitation': 'tp',
                'temperature': 't2m',
                'glofas': 'dis24',
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
            if 'glofas' in alias:
                return cls.glofas
            if 'discharge' in alias:
                return cls.glofas
            if raise_error:
                raise ValueError(f"{alias} is not a valid {cls.__name__} member")
            return None
                 
    
    # DOC: Tool input schema
    class InputSchema(BaseModel):
        
        forecast_variables: None | list[str] = Field(
            title = "Forecast-Variables",
            description = "List of forecast variables to be retrieved from the CDS API. If not specified use None as default.", 
            examples = [
                None,
                ['total_precipitation'],
                ['temperature'],
                ['glofas'],
                ['total_precipitation', 'glofas'],
            ]
        )
        area: None | str | list[float] = Field(
            title = "Area",
            description = """The area of interest for the forecast data. If not specified use None as default.
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
        init_time: None | str = Field(
            title = "Initialization Time",
            description = f"The date of the forecast initialization provided in UTC-0 YYYY-MM-DD. If not specified use {datetime.datetime.now().replace(day=1).strftime('%Y-%m-%d')} as default.",
            examples = [
                None,
                f"{datetime.datetime.now().replace(day=1).strftime('%Y-%m-%d')}"
            ],
            default = None
        )
        lead_time: None | str = Field(
            title = "Lead Time",
            description = f"The end date of the forecast provided in UTC-0 YYYY-MM-DD. It must be after the init_time arg. If not specified use: {(datetime.datetime.now().replace(day=1) + relativedelta.relativedelta(month=1)).strftime('%Y-%m-%d')} as default.",
            examples = [
                None,
                f"{(datetime.datetime.now().replace(day=1) + relativedelta.relativedelta(month=1)).strftime('%Y-%m-%d')}"
            ],
            default = None
        )
        zarr_output: None | str = Field(
            title = "Output Zarr File",
            description = f"The path to the output zarr file with the forecast data. In could be a local path or a remote path. If not specified is None",
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
            name = N.CDS_FORECAST_NOTEBOOK_TOOL,
            description = """Useful when user want to get forecast data from the Climate Data Store (CDS) API.
            This tool builds a jupityer notebook to ingests forecast data for a specific region and time period, and saves it in a zarr format.
            It exploits I-CISK APIs to build data retrieval and storage by leveraging these CDS dataset:
            - "Seasonal-Original-Single-Levels" for the seasonal forecast of temperature and precipitation data.
            - "CEMS Early Warning Data Store" for the river discharge forecasting (GloFAS) data.
            This tool returns the path to the output zarr file with the retireved forecast data and an editable jupyter notebook that was used to build the data ingest procedure.
            If not provided by the user, assign the specified default values to the arguments.
            """,
            args_schema = CDSForecastNotebookTool.InputSchema,
            **kwargs
        )
        self.output_confirmed = True    # INFO: There is already the execution_confirmed:True
        
    
    # DOC: Validation rules ( i.e.: valid init and lead time ... ) 
    def _set_args_validation_rules(self) -> dict:
        
        return {
            'forecast_variables' : [
                lambda **ka: f"Invalid forecast variables: {[v for v in ka['forecast_variables'] if self.InputForecastVariable.from_str(v) is None]}. It should be a list of valid CDS forecast variables: {[self.InputForecastVariable._member_names_]}."
                    if len([v for v in ka['forecast_variables'] if self.InputForecastVariable.from_str(v) is None]) > 0 else None, 
                lambda **ka: f"Invalid combination of variables: {ka['forecast_variables']}. By now, due to different data proveder settings, GLOFAS can't be used in the same tool with other variables."
                    if self.InputForecastVariable.glofas in [self.InputForecastVariable.from_str(v) for v in ka['forecast_variables']] and len(ka['forecast_variables']) > 1 else None,
            ],
            'area': [
                lambda **ka: f"Invalid area coordinates: {ka['area']}. It should be a list of 4 float values representing the bounding box [min_x, min_y, max_x, max_y]." 
                    if isinstance(ka['area'], list) and len(ka['area']) != 4 else None  
            ],
            'init_time': [
                lambda **ka: f"Invalid initialization time: {ka['init_time']}. It should be in the format YYYY-MM-DD."
                    if ka['init_time'] is not None and utils.try_default(lambda: datetime.datetime.strptime(ka['init_time'], "%Y-%m-%d"), None) is None else None,
                lambda **ka: f"Invalid initialization time: {ka['init_time']}. It should be in the past, at least in the previous month."
                    if ka['init_time'] is not None and datetime.datetime.strptime(ka['init_time'], '%Y-%m-%d') > datetime.datetime.now() else None
            ],
            'lead_time': [
                lambda **ka: f"Invalid lead time: {ka['lead_time']}. It should be in the format YYYY-MM-DD."
                    if ka['lead_time'] is not None and utils.try_default(lambda: datetime.datetime.strptime(ka['lead_time'], "%Y-%m-%d"), None) is None else None,
                lambda **ka: f"Invalid lead time: {ka['lead_time']}. It should be at least one month after the init time."
                    if ka['init_time'] is not None and ka['lead_time'] is not None and utils.try_default(lambda: datetime.datetime.strptime(ka['lead_time'], '%Y-%m') <= datetime.datetime.strptime(ka['init_time'], '%Y-%m'), False) else None,
                lambda **ka: f"Invalid lead time: {ka['lead_time']}. It should be no more than 6 months in the future."
                    if ka['lead_time'] is not None and \
                        self.InputForecastVariable.glofas not in [self.InputForecastVariable.from_str(v) for v in ka['forecast_variables']] and \
                        datetime.datetime.strptime(ka['lead_time'], '%Y-%m-%d') > (datetime.datetime.now().replace(day=1) + relativedelta.relativedelta(months=6)) else None,
                lambda **ka: f"Invalid lead time: {ka['lead_time']}. It should be no more than 1 months in the future for the glofas data."
                    if ka['lead_time'] is not None and \
                        self.InputForecastVariable.glofas in [self.InputForecastVariable.from_str(v) for v in ka['forecast_variables']] and \
                        datetime.datetime.strptime(ka['lead_time'], '%Y-%m-%d') > (datetime.datetime.now().replace(day=1) + relativedelta.relativedelta(months=1)) else None
            ]
        }
        
    
    # DOC: Inference rules ( i.e.: from location name to bbox ... )
    def _set_args_inference_rules(self) -> dict:
        
        def infer_forecast_variables(**ka):
            def alias_to_enum(forecast_variables):
                return [self.InputForecastVariable.from_str(fc_var, raise_error=True) for fc_var in forecast_variables]
            def unique_variables(forecast_variables):
                return list(set(forecast_variables))
            forecast_variables = alias_to_enum(ka['forecast_variables'])
            forecast_variables = unique_variables(forecast_variables)
            return forecast_variables
        
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
                    dataset = self.dataset_from_variables(ka['forecast_variables']) if ka['forecast_variables'] is not None else None
                    if dataset is not None:
                        precision = {
                            'seasonal-original-single-levels': 0,
                            'cems-glofas-seasonal': 1
                        }[dataset]
                        area = [
                            utils.floor_decimals(area[0], precision),
                            utils.floor_decimals(area[1], precision),
                            utils.ceil_decimals(area[2], precision),
                            utils.ceil_decimals(area[3], precision)
                        ]
                return area
            area = bounding_box_from_location_name(ka['area'])
            area = round_bounding_box(area)
            return area
        
        def infer_init_time(**ka):
            if ka['init_time'] is None:
                return datetime.datetime.now().replace(day=1).strftime('%Y-%m-%d')
            return ka['init_time']
        
        def infer_lead_time(**ka):
            if ka['lead_time'] is None:
                return (datetime.datetime.now().replace(day=1) + relativedelta.relativedelta(month=1)).strftime('%Y-%m-%d')
            return ka['lead_time']
        
        def infer_zarr_output(**ka):
            if ka['zarr_output'] is None:
                return f"icisk-ai_cds-forecast-{'-'.join([v.as_icisk for v in ka['forecast_variables']])}_{datetime.datetime.now().isoformat(timespec='seconds').replace(':','-')}.zarr"
            if not ka['zarr_output'].endswith('.zarr'):
                return f"{ka['zarr_output']}.zarr"
            return ka['zarr_output']
        
        def infer_jupyter_notebook(**ka):
            if ka['jupyter_notebook'] is None:
                return f"icisk-ai_cds-forecast-{'-'.join([v.as_icisk for v in ka['forecast_variables']])}_{datetime.datetime.now().isoformat(timespec='seconds').replace(':','-')}.ipynb"
            if not ka['jupyter_notebook'].endswith('.ipynb'):
                return f"{ka['jupyter_notebook']}.ipynb"
            return ka['jupyter_notebook']
        
        return {
            'forecast_variables': infer_forecast_variables,
            'area': infer_area,
            'init_time': infer_init_time,
            'lead_time': infer_lead_time,
            'zarr_output': infer_zarr_output,
            'jupyter_notebook': infer_jupyter_notebook,
        }
        
        
    # DOC: Determine the dataset name based on the forecast variables
    def dataset_from_variables(self, forecast_variables):
        if self.InputForecastVariable.glofas not in [self.InputForecastVariable.from_str(v) for v in forecast_variables]:
            return 'seasonal-original-single-levels' 
        else:
            return 'cems-glofas-seasonal'
        
    
    # DOC: Preapre notebook cell code template
    def prepare_notebook(self, jupyter_notebook):
        self.notebook = DBI.notebook_by_name(author=self.graph_state.get('user_id'), notebook_name=jupyter_notebook, retrieve_source=True)
        if self.notebook is None:
            self.notebook = DBS.Notebook(
                name = jupyter_notebook,
                authors = self.graph_state.get('user_id'),
                source = nbf.v4.new_notebook()
            )
        self.notebook.source.cells.extend(nbt_utils.notebook_copy(nbt_cds_forecast).cells)
    
    
    # DOC: Execute the tool → Build notebook, write it to a file and return the path to the notebook and the zarr output file
    def _execute(
        self,
        forecast_variables: list[str],
        area: str | list[float],
        init_time: str,
        lead_time: str,
        zarr_output: str,
        jupyter_notebook: str
    ): 
        self.prepare_notebook(jupyter_notebook)    
        nb_values = {
            'dataset_name': self.dataset_from_variables(forecast_variables),
            'forecast_variables': [self.InputForecastVariable(var).as_cds for var in forecast_variables],
            'area': area,
            'init_time': init_time,
            'lead_time': lead_time,
            'zarr_output': zarr_output,
            
            'forecast_variables_icisk': [self.InputForecastVariable(var).as_icisk for var in forecast_variables],
            
            'dataset_var_name': f"dataset_cds_forecast_{'_'.join([self.InputForecastVariable(var).as_icisk for var in forecast_variables])}",
        }
        nb_values['dataset_var_description'] = utils.dedent(f"""
            \"\"\"
            Object "{nb_values['dataset_var_name']}" is a xarray.Dataset containing forecast values from {init_time} to {lead_time} for this bounding-box: {area}.
            It has four dimensions named:
            - 'model': list of model ids 
            - 'lat': list of latitudes, 
            - 'lon': list of longitudes,
            - 'time': forecast timesteps
            It has these variables: {[self.InputForecastVariable(var).as_icisk for var in forecast_variables]} representing the {[self.InputForecastVariable(var).as_cds for var in forecast_variables]} forecast data values. Variables have a shape of [model, time, lat, lon].
            \"\"\"
        """, add_tab=2, tab_first=False)
        self.notebook.source = nbt_utils.write_notebook_template(self.notebook.source, values_dict=nb_values, mode=nb_values['dataset_name'])   # DOC: We write different code section based on dataset
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
        forecast_variables: list[str],
        area: str | list[float],
        init_time: str = None,
        lead_time: str = None,
        zarr_output: str = None,
        jupyter_notebook: str = None,
        run_manager: None | Optional[CallbackManagerForToolRun] = None
    ) -> dict:
        
        return super()._run(
            tool_args = {
                "forecast_variables": forecast_variables,
                "area": area,
                "init_time": init_time,
                "lead_time": lead_time,
                "zarr_output": zarr_output,
                "jupyter_notebook": jupyter_notebook,
            },
            run_manager=run_manager,
        )