"""Locust scenarios for the CRM shell and health endpoint."""

import os

from locust import HttpUser, between, task


class CRMUser(HttpUser):
    host = os.environ.get("LOCUST_HOST") or "http://127.0.0.1:8000"
    wait_time = between(1, 3)

    @task(3)
    def shell(self):
        self.client.get("/", name="shell", allow_redirects=True)

    @task(1)
    def health(self):
        self.client.get("/api/health", name="health")
