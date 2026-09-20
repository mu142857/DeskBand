`timescale 1ns/1ps

module tb_wavelens_timing_core;
    localparam int NUM_TRACKS = 7;
    localparam int STEPS_PER_BAR = 16;
    localparam logic [1:0] Q_STEP = 2'd0;
    localparam logic [1:0] Q_BEAT = 2'd1;
    localparam logic [1:0] Q_BAR  = 2'd2;

    logic clk = 1'b0;
    logic rst = 1'b1;
    logic run = 1'b0;
    logic transport_reset = 1'b0;
    logic [31:0] cycles_per_step = 32'd8;
    logic [NUM_TRACKS-1:0][STEPS_PER_BAR-1:0] patterns = '0;
    logic request_valid = 1'b0;
    logic [NUM_TRACKS-1:0] requested_mask = '0;
    logic [1:0] request_quantization = Q_STEP;
    logic tick_pulse;
    logic bar_advance_pulse;
    logic [3:0] step_index;
    logic [1:0] beat_index;
    logic [31:0] absolute_tick;
    logic [NUM_TRACKS-1:0] applied_mask;
    logic mask_applied_pulse;
    logic event_valid;
    logic [31:0] event_tick;
    logic [3:0] event_step;
    logic [NUM_TRACKS-1:0] event_mask;

    always #5 clk <= ~clk;

    always @(negedge clk) begin
        if (!rst && beat_index !== step_index[3:2])
            $fatal(1, "beat_index does not match step_index");
    end

    wavelens_timing_core #(
        .NUM_TRACKS(NUM_TRACKS)
    ) dut (.*);

    task automatic request_mask(input logic [NUM_TRACKS-1:0] mask,
                                input logic [1:0] quantization);
        @(negedge clk);
        requested_mask = mask;
        request_quantization = quantization;
        request_valid = 1'b1;
        @(negedge clk);
        request_valid = 1'b0;
    endtask

    task automatic next_event(output logic [31:0] tick,
                              output logic [3:0] step,
                              output logic [NUM_TRACKS-1:0] mask);
        do @(negedge clk); while (!event_valid);
        if (!tick_pulse) $fatal(1, "event_valid without tick_pulse");
        if (event_step == 4'd15 && !bar_advance_pulse)
            $fatal(1, "step 15 did not produce a registered bar pulse");
        if (event_step != 4'd15 && bar_advance_pulse)
            $fatal(1, "bar pulse occurred outside step 15");
        tick = event_tick;
        step = event_step;
        mask = event_mask;
    endtask

    task automatic expect_event(input logic [31:0] wanted_tick,
                                input logic [3:0] wanted_step,
                                input logic [NUM_TRACKS-1:0] wanted_mask);
        logic [31:0] got_tick;
        logic [3:0] got_step;
        logic [NUM_TRACKS-1:0] got_mask;
        next_event(got_tick, got_step, got_mask);
        if (got_tick !== wanted_tick || got_step !== wanted_step || got_mask !== wanted_mask) begin
            $display("wanted tick=%0d step=%0d mask=%07b; got tick=%0d step=%0d mask=%07b",
                     wanted_tick, wanted_step, wanted_mask, got_tick, got_step, got_mask);
            $fatal(1, "event mismatch");
        end
    endtask

    function automatic logic [NUM_TRACKS-1:0] expected_pattern(input logic [3:0] step,
                                                               input logic [NUM_TRACKS-1:0] mask);
        logic [NUM_TRACKS-1:0] result;
        for (int track = 0; track < NUM_TRACKS; track++) begin
            result[track] = patterns[track][step] & mask[track];
        end
        return result;
    endfunction

    initial begin
        logic [31:0] held_tick;
        logic [NUM_TRACKS-1:0] mask_a = 7'b0000111;
        logic [NUM_TRACKS-1:0] mask_b = 7'b0011000;
        logic [NUM_TRACKS-1:0] mask_c = 7'b1000100;

        // Track 0: quarter notes; track 1: eighth notes; track 2: 3-3-2 accents.
        patterns[0] = 16'h1111;
        patterns[1] = 16'h5555;
        patterns[2] = 16'h1041;
        // Tracks 3..6 deliberately overlap on step 0 to prove parallel firing.
        patterns[3] = 16'h0001;
        patterns[4] = 16'h0001;
        patterns[5] = 16'h8000;
        patterns[6] = 16'hFFFF;

        repeat (3) @(negedge clk);
        rst = 1'b0;

        // A next-step request made before START applies on the first event.
        request_mask(mask_a, Q_STEP);
        run = 1'b1;
        for (int step = 0; step < 16; step++) begin
            expect_event(step, step[3:0], expected_pattern(step[3:0], mask_a));
        end

        // Request a bar-quantized mask after step 0. It must remain pending
        // through the rest of this bar and apply precisely at the next step 0.
        expect_event(16, 0, expected_pattern(0, mask_a));
        request_mask(mask_b, Q_BAR);
        for (int tick = 17; tick < 32; tick++) begin
            expect_event(tick, tick[3:0], expected_pattern(tick[3:0], mask_a));
        end
        expect_event(32, 0, expected_pattern(0, mask_b));
        if (applied_mask !== mask_b)
            $fatal(1, "bar-quantized mask was not committed");
        if (!mask_applied_pulse)
            $fatal(1, "bar commit did not emit mask_applied_pulse");

        // A beat-quantized request after step 1 applies at step 4.
        expect_event(33, 1, expected_pattern(1, mask_b));
        request_mask(mask_c, Q_BEAT);
        expect_event(34, 2, expected_pattern(2, mask_b));
        expect_event(35, 3, expected_pattern(3, mask_b));
        expect_event(36, 4, expected_pattern(4, mask_c));
        if (!mask_applied_pulse)
            $fatal(1, "beat commit did not emit mask_applied_pulse");

        // STOP holds musical position and produces no event. Restart begins a
        // full step interval later rather than emitting a shortened step.
        @(negedge clk);
        run = 1'b0;
        held_tick = absolute_tick;
        repeat (20) begin
            @(negedge clk);
            if (event_valid) $fatal(1, "event emitted while stopped");
            if (absolute_tick !== held_tick) $fatal(1, "tick advanced while stopped");
        end
        run = 1'b1;
        expect_event(37, 5, expected_pattern(5, mask_c));

        // Transport reset returns to tick/step zero but intentionally retains
        // the current mix mask and patterns.
        @(negedge clk);
        transport_reset = 1'b1;
        @(negedge clk);
        transport_reset = 1'b0;
        if (absolute_tick !== 0 || step_index !== 0)
            $fatal(1, "transport reset did not reset position");
        expect_event(0, 0, expected_pattern(0, mask_c));

        // Lowering the divider below the counter's current value must produce
        // a prompt tick, not wait for the 32-bit counter to wrap around.
        repeat (5) @(negedge clk);
        cycles_per_step = 32'd3;
        expect_event(1, 1, expected_pattern(1, mask_c));

        $display("PASS: timing, patterns, quantization, stop, and reset");
        $finish;
    end

    initial begin
        #100_000;
        $fatal(1, "simulation watchdog expired");
    end

endmodule
