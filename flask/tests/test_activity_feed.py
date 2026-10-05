"""Activity feed checks without loading station hardware or secrets."""
import importlib.util
import json
from pathlib import Path
import unittest
from concurrent.futures import ThreadPoolExecutor

spec = importlib.util.spec_from_file_location(
    "activity_sse", Path(__file__).parents[1] / "lib/sse/sse_queue_manager.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def take(queue):
    return json.loads(queue.pop_payload().removeprefix("data: "))


class ActivityFeedTests(unittest.TestCase):
    def setUp(self):
        module.SSEQM.activity.clear()
        module.SSEQM.queues.clear()

    def test_limit_order_and_reconnect(self):
        for index in range(25):
            module.SSEQM.publish_activity("job", name=str(index))
        queue = module.SSEQueue()
        module.SSEQM.append(queue)
        snapshot = take(queue)
        self.assertEqual(snapshot["event"], "activity_snapshot")
        self.assertEqual([entry["name"] for entry in snapshot["payload"]],
                         [str(index) for index in range(24, 4, -1)])
        module.SSEQM.publish_activity("notice", name="Next event")
        self.assertEqual(take(queue)["payload"]["kind"], "notice")
        module.SSEQM.remove(queue)
        reconnect = module.SSEQueue()
        module.SSEQM.append(reconnect)
        self.assertEqual(take(reconnect)["payload"][0]["name"], "Next event")

    def test_live_delivery_and_results_are_snapshots(self):
        queues = [module.SSEQueue(), module.SSEQueue()]
        for queue in queues:
            module.SSEQM.append(queue)
            self.assertEqual(take(queue)["payload"], [])
        data = {"results": {"keypad": {"status": "fail", "error": "Timed out"}}}
        module.SSEQM.publish_activity("job", data=data)
        data["results"].clear()
        first, second = [take(queue) for queue in queues]
        self.assertEqual(first, second)
        self.assertEqual(module.SSEQM.activity[0]["data"]["results"]["keypad"]["error"], "Timed out")

    def test_concurrent_jobs_have_consistent_delivery_order(self):
        queue = module.SSEQueue()
        module.SSEQM.append(queue)
        take(queue)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda index: module.SSEQM.publish_activity("job", name=str(index)), range(40)))
        delivered = [take(queue)["payload"]["id"] for _ in range(40)]
        self.assertEqual(len(set(delivered)), 40)
        self.assertEqual([entry["id"] for entry in module.SSEQM.activity], delivered[-20:][::-1])


if __name__ == "__main__":
    unittest.main()
