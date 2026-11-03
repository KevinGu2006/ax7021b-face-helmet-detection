`timescale 1ns/1ps

module tb_bgr2gray_axis;
    localparam integer MAX_PIXELS = 768960;
    reg aclk = 0;
    always #5 aclk = ~aclk;
    reg aresetn = 0;
    reg [31:0] s_axis_tdata = 0;
    reg [3:0] s_axis_tkeep = 4'hf;
    reg s_axis_tvalid = 0;
    wire s_axis_tready;
    reg s_axis_tlast = 0;
    wire [7:0] m_axis_tdata;
    wire m_axis_tkeep;
    wire m_axis_tvalid;
    reg m_axis_tready = 0;
    wire m_axis_tlast;

    reg [31:0] input_mem [0:MAX_PIXELS-1];
    reg [7:0] expected_mem [0:MAX_PIXELS-1];
    integer cases_passed = 0;
    integer pixels_checked = 0;
    integer output_stalls = 0;
    integer input_stalls = 0;
    integer simultaneous = 0;
    integer frames_checked = 0;
    integer rng = 32'h57c21a93;

    bgr2gray_axis dut (
        .aclk(aclk), .aresetn(aresetn),
        .s_axis_tdata(s_axis_tdata), .s_axis_tkeep(s_axis_tkeep),
        .s_axis_tvalid(s_axis_tvalid), .s_axis_tready(s_axis_tready),
        .s_axis_tlast(s_axis_tlast),
        .m_axis_tdata(m_axis_tdata), .m_axis_tkeep(m_axis_tkeep),
        .m_axis_tvalid(m_axis_tvalid), .m_axis_tready(m_axis_tready),
        .m_axis_tlast(m_axis_tlast)
    );

    task automatic run_loaded_case(input string name, input integer count,
                                   input integer continuous_mode);
        integer tx, rx, cycles;
        reg pending;
        reg prev_stall;
        reg [7:0] held_data;
        reg held_last, held_keep;
        begin
            tx = 0; rx = 0; cycles = 0; pending = 0; prev_stall = 0;
            while (rx < count) begin
                @(negedge aclk);
                rng = rng * 32'd1664525 + 32'd1013904223;
                m_axis_tready = continuous_mode ? 1'b1 : (rng[3:0] < 4'd10);
                if (!pending && tx < count) begin
                    rng = rng * 32'd1664525 + 32'd1013904223;
                    if (continuous_mode || rng[3:0] < 4'd12) begin
                        pending = 1;
                        s_axis_tdata = input_mem[tx];
                        s_axis_tlast = (tx == count-1);
                    end
                end
                s_axis_tvalid = pending;
                s_axis_tkeep = 4'hf;
                @(posedge aclk);
                cycles = cycles + 1;
                if (prev_stall && (!m_axis_tvalid ||
                    m_axis_tdata !== held_data || m_axis_tlast !== held_last ||
                    m_axis_tkeep !== held_keep))
                    $fatal(1, "FAIL %s output changed under backpressure", name);
                prev_stall = m_axis_tvalid && !m_axis_tready;
                if (prev_stall) begin
                    held_data = m_axis_tdata;
                    held_last = m_axis_tlast;
                    held_keep = m_axis_tkeep;
                    output_stalls = output_stalls + 1;
                end
                if (s_axis_tvalid && !s_axis_tready) input_stalls = input_stalls + 1;
                if (s_axis_tvalid && s_axis_tready && m_axis_tvalid && m_axis_tready)
                    simultaneous = simultaneous + 1;
                if (m_axis_tvalid && m_axis_tready) begin
                    if (m_axis_tdata !== expected_mem[rx])
                        $fatal(1, "FAIL %s pixel %0d actual=%0d expected=%0d", name,
                               rx, m_axis_tdata, expected_mem[rx]);
                    if (m_axis_tlast !== (rx == count-1))
                        $fatal(1, "FAIL %s pixel %0d TLAST=%b", name, rx, m_axis_tlast);
                    if (m_axis_tkeep !== 1'b1)
                        $fatal(1, "FAIL %s pixel %0d TKEEP=%b", name, rx, m_axis_tkeep);
                    rx = rx + 1;
                    pixels_checked = pixels_checked + 1;
                end
                if (s_axis_tvalid && s_axis_tready) begin
                    tx = tx + 1;
                    pending = 0;
                end
                if (cycles > count*12 + 1000)
                    $fatal(1, "FAIL %s timeout tx=%0d rx=%0d", name, tx, rx);
            end
            @(negedge aclk);
            s_axis_tvalid = 0;
            s_axis_tlast = 0;
            m_axis_tready = 0;
            if (tx != count || m_axis_tvalid)
                $fatal(1, "FAIL %s final drain tx=%0d/%0d valid=%b",
                       name, tx, count, m_axis_tvalid);
            cases_passed = cases_passed + 1;
            frames_checked = frames_checked + 1;
            $display("PASS case=%s pixels=%0d cycles=%0d mode=%s", name, count,
                     cycles, continuous_mode ? "continuous" : "random_backpressure");
        end
    endtask

    task automatic run_image_case(input string name, input integer width,
                                  input integer height, input integer continuous_mode,
                                  input string input_path, input string expected_path);
        integer count;
        begin
            count = width * height;
            if (count < 1 || count > MAX_PIXELS) $fatal(1, "FAIL bad case size %s", name);
            $readmemh(input_path, input_mem, 0, count-1);
            $readmemh(expected_path, expected_mem, 0, count-1);
            run_loaded_case(name, count, continuous_mode);
        end
    endtask

    task automatic run_pixel_csv(input string path);
        integer fd, n, b, g, r, gray, cvgray, word, got;
        string line;
        begin
            fd = $fopen(path, "r");
            if (!fd) $fatal(1, "FAIL cannot open pixel CSV %s", path);
            got = $fgets(line, fd); // header
            n = 0;
            while (!$feof(fd)) begin
                got = $fgets(line, fd);
                if (got > 0) begin
                    if ($sscanf(line, "%d,%d,%d,%h,%d,%d", b,g,r,word,gray,cvgray) != 6)
                        $fatal(1, "FAIL malformed pixel CSV row %0d", n+1);
                    if (word !== ((r << 16) | (g << 8) | b))
                        $fatal(1, "FAIL pixel CSV packing row %0d", n+1);
                    input_mem[n] = word;
                    expected_mem[n] = gray;
                    n = n + 1;
                end
            end
            $fclose(fd);
            run_loaded_case("pixel_vectors.csv", n, 0);
        end
    endtask

    task automatic run_reset_abort;
        begin
            @(negedge aclk);
            s_axis_tdata = 32'h00ffffff;
            s_axis_tlast = 0;
            s_axis_tvalid = 1;
            m_axis_tready = 0;
            @(posedge aclk);
            if (!s_axis_tready) $fatal(1, "FAIL pre-reset input not accepted");
            @(negedge aclk);
            if (!m_axis_tvalid) $fatal(1, "FAIL pre-reset output absent");
            aresetn = 0;
            s_axis_tvalid = 0;
            if (s_axis_tready) $fatal(1, "FAIL input ready during reset");
            repeat (2) @(posedge aclk);
            @(negedge aclk);
            if (m_axis_tvalid) $fatal(1, "FAIL output valid after reset");
            aresetn = 1;
            $display("PASS reset_abort pending output discarded");
        end
    endtask

    initial begin
        repeat (4) @(negedge aclk);
        if (m_axis_tvalid || s_axis_tready) $fatal(1, "FAIL initial reset state");
        aresetn = 1;
        run_reset_abort();
`include "cases.svh"
        if (output_stalls == 0 || input_stalls == 0 || simultaneous == 0)
            $fatal(1, "FAIL missing handshake coverage");
        $display("PASS ALL cases=%0d frames=%0d pixels=%0d output_stalls=%0d input_stalls=%0d simultaneous=%0d",
                 cases_passed, frames_checked, pixels_checked, output_stalls,
                 input_stalls, simultaneous);
        $finish;
    end
endmodule
