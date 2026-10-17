from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class OriginUvMirrorContractTests(unittest.TestCase):
    def test_backend_dockerfile_uses_pinned_docker_hub_uv_image(self):
        dockerfile = (ROOT / "Dockerfile").read_text()

        self.assertIn(
            "COPY --from=docker.io/astral/uv:0.11.26 /uv /uvx /bin/",
            dockerfile,
        )
        self.assertNotIn("ghcr.io/astral-sh/uv", dockerfile)


if __name__ == "__main__":
    unittest.main()
