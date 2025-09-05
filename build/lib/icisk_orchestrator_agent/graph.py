"""
Defining agent graph
"""

from langgraph.graph import StateGraph
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from icisk_orchestrator_agent import names as N

from icisk_orchestrator_agent.common.states import BaseGraphState

from icisk_orchestrator_agent.nodes import (
    chatbot, chatbot_update_messages
)
from icisk_orchestrator_agent.nodes.subgraphs import (
    cds_ingestor_subgraph, 
    spi_calculation_subgraph,
    code_editor_subgraph
)


# DOC: define state
graph_builder = StateGraph(BaseGraphState)


# DOC: define nodes

graph_builder.add_node(chatbot)
graph_builder.add_node(N.CHATBOT_UPDATE_MESSAGES, chatbot_update_messages)

graph_builder.add_node(N.CDS_INGESTOR_SUBGRAPH, cds_ingestor_subgraph)

graph_builder.add_node(N.SPI_CALCULATION_SUBGRAPH, spi_calculation_subgraph)

graph_builder.add_node(N.CODE_EDITOR_SUBGRAPH, code_editor_subgraph)


# DOC: define edges

graph_builder.add_edge(START, N.CHATBOT)
graph_builder.add_edge(N.CHATBOT_UPDATE_MESSAGES, N.CHATBOT)


graph_builder.add_edge(N.CDS_INGESTOR_SUBGRAPH, N.CHATBOT)

graph_builder.add_edge(N.SPI_CALCULATION_SUBGRAPH, N.CHATBOT)

graph_builder.add_edge(N.CODE_EDITOR_SUBGRAPH, N.CHATBOT)

# DOC: build graph
graph = graph_builder.compile() # .compile(checkpointer = MemorySaver())   # REF: when launch with `langgraph dev` command a message says it is not necessary ... 
graph.name = N.GRAPH