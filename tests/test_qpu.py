"""
Unit tests for the QPU device.
"""
import logging

import pytest
import pyquil
import pennylane as qml
from pennylane import numpy as np
from conftest import BaseTest


log = logging.getLogger(__name__)

VALID_QPU_LATTICES = [qc for qc in pyquil.list_quantum_computers() if "qvm" not in qc]


class TestQPUIntegration(BaseTest):
    """Test the wavefunction simulator works correctly from the PennyLane frontend."""

    # pylint: disable=no-self-use

    def test_load_qpu_device(self):
        """Test that the QPU device loads correctly"""
        device = [qpu for qpu in VALID_QPU_LATTICES if '2Q' in qpu][0]
        dev = qml.device("forest.qpu", device=device, load_qc=False)
        self.assertEqual(dev.num_wires, 2)
        self.assertEqual(dev.shots, 1024)
        self.assertEqual(dev.short_name, "forest.qpu")

    def test_load_virtual_qpu_device(self):
        """Test that the QPU simulators load correctly"""
        device = np.random.choice(VALID_QPU_LATTICES)
        qml.device("forest.qpu", device=device, load_qc=False)

    def test_qpu_args(self):
        """Test that the QPU plugin requires correct arguments"""
        device = np.random.choice(VALID_QPU_LATTICES)

        with pytest.raises(ValueError, match="QPU device does not support a wires parameter"):
            qml.device("forest.qpu", device=device, wires=2)

        with pytest.raises(TypeError, match="missing 1 required positional argument"):
            qml.device("forest.qpu")

        with pytest.raises(ValueError, match="Number of shots must be a positive integer"):
            qml.device("forest.qpu", device=device, shots=0)

        with pytest.raises(ValueError, match="Readout error cannot be set on the physical QPU"):
            qml.device("forest.qpu", device=device, load_qc=True, readout_error=[0.9, 0.75])
