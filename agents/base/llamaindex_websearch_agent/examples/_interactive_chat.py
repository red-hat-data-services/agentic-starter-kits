import textwrap
import json
from collections.abc import Generator
from typing import Callable

# ANSI Color Codes for clearer console output
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
RESET = "\033[0m"


class InteractiveChat:
    def __init__(
        self,
        ai_service_invoke: Callable,
        questions: tuple[str] = None,
        stream: bool = False,
        verbose: bool = True,
    ) -> None:
        self.ai_service_invoke = ai_service_invoke
        self._ordered_list = lambda seq_: "\n".join(
            f"\t{i}) {k}" for i, k in enumerate(seq_, 1)
        )
        self._delta_start = False
        self.verbose = verbose
        self.stream = stream

        self.questions = (
            (
                "Hi! How are you?",
                "What does print() in python do?",
                "Search for RedHat and tell me what you found.",
            )
            if questions is None
            else questions
        )

        self._help_message = textwrap.dedent(
            """
        The following commands are supported:
          --> help | h : prints this help message
          --> quit | q : exits the prompt and ends the program
          --> list_questions : prints a list of available questions
        """
        )

    @property
    def questions(self) -> tuple:
        return self._questions

    @questions.setter
    def questions(self, q: tuple) -> None:
        self._questions = q
        self._questions_prompt = (
            f"\n\033[31m\n> Questions:\033[0m\n{self._ordered_list(self._questions)}\n"
        )

    def _user_input_loop(self) -> Generator[str, bool, None]:
        print(self._help_message)
        while True:
            print(self._questions_prompt)
            q = input("\nChoose a question or ask one of your own.\n --> ")
            yield q, "question"

    def _print_message(self, choice: dict) -> None:
        delta = choice.get("delta") or choice.get("message")

        if not delta:
            return

        role = delta.get("role")
        content = delta.get("content")
        tool_calls = delta.get("tool_calls")

        # 1. Handle Tool Calls (The AI wants to run a function)
        if tool_calls:
            self._delta_start = False
            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "unknown_tool")
                args = func.get("arguments", "{}")
                # Print nicely instead of raw JSON
                print(f"\n\033[93m🛠️  [TOOL CALL] Calling function: {name}\033[0m")
                print(f"\033[93m    Arguments: {args}\033[0m")

        # 2. Handle Tool Results (The function finished running)
        elif role == "tool":
            self._delta_start = False
            name = delta.get("name", "Tool")
            print(f"\n\033[92m✅ [TOOL RESULT - {name}]\033[0m")
            print(f"\033[92m    {content}\033[0m\n")

        # 3. Handle Normal Text (The AI is talking to you)
        elif content:
            if not self._delta_start:
                print("\n\033[95m🤖 [ASSISTANT]\033[0m ", end="", flush=True)
                self._delta_start = True

            print(content, flush=True, end="")

        if choice.get("finish_reason"):
            print("")
            self._delta_start = False

    def run(self) -> None:
        while True:
            try:
                user_loop = self._user_input_loop()

                for action, stage in user_loop:
                    if action in ("h", "help"):
                        print(self._help_message)
                    elif action in ("quit", "q"):
                        raise EOFError
                    elif action == "list_questions":
                        print(self._questions_prompt)

                    elif stage == "question":
                        user_message = {}
                        if not action.isdigit():
                            user_message["content"] = action.strip()
                        else:
                            number = int(action)
                            print(f"you chose QUESTION {number}\n")
                            if number > len(self.questions) or number < 0:
                                print(
                                    "provided numbers have to match the available numbers"
                                )
                                continue
                            else:
                                user_message["content"] = self.questions[number - 1]

                        request_payload_json = {
                            "messages": [{"role": "user", **user_message}]
                        }

                        # Invoke the AI Service
                        resp = self.ai_service_invoke(request_payload_json)

                        if self.stream:
                            for r in resp:
                                if isinstance(r, str):
                                    r = json.loads(r)
                                for c in r["choices"]:
                                    self._print_message(c)
                            self._delta_start = False
                        else:
                            resp_choices = resp.get("body", resp)["choices"]
                            choices = (
                                resp_choices if self.verbose else resp_choices[-1:]
                            )
                            for c in choices:
                                self._print_message(c)

            except EOFError:
                print("\nGoodbye!")
                break
            except KeyboardInterrupt:
                print("\nExiting...")
                break
