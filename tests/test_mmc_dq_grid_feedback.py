"""Reproduce the native dq controller's directional grid-feedback instability.

The isolated current-loop test supplies a stiff 256 kV terminal voltage.  This
independent circuit instead puts the requested SCR=5 grid and transformer behind
the measured valve terminal.  Its two 50 us command-delay states represent the
native module/voltage-source interfaces; fundamental phase advance has already
been compensated.  They still delay perturbations of the voltage command.

These are local, unsaturated stability checks, not MMC physical acceptance.  The
model excludes capacitor-energy, dc-link and protection dynamics deliberately:
the problematic approximately 160 Hz mode can be reproduced without them.
"""

import math

import pytest


np = pytest.importorskip("numpy")


class _GridFeedbackModel:
    """A sampled dq controller around an independently derived RL circuit.

    All vectors use the same sine-based rotating frame as the electrical
    convention, with J = [[0, 1], [-1, 0]].  Current flows from grid to converter.

    The passive circuit equations, in the ideal-source reference frame, are::

        (Lg + La) di/dt = E - vc - (Rg + Ra)i + omega (Lg + La) J i
        v = E - Rg i - Lg (di/dt - omega J i)
        v_primary = v + Lt (di/dt - omega J i)

    Lg includes the source and transformer; La is half the physical arm
    inductance.  Thus terminal voltage is measured from the actual circuit,
    including transformer energy exchange in primary active power.  Exact
    zero-order-hold integration is used for this linear passive plant.
    """

    step_s = 50e-6
    command_delay_steps = 2
    frequency_hz = 60.0
    current_bandwidth_hz = 80.0
    damping = 1.0 / math.sqrt(2.0)
    feedback_filter_s = 0.02

    def __init__(self, power_mw, *, pll_bandwidth_hz=10.0, voltage_filter_s=0.0):
        self.power_mw = power_mw
        self.voltage_filter_s = voltage_filter_s
        self.omega = 2.0 * math.pi * self.frequency_hz
        self.j = np.array([[0.0, 1.0], [-1.0, 0.0]])
        self.identity = np.eye(2)

        # Circuit specification, independent of the controller implementation.
        # 640 kV dc, modulation 0.8 => 256 kV phase-peak at the valve side.
        grid_voltage_kv = 230.0
        rated_power_mw = 1000.0
        short_circuit_ratio = 5.0
        x_over_r = 10.0
        valve_phase_peak_kv = 0.5 * 0.8 * 640.0
        valve_voltage_kv = math.sqrt(1.5) * valve_phase_peak_kv
        turns_ratio_squared = (valve_voltage_kv / grid_voltage_kv) ** 2
        grid_impedance = grid_voltage_kv**2 / rated_power_mw / short_circuit_ratio
        self.grid_r = grid_impedance / math.hypot(1.0, x_over_r) * turns_ratio_squared
        self.source_x = self.grid_r * x_over_r
        self.transformer_x = 0.15 * valve_voltage_kv**2 / 1100.0
        self.transformer_l = self.transformer_x / self.omega
        self.grid_l = (self.source_x + self.transformer_x) / self.omega
        self.arm_l = 0.05 / 2.0
        self.arm_r = 0.15 / 2.0
        self.total_l = self.grid_l + self.arm_l
        self.total_r = self.grid_r + self.arm_r
        self.source = np.array([valve_phase_peak_kv, 0.0])

        bandwidth = 2.0 * math.pi * self.current_bandwidth_hz
        self.current_kp = 2.0 * self.damping * self.arm_l * bandwidth
        self.current_ki = self.arm_l * bandwidth**2
        pll_bandwidth = 2.0 * math.pi * pll_bandwidth_hz
        self.pll_kp = 2.0 * self.damping * pll_bandwidth
        self.pll_ki = pll_bandwidth**2

        self.plant_a = -self.total_r / self.total_l * self.identity + self.omega * self.j
        angle = self.omega * self.step_s
        self.plant_discrete_a = math.exp(-self.total_r / self.total_l * self.step_s) * (
            math.cos(angle) * self.identity + math.sin(angle) * self.j
        )
        self.plant_discrete_b = np.linalg.solve(
            self.plant_a, self.plant_discrete_a - self.identity
        ) / self.total_l
        self.controller_start = 2 + 2 * self.command_delay_steps

    def _rotate(self, angle):
        return math.cos(angle) * self.identity + math.sin(angle) * self.j

    def equilibrium(self):
        """Solve the high-voltage, Q_primary=0 load-flow branch analytically.

        For signed p=P/1.5 and x=|V_primary|**2:
        x**2 + (2 Rg p - |E|**2) x + |Z_source|**2 p**2 = 0.
        """
        p = self.power_mw / 1.5
        coefficient = self.source[0] ** 2 - 2.0 * self.grid_r * p
        discriminant = coefficient**2 - 4.0 * (self.grid_r**2 + self.source_x**2) * p**2
        assert discriminant > 0.0, "The chosen operating point has no load-flow solution"
        primary_voltage = math.sqrt(0.5 * (coefficient + math.sqrt(discriminant)))
        primary_current = p / primary_voltage
        primary_angle = -math.atan2(
            self.source_x * primary_current,
            primary_voltage + self.grid_r * primary_current,
        )
        current = self._rotate(primary_angle).T @ np.array([primary_current, 0.0])
        voltage = self.source - self.grid_r * current + self.omega * self.grid_l * self.j @ current
        pll_angle = math.atan2(voltage[1], voltage[0])
        converter_voltage = (
            self.source - self.total_r * current + self.omega * self.total_l * self.j @ current
        )
        # State: grid-frame i[2], two delayed vc[2], current PI[2], PLL angle,
        # PLL PI, outer P PI, outer Q PI, filtered Q, optional filtered Vd.
        return np.r_[
            current,
            np.tile(converter_voltage, self.command_delay_steps),
            [0.0, 0.0, pll_angle, 0.0, 0.0, 0.0, 0.0],
            [np.linalg.norm(voltage)] if self.voltage_filter_s else [],
        ]

    def step(self, state):
        current = state[:2]
        applied_voltage = state[2:4]
        control = state[self.controller_start :]
        rotation = self._rotate(control[2])

        derivative = self.plant_a @ current + (self.source - applied_voltage) / self.total_l
        voltage = self.source - self.grid_r * current - self.grid_l * (
            derivative - self.omega * self.j @ current
        )
        primary_voltage = voltage + self.transformer_l * (
            derivative - self.omega * self.j @ current
        )
        measured_current = rotation @ current
        measured_voltage = rotation @ voltage
        active_power = 1.5 * primary_voltage @ current
        reactive_power = 1.5 * (
            primary_voltage[1] * current[0] - primary_voltage[0] * current[1]
        )
        alpha = -math.expm1(-self.step_s / self.feedback_filter_s)
        filtered_q = control[6] + alpha * (reactive_power - control[6])
        outer_p = control[4] + self.step_s * 2.0 * (self.power_mw - active_power)
        outer_q = control[5] + self.step_s * 2.0 * filtered_q

        if self.voltage_filter_s:
            alpha_v = -math.expm1(-self.step_s / self.voltage_filter_s)
            voltage_base = control[7] + alpha_v * (measured_voltage[0] - control[7])
        else:
            voltage_base = measured_voltage[0]
        transformer_vars = 1.5 * self.transformer_x * (measured_current @ measured_current)
        reference = np.array(
            [
                (self.power_mw + 0.1 * (self.power_mw - active_power) + outer_p),
                (transformer_vars + 0.1 * filtered_q + outer_q),
            ]
        ) / (1.5 * voltage_base)
        error = measured_current - reference
        current_integrator = control[:2] + self.step_s * self.current_ki * error

        # Only the denominator above is filtered.  Voltage feedforward keeps
        # the measured Vd/Vq, otherwise this would be a different current loop.
        command = (
            measured_voltage
            - self.arm_r * measured_current
            + self.omega * self.arm_l * self.j @ measured_current
            + self.current_kp * error
            + current_integrator
        )
        pll_error = math.atan2(measured_voltage[1], measured_voltage[0])
        pll_integrator = control[3] + self.step_s * self.pll_ki * pll_error
        pll_angle = control[2] + self.step_s * (self.pll_kp * pll_error + pll_integrator)

        return np.r_[
            self.plant_discrete_a @ current + self.plant_discrete_b @ (self.source - applied_voltage),
            state[4 : self.controller_start],
            rotation.T @ command,
            current_integrator,
            [pll_angle, pll_integrator, outer_p, outer_q, filtered_q],
            [voltage_base] if self.voltage_filter_s else [],
        ]

    def linear_modes(self):
        operating_point = self.equilibrium()
        np.testing.assert_allclose(self.step(operating_point), operating_point, rtol=0.0, atol=1e-9)
        perturbation = 1e-5
        basis = np.eye(len(operating_point)) * perturbation
        jacobian = np.column_stack(
            [
                (self.step(operating_point + direction) - self.step(operating_point - direction))
                / (2.0 * perturbation)
                for direction in basis
            ]
        )
        # A discrete eigenvalue is stable iff |lambda|<1.  Mapping to
        # log(lambda)/dt also reports its growth rate and oscillation frequency.
        discrete_modes = np.linalg.eigvals(jacobian).astype(complex)
        return discrete_modes, np.log(discrete_modes) / self.step_s


