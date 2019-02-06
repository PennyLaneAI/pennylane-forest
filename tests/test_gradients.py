"""
Integration tests for quantum gradient computations.
"""
import pennylane as qml
from pennylane import numpy as np

from pennylane_forest.ops import PSWAP


def test_simulator_qvm_default_agree(tol, qvm, compiler):
    """Test that forest.wavefunction, forest.qvm, and default.qubit agree
    on the calculation of quantum gradients."""
    w = 2

    dev1 = qml.device('default.qubit', wires=w)
    dev2 = qml.device('forest.wavefunction', wires=w)
    dev3 = qml.device('forest.qvm', device='9q-square-qvm', shots=5000)

    in_state = np.zeros([w])
    in_state[0] = 1
    in_state[1] = 1

    def func(x, y):
        """Reference QNode"""
        qml.BasisState(in_state, wires=list(range(w)))
        qml.RY(x, wires=0)
        qml.RX(y, wires=1)
        qml.CNOT(wires=[0, 1])
        return qml.expval.PauliZ(1)

    func1 = qml.QNode(func, dev1)
    func2 = qml.QNode(func, dev2)
    func3 = qml.QNode(func, dev3)

    params = [0.2, 0.453]

    # check all evaluate to the same value
    # NOTE: we increase the tolerance when using the QVM
    assert np.all(np.abs(func1(*params) - func2(*params)) <= tol)
    assert np.all(np.abs(func1(*params) - func3(*params)) <= 0.1)
    assert np.all(np.abs(func2(*params) - func3(*params)) <= 0.1)

    df1 = qml.grad(func1, argnum=[0, 1])
    df2 = qml.grad(func2, argnum=[0, 1])
    df3 = qml.grad(func3, argnum=[0, 1])

    # check all gradients evaluate to the same value
    # NOTE: we increase the tolerance when using the QVM
    assert np.all(np.abs(np.array(df1(*params)) - np.array(df2(*params))) <= tol)
    assert np.all(np.abs(np.array(df1(*params)) - np.array(df3(*params))) <= 0.1)
    assert np.all(np.abs(np.array(df2(*params)) - np.array(df3(*params))) <= 0.1)


def test_gradient_with_custom_operator(qvm, compiler):
    """Test that forest.wavefunction forest.qvm agree
    on the calculation of quantum gradients when a custom Forest
    operator is used."""
    w = 9

    dev2 = qml.device('forest.wavefunction', wires=w)
    dev3 = qml.device('forest.qvm', device='9q-square-qvm', shots=5000)

    def func(x, y):
        """Reference QNode"""
        qml.BasisState(np.array([1, 1]), wires=0)
        qml.RY(x, wires=0)
        qml.RX(y, wires=1)
        PSWAP(0.432, wires=[0, 1])
        qml.CNOT(wires=[0, 1])
        return qml.expval.PauliZ(1)

    func2 = qml.QNode(func, dev2)
    func3 = qml.QNode(func, dev3)

    params = [0.2, 0.453]

    # check all evaluate to the same value
    # NOTE: we increase the tolerance when using the QVM
    assert np.all(np.abs(func2(*params) - func3(*params)) <= 0.1)

    df2 = qml.grad(func2, argnum=[0, 1])
    df3 = qml.grad(func3, argnum=[0, 1])

    # check all gradients evaluate to the same value
    # NOTE: we increase the tolerance when using the QVM
    assert np.all(np.abs(np.array(df2(*params)) - np.array(df3(*params))) <= 0.1)
