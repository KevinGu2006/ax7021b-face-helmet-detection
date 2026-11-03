`timescale 1ns/1ps
// AXI4-Stream, one BGR pixel per 32-bit beat, one gray pixel per 8-bit beat.
// Input word: {8'h00, R, G, B}; input TKEEP must be 4'b1111.
// TLAST marks the final pixel of the whole frame (AXI DMA packet convention).
// One registered output stage accepts one pixel per clock without backpressure.
module bgr2gray_axis (
    input  wire        aclk,
    input  wire        aresetn,
    input  wire [31:0] s_axis_tdata,
    input  wire [3:0]  s_axis_tkeep,
    input  wire        s_axis_tvalid,
    output wire        s_axis_tready,
    input  wire        s_axis_tlast,
    output reg  [7:0]  m_axis_tdata,
    output wire        m_axis_tkeep,
    output reg         m_axis_tvalid,
    input  wire        m_axis_tready,
    output reg         m_axis_tlast
);
    // The contract requires every input beat to carry all four bytes.
    // TKEEP is intentionally not used to suppress a pixel.
    wire [22:0] weighted_sum =
        (s_axis_tdata[7:0]   * 23'd3735)  +
        (s_axis_tdata[15:8]  * 23'd19235) +
        (s_axis_tdata[23:16] * 23'd9798)  + 23'd16384;

    assign s_axis_tready = aresetn && (!m_axis_tvalid || m_axis_tready);
    assign m_axis_tkeep  = 1'b1;

    always @(posedge aclk) begin
        if (!aresetn) begin
            m_axis_tvalid <= 1'b0;
            m_axis_tdata  <= 8'd0;
            m_axis_tlast  <= 1'b0;
        end else if (s_axis_tready) begin
            m_axis_tvalid <= s_axis_tvalid;
            if (s_axis_tvalid) begin
                m_axis_tdata <= weighted_sum[22:15];
                m_axis_tlast <= s_axis_tlast;
            end
        end
    end
endmodule
