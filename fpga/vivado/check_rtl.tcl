# Out-of-context synthesis check for one DeskBand RTL top.
# Usage:
#   vivado -mode batch -source fpga/vivado/check_rtl.tcl \
#          -tclargs deskband_timing_core

if {$argc != 1} {
    error "usage: check_rtl.tcl <top-module>"
}

set top [lindex $argv 0]
set script_dir [file dirname [file normalize [info script]]]
set fpga_dir [file dirname $script_dir]
set part "xc7z020clg400-1"

read_verilog -sv [glob [file join $fpga_dir rtl *.sv]]
synth_design -mode out_of_context -flatten_hierarchy rebuilt -top $top -part $part
if {[llength [get_ports -quiet clk]]} {
    set clock_port [get_ports clk]
} elseif {[llength [get_ports -quiet s_axi_aclk]]} {
    set clock_port [get_ports s_axi_aclk]
} else {
    error "top $top has no recognized clock port"
}
create_clock -name fclk0 -period 10.000 $clock_port

set report_dir [file join $fpga_dir build vivado $top]
file mkdir $report_dir
report_utilization -file [file join $report_dir utilization.txt]
report_timing_summary -delay_type max -max_paths 10 -file [file join $report_dir timing.txt]
check_timing -verbose -file [file join $report_dir check_timing.txt]

set worst_path [get_timing_paths -delay_type max -max_paths 1 -nworst 1]
if {[llength $worst_path] == 0} {
    error "No timed path was found for $top"
}
set worst_slack [get_property SLACK $worst_path]
if {$worst_slack < 0.0} {
    error "Timing failed for $top: WNS=$worst_slack ns"
}
puts "Timing passed for $top: WNS=$worst_slack ns"

puts "PASS: Vivado synthesized $top for $part"
