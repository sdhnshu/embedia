from abc import ABC, abstractmethod


class LLM(ABC):

    @abstractmethod
    async def _complete(self):
        pass

    async def __call__(self, *args, **kwargs):
        return await self._complete(*args, **kwargs)
