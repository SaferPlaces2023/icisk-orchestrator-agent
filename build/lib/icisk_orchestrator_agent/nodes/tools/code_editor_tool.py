import os

import nbformat as nbf
from nbformat.v4 import new_code_cell

from typing import Optional
from pydantic import BaseModel, Field
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)

from icisk_orchestrator_agent import utils
from icisk_orchestrator_agent import names as N
from icisk_orchestrator_agent.nodes.base import BaseAgentTool

from icisk_orchestrator_db import DBI, DBS



class CodeEditorTool(BaseAgentTool):
    
    class InputSchema(BaseModel):
        
        source: None | str = Field(
            title = "Source",
            description = "The filename of the code file to be edited. It is only filename.ext, without any other parent path. It could be a python notebbok, a script.py. If not specified use None as default.",
            examples = [
                None,
                'python_script.py',
                'python_notebook.ipynb'
            ],
            default=None
        )
        code_request: None | str | list[str] = Field(
            title="Request",
            description="""Meaning and usefulness of the requested code""",
            examples=[
                None,
                "Please add a function to plot the data.",
                "Please add a function to save the data in a different format.",
                [ "Please add a function to filter the data.", "Plot data by category" ]
            ]
        )
        
    # DOC: Additional tool args
    notebook: DBS.Notebook = None
    
    
    # DOC: Initialize the tool with a name, description and args_schema
    def __init__(self, **kwargs):
        super().__init__(
            name = N.CODE_EDITOR_TOOL,
            description = """Edit an existing Jupyter notebook by adding new code lines. It must be provided as an absolute path in local filesystem.
            Use this tool when user asks for an help to edit the notebook by adding something new.""",
            args_schema = CodeEditorTool.InputSchema,
            **kwargs
        )
        
        self.execution_confirmed = True     # DOC: Skip this, there will be output_confirmed:True
        
    
    def _set_args_validation_rules(self):
        return {
            'source': [
                lambda **ka: f"Invalid source: {ka['source']}. It should be the name of a notebook uploaded on databse."
                    if DBI.notebook_by_name(author=self.graph_state.get('user_id'), notebook_name=ka['source']) is None else None
            ]
        }
        
        
    def _execute(
        self, 
        source: None | str,
        code_request: None | str | list[str],
    ):
        
        self.notebook = DBI.notebook_by_name(author=self.graph_state.get('user_id'), notebook_name=source, retrieve_source=True)
        
        def get_source_code():
            source_code = [cell.source for cell in self.notebook.source.cells if cell.cell_type == 'code' and cell.source != '']
            return source_code
        
        def add_source_code(source_code):
            if source_code.startswith('```python\n'):
                source_code = source_code.split('```python\n')[1].split('\n```')[0]
            
            self.notebook.source.cells.append(new_code_cell(source = source_code))
            DBI.save_notebook(self.notebook)#**self.notebook.as_dict)
                    
        if not self.output_confirmed:
            
            generated_code = utils.ask_llm(
                role = 'system',
                message = f"""
                    You are a programming assistant who helps users write python code.
                    Remember that the code is related to an analysis of geospatial data. If map visualizations are requested, use the cartopy library, adding borders, coastlines, lakes and rivers.

                    You have been asked to write python code that satisfies the following request:

                    {code_request}

                    The code produced must be added to this existing code:

                    {get_source_code()}

                    ------------------------------------------

                    Respond only with python code that can be integrated with the existing code. It must use the appropriate variables already defined in the code.
                    Do not attach any other text.
                    Do not produce additional code other than that necessary to satisfy the requests declared in the parameter.
                """,
                eval_output = False
            )
            
        else:
            generated_code = self.output['generated_code']
            add_source_code(generated_code)
            
        # DOC: Back to a consisent state
        self.output_confirmed = False
                        
        return {
            "notebook": source,
            "generated_code" : generated_code
        }
        
    
    
    # DOC: Try running AgentTool → Will check required, validity and inference over arguments thatn call and return _execute()
    def _run(
        self, 
        source: None | str,
        code_request: None | str | list[str],
        run_manager: None | Optional[CallbackManagerForToolRun] = None
    ) -> dict:
        
        return super()._run(
            tool_args = {
                "source": source,
                "code_request": code_request
            },
            run_manager=run_manager
        )