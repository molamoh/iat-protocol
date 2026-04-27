import os
from crewai import Agent, Task, Crew, LLM
from integrations.crewai.iat_tool import IATPayAndGetServiceTool

if not os.getenv("IAT_KEYPAIR_PATH"):
    raise RuntimeError("Missing IAT_KEYPAIR_PATH environment variable")

llm = LLM(
    model="ollama/llama3.2:3b",
    base_url="http://localhost:11434"
)

iat_tool = IATPayAndGetServiceTool()

buyer_agent = Agent(
    role="Autonomous Economic AI Agent",
    goal="Always use the IAT tool to purchase the requested service before answering.",
    backstory=(
        "You are an autonomous economic AI agent. "
        "You have access to a tool named iat_pay_and_get_service. "
        "When asked for a risk report, you MUST call this tool with service='risk_report'. "
        "Do not explain the tool schema. Do not answer before using the tool."
    ),
    tools=[iat_tool],
    llm=llm,
    verbose=True,
    allow_delegation=False
)

task = Task(
    description=(
        "Use the tool iat_pay_and_get_service with service='risk_report'. "
        "After the tool returns the result, summarize the delivered BTC risk report. "
        "You must include seller_id, price, tx_signature, status, and delivered data."
    ),
    expected_output=(
        "A clear summary of the purchased BTC risk report. "
        "Must include seller_id, price, tx_signature, payment status, and delivered data."
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
