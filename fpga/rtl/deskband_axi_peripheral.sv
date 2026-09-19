`timescale 1ns/1ps

// AXI4-Lite peripheral wrapping DeskBand's deterministic timing core.
//
// This block is intended to connect directly to an AXI GP master from the
// Zynq-7000 processing system. It deliberately keeps the UART in PS software:
// the PL owns musical time and buffering, while the ARM owns packet parsing.
module deskband_axi_peripheral #(
    parameter int unsigned AXI_ADDR_WIDTH = 8,
    parameter int unsigned FIFO_DEPTH = 16,
    parameter int unsigned BUTTON_STABLE_CYCLES = 1_000_000,
    parameter int unsigned CONTROL_UPDATE_CYCLES = 1_000_000
) (
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 S_AXI_ACLK CLK",
       X_INTERFACE_PARAMETER = "XIL_INTERFACENAME S_AXI_ACLK, ASSOCIATED_BUSIF S_AXI, ASSOCIATED_RESET s_axi_aresetn, FREQ_HZ 100000000" *)
    input  logic s_axi_aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 S_AXI_ARESETN RST",
       X_INTERFACE_PARAMETER = "XIL_INTERFACENAME S_AXI_ARESETN, POLARITY ACTIVE_LOW" *)
    input  logic s_axi_aresetn,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWADDR",
       X_INTERFACE_PARAMETER = "XIL_INTERFACENAME S_AXI, PROTOCOL AXI4LITE, DATA_WIDTH 32, ADDR_WIDTH 8, READ_WRITE_MODE READ_WRITE" *)
    input  logic [AXI_ADDR_WIDTH-1:0] s_axi_awaddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWVALID" *)
    input  logic s_axi_awvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWREADY" *)
    output logic s_axi_awready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WDATA" *)
    input  logic [31:0] s_axi_wdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WSTRB" *)
    input  logic [3:0] s_axi_wstrb,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WVALID" *)
    input  logic s_axi_wvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WREADY" *)
    output logic s_axi_wready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BRESP" *)
    output logic [1:0] s_axi_bresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BVALID" *)
    output logic s_axi_bvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BREADY" *)
    input  logic s_axi_bready,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARADDR" *)
    input  logic [AXI_ADDR_WIDTH-1:0] s_axi_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARVALID" *)
    input  logic s_axi_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARREADY" *)
    output logic s_axi_arready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RDATA" *)
    output logic [31:0] s_axi_rdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RRESP" *)
    output logic [1:0] s_axi_rresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RVALID" *)
    output logic s_axi_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RREADY" *)
    input  logic s_axi_rready,

    input  logic [3:0] raw_buttons,
    input  logic [3:0] switches,
    output logic [3:0] leds
);

    localparam logic [31:0] ID_VERSION = 32'h4442_0100;
    localparam int unsigned FIFO_PTR_WIDTH = $clog2(FIFO_DEPTH);
    localparam int unsigned FIFO_COUNT_WIDTH = $clog2(FIFO_DEPTH + 1);
    localparam logic [FIFO_COUNT_WIDTH-1:0] FIFO_CAPACITY = FIFO_COUNT_WIDTH'(FIFO_DEPTH);
    localparam int unsigned CONTROL_COUNTER_WIDTH = $clog2(CONTROL_UPDATE_CYCLES + 1);
    localparam logic [CONTROL_COUNTER_WIDTH-1:0] CONTROL_LAST =
        CONTROL_COUNTER_WIDTH'(CONTROL_UPDATE_CYCLES - 1);

    localparam logic [7:0] REG_ID_VERSION       = 8'h00;
    localparam logic [7:0] REG_CONTROL          = 8'h04;
    localparam logic [7:0] REG_CYCLES_PER_STEP  = 8'h08;
    localparam logic [7:0] REG_ABSOLUTE_TICK    = 8'h0C;
    localparam logic [7:0] REG_APPLIED_MASK     = 8'h10;
    localparam logic [7:0] REG_MASK_REQUEST     = 8'h14;
    localparam logic [7:0] REG_BUTTON_STATUS    = 8'h18;
    localparam logic [7:0] REG_STATUS           = 8'h40;
    localparam logic [7:0] REG_EVENT_LO         = 8'h48;
    localparam logic [7:0] REG_EVENT_HI         = 8'h4C;
    localparam logic [7:0] REG_ENVELOPE_ACTIVE  = 8'h58;
    localparam logic [7:0] REG_ENVELOPE_COMMAND = 8'h5C;
    localparam logic [7:0] REG_LFO_COMMAND      = 8'h80;
    localparam logic [7:0] REG_LFO_INCREMENT    = 8'h84;

    logic rst;
    assign rst = !s_axi_aresetn;

    // ---------------------------------------------------------------- AXI writes
    logic aw_stored;
    logic [AXI_ADDR_WIDTH-1:0] awaddr_stored;
    logic w_stored;
    logic [31:0] wdata_stored;
    logic [3:0] wstrb_stored;
    logic write_commit;

    assign s_axi_awready = !aw_stored && !s_axi_bvalid;
    assign s_axi_wready  = !w_stored && !s_axi_bvalid;
    assign s_axi_bresp   = 2'b00;
    assign write_commit  = aw_stored && w_stored && !s_axi_bvalid;

    always_ff @(posedge s_axi_aclk) begin
        if (rst) begin
            aw_stored    <= 1'b0;
            awaddr_stored <= '0;
            w_stored     <= 1'b0;
            wdata_stored <= 32'd0;
            wstrb_stored <= 4'd0;
            s_axi_bvalid <= 1'b0;
        end else begin
            if (s_axi_awready && s_axi_awvalid) begin
                aw_stored     <= 1'b1;
                awaddr_stored <= s_axi_awaddr;
            end
            if (s_axi_wready && s_axi_wvalid) begin
                w_stored     <= 1'b1;
                wdata_stored <= s_axi_wdata;
                wstrb_stored <= s_axi_wstrb;
            end
            if (write_commit) begin
                aw_stored    <= 1'b0;
                w_stored     <= 1'b0;
                s_axi_bvalid <= 1'b1;
            end else if (s_axi_bvalid && s_axi_bready) begin
                s_axi_bvalid <= 1'b0;
            end
        end
    end

    function automatic logic [31:0] merge_wstrb(
        input logic [31:0] old_value,
        input logic [31:0] new_value,
        input logic [3:0] strobes
    );
        logic [31:0] result;
        result = old_value;
        for (int unsigned byte_index = 0; byte_index < 4; byte_index++) begin
            if (strobes[byte_index])
                result[byte_index * 8 +: 8] = new_value[byte_index * 8 +: 8];
        end
        return result;
    endfunction

    function automatic logic [15:0] merge_wstrb16(
        input logic [15:0] old_value,
        input logic [15:0] new_value,
        input logic [1:0] strobes
    );
        logic [15:0] result;
        result = old_value;
        if (strobes[0]) result[7:0] = new_value[7:0];
        if (strobes[1]) result[15:8] = new_value[15:8];
        return result;
    endfunction

    function automatic logic [23:0] merge_wstrb24(
        input logic [23:0] old_value,
        input logic [23:0] new_value,
        input logic [2:0] strobes
    );
        logic [23:0] result;
        result = old_value;
        for (int unsigned byte_index = 0; byte_index < 3; byte_index++) begin
            if (strobes[byte_index])
                result[byte_index * 8 +: 8] = new_value[byte_index * 8 +: 8];
        end
        return result;
    endfunction

    // -------------------------------------------------------------- configuration
    logic run;
    logic transport_reset;
    logic [31:0] cycles_per_step;
    logic [6:0][15:0] patterns;
    logic request_valid;
    logic [6:0] requested_mask;
    logic [1:0] request_quantization;
    logic envelope_command_valid;
    logic [2:0] envelope_command_track;
    logic [7:0] envelope_command_target;
    logic [15:0] envelope_command_duration;
    logic [23:0] lfo_increment_setting;
    logic lfo_command_valid;
    logic [2:0] lfo_command_track;
    logic lfo_command_enable;
    logic lfo_command_reset_phase;
    logic [7:0] lfo_command_depth;

    logic [3:0] step_index;
    logic [31:0] absolute_tick;
    logic [6:0] applied_mask;
    logic mask_applied_pulse;
    logic event_valid;
    logic [31:0] event_tick;
    logic [3:0] event_step;
    logic [6:0] event_mask;

    always_ff @(posedge s_axi_aclk) begin
        if (rst) begin
            run                  <= 1'b0;
            transport_reset      <= 1'b0;
            cycles_per_step      <= 32'd12_500_000;
            request_valid        <= 1'b0;
            requested_mask       <= 7'd0;
            request_quantization <= 2'd0;
            envelope_command_valid <= 1'b0;
            envelope_command_track <= 3'd0;
            envelope_command_target <= 8'hFF;
            envelope_command_duration <= 16'd0;
            lfo_increment_setting <= 24'd0;
            lfo_command_valid <= 1'b0;
            lfo_command_track <= 3'd0;
            lfo_command_enable <= 1'b0;
            lfo_command_reset_phase <= 1'b0;
            lfo_command_depth <= 8'd0;
            patterns[0]          <= 16'h5551;
            patterns[1]          <= 16'h5555;
            patterns[2]          <= 16'h1041;
            patterns[3]          <= 16'h5555;
            patterns[4]          <= 16'h0001;
            patterns[5]          <= 16'h4444;
            patterns[6]          <= 16'h4924;
        end else begin
            transport_reset <= 1'b0;
            request_valid   <= 1'b0;
            envelope_command_valid <= 1'b0;
            lfo_command_valid <= 1'b0;

            if (write_commit) begin
                unique case (awaddr_stored[7:0])
                    REG_CONTROL: begin
                        if (wstrb_stored[0]) begin
                            run <= wdata_stored[0];
                            transport_reset <= wdata_stored[1];
                        end
                    end
                    REG_CYCLES_PER_STEP:
                        cycles_per_step <= merge_wstrb(cycles_per_step, wdata_stored, wstrb_stored);
                    REG_MASK_REQUEST: begin
                        if (wdata_stored[31]) begin
                            requested_mask       <= wdata_stored[6:0];
                            request_quantization <= wdata_stored[9:8];
                            request_valid        <= 1'b1;
                        end
                    end
                    8'h20: patterns[0] <= merge_wstrb16(patterns[0], wdata_stored[15:0], wstrb_stored[1:0]);
                    8'h24: patterns[1] <= merge_wstrb16(patterns[1], wdata_stored[15:0], wstrb_stored[1:0]);
                    8'h28: patterns[2] <= merge_wstrb16(patterns[2], wdata_stored[15:0], wstrb_stored[1:0]);
                    8'h2C: patterns[3] <= merge_wstrb16(patterns[3], wdata_stored[15:0], wstrb_stored[1:0]);
                    8'h30: patterns[4] <= merge_wstrb16(patterns[4], wdata_stored[15:0], wstrb_stored[1:0]);
                    8'h34: patterns[5] <= merge_wstrb16(patterns[5], wdata_stored[15:0], wstrb_stored[1:0]);
                    8'h38: patterns[6] <= merge_wstrb16(patterns[6], wdata_stored[15:0], wstrb_stored[1:0]);
                    REG_ENVELOPE_COMMAND: begin
                        envelope_command_track <= wdata_stored[2:0];
                        envelope_command_target <= wdata_stored[15:8];
                        envelope_command_duration <= wdata_stored[31:16];
                        envelope_command_valid <= 1'b1;
                    end
                    REG_LFO_INCREMENT:
                        lfo_increment_setting <= merge_wstrb24(
                            lfo_increment_setting, wdata_stored[23:0], wstrb_stored[2:0]);
                    REG_LFO_COMMAND: begin
                        if (wdata_stored[31]) begin
                            lfo_command_track <= wdata_stored[2:0];
                            lfo_command_enable <= wdata_stored[29];
                            lfo_command_reset_phase <= wdata_stored[30];
                            lfo_command_depth <= wdata_stored[28:21];
                            lfo_command_valid <= 1'b1;
                        end
                    end
                    default: begin end
                endcase
            end
        end
    end

    /* verilator lint_off PINCONNECTEMPTY */
    deskband_timing_core timing_core (
        .clk(s_axi_aclk),
        .rst(rst),
        .run(run),
        .transport_reset(transport_reset),
        .cycles_per_step(cycles_per_step),
        .patterns(patterns),
        .request_valid(request_valid),
        .requested_mask(requested_mask),
        .request_quantization(request_quantization),
        .tick_pulse(),
        .step_index(step_index),
        .beat_index(),
        .absolute_tick(absolute_tick),
        .applied_mask(applied_mask),
        .mask_applied_pulse(mask_applied_pulse),
        .event_valid(event_valid),
        .event_tick(event_tick),
        .event_step(event_step),
        .event_mask(event_mask)
    );
    /* verilator lint_on PINCONNECTEMPTY */

    // ----------------------------------------------------------- physical buttons
    logic [3:0] button_state;
    logic [3:0] button_pressed;
    logic [3:0] button_released;
    logic [3:0] press_sticky;
    logic [3:0] release_sticky;

    generate
        for (genvar button = 0; button < 4; button++) begin : gen_buttons
            button_debounce #(
                .STABLE_CYCLES(BUTTON_STABLE_CYCLES)
            ) debounce (
                .clk(s_axi_aclk),
                .rst(rst),
                .raw_button(raw_buttons[button]),
                .button_state(button_state[button]),
                .pressed_pulse(button_pressed[button]),
                .released_pulse(button_released[button])
            );
        end
    endgenerate

    always_ff @(posedge s_axi_aclk) begin
        if (rst) begin
            press_sticky   <= 4'd0;
            release_sticky <= 4'd0;
        end else begin
            if (write_commit && awaddr_stored[7:0] == REG_BUTTON_STATUS) begin
                press_sticky   <= (press_sticky & ~wdata_stored[11:8]) | button_pressed;
                release_sticky <= (release_sticky & ~wdata_stored[19:16]) | button_released;
            end else begin
                press_sticky   <= press_sticky | button_pressed;
                release_sticky <= release_sticky | button_released;
            end
        end
    end

    assign leds = run ? step_index : switches;

    // ---------------------------------------------------------- level envelopes
    logic [CONTROL_COUNTER_WIDTH-1:0] control_counter;
    logic control_update_pulse;
    logic [6:0][7:0] envelope_levels;
    logic [6:0] envelope_active;
    logic envelope_command_ready;

    initial begin
        if (CONTROL_UPDATE_CYCLES < 1)
            $error("CONTROL_UPDATE_CYCLES must be at least one");
    end

    always_ff @(posedge s_axi_aclk) begin
        if (rst) begin
            control_counter <= '0;
            control_update_pulse <= 1'b0;
        end else begin
            control_update_pulse <= 1'b0;
            if (control_counter == CONTROL_LAST) begin
                control_counter <= '0;
                control_update_pulse <= 1'b1;
            end else begin
                control_counter <= control_counter + 1'b1;
            end
        end
    end

    level_envelope_bank envelope_bank (
        .clk(s_axi_aclk),
        .rst(rst),
        .update_pulse(control_update_pulse),
        .command_valid(envelope_command_valid),
        .command_track(envelope_command_track),
        .command_target(envelope_command_target),
        .command_duration(envelope_command_duration),
        .levels(envelope_levels),
        .active(envelope_active),
        .command_ready(envelope_command_ready)
    );

    logic [6:0][7:0] lfo_values;
    logic [6:0] lfo_enabled;
    lfo_bank lfos (
        .clk(s_axi_aclk), .rst(rst), .update_pulse(control_update_pulse),
        .command_valid(lfo_command_valid), .command_track(lfo_command_track),
        .command_enable(lfo_command_enable), .command_reset_phase(lfo_command_reset_phase),
        .command_depth(lfo_command_depth), .command_increment(lfo_increment_setting),
        .values(lfo_values), .enabled(lfo_enabled)
    );

    // ---------------------------------------------------------------- event FIFO
    logic [63:0] event_fifo [0:FIFO_DEPTH-1];
    logic [FIFO_PTR_WIDTH-1:0] fifo_write_ptr;
    logic [FIFO_PTR_WIDTH-1:0] fifo_read_ptr;
    logic [FIFO_COUNT_WIDTH-1:0] fifo_count;
    logic fifo_overflow;
    logic fifo_pop;
    logic fifo_push;
    logic [63:0] event_record;

    assign event_record = {13'd0, mask_applied_pulse, applied_mask,
                           event_mask, event_step, event_tick};
    assign fifo_pop = s_axi_arready && s_axi_arvalid &&
                      s_axi_araddr[7:0] == REG_EVENT_HI && fifo_count != 0;
    assign fifo_push = event_valid && ((fifo_count < FIFO_CAPACITY) || fifo_pop);

    always_ff @(posedge s_axi_aclk) begin
        if (rst) begin
            fifo_write_ptr <= '0;
            fifo_read_ptr  <= '0;
            fifo_count     <= '0;
            fifo_overflow  <= 1'b0;
        end else begin
            if (fifo_push) begin
                event_fifo[fifo_write_ptr] <= event_record;
                fifo_write_ptr <= fifo_write_ptr + 1'b1;
            end
            if (fifo_pop)
                fifo_read_ptr <= fifo_read_ptr + 1'b1;

            unique case ({fifo_push, fifo_pop})
                2'b10: fifo_count <= fifo_count + 1'b1;
                2'b01: fifo_count <= fifo_count - 1'b1;
                default: fifo_count <= fifo_count;
            endcase

            if (event_valid && fifo_count == FIFO_CAPACITY && !fifo_pop)
                fifo_overflow <= 1'b1;
            if (write_commit && awaddr_stored[7:0] == REG_STATUS && wdata_stored[31])
                fifo_overflow <= 1'b0;
        end
    end

    // ----------------------------------------------------------------- AXI reads
    assign s_axi_arready = !s_axi_rvalid;
    assign s_axi_rresp = 2'b00;

    function automatic logic [31:0] read_register(input logic [7:0] address);
        unique case (address)
            REG_ID_VERSION:      read_register = ID_VERSION;
            REG_CONTROL:         read_register = {31'd0, run};
            REG_CYCLES_PER_STEP: read_register = cycles_per_step;
            REG_ABSOLUTE_TICK:   read_register = absolute_tick;
            REG_APPLIED_MASK:    read_register = {25'd0, applied_mask};
            REG_BUTTON_STATUS:   read_register = {4'd0, switches, 4'd0, release_sticky,
                                                   4'd0, press_sticky, 4'd0, button_state};
            8'h20: read_register = {16'd0, patterns[0]};
            8'h24: read_register = {16'd0, patterns[1]};
            8'h28: read_register = {16'd0, patterns[2]};
            8'h2C: read_register = {16'd0, patterns[3]};
            8'h30: read_register = {16'd0, patterns[4]};
            8'h34: read_register = {16'd0, patterns[5]};
            8'h38: read_register = {16'd0, patterns[6]};
            REG_STATUS: read_register = {fifo_overflow,
                                         {(31-FIFO_COUNT_WIDTH){1'b0}}, fifo_count};
            REG_EVENT_LO: read_register = (fifo_count != 0) ? event_fifo[fifo_read_ptr][31:0] : 32'd0;
            REG_EVENT_HI: read_register = (fifo_count != 0) ? event_fifo[fifo_read_ptr][63:32] : 32'd0;
            REG_ENVELOPE_ACTIVE: read_register = {envelope_command_ready, 24'd0,
                                                   envelope_active};
            8'h60: read_register = {24'd0, envelope_levels[0]};
            8'h64: read_register = {24'd0, envelope_levels[1]};
            8'h68: read_register = {24'd0, envelope_levels[2]};
            8'h6C: read_register = {24'd0, envelope_levels[3]};
            8'h70: read_register = {24'd0, envelope_levels[4]};
            8'h74: read_register = {24'd0, envelope_levels[5]};
            8'h78: read_register = {24'd0, envelope_levels[6]};
            REG_LFO_INCREMENT: read_register = {8'd0, lfo_increment_setting};
            8'h88: read_register = {25'd0, lfo_enabled};
            8'h90: read_register = {24'd0, lfo_values[0]};
            8'h94: read_register = {24'd0, lfo_values[1]};
            8'h98: read_register = {24'd0, lfo_values[2]};
            8'h9C: read_register = {24'd0, lfo_values[3]};
            8'hA0: read_register = {24'd0, lfo_values[4]};
            8'hA4: read_register = {24'd0, lfo_values[5]};
            8'hA8: read_register = {24'd0, lfo_values[6]};
            default: read_register = 32'd0;
        endcase
    endfunction

    always_ff @(posedge s_axi_aclk) begin
        if (rst) begin
            s_axi_rdata  <= 32'd0;
            s_axi_rvalid <= 1'b0;
        end else begin
            if (s_axi_arready && s_axi_arvalid) begin
                s_axi_rdata  <= read_register(s_axi_araddr[7:0]);
                s_axi_rvalid <= 1'b1;
            end else if (s_axi_rvalid && s_axi_rready) begin
                s_axi_rvalid <= 1'b0;
            end
        end
    end

endmodule
