# -*- coding: utf-8 -*-
"""serve 模式后台任务：job_id → 状态/结果（线程执行 + 锁保护）"""
from __future__ import annotations

import threading
import time
import traceback
import uuid


class JobManager:
    def __init__(self, max_history: int = 50):
        self._jobs: dict = {}
        self._lock = threading.Lock()
        self._max_history = max_history

    def submit(self, func, description: str = "") -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._prune()
            self._jobs[job_id] = {
                "id": job_id, "status": "running", "description": description,
                "progress": "执行中", "result": None, "error": None,
                "created_at": time.time(),
            }
        t = threading.Thread(target=self._run, args=(job_id, func), daemon=True)
        t.start()
        return job_id

    def _run(self, job_id: str, func):
        try:
            result = func(self._progress(job_id))
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["status"] = "done"
                    self._jobs[job_id]["result"] = result
                    self._jobs[job_id]["progress"] = "完成"
        except Exception as e:
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["status"] = "error"
                    self._jobs[job_id]["error"] = f"{e}\n{traceback.format_exc()[-500:]}"
                    self._jobs[job_id]["progress"] = "失败"

    def _progress(self, job_id: str):
        def set_progress(text: str):
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["progress"] = text
        return set_progress

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def _prune(self):
        done = [k for k, v in self._jobs.items() if v["status"] in ("done", "error")]
        if len(done) > self._max_history:
            for k in done[:-self._max_history]:
                self._jobs.pop(k, None)


JOBS = JobManager()
