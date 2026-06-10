from crewai import LLM, Agent, Crew, Process, Task
from crewai.project import CrewBase, after_kickoff, agent, crew, task

from crewai_web_search.tools import WebSearchTool
from crewai_web_search.tracing import wrap_func_with_mlflow_trace


@CrewBase
class AssistanceAgents:
    """Assistants crew"""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    def __init__(self, llm: LLM, **kwargs):
        self.llm = llm
        self.step_callback = kwargs.pop("step_callback", None)
        self.enable_stream = kwargs.pop("stream", False)

    @after_kickoff  # Optional hook to be executed after the crew has finished
    def log_results(self, output):
        # Example of logging results, dynamically changing the output
        print(f"Results: {output}")
        return output

    @agent
    def ai_assistant(self) -> Agent:
        tools = [WebSearchTool()]
        # Manual tool tracing: mlflow.crewai.autolog() does not capture tool spans
        # in newer CrewAI versions (>=1.10). If a future version fixes this, remove
        # the manual wrapping below to avoid duplicate tool spans.
        for tool in tools:
            tool._run = wrap_func_with_mlflow_trace(
                tool._run, span_type="tool", name=tool.name
            )

        return Agent(
            config=self.agents_config["ai_assistant"],
            tools=tools,
            verbose=True,
            llm=self.llm,
            max_iter=3,
            max_retry_limit=1,
        )

    @task
    def generate_response_task(self) -> Task:
        return Task(
            config=self.tasks_config["generate_response_task"],
        )

    @crew
    def crew(self) -> Crew:
        """Creates the AI Assistant crew"""

        return Crew(
            agents=self.agents,  # Automatically created by the @agent decorator
            tasks=self.tasks,  # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=True,
            step_callback=self.step_callback,
            stream=self.enable_stream,
        )
