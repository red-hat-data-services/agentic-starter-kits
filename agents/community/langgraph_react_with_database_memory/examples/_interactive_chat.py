import textwrap
import json
from collections.abc import Generator
from typing import Callable


class InteractiveChat:
    def __init__(
        self,
        ai_service_invoke: Callable,
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

    def _user_input_loop(self) -> Generator[tuple[str, str], None, None]:
        print(self._help_message)

        while True:
            q = input("\nChoose a question or ask one of your own.\n --> ")

            _ = yield q, "question"

    def _print_message(self, choice: dict) -> None:
        if delta := choice.get("delta"):
            if not self._delta_start:
                header = f" {delta['role'].capitalize()} Message ".center(80, "=")
                print("\n", header)
                self._delta_start = (
                    True
                    and (choice.get("finish_reason") is None)
                    and delta["role"] != "tool"
                )
            print(delta.get("content") or delta.get("tool_calls"), flush=True, end="")
        else:
            header = f" {choice['message']['role'].capitalize()} Message ".center(
                80, "="
            )
            print("\n", header)
            print(f"{choice['message'].get('content', choice['message'])}")

    def run(self) -> None:
        while True:
            try:
                q = None

                user_loop = self._user_input_loop()

                for action, stage in user_loop:  # unsupported command support!
                    if action == "h" or action == "help":
                        print(self._help_message)
                    elif action == "quit" or action == "q":
                        raise EOFError

                    elif stage == "question":
                        user_message = {}
                        user_message["content"] = action.strip()

                        request_payload_json = {
                            "messages": [{"role": "user", **user_message}]
                        }

                        resp = self.ai_service_invoke(request_payload_json)

                        if self.stream:
                            for r in resp:
                                if type(r) == str:
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
                break
