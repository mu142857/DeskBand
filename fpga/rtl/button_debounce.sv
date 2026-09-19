`timescale 1ns/1ps

// Synchronize one active-high physical button, reject contact bounce, and
// emit exactly one clock-wide pulse for each accepted press/release.
module button_debounce #(
    parameter int unsigned STABLE_CYCLES = 1_000_000,
    parameter int unsigned COUNTER_WIDTH = $clog2(STABLE_CYCLES + 1)
) (
    input  logic clk,
    input  logic rst,
    input  logic raw_button,
    output logic button_state,
    output logic pressed_pulse,
    output logic released_pulse
);

    logic sync_meta;
    logic sync_button;
    logic [COUNTER_WIDTH-1:0] stable_count;
    localparam logic [COUNTER_WIDTH-1:0] STABLE_LAST = COUNTER_WIDTH'(STABLE_CYCLES - 1);

    initial begin
        if (STABLE_CYCLES < 1) $error("STABLE_CYCLES must be at least one");
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            sync_meta     <= 1'b0;
            sync_button   <= 1'b0;
            button_state  <= 1'b0;
            stable_count  <= '0;
            pressed_pulse <= 1'b0;
            released_pulse <= 1'b0;
        end else begin
            sync_meta   <= raw_button;
            sync_button <= sync_meta;
            pressed_pulse  <= 1'b0;
            released_pulse <= 1'b0;

            if (sync_button == button_state) begin
                stable_count <= '0;
            end else if (stable_count == STABLE_LAST) begin
                button_state <= sync_button;
                stable_count <= '0;
                if (sync_button)
                    pressed_pulse <= 1'b1;
                else
                    released_pulse <= 1'b1;
            end else begin
                stable_count <= stable_count + 1'b1;
            end
        end
    end

endmodule
