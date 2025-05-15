from typing_extensions import Literal

from langgraph.graph import StateGraph
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command

from icisk_orchestrator_agent import utils
from icisk_orchestrator_agent import names as N
from icisk_orchestrator_agent.common.states import BaseGraphState
from icisk_orchestrator_agent.nodes.base import BaseToolInterrupt, BaseToolHandlerNode, BaseToolInterruptNode, BaseToolInterruptOutputConfirmationHandler
from icisk_orchestrator_agent.nodes.tools import CodeEditorTool



# DOC: This node is responsible for calculating the SPI (Standardized Precipitation Index) using the provided data and building a jupyter notebook for visualization.



code_editor_tool = CodeEditorTool()

code_editor_tools_dict = {
    code_editor_tool.name: code_editor_tool
}
code_editor_tool_names = list(code_editor_tools_dict.keys())
code_editor_tools = list(code_editor_tools_dict.values())

llm_with_code_editor_tools = utils._base_llm.bind_tools(code_editor_tools)

    

# DOC: Base tool handler: runs the tool, if tool interrupt go to interrupt node handler
code_editor_tool_handler = BaseToolHandlerNode(
    state = BaseGraphState,
    tool_handler_node_name = N.CODE_EDITOR_TOOL_HANDLER,
    tool_interrupt_node_name = N.CODE_EDITOR_TOOL_INTERRUPT,
    tools = code_editor_tools_dict,
    additional_ouput_state = { 'requested_agent': None, 'node_params': dict() }
)



# DOC: Override this method to handle CodeEditor output updating
class CodeEditorToolInterruptOutputConfirmationHandler(BaseToolInterruptOutputConfirmationHandler):
    
    def _generate_provided_output(self, response):        
        args_value = '\n'.join([ f'- {arg}: {val}' for arg,val in self.tool_interrupt["data"]["args"].items() ])
        update_inputs = utils.ask_llm(
            role = 'system',
            message = f"""Tool was called with this input arguments:
            {args_value}
            
            Output was:
            {self.tool_interrupt['reason']}
            
            But user provided this additional information for the execution:
            {response}
            
            Update the initial input argument 'code_request' with the user provided information in order to get a more detailed request.
            Return the updated dictionary of input arguments and nothing else.
            """,
            eval_output = True
        )
        return update_inputs
    
      
# DOC: Base tool interrupt node: handle tool interrupt by type and go back to tool hndler with updatet state to rerun tool
code_editor_tool_interrupt = BaseToolInterruptNode(
    state = BaseGraphState,
    tool_handler_node_name = N.CODE_EDITOR_TOOL_HANDLER,
    tool_interrupt_node_name = N.CODE_EDITOR_TOOL_INTERRUPT,
    tools = code_editor_tools_dict,
    custom_tool_interupt_handlers = {
        BaseToolInterrupt.BaseToolInterruptType.CONFIRM_OUTPUT: CodeEditorToolInterruptOutputConfirmationHandler(),
    }
)



# DOC: State
code_editor_graph_builder = StateGraph(BaseGraphState)

# DOC: Nodes
code_editor_graph_builder.add_node(N.CODE_EDITOR_TOOL_HANDLER, code_editor_tool_handler)
code_editor_graph_builder.add_node(N.CODE_EDITOR_TOOL_INTERRUPT, code_editor_tool_interrupt)

# DOC: Edges
code_editor_graph_builder.add_edge(START, N.CODE_EDITOR_TOOL_HANDLER)

# DOC: Compile
code_editor_subgraph = code_editor_graph_builder.compile()
code_editor_subgraph.name = N.CODE_EDITOR_SUBGRAPH