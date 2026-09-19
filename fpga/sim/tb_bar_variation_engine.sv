`timescale 1ns/1ps

module tb_bar_variation_engine;
    localparam int NUM_TRACKS = 7;

    logic clk = 1'b0;
    logic rst = 1'b1;
    logic transport_reset = 1'b0;
    logic bar_advance_pulse = 1'b0;
    logic enable = 1'b1;
    logic [NUM_TRACKS-1:0][15:0] base_patterns;
    logic performance_mode = 1'b0;
    logic [2:0] selected_track = 3'd0;
    logic lock_button_pulse = 1'b0;
    logic energy_button_pulse = 1'b0;
    logic fill_button_pulse = 1'b0;
    logic eighth_button_pulse = 1'b0;
    logic [NUM_TRACKS-1:0][15:0] generated_patterns;
    logic [1:0] energy;
    logic energy_pending;
    logic [NUM_TRACKS-1:0] locked_mask;
    logic [NUM_TRACKS-1:0] lock_pending_mask;
    logic fill_pending;
    logic fill_active;
    logic eighth_only;
    logic eighth_pending;
    logic [15:0] random_state;
    logic [31:0] bar_index;

    always #5 clk <= ~clk;

    bar_variation_engine dut (.*);

    function automatic integer popcount(input logic [15:0] value);
        integer count = 0;
        for (integer bit_index = 0; bit_index < 16; bit_index++)
            count += integer'(value[bit_index]);
        return count;
    endfunction

    function automatic logic [15:0] candidate_grid(
        input integer track,
        input logic [15:0] written,
        input logic eighths
    );
        case (track)
            2, 4:    candidate_grid = written;
            5:       candidate_grid = eighths ? 16'h5554 : 16'h7776;
            default: candidate_grid = eighths ? 16'h5555 : 16'h7777;
        endcase
    endfunction

    task automatic pulse_bar;
        @(negedge clk); bar_advance_pulse = 1'b1;
        @(negedge clk); bar_advance_pulse = 1'b0;
    endtask

    task automatic pulse_lock;
        @(negedge clk); lock_button_pulse = 1'b1;
        @(negedge clk); lock_button_pulse = 1'b0;
    endtask

    task automatic pulse_energy;
        @(negedge clk); energy_button_pulse = 1'b1;
        @(negedge clk); energy_button_pulse = 1'b0;
    endtask

    task automatic pulse_fill;
        @(negedge clk); fill_button_pulse = 1'b1;
        @(negedge clk); fill_button_pulse = 1'b0;
    endtask

    task automatic pulse_eighth;
        @(negedge clk); eighth_button_pulse = 1'b1;
        @(negedge clk); eighth_button_pulse = 1'b0;
    endtask

    initial begin
        logic [15:0] locked_pattern;
        logic [15:0] first_random;

        base_patterns[0] = 16'h5551;
        base_patterns[1] = 16'h5555;
        base_patterns[2] = 16'h1041;
        base_patterns[3] = 16'h5555;
        base_patterns[4] = 16'h0001;
        base_patterns[5] = 16'h4444;
        base_patterns[6] = 16'h4924;

        repeat (3) @(negedge clk);
        rst = 1'b0;
        @(negedge clk);

        if (energy != 1 || bar_index != 0 || locked_mask != 0 || fill_active ||
            eighth_only || eighth_pending)
            $fatal(1, "variation reset state is incorrect");
        for (int track = 0; track < NUM_TRACKS; track++) begin
            if (generated_patterns[track] !== base_patterns[track])
                $fatal(1, "opening bar must preserve the base pattern");
        end

        first_random = random_state;
        pulse_bar();
        if (bar_index != 1 || random_state != 16'h359D || random_state == first_random)
            $fatal(1, "bar edge did not advance PRNG and bar index");
        if (generated_patterns[0] != 16'h5253 ||
            generated_patterns[1] != 16'h7357 ||
            generated_patterns[2] != 16'h1041 ||
            generated_patterns[3] != 16'h2105 ||
            generated_patterns[4] != 16'h0001 ||
            generated_patterns[5] != 16'h3566 ||
            generated_patterns[6] != 16'h7357)
            $fatal(1, "first generated bar changed from the reference model");
        for (int track = 0; track < NUM_TRACKS; track++) begin
            if ((generated_patterns[track] &
                 ~candidate_grid(track, base_patterns[track], 1'b0)) != 0)
                $fatal(1, "generator created a trigger outside the safe grid");
            if (base_patterns[track][0] && !generated_patterns[track][0])
                $fatal(1, "generator removed a protected downbeat");
        end
        if (((generated_patterns[3] & ~base_patterns[3]) |
             (generated_patterns[5] & ~base_patterns[5]) |
             (generated_patterns[6] & ~base_patterns[6])) == 0)
            $fatal(1, "generator did not create new rhythmic onsets");
        if (generated_patterns[2] != base_patterns[2] ||
            generated_patterns[4] != base_patterns[4])
            $fatal(1, "bass or strings anchor was modified");
        if (generated_patterns == base_patterns)
            $fatal(1, "normal energy did not produce any variation");

        // Buttons do nothing until the upper switch selects performance mode.
        selected_track = 3'd3;
        pulse_lock();
        if (lock_pending_mask != 0)
            $fatal(1, "mixer-mode button altered composition state");

        performance_mode = 1'b1;
        locked_pattern = generated_patterns[3];
        pulse_lock();
        if (!lock_pending_mask[3] || locked_mask[3])
            $fatal(1, "track lock was not queued");
        pulse_bar();
        if (!locked_mask[3] || lock_pending_mask != 0 ||
            generated_patterns[3] != locked_pattern)
            $fatal(1, "queued track lock did not commit at the bar edge");
        pulse_bar();
        if (generated_patterns[3] != locked_pattern)
            $fatal(1, "locked track changed on a later generated bar");

        // NORMAL -> FULL is queued and makes every unlocked track use its
        // complete safe candidate grid on the next bar.
        pulse_energy();
        if (!energy_pending || energy != 1)
            $fatal(1, "energy change was not queued");
        pulse_bar();
        if (energy != 2 || energy_pending)
            $fatal(1, "energy change did not commit at the bar edge");
        for (int track = 0; track < NUM_TRACKS; track++) begin
            if (track != 3 && generated_patterns[track] !=
                              candidate_grid(track, base_patterns[track], 1'b0))
                $fatal(1, "full energy did not restore all available hits");
        end

        // A fill is exactly one full-density bar, then automatic generation
        // resumes. FULL -> SPARSE is applied first so the return is observable.
        pulse_energy();
        pulse_bar();
        if (energy != 0)
            $fatal(1, "energy cycle did not wrap FULL to SPARSE");
        pulse_fill();
        if (!fill_pending || fill_active)
            $fatal(1, "fill was not queued");
        pulse_bar();
        if (!fill_active || fill_pending)
            $fatal(1, "fill did not activate for the queued bar");
        for (int track = 0; track < NUM_TRACKS; track++) begin
            if (track != 3 && generated_patterns[track] !=
                              candidate_grid(track, base_patterns[track], 1'b0))
                $fatal(1, "fill bar was not full density");
        end
        pulse_bar();
        if (fill_active)
            $fatal(1, "fill did not end after one bar");
        if (generated_patterns[0] == base_patterns[0] &&
            generated_patterns[1] == base_patterns[1] &&
            generated_patterns[5] == base_patterns[5] &&
            generated_patterns[6] == base_patterns[6])
            $fatal(1, "automatic sparse generation did not resume after fill");

        // BTN2 toggles eighth-note-only generation at the next bar boundary.
        pulse_eighth();
        if (!eighth_pending || eighth_only)
            $fatal(1, "eighth-note mode was not queued");
        pulse_bar();
        if (!eighth_only || eighth_pending)
            $fatal(1, "eighth-note mode did not commit on the bar edge");
        for (int track = 0; track < NUM_TRACKS; track++) begin
            if (track != 2 && track != 4 && (generated_patterns[track] & 16'haaaa) != 0)
                $fatal(1, "eighth-note mode emitted a sixteenth-note onset");
        end
        pulse_eighth();
        pulse_bar();
        if (eighth_only || eighth_pending)
            $fatal(1, "second BTN2 press did not restore mixed-grid mode");

        enable = 1'b0;
        @(negedge clk);
        for (int track = 0; track < NUM_TRACKS; track++) begin
            if (generated_patterns[track] != base_patterns[track])
                $fatal(1, "disabled generator did not bypass to base patterns");
        end

        $display("PASS: deterministic Euclidean bars, locks, energy, and fills");
        $finish;
    end

    initial begin
        #100_000;
        $fatal(1, "simulation watchdog expired");
    end
endmodule
