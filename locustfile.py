from locust import HttpUser, between, task


class Viewer(HttpUser):
    wait_time = between(0.5, 2)

    def on_start(self):
        self.client.post("/auth/register", json={"username": f"load{id(self)}", "password": "password123"})
        r = self.client.post("/auth/login", json={"username": f"load{id(self)}", "password": "password123"})
        self.h = {"Authorization": f"Bearer {r.json().get('access_token','')}"}

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
