`timescale 1ns/1ps

module tb_level_envelope_bank;
    localparam int NUM_TRACKS = 7;

    logic clk = 1'b0;
    logic rst = 1'b1;
    logic update_pulse = 1'b0;
    logic command_valid = 1'b0;
    logic [2:0] command_track = 0;
    logic [7:0] command_target = 0;
    logic [15:0] command_duration = 0;
    logic [NUM_TRACKS-1:0][7:0] levels;
    logic [NUM_TRACKS-1:0] active;
    logic command_ready;

    always #5 clk <= ~clk;

    level_envelope_bank #(.NUM_TRACKS(NUM_TRACKS)) dut (.*);

    task automatic command(input logic [2:0] track,
                           input logic [7:0] target,
                           input logic [15:0] duration);
        @(negedge clk);
        command_track = track;
        command_target = target;
        command_duration = duration;
        command_valid = 1'b1;
        @(negedge clk);
        command_valid = 1'b0;
        if (duration != 0) begin
            do @(negedge clk); while (!command_ready);
        end
    endtask

    task automatic update;
        @(negedge clk);
        update_pulse = 1'b1;
        @(negedge clk);
        update_pulse = 1'b0;
    endtask

    initial begin
        logic [7:0] previous;

        repeat (3) @(negedge clk);
        rst = 1'b0;
        @(negedge clk);
        for (int track = 0; track < NUM_TRACKS; track++) begin
            if (levels[track] != 8'hFF || active[track])
                $fatal(1, "envelope reset state is incorrect");
        end

        // Four updates must reach the exact endpoint without increasing.
        command(0, 8'd0, 16'd4);
        previous = levels[0];
        for (int i = 0; i < 4; i++) begin
            update();
            if (levels[0] > previous) $fatal(1, "fade-down is not monotonic");
            previous = levels[0];
        end
        if (levels[0] != 0 || active[0])
            $fatal(1, "fade-down did not finish exactly at zero");

        // Two lanes must advance independently and concurrently.
        command(0, 8'd200, 16'd5);
        command(3, 8'd55, 16'd5);
        for (int i = 0; i < 5; i++) update();
        if (levels[0] != 200 || levels[3] != 55 || active[0] || active[3])
            $fatal(1, "parallel envelopes did not reach exact endpoints");
        for (int track = 1; track < NUM_TRACKS; track++) begin
            if (track != 3 && levels[track] != 255)
                $fatal(1, "an envelope modified another lane");
        end

        // A new command interrupts a running ramp from its current value.
        command(2, 8'd0, 16'd20);
        repeat (4) update();
        command(2, 8'd180, 16'd3);
        repeat (3) update();
        if (levels[2] != 180 || active[2])
            $fatal(1, "replacement envelope did not win");

        // Duration zero is an immediate, exact assignment.
        command(6, 8'd17, 16'd0);
        if (levels[6] != 17 || active[6])
            $fatal(1, "zero-duration command was not immediate");

        // Invalid track 7 must be ignored.
        command(7, 8'd0, 16'd1);
        update();
        if (levels[6] != 17)
            $fatal(1, "invalid track command corrupted a valid lane");

        $display("PASS: seven parallel fixed-point level envelopes");
        $finish;
    end

    initial begin
        #100_000;
        $fatal(1, "simulation watchdog expired");
    end

endmodule
