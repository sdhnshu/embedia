from embedia.tool import Tool
from typing import Optional, Type
from embedia.message import Message
from embedia.chatllm import ChatLLM
import subprocess
import asyncio

SHELL_EXPERT_SYSTEM = """You are an expert in writing commands for the {executable} shell.
Write one-line commands with inbuilt libraries to solve the user's problems. Reply only with the command and nothing else."""


class BashShell(Tool):

    def __init__(self, chatllm: Optional[Type[ChatLLM]] = None,
                 executable='/bin/sh', timeout=60, human_verification=True):
        super().__init__(name="Bash Shell",
                         desc="Run bash commands",
                         examples="ls -l, pwd",
                         args="command: str",
                         returns="output: str",
                         chatllm=chatllm)
        self.executable = executable
        self.timeout = timeout
        self.human_verification = human_verification

    async def _run(self, command: str):
        if self.chatllm:
            shell_expert = self.chatllm(
                system_prompt=SHELL_EXPERT_SYSTEM.format(executable=self.executable))
            command = await shell_expert.reply(Message(role='user', content=command))
            command = command.content
            if self.human_verification:
                self.confirm_before_running(command=command)

        process = await asyncio.create_subprocess_shell(
            command, executable=self.executable, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError:
            process.kill()
            raise

        return stdout.decode(), stderr.decode()
