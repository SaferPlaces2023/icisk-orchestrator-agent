# icisk-orchestrator-agent
I-Cisk agent packet to be installed in icisk-orchestrator-webapp

To setup and test a local environment update the docker-compose file with the environment variables (OPENAI_API_KEY, LANGSMITH_API_KEY) and run the following commands:
```
langgraph build --tag test_agent:local --config ./src/icisk_orchestrator_agent/langgraph.json
```