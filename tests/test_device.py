import unittest
from unittest.mock import patch

from egg_benchmark.models import resolve_torch_device


class DeviceResolutionTest(unittest.TestCase):
    @patch("torch.backends.mps.is_available", return_value=True)
    @patch("torch.cuda.is_available", return_value=True)
    def test_cuda_has_priority(self, cuda_available, mps_available) -> None:
        self.assertEqual(resolve_torch_device("auto"), "cuda")

    @patch("torch.backends.mps.is_available", return_value=True)
    @patch("torch.cuda.is_available", return_value=False)
    def test_mps_is_used_on_apple(self, cuda_available, mps_available) -> None:
        self.assertEqual(resolve_torch_device("auto"), "mps")

    @patch("torch.backends.mps.is_available", return_value=False)
    @patch("torch.cuda.is_available", return_value=False)
    def test_cpu_fallback(self, cuda_available, mps_available) -> None:
        self.assertEqual(resolve_torch_device("auto"), "cpu")

    def test_explicit_device_is_preserved(self) -> None:
        self.assertEqual(resolve_torch_device("cpu"), "cpu")


if __name__ == "__main__":
    unittest.main()
