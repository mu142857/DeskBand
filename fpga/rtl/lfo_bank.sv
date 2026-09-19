`timescale 1ns/1ps

// Seven independent triangle LFOs. Phase advances on the shared 100 Hz
// control update, so all tracks remain deterministic and phase coherent.
module lfo_bank (
    input  logic clk,
    input  logic rst,
    input  logic update_pulse,
    input  logic command_valid,
    input  logic [2:0] command_track,
    input  logic command_enable,
    input  logic command_reset_phase,
    input  logic [7:0] command_depth,
    input  logic [23:0] command_increment,
    output logic [6:0][7:0] values,
    output logic [6:0] enabled
);
    logic [6:0][23:0] phase;
    logic [6:0][23:0] increment;
    logic [6:0][7:0] depth;

    function automatic logic [7:0] scale_triangle(
        /* verilator lint_off UNUSEDSIGNAL */
        input logic [23:0] phase_value,
        input logic [7:0] depth_value
    );
        logic [7:0] triangle;
        logic [15:0] product;
        /* verilator lint_on UNUSEDSIGNAL */
        triangle = phase_value[23] ? ~phase_value[22:15] : phase_value[22:15];
        product = triangle * depth_value;
        return product[15:8];
    endfunction

    always_ff @(posedge clk) begin
        if (rst) begin
            phase <= '0;
            increment <= '0;
            depth <= '0;
            values <= '0;
            enabled <= '0;
        end else begin
            if (command_valid && command_track < 7) begin
                increment[command_track] <= command_increment;
                depth[command_track] <= command_depth;
                enabled[command_track] <= command_enable;
                if (command_reset_phase) begin
                    phase[command_track] <= '0;
                    values[command_track] <= '0;
                end else begin
                    values[command_track] <= scale_triangle(
                        phase[command_track], command_depth
                    );
                end
            end else if (update_pulse) begin
                for (int unsigned track = 0; track < 7; track++) begin
                    if (enabled[track]) begin
                        phase[track] <= phase[track] + increment[track];
                        values[track] <= scale_triangle(
                            phase[track] + increment[track], depth[track]
                        );
                    end
                end
            end
        end
    end
endmodule
