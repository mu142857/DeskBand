# Reproducibly construct the complete Zybo Z7-20 hardware design.
# Usage: vivado -mode batch -source build_project.tcl -tclargs BOARD_REPO [bitstream]

if {$argc < 1 || $argc > 2} {
    error "usage: build_project.tcl <Digilent board_files directory> ?bitstream?"
}

set board_repo [file normalize [lindex $argv 0]]
set build_bitstream [expr {$argc == 2 && [lindex $argv 1] eq "bitstream"}]
set script_dir [file dirname [file normalize [info script]]]
set fpga_dir [file dirname $script_dir]
set build_dir [file join $fpga_dir build vivado_project]
set project_name deskband_zybo

set_param board.repoPaths [list $board_repo]
set board_part "digilentinc.com:zybo-z7-20:part0:1.2"
if {[llength [get_board_parts -quiet $board_part]] == 0} {
    error "Zybo Z7-20 board part not found below $board_repo"
}

create_project -force $project_name $build_dir -part xc7z020clg400-1
set_property board_part $board_part [current_project]
add_files -norecurse [glob [file join $fpga_dir rtl *.sv] [file join $fpga_dir rtl *.v]]
set_property file_type SystemVerilog [get_files *.sv]
update_compile_order -fileset sources_1
add_files -fileset constrs_1 -norecurse [file join $script_dir zybo_z7_20.xdc]

create_bd_design system
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:* ps7]
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config {apply_board_preset "1" make_external "FIXED_IO, DDR"} $ps
set_property CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100.000000} $ps

set core [create_bd_cell -type module -reference deskband_axi_ip deskband_core]
set interconnect [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:* axi_interconnect]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {1}] $interconnect
set reset [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:* peripheral_reset]

connect_bd_intf_net [get_bd_intf_pins ps7/M_AXI_GP0] [get_bd_intf_pins axi_interconnect/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_interconnect/M00_AXI] [get_bd_intf_pins deskband_core/S_AXI]

connect_bd_net [get_bd_pins ps7/FCLK_CLK0] \
    [get_bd_pins ps7/M_AXI_GP0_ACLK] \
    [get_bd_pins axi_interconnect/ACLK] \
    [get_bd_pins axi_interconnect/S00_ACLK] \
    [get_bd_pins axi_interconnect/M00_ACLK] \
    [get_bd_pins deskband_core/s_axi_aclk] \
    [get_bd_pins peripheral_reset/slowest_sync_clk]
connect_bd_net [get_bd_pins ps7/FCLK_RESET0_N] [get_bd_pins peripheral_reset/ext_reset_in]
connect_bd_net [get_bd_pins peripheral_reset/interconnect_aresetn] \
    [get_bd_pins axi_interconnect/ARESETN]
connect_bd_net [get_bd_pins peripheral_reset/peripheral_aresetn] \
    [get_bd_pins axi_interconnect/S00_ARESETN] \
    [get_bd_pins axi_interconnect/M00_ARESETN] \
    [get_bd_pins deskband_core/s_axi_aresetn]

make_bd_pins_external [get_bd_pins deskband_core/raw_buttons]
make_bd_pins_external [get_bd_pins deskband_core/switches]
make_bd_pins_external [get_bd_pins deskband_core/leds]
set_property name btn [get_bd_ports raw_buttons_0]
set_property name sw [get_bd_ports switches_0]
set_property name led [get_bd_ports leds_0]

set core_segment [lindex [get_bd_addr_segs -of_objects [get_bd_intf_pins deskband_core/S_AXI]] 0]
if {$core_segment eq ""} { error "no AXI address segment inferred for deskband_core" }
assign_bd_address -offset 0x43C00000 -range 4K \
    -target_address_space [get_bd_addr_spaces ps7/Data] $core_segment -force
validate_bd_design
save_bd_design

set wrapper [make_wrapper -files [get_files system.bd] -top]
add_files -norecurse $wrapper
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1
generate_target all [get_files system.bd]

write_hw_platform -fixed -force -file [file join $build_dir deskband_zybo.xsa]

if {$build_bitstream} {
    launch_runs impl_1 -to_step write_bitstream -jobs 4
    wait_on_run impl_1
    if {[get_property STATUS [get_runs impl_1]] ne "write_bitstream Complete!"} {
        error "implementation failed: [get_property STATUS [get_runs impl_1]]"
    }
    open_run impl_1
    report_timing_summary -file [file join $build_dir timing_implemented.txt]
    set worst_slack [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
    if {$worst_slack < 0.0} { error "implemented timing failed: WNS=$worst_slack ns" }
    write_hw_platform -fixed -include_bit -force -file [file join $build_dir deskband_zybo.xsa]
}

puts "PASS: generated Zybo Z7-20 design at $build_dir"
