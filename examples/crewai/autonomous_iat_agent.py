import os
from crewai import Agent, Task, Crew
from integrations.crewai.iat_tool import IATPayAndGetServiceTool

if not os.getenv("IAT_KEYPAIR_PATH"):
    raise RuntimeError("Missing IAT_KEYPAIR_PATH environment variable")

iat_tool = IATPayAndGetServiceTool()

buyer_agent = Agent(
    role="Autonomous Economic AI Agent",
    goal="Use IAT Protocol to buy external AI services when needed.",
    backstory=(
        "You are an autonomous AI agent connected to the IAT Protocol. "
        "When you need external intelligence or data, you can purchase services "
        "from other agents using IAT payments."
    ),
    tools=[iat_tool],
    verbose=True
)

task = Task(
    description=(
        "You need a BTC risk report. "
        "Use the IAT tool to buy the risk_report service, then summarize the delivered result."
    ),
    expected_output=(
        "A concise summary of the BTC risk report purchased through IAT Protocol, "
        "including seller, price, transaction status, and delivered data."
    ),
    agent=buyer_agent
)

crew = Crew(
    agents=[buyer_agent],
    tasks=[task],
    verbose=True
)

result = crew.kickoff()
print(result)
