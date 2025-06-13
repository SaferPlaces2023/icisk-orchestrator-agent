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
from icisk_orchestrator_agent.common import names as N
from icisk_orchestrator_agent.common.notebook_templates import nbt_utils
from icisk_orchestrator_agent.common.notebook_templates.nbt_spi_forecast import notebook_template as nbt_spi_forecast

from icisk_orchestrator_agent.nodes.base import BaseAgentTool

from icisk_orchestrator_db import DBI, DBS



# DOC: This is a tool that exploits I-Cisk API to calculate SPI (Standard Precipitation Index) for a given location in a give time period.

class SPIForecastNotebookTool(BaseAgentTool):
    
    
    # DOC: Tool input schema
    class InputSchema(BaseModel):
        
        area: None | str | list[float] = Field(
            title = "Area",
            description = """The area of interest for the forecast data. If not specified use None as default.
            It   could be a bouning-box defined by [min_x, min_y, max_x, max_y] coordinates provided in EPSG:4326 Coordinate Reference System.
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
        reference_period: None | tuple = Field(
            title = "Reference Period",
            description = f"Tuple of two integere representing the start and end year of the reference period. Default is (1981, 2010).",
            examples = [
                None,
                (1981, 2010),
                (1990, 2000),
                (2000, 2020),
            ],
            default = (1981, 2010)
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
            description = f"The end date of the forecast lead time provided in UTC-0 YYYY-MM-DD. It must be after the init_time arg. If not specified use: {(datetime.datetime.now().replace(day=1) + relativedelta.relativedelta(month=1)).strftime('%Y-%m-%d')} as default.",
            examples = [
                None,
                f"{(datetime.datetime.now().replace(day=1) + relativedelta.relativedelta(month=1)).strftime('%Y-%m-%d')}"
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
            name = N.SPI_FORECAST_NOTEBOOK_TOOL,
            description = """Build a new Jupyter notebook for calculating the forecast values of Standardized Precipitation Index (SPI) for a given region and return the path where the notebook is saved.
            The tool uses the Climate Data Store (CDS) API to retrieve the necessary data from "ERA5-Land monthly averaged data from 1950 to present" dataset
            Use this tool when user asks for an help in SPI calculation even if user does not provide region.""",
            args_schema = SPIForecastNotebookTool.InputSchema,
            **kwargs
        )
        self.output_confirmed = True    # INFO: There is already the execution_confirmed:True
        
        
    # DOC: Validation rules ( i.e.: valid init and lead time ... ) 
    def _set_args_validation_rules(self) -> dict:
        
        return {
            'area': [
                lambda **ka: f"Invalid area coordinates: {ka['area']}. It should be a list of 4 float values representing the bounding box [min_x, min_y, max_x, max_y]." 
                    if isinstance(ka['area'], list) and len(ka['area']) != 4 else None  
            ],
            'reference_period': [
                lambda **ka: f"Invalid reference_period: {ka['reference_period']}. It should be a tuple of start and ending year as integers."
                    if type(ka['reference_period']) not in (tuple, list) or len(ka['reference_period']) != 2 else None,
                lambda **ka: f"Invalid reference_period: {ka['reference_period']}. It should be in the past, at least in the previous year."
                    if ka['reference_period'][1] > datetime.datetime.now().year else None
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
                lambda **ka: f"Invalid lead time: {ka['lead_time']}. It should be in the after the init time."
                    if ka['init_time'] is not None and ka['lead_time'] is not None and utils.try_default(lambda: datetime.datetime.strptime(ka['lead_time'], '%Y-%m-%d') < datetime.datetime.strptime(ka['init_time'], '%Y-%m-%d'), False) else None,
                lambda **ka: f"Invalid lead time: {ka['lead_time']}. It should be no more than 6 months in the future."
                    if ka['lead_time'] is not None and datetime.datetime.strptime(ka['lead_time'], '%Y-%m-%d') > (datetime.datetime.now().replace(day=1) + relativedelta.relativedelta(months=6)) else None
            ],
            'jupyter_notebook': [
                lambda **ka: f"Invalid notebook path: {ka['jupyter_notebook']}. It should be a valid jupyter notebook file path."
                    if ka['jupyter_notebook'] is not None and not ka['jupyter_notebook'].lower().endswith('.ipynb') else None
            ]
        }
    
    
    # DOC: Inference rules ( i.e.: from location name to bbox ... )
    def _set_args_inference_rules(self) -> dict:
        
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
            return bounding_box_from_location_name(ka['area'])
        
        def infer_init_time(**ka):
            if ka['init_time'] is None:
                return datetime.datetime.now().replace(day=1).strftime('%Y-%m-%d')
            return ka['init_time']
        
        def infer_lead_time(**ka):
            if ka['lead_time'] is None:
                return (datetime.datetime.now().replace(day=1) + relativedelta.relativedelta(month=1)).strftime('%Y-%m-%d')
            return ka['lead_time']
        
        def infer_jupyter_notebook(**ka):
            if ka['jupyter_notebook'] is None:
                return f"icisk-ai_spi-forecast_{datetime.datetime.now().isoformat(timespec='seconds').replace(':','-')}.ipynb"
            return ka['jupyter_notebook']
        
        return {
            'area': infer_area,
            'init_time': infer_init_time,
            'lead_time': infer_lead_time,
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
          
        self.notebook.source.cells.extend(nbt_utils.notebook_copy(nbt_spi_forecast).cells)    
        
        
    # DOC: Execute the tool → Build notebook, write it to a file and return the path to the notebook and the zarr output file
    def _execute(
        self,
        area: str | list[float],
        reference_period: tuple = (1981, 2010),
        init_time: str = None,
        lead_time: str = None,
        jupyter_notebook: str = None,
    ): 
        self.prepare_notebook(jupyter_notebook)    
        nb_values = {
            'area': area,
            'reference_period': reference_period,
            'init_time': init_time,
            'lead_time': lead_time
        }
        self.notebook.source = nbt_utils.write_notebook_template(self.notebook.source, values_dict=nb_values)
        DBI.save_notebook(self.notebook)
        
        # DOC: Back to a consisent state
        self.execution_confirmed = False
        
        return {
            "notebook": jupyter_notebook
        }
        
    
    # DOC: Back to a consisent state
    def _on_tool_end(self):
        self.execution_confirmed = False
        self.output_confirmed = True   
        
    
    # DOC: Try running AgentTool → Will check required, validity and inference over arguments thatn call and return _execute()
    def _run(
        self, 
        area: str | list[float],
        reference_period: tuple = (1981, 2010),
        init_time: str = None,
        lead_time: str = None,
        jupyter_notebook: str = None,
        run_manager: None | Optional[CallbackManagerForToolRun] = None
    ) -> dict:
        
        return super()._run(
            tool_args = {
                "area": area,
                "reference_period": reference_period,
                'init_time': init_time,
                'lead_time': lead_time,
                "jupyter_notebook": jupyter_notebook
            },
            run_manager=run_manager
        )