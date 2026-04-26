# IAT Protocol for CrewAI

This tool allows CrewAI agents to buy services from the IAT Protocol marketplace.

## Usage

from crewai import Agent, Task, Crew
from integrations.crewai.iat_tool import IATPayAndGetServiceTool

iat_tool = IATPayAndGetServiceTool()

agent = Agent(
    role="Autonomous Buyer Agent",
    goal="Buy services using IAT Protocol",
    backstory="An AI agent able to pay other agents for services.",
    tools=[iat_tool]
)

task = Task(
    description="Use IAT to buy the risk_report service.",
    expected_output="The delivered service result.",
    agent=agent
)

crew = Crew(agents=[agent], tasks=[task])
result = crew.kickoff()
print(result)
