"""Set LOAD_EMAIL and LOAD_PASSWORD in your environment; never pass credentials as arguments."""

import os

from locust import HttpUser, between, tag, task


class ResearchUser(HttpUser):
    wait_time = between(0.1, 0.3) if os.environ.get("LOAD_MODE") == "read" else between(10, 20)

    def on_start(self):
        result = self.client.post(
            "/api/v1/auth/login",
            json={"email": os.environ["LOAD_EMAIL"], "password": os.environ["LOAD_PASSWORD"]},
        )
        result.raise_for_status()
        self.client.headers["X-CSRF-Token"] = result.json()["csrf_token"]

    @tag("read")
    @task(4)
    def browse(self):
        self.client.get("/api/v1/documents")

    @tag("llm")
    @task(1)
    def research(self):
        c = self.client.post("/api/v1/conversations", json={"title": "Carga local"})
        if c.status_code != 201:
            return
        result = self.client.post(
            f"/api/v1/conversations/{c.json()['id']}/messages",
            json={"content": "Quem é considerado empregador?"},
        )
        if result.status_code == 202:
            self.client.get(f"/api/v1/jobs/{result.json()['id']}")
