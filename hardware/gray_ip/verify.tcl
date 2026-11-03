set dev [file dirname [file normalize [info script]]]
set vivado_bin [file normalize [file join [file dirname [info nameofexecutable]] .. ..]]
set rtl [file join $dev bgr2gray_axis.v]
set tb [file join $dev tb_bgr2gray_axis.sv]
cd $dev

proc run_external {name args} {
    set log [open "${name}.log" w]
    set result [catch {exec {*}$args 2>@1} output]
    puts $log $output
    close $log
    puts $output
    if {$result} { error "$name failed; see ${name}.log" }
}

run_external xvlog [file join $vivado_bin xvlog.bat] -sv -i $dev $rtl $tb
run_external xelab [file join $vivado_bin xelab.bat] work.tb_bgr2gray_axis -s bgr2gray_test
run_external sim [file join $vivado_bin xsim.bat] bgr2gray_test -runall
set sim_file [open sim.log r]
set sim_text [read $sim_file]
close $sim_file
if {![string match {*PASS ALL*} $sim_text]} { error "Simulation did not print PASS ALL" }

set synth_log [open synth.log w]
set synth_result [catch {
    read_verilog $rtl
    synth_design -top bgr2gray_axis -part xc7z020clg484-2
    report_utilization -file [file join $dev utilization.rpt]
} synth_message]
puts $synth_log $synth_message
if {$synth_result} {
    puts $synth_log "FAIL SYNTHESIS: $synth_message"
} else {
    puts $synth_log "PASS SYNTHESIS: xc7z020clg484-2; see utilization.rpt and vivado_batch.log"
}
close $synth_log
if {$synth_result} { error "Synthesis failed: $synth_message" }
puts "PASS SYNTHESIS: xc7z020clg484-2; see utilization.rpt"
puts "PASS VERIFICATION: simulation and synthesis completed"
