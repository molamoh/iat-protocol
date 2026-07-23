# IAT Protocol for CrewAI

This tool allows CrewAI agents to buy services from the IAT Protocol marketplace.

## Usage

```python
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
```

Required environment:

```bash
export IAT_API_URL="http://127.0.0.1:8000"
export IAT_KEYPAIR_PATH="/run/secrets/buyer-keypair.json"
```

The tool performs a real token transfer when invoked. Use a controlled wallet
and environment.
