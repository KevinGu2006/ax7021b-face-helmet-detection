# 1280x720@60 candidate constraint. Dynamic Clock is programmed to 74.25 MHz.
# The 100 MHz source is the PL Clocking Wizard driven by PS FCLK0. Ratio 297/400 gives 74.25 MHz.
# SiI9134 single-edge setup >=1.0 ns, hold >=0.8 ns (falling EDGE=0).
# max=2.0 and min=-1.8 include a provisional 1 ns board-skew margin;
# PCB data/clock skew and SiI9134 EDGE register must be confirmed before board load.
set px_ref [get_pins -hier -filter {NAME =~ *axi_dynclk_0/REF_CLK_I}]
set px_out [get_pins -hier -filter {NAME =~ *axi_dynclk_0/PXL_CLK_O}]
create_generated_clock -name hdmi_pixel_720p -source $px_ref -multiply_by 297 -divide_by 400 $px_out
set vid_ports [get_ports {hdmi_out_data[*] hdmi_out_de hdmi_out_hs hdmi_out_vs}]
set_output_delay -clock [get_clocks hdmi_pixel_720p] -max 2.0 $vid_ports
set_output_delay -clock [get_clocks hdmi_pixel_720p] -min -1.8 $vid_ports
