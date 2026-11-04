"""Send real fragment requests through AppTest's installed ScriptRunner.

AppTest.run always requests a full script run. This adapter changes only the
test transport: it supplies the browser's fragment id, retains client deltas
and restores the multipage registry on the fresh test runner. Production
fragment execution, widget callbacks and message serialization remain real.
"""

from copy import deepcopy
from unittest.mock import patch

from streamlit.runtime.scriptrunner_utils.script_requests import RerunData
from streamlit.testing.v1.local_script_runner import LocalScriptRunner


class FragmentRunner:
    """Capture full runs and request partial runs without starting a server."""

    def __init__(self):
        self.messages = []
        self.pages = {}
        self.fragment_ids = []
        self.partial_runs = 0
        self.new_messages = []
        self.original_run = LocalScriptRunner.run

    def __enter__(self):
        # A plain function preserves descriptor binding to LocalScriptRunner.
        def run(runner, *args, **kwargs):
            return self._run(runner, *args, **kwargs)

        self.patch = patch.object(LocalScriptRunner, "run", run)
        self.patch.start()
        return self

    def __exit__(self, *args):
        self.patch.stop()

    def _run(self, runner, *args, **kwargs):
        if self.fragment_ids:
            runner._pages_manager._set_pages(self.pages)
            for message in deepcopy(self.messages):
                runner.forward_msg_queue.enqueue(message)
        tree = self.original_run(runner, *args, **kwargs)
        self.messages = deepcopy(runner.forward_msgs())
        self.pages = runner._pages_manager.get_pages().copy()
        starts = [data for data in runner.event_data if "fragment_ids_this_run" in data]
        if self.fragment_ids:
            assert starts and any(data["fragment_ids_this_run"] for data in starts)
            self.partial_runs += 1
        self.new_messages = [
            data["forward_msg"] for data in runner.event_data if "forward_msg" in data
        ]
        return tree

    def run_fragment(self, app, key="episode_card"):
        """Run real queued fragments, retaining outside widgets like a browser."""
        self.fragment_ids = app._fragment_storage.resolve_target(key)

        def request(**values):
            return RerunData(**values, fragment_id_queue=self.fragment_ids)

        try:
            # Patch before the test runner constructor: its initial empty full
            # request would otherwise coalesce with and override the fragment.
            with patch("streamlit.testing.v1.local_script_runner.RerunData", request):
                return app.run()
        finally:
            self.fragment_ids = []
