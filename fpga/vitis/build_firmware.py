#!/usr/bin/env python3
"""Vitis 2025.2 batch build for the Zybo Cortex-A9 UART firmware."""

import os
import vitis

script_dir = os.path.dirname(os.path.abspath(__file__))
fpga_dir = os.path.dirname(script_dir)
repo_dir = os.path.dirname(fpga_dir)
workspace = os.path.join(fpga_dir, "build", "vitis_workspace")
xsa = os.path.join(fpga_dir, "build", "vivado_project", "deskband_zybo.xsa")
if not os.path.isfile(xsa):
    raise RuntimeError(f"hardware platform is missing: {xsa}")

client = vitis.create_client()
client.set_workspace(path=workspace)
# Make the batch build repeatable when the hardware XSA or firmware changes.
# The workspace contains generated components only; source remains under fpga/ps.
for component_name in ("deskband_firmware", "deskband_platform"):
    try:
        client.delete_component(name=component_name)
    except Exception:
        pass
platform = client.create_platform_component(
    name="deskband_platform", hw_design=xsa, os="standalone",
    cpu="ps7_cortexa9_0", domain_name="standalone_a9_0")
platform.build()

platform_xpfm = client.find_platform_in_repos("deskband_platform")
app = client.create_app_component(
    name="deskband_firmware", platform=platform_xpfm,
    domain="standalone_a9_0", template="empty_application")
app.import_files(from_loc=os.path.join(fpga_dir, "ps", "src"),
                 files=["main.c", "protocol.c"], dest_dir_in_cmp="src")
app.import_files(from_loc=os.path.join(fpga_dir, "ps", "include"),
                 files=["deskband_regs.h", "protocol.h"], dest_dir_in_cmp="src")
app.set_app_config(key="USER_COMPILE_OTHER_FLAGS", values="-Wall -Wextra -O2")
app.build()
elf = os.path.join(workspace, "deskband_firmware", "build", "deskband_firmware.elf")
if not os.path.isfile(elf):
    raise RuntimeError(f"firmware build did not produce {elf}")
print(f"PASS: firmware built in {workspace}")
vitis.dispose()
