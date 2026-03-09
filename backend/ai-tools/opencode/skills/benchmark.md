name: benchmark
description: Create network or compute benchmark scripts for FABRIC experiments
---
Create benchmark scripts for FABRIC experiments.

1. **Understand what to benchmark**:
   - Network bandwidth (iPerf3)
   - Network latency (ping, sockperf)
   - Disk I/O (fio)
   - CPU (stress-ng, sysbench)
   - GPU (cuda-memcheck, nvidia-smi)

2. **Write benchmark scripts** with:
   - Proper tool installation
   - Server/client setup for network tests
   - Result collection and formatting
   - `### PROGRESS:` markers for status

3. **Common benchmarks**:

   **iPerf3 bandwidth test**:
   ```bash
   # Server: iperf3 -s
   # Client: iperf3 -c <server_ip> -t 30 -P 4 -J > results.json
   ```

   **Latency test**:
   ```bash
   ping -c 100 <target_ip> | tail -1
   ```

   **Disk I/O test**:
   ```bash
   sudo apt-get install -y fio
   fio --name=randwrite --ioengine=libaio --direct=1 --bs=4k --numjobs=4 \
       --size=1G --runtime=60 --group_reporting --rw=randwrite
   ```

4. **Output**: Save scripts to the working directory or integrate into a slice template.
