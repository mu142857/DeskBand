`timescale 1ns/1ps

// DeskBand's deterministic musical timing core.
//
// `step_index` identifies the next step that will fire.  On each tick the
// core emits one timestamped, seven-bit event mask and then advances the
// position. Track patterns and configuration come from the AXI-Lite wrapper
// driven by the Zynq processing system.
module deskband_timing_core #(
    parameter int unsigned NUM_TRACKS = 7
) (
    input  logic clk,
    input  logic rst,

    input  logic run,
    input  logic transport_reset,
    input  logic [31:0] cycles_per_step,

    input  logic [NUM_TRACKS-1:0][15:0] patterns,

    // A request is retained until the requested boundary. A later request
    // replaces an earlier request that has not yet been applied.
    input  logic request_valid,
    input  logic [NUM_TRACKS-1:0] requested_mask,
    input  logic [1:0] request_quantization,

    output logic tick_pulse,
    output logic [3:0] step_index,
    output logic [1:0] beat_index,
    output logic [31:0] absolute_tick,
    output logic [NUM_TRACKS-1:0] applied_mask,
    output logic mask_applied_pulse,

    // One-cycle event record. `event_tick` and `event_step` describe the
// position that fired, while step_index advances on the same clock edge.
    output logic event_valid,
    output logic [31:0] event_tick,
    output logic [3:0] event_step,
    output logic [NUM_TRACKS-1:0] event_mask
);

    localparam logic [1:0] QUANTIZE_STEP = 2'd0;
    localparam logic [1:0] QUANTIZE_BEAT = 2'd1;
    localparam logic [1:0] QUANTIZE_BAR  = 2'd2;

    logic [31:0] cycle_count;
    logic pending_valid;
    logic [NUM_TRACKS-1:0] pending_mask;
    logic [1:0] pending_quantization;
    logic [NUM_TRACKS-1:0] pattern_mask;
    logic pending_boundary;
    logic [31:0] safe_cycles_per_step;

    assign safe_cycles_per_step = (cycles_per_step == 0) ? 32'd1 : cycles_per_step;
    assign beat_index = step_index[3:2];

    always_comb begin
        for (int unsigned track = 0; track < NUM_TRACKS; track++) begin
            pattern_mask[track] = patterns[track][step_index];
        end

        unique case (pending_quantization)
            QUANTIZE_STEP: pending_boundary = 1'b1;
            QUANTIZE_BEAT: pending_boundary = (step_index[1:0] == 2'd0);
            QUANTIZE_BAR:  pending_boundary = (step_index == 4'd0);
            default:       pending_boundary = 1'b0;
        endcase
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            cycle_count          <= 32'd0;
            step_index           <= 4'd0;
            absolute_tick        <= 32'd0;
            applied_mask         <= '0;
            pending_valid        <= 1'b0;
            pending_mask         <= '0;
            pending_quantization <= QUANTIZE_STEP;
            tick_pulse           <= 1'b0;
            mask_applied_pulse   <= 1'b0;
            event_valid          <= 1'b0;
            event_tick           <= 32'd0;
            event_step           <= 4'd0;
            event_mask           <= '0;
        end else begin
            tick_pulse         <= 1'b0;
            mask_applied_pulse <= 1'b0;
            event_valid        <= 1'b0;

            if (request_valid) begin
                pending_valid        <= 1'b1;
                pending_mask         <= requested_mask;
                pending_quantization <= request_quantization;
            end

            if (transport_reset) begin
                cycle_count   <= 32'd0;
                step_index    <= 4'd0;
                absolute_tick <= 32'd0;
                pending_valid <= 1'b0;
            end else if (!run) begin
                // Stopping resets the fractional phase but preserves the
                // musical position and applied configuration.
                cycle_count <= 32'd0;
            // Use >= so lowering the tempo divider while running cannot leave
            // the counter waiting for a 32-bit wraparound.
            end else if (cycle_count >= safe_cycles_per_step - 1'b1) begin
                cycle_count   <= 32'd0;
                tick_pulse    <= 1'b1;
                event_valid   <= 1'b1;
                event_tick    <= absolute_tick;
                event_step    <= step_index;
                absolute_tick <= absolute_tick + 1'b1;

                if (pending_valid && pending_boundary) begin
                    applied_mask       <= pending_mask;
                    mask_applied_pulse <= 1'b1;
                    pending_valid      <= 1'b0;
                    event_mask         <= pattern_mask & pending_mask;
                end else begin
                    event_mask <= pattern_mask & applied_mask;
                end

                if (step_index == 4'd15) begin
                    step_index <= 4'd0;
                end else begin
                    step_index <= step_index + 1'b1;
                end
            end else begin
                cycle_count <= cycle_count + 1'b1;
            end
        end
    end

endmodule
