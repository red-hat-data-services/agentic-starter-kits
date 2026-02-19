import textwrap
import json
from collections.abc import Generator
from typing import Callable


class InteractiveChat:
    """Interactive REPL that prompts for user input and calls the AI service for each question."""

    def __init__(
            self,
            ai_service_invoke: Callable,
            questions: tuple[str] = None,
            stream: bool = False,
            verbose: bool = True,
    ) -> None:
        """Set up the chat: invoke callable, optional preset questions, and stream/verbose flags."""
        self.ai_service_invoke = ai_service_invoke
        self._ordered_list = lambda seq_: "\n".join(
            f"\t{i}) {k}" for i, k in enumerate(seq_, 1)
        )
        self.verbose = verbose
        self.stream = stream
        self._last_role = None  # Tracks role changes to split headers

        self.questions = ("Hi! How are you?",) if questions is None else questions
        self._help_message = textwrap.dedent("""
        The following commands are supported:
          --> help | h : prints this help message
          --> quit | q : exits the prompt and ends the program
          --> list_questions : prints a list of available questions
        """)

    @property
    def questions(self) -> tuple:
        """Return the tuple of preset questions (e.g. for list_questions)."""
        return self._questions

    @questions.setter
    def questions(self, q: tuple) -> None:
        """Set preset questions and refresh the list shown by list_questions."""
        self._questions = q
        self._questions_prompt = f"\tQuestions:\n{self._ordered_list(self._questions)}\n"

    def _print_message(self, choice: dict) -> None:
        """Print one choice from the AI response (streaming delta or full message) with role headers."""
        if delta := choice.get("delta"):
            current_role = delta.get("role")

            # Check if we need to print a new header
            if current_role != self._last_role:
                display_names = {
                    "tool_answer": "Answer from tool",
                    "assistant_answer": "Assistant answer"
                }
                header_text = display_names.get(current_role, current_role.capitalize())
                print(f"\n{f' {header_text} '.center(80, '=')}")
                self._last_role = current_role

            content = delta.get("content")
            if content:
                print(content, flush=True, end="")
        else:
            # Non-streaming fallback
            msg = choice.get("message", {})
            header = f" {msg.get('role', 'Assistant').capitalize()} Message ".center(80, "=")
            print(f"\n{header}\n{msg.get('content', '')}")

    def _user_input_loop(self) -> Generator[tuple[str, str], None, None]:
        """Yield (user input line, stage) forever; stage is 'question' for normal prompts."""
        print(self._help_message)
        while True:
            q = input("\nChoose a question or ask one of your own.\n --> ")
            yield q, "question"

    def run(self) -> None:
        """Run the REPL: read input, handle help/quit/list_questions, or send questions to the AI and print replies."""
        user_loop = self._user_input_loop()
        while True:
            try:
                action, stage = next(user_loop)

                if action in ["h", "help"]:
                    print(self._help_message)
                elif action in ["quit", "q"]:
                    break
                elif action == "list_questions":
                    print(self._questions_prompt)
                elif stage == "question":
                    # Reset role tracking for new question
                    self._last_role = None

                    user_content = action.strip()
                    if action.isdigit():
                        idx = int(action) - 1
                        if 0 <= idx < len(self.questions):
                            user_content = self.questions[idx]
                            print(f"You chose: {user_content}\n")

                    payload = {"messages": [{"role": "user", "content": user_content}]}
                    resp = self.ai_service_invoke(payload)

                    if self.stream:
                        for r in resp:
                            if isinstance(r, str):
                                r = json.loads(r)
                            for c in r.get("choices", []):
                                self._print_message(c)
                        print()  # Final newline
                    else:
                        # Standard invoke handling
                        choices = resp.get("body", {}).get("choices", [])
                        for c in choices:
                            self._print_message(c)

            except (EOFError, StopIteration):
                break
