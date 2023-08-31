import time
from copy import deepcopy
from typing import Any, List, Tuple

from embedia.core.chatllm import ChatLLM
from embedia.core.tool import Tool
from embedia.schema.actionstep import Action, ActionStep
from embedia.schema.persona import Persona
from embedia.schema.pubsub import Event
from embedia.utils.exceptions import AgentError
from embedia.utils.pubsub import publish_event
from embedia.utils.typechecking import check_min_val, check_type


class ToolUser(Tool):
    def __init__(self, chatllm: ChatLLM, tools: List[Tool],
                 max_steps: int = 10, max_duration: int = 60) -> None:
        super().__init__(name="Tool User",
                         desc="It uses the available tools to answer the user's question",
                         args={'question': 'The main question that needs to be answered (Type: str)'})
        self.tools = tools
        self.max_steps = max_steps
        self.max_duration = max_duration
        self.arg_chooser = deepcopy(chatllm)
        self.tool_chooser = deepcopy(chatllm)
        self.sys1_thinker = deepcopy(chatllm)
        self.action_steps = []
        self._check_init()

    def _check_init(self) -> None:
        check_type(self.chatllm, ChatLLM)
        check_min_val(len(self.tools), 1, 'len(tools)')
        for tool in self.tools:
            check_type(tool, Tool)

    async def _choose_tool(self, question: str) -> Tool:
        if len(self.tools) == 1:
            return self.tools[0]
        available_tools = "\n".join([f"{tool.name}: {tool.desc}" for tool in self.tools])
        prompt = (f"Question: {question}\n\n"
                  f"Tools:\n{available_tools}")
        await self.tool_chooser.set_system_prompt(Persona.ToolChooser)
        tool_choice = await self.tool_chooser(prompt)
        tool_choice = tool_choice.content
        for tool in self.tools:
            if tool.name == tool_choice:
                tool_choice = tool
                break
        if isinstance(tool_choice, str):
            raise AgentError(f"Agent's tool choice: {tool_choice} could not be found")
        return tool_choice

    async def _choose_args(self, question: str, tool_choice: Tool) -> dict:
        if len(tool_choice.args) == 0:
            return {}
        arg_docs = ''
        for arg_key, arg_desc in tool_choice.args.items():
            arg_docs += f"{arg_key}: {arg_desc}\n"
        prompt = (f"Question: {question}\n"
                  f"Function: {tool_choice.desc}\n"
                  f"Arguments:\n{arg_docs}")

        await self.arg_chooser.set_system_prompt(Persona.ArgChooser)
        arg_choice = await self.arg_chooser(prompt)
        arg_choice = arg_choice.content
        arg_choice = arg_choice.split('\n')
        arg_choice_dict = {}
        for choice in arg_choice:
            choice = choice.split(':')
            arg_name = choice[0].strip()
            arg_value = ':'.join(choice[1:]).strip()
            arg_choice_dict[arg_name] = arg_value

        kwargs = {}
        for arg_name in arg_choice_dict.keys():
            if arg_name not in tool_choice.args.keys():
                raise AgentError(f"Argument choice: {arg_name} not found in Tool: {tool_choice.name} Tool args: {tool_choice.args}")
            try:
                kwargs[arg_name] = eval(arg_choice_dict[arg_name])
            except Exception:
                kwargs[arg_name] = arg_choice_dict[arg_name]
        return kwargs

    async def _choose_next_step(self) -> Tuple[str, str]:
        await self.sys1_thinker.set_system_prompt(Persona.Sys1Thinker)
        prompt = "\n".join([str(step) for step in self.action_steps])
        resp = await self.sys1_thinker(prompt)
        resp = resp.content
        if resp.split(':')[0] == 'Question':
            return resp.split(':')[1], 'Question'
        elif resp.split(':')[0] == 'Final Answer':
            return resp.split(':')[1], 'Final Answer'
        else:
            raise AgentError(f"Agent's response: {resp} could not be parsed")

    async def _run(self, question: str) -> Tuple[Any, int]:
        steps = 1
        now = time.time()
        while steps <= self.max_steps and time.time() - now <= self.max_duration:

            if self.action_steps:
                thought, thought_type = self._choose_next_step()
                if thought_type == 'Question':
                    question = thought
                elif thought_type == 'Final Answer':
                    return thought, 0

            tool_choice = await self._choose_tool(question)
            kwargs = await self._choose_args(question, tool_choice)

            await self.human_confirmation({'tool': tool_choice.name, 'args': kwargs})
            result = await tool_choice(**kwargs)

            action_step = ActionStep(question=question,
                                     action=Action(tool_name=tool_choice.name,
                                                   args=kwargs),
                                     result=result)
            self.action_steps.append(action_step)
            steps += 1
            publish_event(Event.AgentStep, data={'action_step': action_step})

        publish_event(Event.AgentTimeout, data={'action_steps': self.action_steps,
                                                'duration': f'{time.time() - now :.2f}s',
                                                'num_steps': steps - 1})
        return self.action_steps[-1].result, 1
