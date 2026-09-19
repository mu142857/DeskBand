`timescale 1ns/1ps

module tb_lfo_bank;
    logic clk = 0, rst = 1, update_pulse = 0, command_valid = 0;
    logic [2:0] command_track;
    logic command_enable, command_reset_phase;
    logic [7:0] command_depth;
    logic [23:0] command_increment;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [6:0][7:0] values;
    /* verilator lint_on UNUSEDSIGNAL */
    logic [6:0] enabled;
    always #5 clk = ~clk;

    lfo_bank dut (.*);

    task automatic update;
        update_pulse = 1; @(posedge clk); #1; update_pulse = 0;
    endtask

    task automatic configure(input logic [2:0] track, input logic enable,
                             input logic reset_phase, input logic [7:0] new_depth,
                             input logic [23:0] new_increment);
        command_track = track; command_enable = enable; command_reset_phase = reset_phase;
        command_depth = new_depth; command_increment = new_increment; command_valid = 1;
        @(posedge clk); #1; command_valid = 0;
    endtask

    initial begin
        repeat (3) @(posedge clk); #1; rst = 0;
        configure(0, 1, 1, 8'hff, 24'h400000);
        if (enabled != 7'h01 || values[0] != 0) $fatal(1, "LFO configuration failed");
        update(); if (values[0] != 8'd127) $fatal(1, "quarter-cycle value incorrect");
        update(); if (values[0] != 8'd254) $fatal(1, "peak value incorrect");
        update(); if (values[0] != 8'd126) $fatal(1, "falling value incorrect");
        update(); if (values[0] != 0) $fatal(1, "wrap value incorrect");

        configure(3, 1, 1, 8'h80, 24'h800000);
        update();
        if (values[3] != 8'd127 || values[0] != 8'd127)
            $fatal(1, "parallel LFO update failed");
        configure(0, 0, 0, 8'hff, 24'h400000);
        update();
        if (enabled[0] || values[0] != 8'd127) $fatal(1, "disabled LFO phase moved");
        if (values[1] != 0 || values[2] != 0 || values[4] != 0)
            $fatal(1, "unconfigured lane moved");
        $display("PASS: seven parallel deterministic triangle LFOs");
        $finish;
    end
endmodule
