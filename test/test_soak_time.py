"""Windows integration test for setting soak time in TRIOS.

This test assumes TRIOS is already running and the procedure containing the
soak time step is already loaded.
"""

from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
import time

STEP_LABEL = "1: Conditioning Sample"
PROCEDURE_FILE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "autorios"
    / "data"
    / "settings"
    / "user"
    / "protocol_config"
    / "procedure_files"
    / "HBE_Protokoll2a.tprc"
)

# Test cases for soak time
TEST_CASES = [
    {"label": "1: Conditioning Sample", "soak_time": 10.0},
    {"label": "2: Conditioning Sample", "soak_time": 30.5},
    {"label": "3: Conditioning Sample", "soak_time": 60.0},
    {"label": "4: Conditioning Sample", "soak_time": 120.0},
]


def _import_runtime_modules():
    try:
        settings_module = importlib.import_module("autorios.settings")
        trios_module = importlib.import_module("autorios.trios")
        utility_module = importlib.import_module("autorios.utility")
        protocol_module = importlib.import_module("autorios.protocol")
    except ImportError:
        settings_module = importlib.import_module("autotrios.settings")
        trios_module = importlib.import_module("autotrios.trios")
        utility_module = importlib.import_module("autotrios.utility")
        protocol_module = importlib.import_module("autotrios.protocol")

    return (
        settings_module.get_settings_default,
        settings_module.Settings,
        trios_module.TRIOS,
        protocol_module.Protocol,
        protocol_module.Step,
        protocol_module.STEP_TYPE,
    )


@unittest.skipUnless(sys.platform.startswith("win"), "Windows-only integration test")
class TestTriosSoakTimeIntegration(unittest.TestCase):
    def test_set_soak_time(self):
        (
            get_settings_default,
            Settings,
            TRIOS,
            Protocol,
            Step,
            STEP_TYPE,
        ) = _import_runtime_modules()

        settings = get_settings_default()
        trios = TRIOS.connect(
            window_name=settings.trios_windowname,
            paths=settings.trios_paths,
            start_if_not_open=False,
            backend="uia",
            settings=settings,
        )

        trios.window_main.set_focus()

        for test_case in TEST_CASES:
            with self.subTest(test_case=test_case):
                trios._check_for_stop_event()

                protocol = Protocol(
                    procedure_file_path=PROCEDURE_FILE,
                    settings_update=Settings(),
                    steps=[
                        Step(
                            label=test_case["label"],
                            type_=STEP_TYPE.SOAK_TIME,
                            eval_str=str(test_case["soak_time"]),
                        )
                    ],
                )
                step = protocol.steps[0]

                step_ctrl = trios.window_main.child_window(
                    title=step.label,
                    auto_id="LabelDisabledText",
                    control_type="Text",
                ).wrapper_object()
                step_top_parent = step_ctrl.parent().parent().parent()

                step_dropdown = step_ctrl.parent().parent().children()[0]
               

                try:
                    trios._type_protocol_values(protocol, None) 
                    step_dropdown.draw_outline("blue")
                    step_dropdown.click_input()
                    step_env_control = step_top_parent.descendants(
                        title="Environmental Control", control_type="Group"
                    )[0]
                    soak_time_block = next(
                            custon for custon in step_env_control.descendants(control_type="Custom")
                            if custon.automation_id() == "SoakTimeBlock"
                    )
                    soak_time_edit = soak_time_block.children(control_type="Edit")[0]
                    soak_time_edit.draw_outline("green")
                    actual_soak_time = float(soak_time_edit.window_text().replace(",", "."))
                    print(f"Soak time readback: {actual_soak_time}")
                    self.assertAlmostEqual(actual_soak_time, test_case["soak_time"], places=1)
                    

                finally:
                    # Ensure dropdown is closed for next test
                    step_dropdown.click_input()
                    time.sleep(0.5)


if __name__ == "__main__":
    unittest.main()