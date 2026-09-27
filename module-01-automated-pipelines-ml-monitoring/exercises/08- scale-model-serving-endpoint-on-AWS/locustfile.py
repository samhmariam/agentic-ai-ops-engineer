"""Generate sustained inference traffic for the Beans API.

Install on the load-generator machine:
    python -m pip install locust

Run from this directory (replace TASK_PUBLIC_IP with your task's public IP):
    locust --host http://TASK_PUBLIC_IP:8000

Or run 50 users, adding 5 users/second, for 10 minutes:
    locust --host http://TASK_PUBLIC_IP:8000 --headless \
        --users 50 --spawn-rate 5 --run-time 10m --csv beans-load

The default image comes from exercise 06. Set LOCUST_IMAGE_PATH to use another
JPEG or PNG. Image bytes are cached per worker, outside the timed requests.
Increase users gradually while monitoring ECS CPU, latency, and errors; a fixed
user count does not guarantee CPU exceeds 70%. After stopping the load, allow
at least five low-CPU minutes for the scale-in alarm.

A task public IP targets only that task. An Application Load Balancer is needed
to distribute traffic across new tasks; service-average CPU can fall as idle
tasks are added. This exercise's deploy.sh does not configure a load balancer.
"""

import mimetypes
import os
from functools import lru_cache
from pathlib import Path

from locust import HttpUser, between, task


@lru_cache(maxsize=1)
def load_image():
    default_path = (
        Path(__file__).resolve().parent.parent
        / "06-containerize-FastAPI-classifier-api"
        / "test-image.jpg"
    )
    image_path = Path(os.getenv("LOCUST_IMAGE_PATH", str(default_path))).expanduser()
    content_type = mimetypes.guess_type(image_path.name)[0]
    if content_type not in {"image/jpeg", "image/png"}:
        raise ValueError("LOCUST_IMAGE_PATH must point to a JPEG or PNG image")
    image_bytes = image_path.read_bytes()
    if not image_bytes:
        raise ValueError(f"Test image is empty: {image_path}")
    return image_path.name, image_bytes, content_type


class BeansAPIUser(HttpUser):
    # Keep inference requests frequent enough to generate sustained CPU load.
    wait_time = between(0.1, 0.5)

    def on_start(self):
        self.image_upload = load_image()

    @task
    def predict(self):
        with self.client.post(
            "/predict",
            files={"file": self.image_upload},
            name="/predict",
            timeout=60,
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"Prediction returned HTTP {response.status_code}")
                return
            try:
                prediction = response.json()
            except ValueError:
                response.failure("Prediction response is not JSON")
                return
            if not isinstance(prediction, dict):
                response.failure("Prediction response is not an object")
                return
            label = prediction.get("label")
            score = prediction.get("score")
            if (
                not isinstance(label, str)
                or not label
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not 0 <= score <= 1
            ):
                response.failure("Prediction response has an invalid label or score")