@pytest.mark.parametrize(
    "power_mw, pll_bandwidth_hz, voltage_filter_s, stable, unstable_frequency_hz",
    [
        pytest.param(1000.0, 10.0, 0.0, False, (140.0, 180.0), id="rectifier-unfiltered"),
        pytest.param(1000.0, 1.0, 0.0, False, (140.0, 180.0), id="slow-pll-does-not-repair"),
        pytest.param(-1000.0, 10.0, 0.0, True, None, id="inverter-unfiltered"),
        pytest.param(300.0, 10.0, 0.0, True, None, id="low-power-unfiltered"),
        pytest.param(1000.0, 10.0, 0.02, True, None, id="rectifier-20ms-filter"),
        pytest.param(1000.0, 1.0, 0.02, True, None, id="rectifier-20ms-filter-slow-pll"),
        pytest.param(1000.0, 10.0, 0.001, False, (100.0, 140.0), id="1ms-filter-insufficient"),
    ],
)
def test_dq_power_voltage_feedback_with_grid_impedance_and_native_delay(
    power_mw, pll_bandwidth_hz, voltage_filter_s, stable, unstable_frequency_hz
):
    model = _GridFeedbackModel(
        power_mw, pll_bandwidth_hz=pll_bandwidth_hz, voltage_filter_s=voltage_filter_s
    )
    discrete_modes, continuous_modes = model.linear_modes()
    dominant = continuous_modes[np.argmax(continuous_modes.real)]
    if stable:
        assert np.max(np.abs(discrete_modes)) < 1.0
        assert dominant.real < -1.0, continuous_modes
    else:
        assert np.max(np.abs(discrete_modes)) > 1.0
        assert dominant.real > 10.0, continuous_modes
        lower, upper = unstable_frequency_hz
        assert lower < abs(dominant.imag) / (2.0 * math.pi) < upper
