cd /tmp
nohup /usr/local/bin/pynq-a-python2025 /home/xilinx/A_hdmi_integration_20261029/hdmi_worker.py > /home/xilinx/A_hdmi_integration_20261029/worker.log 2>&1 < /dev/null &
echo "HDMI controller PID: $!"
