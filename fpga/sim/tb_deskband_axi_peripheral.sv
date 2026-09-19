`timescale 1ns/1ps

module tb_deskband_axi_peripheral;
    localparam int FIFO_DEPTH = 4;

    logic clk = 1'b0;
    logic resetn = 1'b0;
    logic [7:0] awaddr = 0;
    logic awvalid = 0;
    logic awready;
    logic [31:0] wdata = 0;
    logic [3:0] wstrb = 0;
    logic wvalid = 0;
    logic wready;
    logic [1:0] bresp;
    logic bvalid;
    logic bready = 0;
    logic [7:0] araddr = 0;
    logic arvalid = 0;
    logic arready;
    logic [31:0] rdata;
    logic [1:0] rresp;
    logic rvalid;
    logic rready = 0;
    logic [3:0] raw_buttons = 0;
    logic [3:0] switches = 4'hA;
    logic [3:0] leds;

    always #5 clk <= ~clk;

    deskband_axi_peripheral #(
        .FIFO_DEPTH(FIFO_DEPTH),
        .BUTTON_STABLE_CYCLES(4),
        .CONTROL_UPDATE_CYCLES(4)
    ) dut (
        .s_axi_aclk(clk),
        .s_axi_aresetn(resetn),
        .s_axi_awaddr(awaddr),
        .s_axi_awvalid(awvalid),
        .s_axi_awready(awready),
        .s_axi_wdata(wdata),
        .s_axi_wstrb(wstrb),
        .s_axi_wvalid(wvalid),
        .s_axi_wready(wready),
        .s_axi_bresp(bresp),
        .s_axi_bvalid(bvalid),
        .s_axi_bready(bready),
        .s_axi_araddr(araddr),
        .s_axi_arvalid(arvalid),
        .s_axi_arready(arready),
        .s_axi_rdata(rdata),
        .s_axi_rresp(rresp),
        .s_axi_rvalid(rvalid),
        .s_axi_rready(rready),
        .raw_buttons(raw_buttons),
        .switches(switches),
        .leds(leds)
    );

    task automatic axi_write(input logic [7:0] address,
                             input logic [31:0] value,
                             input logic [3:0] strobes = 4'hF);
        // Deliberately skew AW and W to verify independent channel handling.
        @(negedge clk);
        awaddr = address;
        awvalid = 1'b1;
        do @(posedge clk); while (!awready);
        @(negedge clk);
        awvalid = 1'b0;
        wdata = value;
        wstrb = strobes;
        wvalid = 1'b1;
        do @(posedge clk); while (!wready);
        @(negedge clk);
        wvalid = 1'b0;
        bready = 1'b1;
        do @(posedge clk); while (!bvalid);
        if (bresp != 2'b00) $fatal(1, "AXI write returned an error");
        @(negedge clk);
        bready = 1'b0;
    endtask

    task automatic axi_read(input logic [7:0] address,
                            output logic [31:0] value);
        @(negedge clk);
        araddr = address;
        arvalid = 1'b1;
        do @(posedge clk); while (!arready);
        @(negedge clk);
        arvalid = 1'b0;
        rready = 1'b1;
        do @(posedge clk); while (!rvalid);
        if (rresp != 2'b00) $fatal(1, "AXI read returned an error");
        value = rdata;
        if (^value === 1'bx) $fatal(1, "AXI read contained unknown bits");
        @(negedge clk);
        rready = 1'b0;
    endtask

    task automatic expect_read(input logic [7:0] address,
                               input logic [31:0] expected);
        logic [31:0] got;
        axi_read(address, got);
        if (got !== expected) begin
            $display("read %02x: wanted %08x, got %08x", address, expected, got);
            $fatal(1, "AXI register mismatch");
        end
    endtask

    task automatic pop_event(output logic [31:0] tick,
                             output logic [3:0] step,
                             output logic [6:0] mask,
                             output logic [6:0] active,
                             output logic mask_changed);
        logic [31:0] lo;
        logic [31:0] hi;
        axi_read(8'h48, lo);
        axi_read(8'h4C, hi);
        if (hi[31:19] != 0) $fatal(1, "event reserved bits are nonzero");
        tick = lo;
        step = hi[3:0];
        mask = hi[10:4];
        active = hi[17:11];
        mask_changed = hi[18];
    endtask

    initial begin
        /* verilator lint_off UNUSEDSIGNAL */
        logic [31:0] value;
        /* verilator lint_on UNUSEDSIGNAL */
        logic [31:0] tick;
        logic [3:0] step;
        logic [6:0] mask;
        logic [6:0] active;
        logic mask_changed;

        repeat (4) @(negedge clk);
        resetn = 1'b1;

        expect_read(8'h00, 32'h4442_0100);
        axi_read(8'h18, value);
        if (value[27:24] != switches) $fatal(1, "switch state not exposed through AXI");
        expect_read(8'h08, 32'd12_500_000);
        if (leds !== switches) $fatal(1, "stopped LEDs should mirror switches");

        // Byte strobes must update only the selected bytes.
        axi_write(8'h20, 32'h0000_ABCD);
        axi_write(8'h20, 32'h0000_1200, 4'b0010);
        expect_read(8'h20, 32'h0000_12CD);

        // Hardware envelope lane 0 fades from 255 to 0 and lands exactly.
        expect_read(8'h60, 32'h0000_00FF);
        axi_write(8'h5C, 32'h0004_0000);
        value = 32'h0;
        for (int attempt = 0; attempt < 24 && !value[31]; attempt++)
            axi_read(8'h58, value);
        if (!value[31]) $fatal(1, "AXI envelope command never completed setup");

        axi_read(8'h60, value);
        for (int attempt = 0; attempt < 24 && value[7:0] != 0; attempt++)
            axi_read(8'h60, value);
        if (value[7:0] != 0) $fatal(1, "AXI envelope did not reach target");
        expect_read(8'h58, 32'h8000_0000);

        // Configure hardware LFO 0 for a quarter-cycle/update triangle.
        axi_write(8'h84, 32'h0040_0000);
        axi_write(8'h80, 32'hFFE0_0000);
        expect_read(8'h88, 32'h0000_0001);
        value = 0;
        for (int attempt = 0; attempt < 8 && value[7:0] == 0; attempt++)
            axi_read(8'h90, value);
        if (value[7:0] == 0) $fatal(1, "AXI LFO did not advance");
        axi_write(8'h80, 32'h8000_0000);
        expect_read(8'h88, 32'h0000_0000);

        // Fast simulated clock; enable tracks 0 and 1 on the first step.
        axi_write(8'h08, 32'd4);
        axi_write(8'h14, 32'h8000_0003);
        axi_write(8'h04, 32'h0000_0001);

        // Wait for at least one FIFO record, then verify its packed fields.
        value = 0;
        while (value[7:0] == 0) axi_read(8'h40, value);
        pop_event(tick, step, mask, active, mask_changed);
        if (tick != 0 || step != 0 || active != 7'h03 || mask != 7'h03 || !mask_changed)
            $fatal(1, "first event record is incorrect");

        // Button bounce must not set sticky status; a stable press must.
        raw_buttons[0] = 1'b1;
        @(negedge clk);
        raw_buttons[0] = 1'b0;
        repeat (8) @(negedge clk);
        axi_read(8'h18, value);
        if (value[8] != 0) $fatal(1, "button bounce set sticky press");
        raw_buttons[0] = 1'b1;
        repeat (8) @(negedge clk);
        axi_read(8'h18, value);
        if (value[8] != 1 || value[0] != 1)
            $fatal(1, "stable button press not exposed through AXI");
        axi_write(8'h18, 32'h0000_0100);
        axi_read(8'h18, value);
        if (value[8] != 0 || value[0] != 1)
            $fatal(1, "button sticky clear changed live state");

        // Leave the fast sequencer unread long enough to overflow the small
        // test FIFO. Overflow is sticky and software-clearable.
        repeat (40) @(negedge clk);
        axi_read(8'h40, value);
        if (value[31] != 1 || value[7:0] != 8'(FIFO_DEPTH))
            $fatal(1, "FIFO overflow/count status incorrect");
        // Stop event production before clearing a sticky overflow; otherwise
        // the still-full FIFO correctly reasserts it on the next tick.
        axi_write(8'h04, 32'h0000_0000);
        axi_write(8'h40, 32'h8000_0000);
        axi_read(8'h40, value);
        if (value[31] != 0) $fatal(1, "FIFO overflow flag did not clear");

        // A control write with reset set returns the musical position to zero.
        axi_write(8'h04, 32'h0000_0002);
        repeat (2) @(negedge clk);
        expect_read(8'h0C, 32'd0);

        $display("PASS: AXI registers, event FIFO, overflow, buttons, and core integration");
        $finish;
    end

    initial begin
        #200_000;
        $fatal(1, "simulation watchdog expired");
    end

endmodule
