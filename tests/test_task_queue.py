import unittest
import tempfile
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import core.task_queue as task_queue
from core.task_queue import TaskStatus, add_task, get_task, list_tasks, cancel_task, pause_task, resume_task


class TestTaskQueue(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        task_queue.TASKS_DB_PATH = self.temp_dir / "tasks_test.db"
        from sqlmodel import create_engine
        task_queue.engine = create_engine(f"sqlite:///{task_queue.TASKS_DB_PATH}", connect_args={"check_same_thread": False})
        task_queue.init_tasks_db()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_task_lifecycle(self):
        task_id = add_task("book_abc", "process_book", param="value")
        self.assertIsNotNone(task_id)

        task = get_task(task_id)
        self.assertIsNotNone(task)
        self.assertEqual(task.book_id, "book_abc")
        self.assertEqual(task.type, "process_book")
        self.assertEqual(task.status, TaskStatus.QUEUED)
        self.assertEqual(task.kwargs, {"param": "value"})

        all_tasks = list_tasks()
        self.assertGreaterEqual(len(all_tasks), 1)

        cancel_task(task_id)
        task_after_cancel = get_task(task_id)
        self.assertEqual(task_after_cancel.status, TaskStatus.CANCELLED)

    def test_pause_resume_task(self):
        task_id = add_task("book_xyz", "generate_summary")
        with task_queue.Session(task_queue.engine) as session:
            t = session.get(task_queue.TaskRecord, task_id)
            t.status = TaskStatus.PROCESSING
            session.add(t)
            session.commit()

        pause_task(task_id)
        t_paused = get_task(task_id)
        self.assertEqual(t_paused.status, TaskStatus.PAUSED)

        resume_task(task_id)
        t_resumed = get_task(task_id)
        self.assertEqual(t_resumed.status, TaskStatus.PROCESSING)


if __name__ == "__main__":
    unittest.main()
