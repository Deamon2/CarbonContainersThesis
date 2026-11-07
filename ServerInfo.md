thesis@Ubuntu-noble-latest-amd64-base:~$ inxi -Fazy
System:
  Kernel: 6.8.0-139-generic arch: x86_64 bits: 64 compiler: gcc v: 13.3.0
    clocksource: tsc avail: hpet,acpi_pm
    parameters: BOOT_IMAGE=/vmlinuz-6.8.0-139-generic
    root=UUID=d743e5b9-57ba-4c99-a215-a5311165d325 ro consoleblank=0
    systemd.show_status=true consoleblank=0
  Console: pty pts/0 Distro: Ubuntu 24.04.4 LTS (Noble Numbat)
Machine:
  Type: Desktop Mobo: ASUSTeK model: WS C422 DC v: Rev 1.xx
    serial: <superuser required> part-nu: ASUS_MB_KBLX uuid: <superuser required>
    BIOS: American Megatrends v: 3205 date: 11/17/2021
CPU:
  Info: model: Intel Xeon W-2295 bits: 64 type: MT MCP arch: Cascade Lake
    level: v4 note: check built: 2019 process: Intel 14nm family: 6
    model-id: 0x55 (85) stepping: 7 microcode: 0x5003901
  Topology: cpus: 1x cores: 18 tpc: 2 threads: 36 smt: enabled cache:
    L1: 1.1 MiB desc: d-18x32 KiB; i-18x32 KiB L2: 18 MiB desc: 18x1024 KiB
    L3: 24.8 MiB desc: 1x24.8 MiB
  Speed (MHz): avg: 1200 min/max: 1200/4800:4600:4700 scaling:
    driver: intel_pstate governor: powersave cores: 1: 1200 2: 1200 3: 1200
    4: 1200 5: 1200 6: 1200 7: 1200 8: 1200 9: 1200 10: 1200 11: 1200 12: 1200
    13: 1200 14: 1200 15: 1200 16: 1200 17: 1200 18: 1200 19: 1200 20: 1200
    21: 1200 22: 1200 23: 1200 24: 1200 25: 1200 26: 1200 27: 1200 28: 1200
    29: 1200 30: 1200 31: 1200 32: 1200 33: 1200 34: 1200 35: 1200 36: 1200
    bogomips: 216000
  Flags: avx avx2 ht lm nx pae sse sse2 sse3 sse4_1 sse4_2 ssse3 vmx
  Vulnerabilities:
  Type: gather_data_sampling mitigation: Microcode
  Type: indirect_target_selection mitigation: Aligned branch/return thunks
  Type: itlb_multihit status: KVM: VMX disabled
  Type: l1tf status: Not affected
  Type: mds status: Not affected
  Type: meltdown status: Not affected
  Type: mmio_stale_data mitigation: Clear CPU buffers; SMT vulnerable
  Type: reg_file_data_sampling status: Not affected
  Type: retbleed mitigation: Enhanced IBRS
  Type: spec_rstack_overflow status: Not affected
  Type: spec_store_bypass mitigation: Speculative Store Bypass disabled via
    prctl
  Type: spectre_v1 mitigation: usercopy/swapgs barriers and __user pointer
    sanitization
  Type: spectre_v2 mitigation: Enhanced / Automatic IBRS; IBPB: conditional;
    PBRSB-eIBRS: SW sequence; BHI: SW loop, KVM: SW loop
  Type: srbds status: Not affected
  Type: tsa status: Not affected
  Type: tsx_async_abort mitigation: TSX disabled
  Type: vmscape mitigation: IBPB before exit to userspace
Graphics:
  Device-1: ASPEED Graphics Family driver: ast v: kernel ports: active: VGA-1
    empty: Virtual-1 bus-ID: 03:00.0 chip-ID: 1a03:2000 class-ID: 0300
  Display: server: X.org v: 1.21.1.11 driver: X: loaded: modesetting
    unloaded: fbdev,vesa gpu: ast tty: 252x62
  Monitor-1: VGA-1 size-res: N/A in console modes: max: 1024x768 min: 640x480
  API: EGL v: 1.5 platforms: device: 0 drv: swrast surfaceless: drv: swrast
    inactive: gbm,wayland,x11
  API: OpenGL v: 4.5 vendor: mesa v: 25.2.8-0ubuntu0.24.04.2
    note: console (EGL sourced) renderer: llvmpipe (LLVM 20.1.2 256 bits)
Audio:
  Message: No device data found.
  API: ALSA v: k6.8.0-139-generic status: inactive tools: N/A
  Server-1: PulseAudio v: 16.1 status: off tools: pacat,pactl,pavucontrol
Network:
  Device-1: Intel I210 Gigabit Network vendor: ASUSTeK driver: igb v: kernel
    pcie: gen: 1 speed: 2.5 GT/s lanes: 1 port: 2000 bus-ID: 05:00.0
    chip-ID: 8086:1533 class-ID: 0200
  IF: enp5s0 state: up speed: 1000 Mbps duplex: full mac: <filter>
  IF-ID-1: lxcbr0 state: down mac: <filter>
  Info: services: NetworkManager, sshd, systemd-networkd, systemd-timesyncd,
    wpa_supplicant
Drives:
  Local Storage: total: 894.25 GiB used: 23.29 GiB (2.6%)
  SMART Message: Required tool smartctl not installed. Check --recommends
  ID-1: /dev/sda maj-min: 8:0 vendor: Micron model: 5100 MTFDDAK960TBY
    size: 894.25 GiB block-size: physical: 4096 B logical: 512 B speed: 6.0 Gb/s
    tech: N/A serial: <filter> fw-rev: U071 scheme: MBR
Partition:
  ID-1: / raw-size: 889.25 GiB size: 874.19 GiB (98.31%) used: 23.09 GiB (2.6%)
    fs: ext4 dev: /dev/sda3 maj-min: 8:3
  ID-2: /boot raw-size: 1024 MiB size: 974.7 MiB (95.18%)
    used: 203.9 MiB (20.9%) fs: ext3 dev: /dev/sda2 maj-min: 8:2
Swap:
  Kernel: swappiness: 60 (default) cache-pressure: 100 (default) zswap: no
  ID-1: swap-1 type: partition size: 4 GiB used: 0 KiB (0.0%) priority: -2
    dev: /dev/sda1 maj-min: 8:1
Sensors:
  System Temperatures: cpu: 42.0 C mobo: N/A
  Fan Speeds (rpm): N/A
Info:
  Memory: total: 128 GiB note: est. available: 125.49 GiB used: 4.49 GiB (3.6%)
  Processes: 442 Power: uptime: 9d 1h 47m states: freeze,mem,disk
    suspend: deep avail: s2idle wakeups: 0 hibernate: platform avail: shutdown,
    reboot, suspend, test_resume image: 50.16 GiB Init: systemd v: 255
    target: graphical (5) default: graphical tool: systemctl
  Packages: 1475 pm: dpkg pkgs: 1465 libs: 755 tools: apt,apt-get pm: snap
    pkgs: 10 Compilers: gcc: 13.3.0 Shell: Bash v: 5.2.21
    running-in: pty pts/0 (SSH) inxi: 3.3.34
    

4x RAM 32768 MB DDR4 ECC reg.
