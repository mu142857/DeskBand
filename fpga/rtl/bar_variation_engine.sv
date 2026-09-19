`timescale 1ns/1ps

// Deterministic, musically constrained next-bar generator.
//
// A 16-bit Fibonacci LFSR supplies repeatable variation.  For every track an
// modulo-four phase accumulator distributes 1/2, 3/4, or all hits across only
// the set bits in its base pattern (the same integer technique used by
// Euclidean / Bresenham rhythm generators). Step zero is protected whenever
// present. Restricting density to musically useful quarters keeps the circuit
// shallow enough for the 100 MHz fabric clock; no divider is synthesized.
// Energy, track-lock and fill requests are committed together at a bar edge.
module bar_variation_engine #(
    parameter int unsigned NUM_TRACKS = 7,
    parameter logic [15:0] RESET_SEED = 16'h1ACE
) (
    input  logic clk,
    input  logic rst,
    input  logic transport_reset,
    input  logic bar_advance_pulse,
    input  logic enable,
    input  logic [NUM_TRACKS-1:0][15:0] base_patterns,

    input  logic performance_mode,
    input  logic [2:0] selected_track,
    input  logic lock_button_pulse,
    input  logic energy_button_pulse,
    input  logic fill_button_pulse,

    output logic [NUM_TRACKS-1:0][15:0] generated_patterns,
    output logic [1:0] energy,
    output logic energy_pending,
    output logic [NUM_TRACKS-1:0] locked_mask,
    output logic [NUM_TRACKS-1:0] lock_pending_mask,
    output logic fill_pending,
    output logic fill_active,
    output logic [15:0] random_state,
    output logic [31:0] bar_index
);

    localparam logic [1:0] ENERGY_SPARSE = 2'd0;
    localparam logic [1:0] ENERGY_NORMAL = 2'd1;
    localparam logic [1:0] ENERGY_FULL   = 2'd2;

    logic [1:0] requested_energy;
    logic [NUM_TRACKS-1:0][15:0] locked_patterns;

    function automatic logic [15:0] next_lfsr(input logic [15:0] state);
        logic feedback;
        begin
            // x^16 + x^14 + x^13 + x^11 + 1, maximal length for nonzero seed.
            feedback = state[15] ^ state[13] ^ state[12] ^ state[10];
            next_lfsr = {state[14:0], feedback};
            if (next_lfsr == 16'd0)
                next_lfsr = RESET_SEED;
        end
    endfunction

    function automatic logic [15:0] euclidean_subset(
        input logic [15:0] candidates,
        input logic [2:0] numerator,
        input logic [1:0] phase
    );
        logic [15:0] result;
        logic [2:0] accumulator;
        begin
            result = 16'd0;
            accumulator = {1'b0, phase};
            for (integer step = 0; step < 16; step++) begin
                if (candidates[step]) begin
                    unique case (numerator)
                        3'd2: result[step] = !accumulator[0];
                        3'd3: result[step] = accumulator[1:0] != 2'd3;
                        default: result[step] = 1'b1;
                    endcase
                    accumulator = accumulator + 1'b1;
                end
            end
            // Never lose the strongest musical landmark.
            result[0] = candidates[0];
            return result;
        end
    endfunction

    function automatic logic [1:0] next_energy(input logic [1:0] current);
        unique case (current)
            ENERGY_SPARSE: next_energy = ENERGY_NORMAL;
            ENERGY_NORMAL: next_energy = ENERGY_FULL;
            default:       next_energy = ENERGY_SPARSE;
        endcase
    endfunction

    always_comb begin
        for (int unsigned track = 0; track < NUM_TRACKS; track++) begin
            logic [2:0] numerator;
            logic random_dense;

            random_dense = random_state[track] ^ random_state[track + 7];

            unique case (energy)
                ENERGY_SPARSE: numerator = random_dense ? 3'd3 : 3'd2; // 1/2 or 3/4
                ENERGY_NORMAL: numerator = random_dense ? 3'd4 : 3'd3; // 3/4 or full
                default:       numerator = 3'd4;                        // full
            endcase

            // Bass is the harmonic anchor and strings have only a downbeat;
            // keep both stable while the other five parts breathe around them.
            if (track == 2 || track == 4 || fill_active || bar_index == 0)
                numerator = 3'd4;

            generated_patterns[track] = euclidean_subset(
                base_patterns[track], numerator,
                random_state[(track * 2) +: 2]);

            if (!enable)
                generated_patterns[track] = base_patterns[track];
            else if (locked_mask[track])
                generated_patterns[track] = locked_patterns[track];
        end
    end

    always_ff @(posedge clk) begin
        if (rst || transport_reset) begin
            energy           <= ENERGY_NORMAL;
            requested_energy <= ENERGY_NORMAL;
            energy_pending   <= 1'b0;
            locked_mask      <= '0;
            lock_pending_mask <= '0;
            locked_patterns  <= '0;
            fill_pending     <= 1'b0;
            fill_active      <= 1'b0;
            random_state     <= RESET_SEED;
            bar_index        <= 32'd0;
        end else begin
            if (performance_mode && lock_button_pulse &&
                selected_track < 3'(NUM_TRACKS)) begin
                lock_pending_mask[selected_track] <=
                    ~lock_pending_mask[selected_track];
                if (!locked_mask[selected_track])
                    locked_patterns[selected_track] <= generated_patterns[selected_track];
            end

            if (performance_mode && energy_button_pulse) begin
                requested_energy <= next_energy(
                    energy_pending ? requested_energy : energy);
                energy_pending <= 1'b1;
            end

            if (performance_mode && fill_button_pulse)
                fill_pending <= 1'b1;

            if (bar_advance_pulse) begin
                random_state <= next_lfsr(random_state);
                bar_index <= bar_index + 1'b1;

                if (energy_pending) begin
                    energy <= requested_energy;
                    energy_pending <= 1'b0;
                end

                locked_mask <= locked_mask ^ lock_pending_mask;
                lock_pending_mask <= '0;

                fill_active <= fill_pending;
                fill_pending <= 1'b0;
            end
        end
    end

endmodule
