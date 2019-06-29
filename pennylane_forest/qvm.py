"""
QVM Device
==========

**Module name:** :mod:`pennylane_forest.qvm`

.. currentmodule:: pennylane_forest.qvm

This module contains the :class:`~.QVMDevice` class, a PennyLane device that allows
evaluation and differentiation of Rigetti's Forest Quantum Virtual Machines (QVMs)
using PennyLane.

Classes
-------

.. autosummary::
   QVMDevice

Code details
~~~~~~~~~~~~
"""
import re
import numpy as np

import networkx as nx
from pyquil import get_qc
from pyquil.api._quantum_computer import _get_qvm_with_topology
from pyquil.gates import MEASURE, RESET
from pyquil.quil import Pragma, Program

from .device import ForestDevice
from ._version import __version__


class QVMDevice(ForestDevice):
    r"""Forest QVM device for PennyLane.

    This device supports both the Rigetti Lisp QVM, as well as the built-in pyQuil pyQVM.
    If using the pyQVM, the ``qvm_url`` QVM server url keyword argument does not need to
    be set.

    Args:
        device (Union[str, nx.Graph]): the name or topology of the device to initialise.

            * ``Nq-qvm``: for a fully connected/unrestricted N-qubit QVM
            * ``9q-qvm-square``: a :math:`9\times 9` lattice.
            * ``Nq-pyqvm`` or ``9q-pyqvm-square``, for the same as the above but run
              via the built-in pyQuil pyQVM device.
            * Any other supported Rigetti device architecture.
            * Graph topology representing the device architecture.

        shots (int): number of circuit evaluations/random samples used
            to estimate expectation values of observables.
        noisy (bool): set to ``True`` to add noise models to your QVM.

    Keyword args:
        forest_url (str): the Forest URL server. Can also be set by
            the environment variable ``FOREST_SERVER_URL``, or in the ``~/.qcs_config``
            configuration file. Default value is ``"https://forest-server.qcs.rigetti.com"``.
        qvm_url (str): the QVM server URL. Can also be set by the environment
            variable ``QVM_URL``, or in the ``~/.forest_config`` configuration file.
            Default value is ``"http://127.0.0.1:5000"``.
        compiler_url (str): the compiler server URL. Can also be set by the environment
            variable ``COMPILER_URL``, or in the ``~/.forest_config`` configuration file.
            Default value is ``"http://127.0.0.1:6000"``.
    """
    name = "Forest QVM Device"
    short_name = "forest.qvm"
    observables = {"PauliX", "PauliY", "PauliZ", "Identity", "Hadamard", "Hermitian"}

    def __init__(self, device, *, shots=1024, noisy=False, **kwargs):
        self._eigs = {}

        if shots <= 0:
            raise ValueError("Number of shots must be a positive integer.")

        # ignore any 'wires' keyword argument passed to the device
        kwargs.pop("wires", None)

        # get the number of wires
        if isinstance(device, nx.Graph):
            # load a QVM based on a graph topology
            num_wires = device.number_of_nodes()
        elif isinstance(device, str):
            # the device string must match a valid QVM device, i.e.
            # N-qvm, or 9q-square-qvm, or Aspen-1-16Q-A
            wire_match = re.search(r"(\d+)(q|Q)", device)

            if wire_match is None:
                # with the current Rigetti naming scheme, this error should never
                # appear as long as the QVM quantum computer has the correct name
                raise ValueError("QVM device string does not indicate the number of qubits!")

            num_wires = int(wire_match.groups()[0])
        else:
            raise ValueError(
                "Required argument device must be a string corresponding to "
                "a valid QVM quantum computer, or a NetworkX graph object."
            )

        super().__init__(num_wires, shots, **kwargs)

        # get the qc
        if isinstance(device, nx.Graph):
            self.qc = _get_qvm_with_topology(
                "device", topology=device, noisy=noisy, connection=self.connection
            )
        elif isinstance(device, str):
            self.qc = get_qc(device, as_qvm=True, noisy=noisy, connection=self.connection)

        self.active_reset = False

    def pre_measure(self):
        """Run the QVM"""
        # pylint: disable=attribute-defined-outside-init
        for e in self.obs_queue:
            wires = e.wires

            if e.name == "PauliX":
                # X = H.Z.H
                self.apply("Hadamard", wires, [])

            elif e.name == "PauliY":
                # Y = (HS^)^.Z.(HS^) and S^=SZ
                self.apply("PauliZ", wires, [])
                self.apply("S", wires, [])
                self.apply("Hadamard", wires, [])

            elif e.name == "Hadamard":
                # H = Ry(-pi/4)^.Z.Ry(-pi/4)
                self.apply("RY", wires, [-np.pi / 4])

            elif e.name == "Hermitian":
                # For arbitrary Hermitian matrix H, let U be the unitary matrix
                # that diagonalises it, and w_i be the eigenvalues.
                H = e.parameters[0]
                Hkey = tuple(H.flatten().tolist())

                if Hkey in self._eigs:
                    # retrieve eigenvectors
                    U = self._eigs[Hkey]["eigvec"]
                else:
                    # store the eigenvalues corresponding to H
                    # in a dictionary, so that they do not need to
                    # be calculated later
                    w, U = np.linalg.eigh(H)
                    self._eigs[Hkey] = {"eigval": w, "eigvec": U}

                # Perform a change of basis before measuring by applying U^ to the circuit
                self.apply("QubitUnitary", wires, [U.conj().T])

        prag = Program(Pragma("INITIAL_REWIRING", ['"PARTIAL"']))

        if self.active_reset:
            prag += RESET()

        self.prog = prag + self.prog

        qubits = list(self.prog.get_qubits())
        ro = self.prog.declare("ro", "BIT", len(qubits))
        for i, q in enumerate(qubits):
            self.prog.inst(MEASURE(q, ro[i]))

        self.prog.wrap_in_numshots_loop(self.shots)

        if "pyqvm" in self.qc.name:
            bitstring_array = self.qc.run(self.prog)
        else:
            executable = self.qc.compile(self.prog)
            bitstring_array = self.qc.run(executable=executable)

        self.state = {}
        for i, q in enumerate(qubits):
            self.state[q] = bitstring_array[:, i]

    def expval(self, observable, wires, par):
        if len(wires) == 1:
            # 1 qubit observable
            evZ = np.mean(1 - 2 * self.state[wires[0]])

            # for single qubit state probabilities |psi|^2 = (p0, p1),
            # we know that p0+p1=1 and that <Z>=p0-p1
            p0 = (1 + evZ) / 2
            p1 = (1 - evZ) / 2

            if observable == "Identity":
                # <I> = \sum_i p_i
                return p0 + p1

            if observable == "Hermitian":
                # <H> = \sum_i w_i p_i
                Hkey = tuple(par[0].flatten().tolist())
                w = self._eigs[Hkey]["eigval"]
                return w[0] * p0 + w[1] * p1

            return evZ

        # Multi-qubit observable
        # ----------------------
        # Currently, we only support qml.expval.Hermitian(A, wires),
        # where A is a 2^N x 2^N matrix acting on N wires.
        #
        # Eventually, we will also support tensor products of Pauli
        # matrices in the PennyLane UI.

        probs = self.probabilities(wires)

        if observable == "Hermitian":
            Hkey = tuple(par[0].flatten().tolist())
            w = self._eigs[Hkey]["eigval"]
            # <A> = \sum_i w_i p_i
            return w @ probs

    def probabilities(self, wires):
        """Returns the (marginal) probabilities of the quantum state.

        Args:
            wires (Sequence[int]): sequence of wires to return
                marginal probabilities for. Wires not provided
                are traced out of the system.

        Returns:
            array: array of shape ``[2**len(wires)]`` containing
            the probabilities of each computational basis state
        """

        # create an array of size [2^len(wires), 2] to store
        # the resulting probability of each computational basis state
        probs = np.zeros([2 ** len(wires), 2])
        probs[:, 0] = np.arange(2 ** len(wires))

        # extract the measured samples
        res = np.array([self.state[w] for w in wires]).T
        for i in res:
            # for each sample, calculate which
            # computational basis state it corresponds to
            cb = np.sum(2 ** np.arange(len(wires) - 1, -1, -1) * i)
            # add a tally for this computational basis state
            # to our array of basis probabilities
            probs[cb, 1] += 1

        # sort the probabilities by the first column,
        # and divide by the number of shots
        probs = probs[probs[:, 0].argsort()] / self.shots
        probs = probs[:, 1]

        return probs

    def var(self, observable, wires, par):
        if len(wires) == 1:
            # 1 qubit observable
            if observable == "Identity":
                return 0

            varZ = np.var(1 - 2 * self.state[wires[0]])

            if observable in {"PauliX", "PauliY", "PauliZ", "Hadamard"}:
                return varZ

            # for single qubit state probabilities |psi|^2 = (p0, p1),
            # we know that p0+p1=1 and that <Z>=p0-p1
            evZ = np.mean(1 - 2 * self.state[wires[0]])
            probs = np.array([(1 + evZ) / 2, (1 - evZ) / 2])

            if observable == "Hermitian":
                # <H> = \sum_i w_i p_i
                Hkey = tuple(par[0].flatten().tolist())
                w = self._eigs[Hkey]["eigval"]
                return (w ** 2) @ probs - (w @ probs) ** 2

        # Multi-qubit observable
        # ----------------------
        # Currently, we only support qml.expval.Hermitian(A, wires),
        # where A is a 2^N x 2^N matrix acting on N wires.
        #
        # Eventually, we will also support tensor products of Pauli
        # matrices in the PennyLane UI.

        probs = self.probabilities(wires)

        if observable == "Hermitian":
            Hkey = tuple(par[0].flatten().tolist())
            w = self._eigs[Hkey]["eigval"]
            # <A> = \sum_i w_i p_i
            return (w ** 2) @ probs - (w @ probs) ** 2
