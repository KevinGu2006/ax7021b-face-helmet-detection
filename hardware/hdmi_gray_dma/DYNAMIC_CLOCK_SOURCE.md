# Dynamic Clock IP dependency

The original local `axi_dynclk_v1_0` IP advertises `digilentinc.com:user:axi_dynclk:1.0` and contains Xilinx/Digilent-derived HDL. The public [Digilent vivado-library](https://github.com/Digilent/vivado-library) has an [MIT license](https://github.com/Digilent/vivado-library/blob/master/License.txt), but the local `mmcme2_drp.v` also carries a Xilinx all-rights-reserved notice. We have not proved that the exact local files can be republished under Digilent's repository-wide license. They are omitted from this proposed public submission.

To reproduce the project, obtain the compatible `axi_dynclk_v1_0` source from the [ALINX AX7021B reference](https://github.com/alinxalinx/AX7021B_2023.1) or Digilent under its applicable terms. Place the directory at `hardware/hdmi_gray_dma/hdmi_reference/axi_dynclk_v1_0` before running `rebuild_hdmi_project.tcl`. Check each local source against these source-snapshot SHA256 values:

| Relative path | SHA256 |
| --- | --- |
| `component.xml` | `21813665c84b1b75d9076f7e772730df199bc3ca71215d2a48a383cb37da38cd` |
| `src/axi_dynclk.vhd` | `2b8d2de5d2731fd0b83c06efb0566f83bd64016e699d067e39dc396de681ecaf` |
| `src/axi_dynclk_S00_AXI.vhd` | `871c0b0a56ad7caefecc844d23faf5af6ad904019c2cdbbb3ef5edc5048495e0` |
| `src/mmcme2_drp.v` | `3833e1439bc56a53d682cd4a8c99b6a9d3e6378b9e27667df290f0f8896faeac` |
| `xgui/axi_dynclk_v1_0.tcl` | `729c79ebdf8c55ede738aa3047c3e26d25926fb14317da1a741e4e10c0c2d7c3` |

These hashes identify the local source snapshot only; they do not grant redistribution permission. An alternate Digilent version needs independent Vivado validation and timing/board checks.
