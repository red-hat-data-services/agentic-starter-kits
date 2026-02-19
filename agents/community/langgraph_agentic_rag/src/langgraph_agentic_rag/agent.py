from typing import Callable, Annotated, Sequence

from langchain_core.messages import BaseMessage, SystemMessage, AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from .tools import retriever_tool
from langgraph_agentic_rag.utils import get_env_var
from typing_extensions import TypedDict


def get_graph_closure(
    model_id: str = None,
    base_url: str = None,
    api_key: str = None,
) -> Callable:
    """Build and return a LangGraph RAG agent with the configured LLM and retrieval tool.

    Creates a ChatOpenAI client, wires a retriever tool based on vector store configuration,
    and uses a StateGraph to produce an agentic RAG workflow (decide to retrieve, retrieve, generate).

    Args:
        model_id: LLM model identifier (e.g. for OpenAI-compatible API). Uses MODEL_ID env if omitted.
        base_url: Base URL for the LLM API. Uses BASE_URL env if omitted.
        api_key: API key for the LLM. Uses API_KEY env if omitted; required for non-local base_url.

    Returns:
        A function that creates a CompiledGraph agent accepting {"messages": [...]} and returns updated state.
        :param api_key:
        :param base_url:
        :param model_id:
    """

    # Get environment variables if not provided
    if not api_key:
        api_key = get_env_var("API_KEY")
    if not base_url:
        base_url = get_env_var("BASE_URL")
    if not model_id:
        model_id = get_env_var("MODEL_ID")

    # Check if using local deployment
    is_local = any(host in base_url for host in ["localhost", "127.0.0.1"])

    if not is_local and not api_key:
        raise ValueError("API_KEY is required for non-local environments.")

    # Initialize ChatOpenAI
    chat = ChatOpenAI(
        model=model_id,
        temperature=0.3,  # Higher temperature for better rephrasing
        api_key=api_key or "not-needed",
        base_url=base_url,
    )

    TOOLS = [retriever_tool]

    # Define system prompt
    default_system_prompt = (
        "You are a helpful AI assistant that can retrieve information from a knowledge base."
        "When you receive a question, first check if you need to retrieve information using the retriever tool."
        "If the question requires specific knowledge that you might not have, use the retriever tool to get relevant information. "
        "Then provide a meaningfully but short sentenced answer with a use of retrieved data from chunks"
    )

    class AgentState(TypedDict):
        """State for the RAG agent workflow."""

        messages: Annotated[Sequence[BaseMessage], add_messages]

    def agent_with_instruction(instruction_prompt: str | None) -> Callable:
        """Create agent function with custom system prompt."""

        def agent(state: AgentState) -> dict:
            """
            Invokes the agent model to generate a response based on the current state.
            Given the question, it will decide to retrieve using the retriever tool, or simply end.

            Args:
                state: The current state with messages

            Returns:
                dict: The updated state with the agent response appended to messages
            """
            messages = state["messages"]

            model = chat.bind_tools(TOOLS)
            system_prompt = SystemMessage(
                default_system_prompt + "\n" + (instruction_prompt or "")
            )
            response = model.invoke([system_prompt] + list(messages))
            return {"messages": [response]}

        return agent

    def generate(state: AgentState):
        """
        Generate final answer based on retrieved context.

        Args:
            state: The current state with messages

        Returns:
            dict: The updated state with the generated answer
        """
        print("\n🤖 Generate node called - synthesizing answer...")
        messages = state["messages"]

        # Find the last user question (looking backward for HumanMessage)
        question = None
        for msg in reversed(messages):
            if msg.type == "human":
                question = msg.content
                break

        # Get the tool response (last ToolMessage)
        docs = None
        for msg in reversed(messages):
            if msg.type == "tool":
                docs = msg.content
                break

        if not question or not docs:
            # Fallback if we can't find the question or docs
            return {
                "messages": [
                    AIMessage(
                        content="I couldn't find the information needed to answer your question."
                    )
                ]
            }

        # Create a simple, direct prompt for the LLM
        # Check if docs indicate no relevant information
        if "No relevant information" in docs or not docs.strip():
            return {
                "messages": [
                    AIMessage(
                        content="I couldn't find relevant information in the provided documents to answer your question."
                    )
                ]
            }

        # Use HumanMessage instead of SystemMessage for better compatibility with smaller models
        rag_prompt_text = f"""Based on the following context, answer the question.

Context:
{docs}

Question: {question}

Answer[start response with 'based on provided documents]:"""

        # Generate response
        try:
            response = chat.invoke([HumanMessage(content=rag_prompt_text)])

            if not response.content or not response.content.strip():
                return {
                    "messages": [
                        AIMessage(
                            content="I couldn't find relevant information in the provided documents to answer your question."
                        )
                    ]
                }

            return {"messages": [AIMessage(content=response.content.strip())]}
        except Exception:
            return {
                "messages": [
                    AIMessage(
                        content="I couldn't find relevant information in the provided documents to answer your question."
                    )
                ]
            }

    def get_graph(instruction_prompt: SystemMessage | None = None):
        """Create and compile the RAG workflow graph.

        Args:
            instruction_prompt: Optional custom system message to override default

        Returns:
            CompiledGraph: The compiled LangGraph workflow
        """
        # Define a new graph
        workflow = StateGraph(AgentState)

        if instruction_prompt is None:
            agent = agent_with_instruction(None)
        else:
            agent = agent_with_instruction(instruction_prompt.content)

        # Define the nodes
        workflow.add_node("agent", agent)  # agent decides to retrieve or not
        retrieve = ToolNode(TOOLS)
        workflow.add_node("retrieve", retrieve)  # retrieval
        workflow.add_node("generate", generate)  # generate final answer

        # Call agent node to decide to retrieve or not
        workflow.add_edge(START, "agent")

        # Decide whether to retrieve
        workflow.add_conditional_edges(
            "agent",
            # Assess agent decision
            tools_condition,
            {
                # Translate the condition outputs to nodes in our graph
                "tools": "retrieve",
                END: END,
            },
        )

        # After retrieval, generate the answer
        workflow.add_edge("retrieve", "generate")
        workflow.add_edge("generate", END)

        # Compile
        graph = workflow.compile()

        return graph

    return get_graph
