VERILATOR ?= verilator
BUILD_DIR := build
TIMING_TOP := tb_deskband_timing_core
BUTTON_TOP := tb_button_debounce
AXI_TOP := tb_deskband_axi_peripheral
ENVELOPE_TOP := tb_level_envelope_bank
LFO_TOP := tb_lfo_bank

.PHONY: test test-timing test-button test-envelope test-lfo test-axi ps-test lint vivado-check clean

test: test-timing test-button test-envelope test-lfo test-axi

test-timing: $(BUILD_DIR)/timing/V$(TIMING_TOP)
	./$(BUILD_DIR)/timing/V$(TIMING_TOP)

test-button: $(BUILD_DIR)/button/V$(BUTTON_TOP)
	./$(BUILD_DIR)/button/V$(BUTTON_TOP)

test-envelope: $(BUILD_DIR)/envelope/V$(ENVELOPE_TOP)
	./$(BUILD_DIR)/envelope/V$(ENVELOPE_TOP)

test-lfo: $(BUILD_DIR)/lfo/V$(LFO_TOP)
	./$(BUILD_DIR)/lfo/V$(LFO_TOP)

test-axi: $(BUILD_DIR)/axi/V$(AXI_TOP)
	./$(BUILD_DIR)/axi/V$(AXI_TOP)

ps-test:
	mkdir -p $(BUILD_DIR)/ps_test
	$(CC) -std=c11 -Wall -Wextra -Werror -Ips/include \
		ps/src/protocol.c ps/tests/test_protocol.c -o $(BUILD_DIR)/ps_test/test_protocol
	./$(BUILD_DIR)/ps_test/test_protocol

$(BUILD_DIR)/timing/V$(TIMING_TOP): rtl/deskband_timing_core.sv sim/tb_deskband_timing_core.sv
	mkdir -p $(BUILD_DIR)/timing
	$(VERILATOR) --binary --timing --assert -Wall -Wno-fatal \
		--Mdir $(BUILD_DIR)/timing --top-module $(TIMING_TOP) $^

$(BUILD_DIR)/button/V$(BUTTON_TOP): rtl/button_debounce.sv sim/tb_button_debounce.sv
	mkdir -p $(BUILD_DIR)/button
	$(VERILATOR) --binary --timing --assert -Wall -Wno-fatal \
		--Mdir $(BUILD_DIR)/button --top-module $(BUTTON_TOP) $^

$(BUILD_DIR)/envelope/V$(ENVELOPE_TOP): rtl/unsigned_divider.sv rtl/level_envelope_bank.sv sim/tb_level_envelope_bank.sv
	mkdir -p $(BUILD_DIR)/envelope
	$(VERILATOR) --binary --timing --assert -Wall -Wno-fatal \
		--Mdir $(BUILD_DIR)/envelope --top-module $(ENVELOPE_TOP) $^

$(BUILD_DIR)/lfo/V$(LFO_TOP): rtl/lfo_bank.sv sim/tb_lfo_bank.sv
	mkdir -p $(BUILD_DIR)/lfo
	$(VERILATOR) --binary --timing --assert -Wall -Wno-fatal \
		--Mdir $(BUILD_DIR)/lfo --top-module $(LFO_TOP) $^

$(BUILD_DIR)/axi/V$(AXI_TOP): rtl/deskband_timing_core.sv rtl/button_debounce.sv rtl/unsigned_divider.sv rtl/level_envelope_bank.sv rtl/lfo_bank.sv rtl/deskband_axi_peripheral.sv sim/tb_deskband_axi_peripheral.sv
	mkdir -p $(BUILD_DIR)/axi
	$(VERILATOR) --binary --timing --assert -Wall -Wno-fatal \
		--Mdir $(BUILD_DIR)/axi --top-module $(AXI_TOP) $^

lint:
	$(VERILATOR) --lint-only -Wall -Wno-fatal --top-module deskband_timing_core rtl/deskband_timing_core.sv
	$(VERILATOR) --lint-only -Wall -Wno-fatal --top-module button_debounce rtl/button_debounce.sv
	$(VERILATOR) --lint-only -Wall -Wno-fatal --top-module level_envelope_bank rtl/unsigned_divider.sv rtl/level_envelope_bank.sv
	$(VERILATOR) --lint-only -Wall -Wno-fatal --top-module lfo_bank rtl/lfo_bank.sv
	$(VERILATOR) --lint-only -Wall -Wno-fatal --top-module deskband_axi_peripheral \
		rtl/deskband_timing_core.sv rtl/button_debounce.sv rtl/unsigned_divider.sv rtl/level_envelope_bank.sv rtl/lfo_bank.sv rtl/deskband_axi_peripheral.sv

# Out-of-context synthesis for the exact Zynq-7020 device on the Zybo Z7-20.
# Run this from a shell where Vivado's settings64.sh has been sourced.
vivado-check:
	vivado -mode batch -nolog -nojournal -source vivado/check_rtl.tcl -tclargs deskband_timing_core
	vivado -mode batch -nolog -nojournal -source vivado/check_rtl.tcl -tclargs button_debounce
	vivado -mode batch -nolog -nojournal -source vivado/check_rtl.tcl -tclargs level_envelope_bank
	vivado -mode batch -nolog -nojournal -source vivado/check_rtl.tcl -tclargs lfo_bank
	vivado -mode batch -nolog -nojournal -source vivado/check_rtl.tcl -tclargs deskband_axi_peripheral

clean:
	rm -rf $(BUILD_DIR)
