`timescale 1ns/1ps

module tb_button_debounce;
    localparam int STABLE_CYCLES = 4;

    logic clk = 1'b0;
    logic rst = 1'b1;
    logic raw_button = 1'b0;
    logic button_state;
    logic pressed_pulse;
    logic released_pulse;
    int press_count = 0;
    int release_count = 0;

    always #5 clk <= ~clk;

    button_debounce #(
        .STABLE_CYCLES(STABLE_CYCLES)
    ) dut (.*);

    // Testbench scoreboards intentionally update immediately at the sampling
    // edge so checks in the stimulus process see the new count.
    /* verilator lint_off BLKSEQ */
    always @(negedge clk) begin
        if (pressed_pulse) press_count++;
        if (released_pulse) release_count++;
        if (pressed_pulse && released_pulse)
            $fatal(1, "press and release pulses asserted together");
    end
    /* verilator lint_on BLKSEQ */

    task automatic hold_raw(input logic value, input int cycles);
        raw_button = value;
        repeat (cycles) @(negedge clk);
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst = 1'b0;

        // Contact bounce and short glitches must not become a press.
        hold_raw(1'b1, 1);
        hold_raw(1'b0, 1);
        hold_raw(1'b1, 2);
        hold_raw(1'b0, STABLE_CYCLES + 3);
        if (press_count != 0 || button_state != 0)
            $fatal(1, "bounce was incorrectly accepted as a press");

        // A stable press produces one pulse, regardless of how long it is held.
        hold_raw(1'b1, STABLE_CYCLES + 3);
        if (press_count != 1 || button_state != 1)
            $fatal(1, "stable press was not accepted exactly once");
        hold_raw(1'b1, 12);
        if (press_count != 1)
            $fatal(1, "held button generated repeated presses");

        // A bouncing release is also ignored until it remains stable.
        hold_raw(1'b0, 1);
        hold_raw(1'b1, 1);
        hold_raw(1'b0, 2);
        hold_raw(1'b1, STABLE_CYCLES + 3);
        if (release_count != 0 || button_state != 1)
            $fatal(1, "release bounce changed the accepted state");
        hold_raw(1'b0, STABLE_CYCLES + 3);
        if (release_count != 1 || button_state != 0)
            $fatal(1, "stable release was not accepted exactly once");

        $display("PASS: button synchronization, debounce, and one-shot pulses");
        $finish;
    end

endmodule
