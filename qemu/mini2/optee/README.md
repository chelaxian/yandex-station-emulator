# Isolated OP-TEE experiment

The production stand and this probe have separate disks and serial sockets.
The probe uses `probe.ext4`, an APFS clone of the stand disk. Firmware backups
are unchanged. NV is attached read-only and copied into the disposable probe disk.

## Verified on 2026-10-23

- TF-A v2.11.0 (f2735ebccf5173f74c0458736ec526276106097e).
- OP-TEE 4.3.0 (1c0d52ace3c237ca6276cafb5c73f699a75c1d40), ARM64 core with ARM32 TA support.
- Debian Linux 6.1.0-53-arm64 (6.1.187-1), SHA256 of its Debian package:
  b7b22756c676a715c20476ddecfaf0890bc2804a9b76ebdb1aa42157ac6b28f8.
- QEMU secure world boots; Linux initializes OP-TEE and exposes tee0/teepriv0.
- The legacy Mini 2 supplicant needs reserved shared memory: CFG_CORE_DYN_SHM=n.
- The vendor TA container is rejected by stock OP-TEE with 0xffff000f.
  Its unchanged ELF is repackaged and signed with the emulator development key
  only on the probe copy. This loads the Amlogic Keymaster 2.0 TA successfully.
- The original keymaster service completes TA initialization, Get version and
  Configure. A public-key request then fails with an iostream error.
- File-only strace establishes the first missing interface:
  openat(AT_FDCWD, "/sys/class/unifykeys/attach", O_RDONLY|O_LARGEFILE) = -1 ENOENT.
  The service also contains key_blob/name/exist/size/read/write interface names.
- This does not establish that the original device key is decryptable in QEMU.
  No successful export/signing or app onboarding has been demonstrated.

## Second dump

`mini2_clean_factory_full_dump.tar.gz`:
all seven item sizes and SHA256 values match its manifest. Quasar is newer
(0.369.1.46.4778262943.20261013.299), but keymaster_svc and its TA are byte-identical
to the first dump. New NV contains the same named 16384-byte protected object;
its bytes differ. The new /data archive has account/token state, so it has not
been merged into the running networked stand. No separate unifykeys/key_blob
export was found by archive filename inspection. Using the new NV in the probe
still stops at the missing unifykeys interface. The manifest's 'full' label
does not establish completeness of hardware key storage; bootloader is 258048 bytes.

## Rebuild and run

This repository includes experiment scripts only. Vendor source checkouts, LLVM 20 host tools, Debian kernel/modules, Python dependencies and probe images are not bundled. The revisions above record the original local experiment; the normal setup does not rebuild or run this probe.
`bash build_secure.sh` rebuilds TF-A, OP-TEE, the test-signed TA and probe initramfs.
`NV_IMAGE=/absolute/path/to/nv.bin bash run_probe.sh` runs the probe.
Normal/secure logs and PID are under run/. The diagnostic serial socket is
run/console.sock, separate from ../run/console.sock used by the normal stand.

Use `../tools/console.py --socket run/console.sock 'COMMAND'` from this directory.
The probe automatically runs a bounded public-key request and leaves a diagnostic
shell. Its keymaster failure must not be represented as a functional key service.

Next: locate an actual export of the original Mini 2 unifykeys key_blob and
understand its storage format before claiming that the NV master-key object is
sufficient. Station 1 uses a different file-key backend and is not a substitute.
