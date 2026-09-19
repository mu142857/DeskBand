`timescale 1ns/1ps

// Seven independent linear level envelopes. Levels are exposed as unsigned
// 8-bit values while each lane retains sixteen fractional bits internally.
// A single shared command divider computes the slope only when a new envelope
// is loaded; all active lanes then advance concurrently on update_pulse.
module level_envelope_bank #(
    parameter int unsigned NUM_TRACKS = 7
) (
    input  logic clk,
    input  logic rst,
    input  logic update_pulse,

    input  logic command_valid,
    input  logic [2:0] command_track,
    input  logic [7:0] command_target,
    input  logic [15:0] command_duration,

    output logic [NUM_TRACKS-1:0][7:0] levels,
    output logic [NUM_TRACKS-1:0] active,
    output logic command_ready
);

    logic signed [24:0] level_q [0:NUM_TRACKS-1];
    logic signed [24:0] target_q [0:NUM_TRACKS-1];
    logic signed [24:0] slope_q [0:NUM_TRACKS-1];
    logic [15:0] remaining [0:NUM_TRACKS-1];

    logic command_track_valid;
    logic signed [24:0] command_target_q;
    logic signed [24:0] command_delta_q;
    localparam logic [2:0] TRACK_COUNT = 3'(NUM_TRACKS);

    logic divider_start;
    logic divider_busy;
    logic divider_done;
    logic [24:0] divider_numerator;
    logic [15:0] divider_denominator;
    logic [24:0] divider_quotient;
    logic division_pending;
    logic pending_negative;
    logic [2:0] pending_track;
    logic signed [24:0] pending_target_q;
    logic [15:0] pending_duration;

    assign command_track_valid = command_track < TRACK_COUNT;
    assign command_target_q = $signed({1'b0, command_target, 16'd0});
    assign command_delta_q = command_track_valid
                           ? command_target_q - level_q[command_track]
                           : 25'sd0;
    assign command_ready = !division_pending && !divider_busy;

    unsigned_divider divider (
        .clk(clk),
        .rst(rst),
        .start(divider_start),
        .numerator(divider_numerator),
        .denominator(divider_denominator),
        .busy(divider_busy),
        .done(divider_done),
        .quotient(divider_quotient)
    );

    generate
        for (genvar track = 0; track < NUM_TRACKS; track++) begin : gen_outputs
            assign levels[track] = level_q[track][23:16];
            assign active[track] = (remaining[track] != 0);
        end
    endgenerate

    always_ff @(posedge clk) begin
        if (rst) begin
            for (int unsigned track = 0; track < NUM_TRACKS; track++) begin
                level_q[track]  <= $signed({1'b0, 8'hFF, 16'd0});
                target_q[track] <= $signed({1'b0, 8'hFF, 16'd0});
                slope_q[track]  <= 25'sd0;
                remaining[track] <= 16'd0;
            end
            divider_start       <= 1'b0;
            divider_numerator   <= 25'd0;
            divider_denominator <= 16'd1;
            division_pending    <= 1'b0;
            pending_negative    <= 1'b0;
            pending_track       <= 3'd0;
            pending_target_q    <= 25'sd0;
            pending_duration    <= 16'd0;
        end else begin
            divider_start <= 1'b0;

            if (update_pulse) begin
                for (int unsigned track = 0; track < NUM_TRACKS; track++) begin
                    if (remaining[track] > 1) begin
                        level_q[track] <= level_q[track] + slope_q[track];
                        remaining[track] <= remaining[track] - 1'b1;
                    end else if (remaining[track] == 1) begin
                        // Force the exact endpoint to remove fixed-point
                        // division remainder and accumulated roundoff.
                        level_q[track] <= target_q[track];
                        remaining[track] <= 16'd0;
                    end
                end
            end

            // Divider completion wins over an update for its selected lane.
            if (divider_done && division_pending) begin
                target_q[pending_track] <= pending_target_q;
                slope_q[pending_track] <= pending_negative
                                        ? -$signed(divider_quotient)
                                        : $signed(divider_quotient);
                remaining[pending_track] <= pending_duration;
                division_pending <= 1'b0;
            end

            // Only one slope calculation is in flight. Software can read
            // command_ready and retry instead of silently losing a command.
            if (command_valid && command_track_valid && command_ready) begin
                target_q[command_track] <= command_target_q;
                if (command_duration == 0) begin
                    level_q[command_track] <= command_target_q;
                    slope_q[command_track] <= 25'sd0;
                    remaining[command_track] <= 16'd0;
                end else begin
                    divider_numerator <= command_delta_q[24]
                                       ? $unsigned(-command_delta_q)
                                       : $unsigned(command_delta_q);
                    divider_denominator <= command_duration;
                    divider_start <= 1'b1;
                    division_pending <= 1'b1;
                    pending_negative <= command_delta_q[24];
                    pending_track <= command_track;
                    pending_target_q <= command_target_q;
                    pending_duration <= command_duration;
                end
            end
        end
    end

endmodule
