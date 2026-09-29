import os

import requests
from locust import HttpUser, between, events, task

TOKEN = None


@events.test_start.add_listener
def login_once(environment, **kwargs):
    global TOKEN
    r = requests.post(
        f"{environment.host}/auth/login",
        json={
            "username": os.environ.get("LOAD_USER", "viewer1"),
            "password": os.environ.get("LOAD_PASSWORD", "password123"),
        },
        timeout=10,
    )
    r.raise_for_status()
    TOKEN = r.json()["access_token"]


class Viewer(HttpUser):
    wait_time = between(0.5, 2)

    def on_start(self):
        self.h = {"Authorization": f"Bearer {TOKEN}"}

    @task(5)
    def whatif(self):
        self.client.get("/api/whatif", headers=self.h)

    @task(3)
    def simulate(self):
        self.client.get("/api/simulate/24", headers=self.h)

    @task(3)
    def state(self):
        self.client.get("/api/state", headers=self.h)

    @task(1)
    def alerts(self):
        self.client.get("/api/alerts", headers=self.h)

    @task(1)
    def health(self):
        self.client.get("/healthz")
