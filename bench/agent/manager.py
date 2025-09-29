class AgentBenchManager:
    def __init__(self, agent_class, *agent_args, **agent_kwargs):
        self._agent_class = agent_class
        self._agent_args = agent_args
        self._agent_kwargs = agent_kwargs

    async def __aenter__(self):
        self._agent_instance = self._agent_class(
            *self._agent_args, **self._agent_kwargs)
        await self._agent_instance.start()
        return self._agent_instance

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._agent_instance.stop()
