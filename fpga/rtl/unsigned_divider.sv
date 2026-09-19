`timescale 1ns/1ps

// Iterative unsigned restoring divider: one quotient bit per clock. This is
// used only when an envelope command is loaded, avoiding a long combinational
// divide path in the 100 MHz control domain.
module unsigned_divider #(
    parameter int unsigned NUMERATOR_WIDTH = 25,
    parameter int unsigned DENOMINATOR_WIDTH = 16,
    parameter int unsigned COUNT_WIDTH = $clog2(NUMERATOR_WIDTH + 1)
) (
    input  logic clk,
    input  logic rst,
    input  logic start,
    input  logic [NUMERATOR_WIDTH-1:0] numerator,
    input  logic [DENOMINATOR_WIDTH-1:0] denominator,
    output logic busy,
    output logic done,
    output logic [NUMERATOR_WIDTH-1:0] quotient
);

    logic [NUMERATOR_WIDTH-1:0] numerator_shift;
    logic [DENOMINATOR_WIDTH-1:0] remainder;
    logic [COUNT_WIDTH-1:0] iterations_left;
    logic [DENOMINATOR_WIDTH:0] shifted_remainder;
    logic [DENOMINATOR_WIDTH-1:0] next_remainder;
    logic [NUMERATOR_WIDTH-1:0] next_quotient;
    logic quotient_bit;

    always_comb begin
        shifted_remainder = {remainder, numerator_shift[NUMERATOR_WIDTH-1]};
        quotient_bit = shifted_remainder >= {1'b0, denominator};
        next_remainder = quotient_bit
                       ? shifted_remainder[DENOMINATOR_WIDTH-1:0] - denominator
                       : shifted_remainder[DENOMINATOR_WIDTH-1:0];
        next_quotient = {quotient[NUMERATOR_WIDTH-2:0], quotient_bit};
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            busy             <= 1'b0;
            done             <= 1'b0;
            quotient         <= '0;
            numerator_shift  <= '0;
            remainder        <= '0;
            iterations_left  <= '0;
        end else begin
            done <= 1'b0;
            if (start && !busy) begin
                if (denominator == 0) begin
                    quotient <= '0;
                    done <= 1'b1;
                end else begin
                    busy            <= 1'b1;
                    quotient        <= '0;
                    numerator_shift <= numerator;
                    remainder       <= '0;
                    iterations_left <= COUNT_WIDTH'(NUMERATOR_WIDTH);
                end
            end else if (busy) begin
                numerator_shift <= {numerator_shift[NUMERATOR_WIDTH-2:0], 1'b0};
                remainder <= next_remainder;
                quotient <= next_quotient;
                iterations_left <= iterations_left - 1'b1;
                if (iterations_left == 1) begin
                    busy <= 1'b0;
                    done <= 1'b1;
                end
            end
        end
    end

endmodule
