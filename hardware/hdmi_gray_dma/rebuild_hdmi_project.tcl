# Vivado 2025.2: rebuild the HDMI + gray DMA source project in a NEW folder.
# Usage: vivado -mode batch -source rebuild_hdmi_project.tcl -tclargs <new_absolute_folder>
set root [file normalize [file dirname [info script]]]
set out [lindex $argv 0]
if {$out eq ""} {error "Pass a new empty output folder as the first Tcl argument"}
set out [file normalize $out]
if {[file exists $out]} {error "Refusing to overwrite existing output folder: $out"}
file mkdir $out
create_project hdmi_gray_dma_rebuild $out -part xc7z020clg484-2
set_property target_language Verilog [current_project]
set_property IP_REPO_PATHS [list [file join $root ip_repo] [file join $root hdmi_reference]] [current_project]
update_ip_catalog -rebuild
set ::origin_dir_loc [file join $out source_base]
source [file join $root rebuild_hdmi_bd.tcl]
set bd [get_files [file join $out source_base system system.bd]]
if {[llength $bd] != 1} {error "BD creation failed"}
generate_target all $bd
set wrapper [make_wrapper -files $bd -top]
add_files -norecurse $wrapper
add_files -fileset constrs_1 -norecurse [file join $root hdmi_reference hdmi_out.xdc]
add_files -fileset constrs_1 -norecurse [file join $root hdmi_reference hdmi_720p_timing.xdc]
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1
validate_bd_design
puts "REBUILD_READY=$out"
close_project
