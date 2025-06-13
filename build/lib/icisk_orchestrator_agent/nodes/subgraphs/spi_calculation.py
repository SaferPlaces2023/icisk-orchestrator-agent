from langgraph.graph import StateGraph
from langgraph.graph import StateGraph, START

from icisk_orchestrator_agent import utils
from icisk_orchestrator_agent import names as N
from icisk_orchestrator_agent.common.states import BaseGraphState
from icisk_orchestrator_agent.nodes.tools import SPIHistoricNotebookTool, SPIForecastNotebookTool
from icisk_orchestrator_agent.nodes.base import BaseToolHandlerNode, BaseToolInterruptNode



# DOC: This node is responsible for calculating the SPI (Standardized Precipitation Index) using the provided data and building a jupyter notebook for visualization.



spi_historic_notebook_tool = SPIHistoricNotebookTool()
spi_forecast_notebook_tool = SPIForecastNotebookTool()
spi_calculation_tools_dict = {
    spi_historic_notebook_tool.name: spi_historic_notebook_tool,
    spi_forecast_notebook_tool.name: spi_forecast_notebook_tool
}
spi_tool_names = list(spi_calculation_tools_dict.keys())
spi_tools = list(spi_calculation_tools_dict.values())

llm_with_spi_tools = utils._base_llm.bind_tools(spi_tools)

    

# DOC: Base tool handler: runs the tool, if tool interrupt go to interrupt node handler
spi_calculation_tool_handler = BaseToolHandlerNode(
    state = BaseGraphState,
    tool_handler_node_name = N.SPI_CALCULATION_TOOL_HANDLER,
    tool_interrupt_node_name = N.SPI_CALCULATION_TOOL_INTERRUPT,
    tools = spi_calculation_tools_dict,
    additional_ouput_state = { 'requested_agent': None, 'node_params': dict() }
)


# DOC: Base tool interrupt node: handle tool interrupt by type and go back to tool hndler with updatet state to rerun tool
spi_calculation_tool_interrupt = BaseToolInterruptNode(
    state = BaseGraphState,
    tool_handler_node_name = N.SPI_CALCULATION_TOOL_HANDLER,
    tool_interrupt_node_name = N.SPI_CALCULATION_TOOL_INTERRUPT,
    tools = spi_calculation_tools_dict,
    custom_tool_interupt_handlers = dict()     # DOC: use default 
)



# DOC: State
spi_calculation_graph_builder = StateGraph(BaseGraphState)

# DOC: Nodes
spi_calculation_graph_builder.add_node(N.SPI_CALCULATION_TOOL_HANDLER, spi_calculation_tool_handler)
spi_calculation_graph_builder.add_node(N.SPI_CALCULATION_TOOL_INTERRUPT, spi_calculation_tool_interrupt)

# DOC: Edges
spi_calculation_graph_builder.add_edge(START, N.SPI_CALCULATION_TOOL_HANDLER)

# DOC: Compile
spi_calculation_subgraph = spi_calculation_graph_builder.compile()
spi_calculation_subgraph.name = N.SPI_CALCULATION_SUBGRAPH