#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""WSL side of the V100 wired monitor (diag15+ stub).

Owns the frame's USB device (attached into WSL with usbipd), listens on localhost TCP for raw RGB565 frames from
mirror.py (Windows) and updates the panel through the resident streamer stub.

Three ways to run:
  (default)  1024x600 frames, changed-row band updates (sharp; zero traffic when the screen is static)
  --zoom     512x300 frames, the display engine zooms them 2x in hardware (TURBO: a quarter of the data, 60+ fps)
  --auto     the mirror tags every frame 'S' (1024x600, sharp) or 'T' (512x300, turbo) and this program switches the
             display engine between 1:1 and 2x zoom without a visible glitch: sharp text when the screen is calm,
             fast motion when large areas change.

Band updates (sharp mode): the stub double-buffers (it writes the BACK buffer, then flips). So that the back buffer never
goes stale, each update carries every row that changed between the last two sent frames OR changed now: an exact per-row
mask split into runs (small gaps merged); all bands go out in ONE transfer and only the last band flips (header word 28
bit0 = "no flip"). Unchanged frames cost nothing. The first two sharp updates are full frames.

Mode switches: a data frame is sent with the OLD mode's display registers (so nothing is shown mis-scaled while it is
being received) and is followed by a poke-only header that applies the NEW mode's registers right after the flip.

Header words: 0-3 magic | 4 OUT EPCON | 5..20 pokes {addr,val} | 21..24 peeks | 25 exec mode | 26 y0 | 27 rows | 28 bit0 = no flip
Frames arriving while a transfer runs are dropped (latest wins); diffs are always against the last frame SENT.

usage: python3 frame_sender.py [--port 9100] [--mode 1] [--zoom | --auto] [--full]
"""
import argparse, signal, socket, struct, sys, threading, time
from pathlib import Path
import numpy as np
import usb.core

W, H = 1024, 600
OUT_EP = 0x01
IN_EP = 0x82
PKT = 512
ROW = 2048
MAGIC = (0x44483156, 0x5F4D5246, 0xA55AC33C, 0x3CC35AA5)
DE = 0xB02F0000
POKES_NORMAL = [(DE + 0x40, 0x00040000), (DE + 0x70, 512)]      # 1:1, 1024-px source lines
POKES_ZOOM2 = [(DE + 0x40, 0x000C0000), (DE + 0x70, 256)]       # hardware 2x zoom-in, 512-px source lines
GAP = 8                      # merge changed-row runs separated by <= GAP unchanged rows (a header costs more than 8 rows)
SHARP = (1024, 600)
TURBO = (512, 300)
TAG_S, TAG_T = b"S\0\0\0", b"T\0\0\0"


def make_header(epcon=0x89, mode=0, y0=0, rows=0, noflip=0, pokes=()):
    pokes = list(pokes)[:8]
    w = [*MAGIC, epcon]
    for a, v in pokes:
        w += [a, v]
    w += [0, 0] * (8 - len(pokes))
    w += [0, 0, 0, 0]                                   # peeks
    w += [mode, y0, rows, noflip]
    return struct.pack("<%dI" % len(w), *w) + bytes(PKT - 4 * len(w))


def poke_only(pokes):
    """A header that only applies register pokes: a 1-row band into the unused last row of the BACK buffer, no flip."""
    return make_header(0x89, 0, 599, 1, 1, pokes) + bytes(ROW)


def runs_from_mask(mask, gap=GAP):
    """Contiguous runs [y0, y1) of True rows; runs closer than `gap` rows are merged."""
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    splits = np.flatnonzero(np.diff(idx) > gap + 1)
    starts = np.concatenate(([idx[0]], idx[splits + 1]))
    ends = np.concatenate((idx[splits], [idx[-1]])) + 1
    return list(zip(starts.tolist(), ends.tolist()))


def build_update(frame, runs, epcon, mode, pokes=()):
    """One USB transfer: for each run a header + its rows; only the LAST band flips the display."""
    out = bytearray()
    for i, (y0, y1) in enumerate(runs):
        out += make_header(epcon, mode, y0, y1 - y0, noflip=0 if i == len(runs) - 1 else 1, pokes=pokes)
        out += frame[y0:y1].tobytes()
    return out


def open_frame():
    dev = usb.core.find(idVendor=0x10D6, idProduct=0x10D6)
    if dev is None:
        sys.exit("frame (10d6:10d6) not visible - replug into ADFU and `usbipd attach --wsl Ubuntu --busid 4-7`")
    try:
        dev.set_configuration()
    except usb.core.USBError:
        pass
    return dev


class Latest:
    """Single-slot mailbox: the reader overwrites, the sender takes the newest."""
    def __init__(self):
        self.cv = threading.Condition()
        self.item = None
        self.seq = 0

    def put(self, item):
        with self.cv:
            self.item = item
            self.seq += 1
            self.cv.notify()

    def get(self, last_seq, timeout=1.0):
        with self.cv:
            if self.seq == last_seq:
                self.cv.wait(timeout)
            return self.item, self.seq


def recv_exact(conn, n):
    buf = bytearray(n)
    view, got = memoryview(buf), 0
    while got < n:
        k = conn.recv_into(view[got:], n - got)
        if k == 0:
            raise ConnectionError("capture closed")
        got += k
    return buf


def reader(port, box, stats, fixed_size, auto):
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(1)
    print("listening on :%d for %s" % (port, "tagged S/T frames" if auto else "%d-byte frames" % fixed_size), flush=True)
    while True:
        conn, addr = srv.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        print("capture connected from", addr[0], flush=True)
        try:
            while True:
                if auto:
                    tag = bytes(recv_exact(conn, 4))
                    if tag not in (TAG_S, TAG_T):
                        raise ConnectionError("bad frame tag %r" % tag)
                    size = SHARP[0] * SHARP[1] * 2 if tag == TAG_S else TURBO[0] * TURBO[1] * 2
                    box.put((tag[:1], recv_exact(conn, size)))
                else:
                    box.put((b"F", recv_exact(conn, fixed_size)))
                stats["rx"] += 1
        except (ConnectionError, OSError) as ex:
            print("capture disconnected:", ex, flush=True)
        finally:
            conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9100)
    ap.add_argument("--mode", type=lambda s: int(s, 0), default=0, help="stub exec mode word, repeated every update (1 = cached kseg0 fetch)")
    ap.add_argument("--full", action="store_true", help="always send whole frames (no band updates)")
    ap.add_argument("--zoom", action="store_true", help="TURBO only: 512x300 frames zoomed 2x by the display engine")
    ap.add_argument("--auto", action="store_true", help="tagged S/T frames from mirror.py --auto; switch sharp <-> turbo")
    ap.add_argument("--c444", action="store_true", help="12-bit packed frames from mirror.py --c444, decoded by the stage-2 blob (needs the diag21 stub); ~29 fps at 1024x600")
    ap.add_argument('--fresh-loader',action='store_true',help='Stage 1 was just loaded in a separate ROM upload process')
    ap.add_argument('--loading-frame',type=Path,default=Path(__file__).parent/'assets'/'loading.c444')
    args = ap.parse_args()
    if args.zoom and args.auto:
        sys.exit("--zoom and --auto are exclusive")

    dev = open_frame()
    fixed = (TURBO if args.zoom else SHARP)
    box, stats = Latest(), {"rx": 0}
    if args.c444:
        import c444
        fsize = c444.NPKT * PKT
    else:
        fsize = fixed[0] * fixed[1] * 2
    threading.Thread(target=reader, args=(args.port, box, stats, fsize, args.auto), daemon=True).start()
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))   # finish the current transfer, then exit
    if args.c444:
        return run_c444(dev, box, stats, stop, fresh=args.fresh_loader, loading_frame=args.loading_frame)

    # display state: what the display engine is configured for right now
    cur = "T" if args.zoom else "S"
    cur_pokes = POKES_ZOOM2 if args.zoom else POKES_NORMAL
    last_s, prev_changed, need_full = None, np.ones(H, dtype=bool), 2     # sharp-mode band bookkeeping
    last_t = None
    seq, t_rep = 0, time.time()
    c = {"upd": 0, "skip": 0, "rows": 0, "bands": 0, "bytes": 0, "sw": 0}

    def send(pkt):
        dev.write(OUT_EP, pkt, timeout=10000)
        try:                                         # drain the stub's per-frame reply so its IN endpoint stays free
            dev.read(IN_EP, 512, timeout=2)
        except usb.core.USBError:
            pass
        c["upd"] += 1
        c["bytes"] += len(pkt)

    while not stop["now"]:
        item, new_seq = box.get(seq)
        if new_seq == seq or item is None:
            continue
        seq = new_seq
        tag, buf = item
        want = "T" if (tag == b"T" or (tag == b"F" and args.zoom)) else "S"

        if want == "T":
            frame = np.frombuffer(buf, dtype="<u2").reshape(TURBO[1], TURBO[0])
            if last_t is not None and cur == "T" and np.array_equal(frame, last_t):
                c["skip"] += 1
                t_rep = _maybe_report(c, t_rep, stats)
                continue
            data_pokes = cur_pokes if cur != "T" else POKES_ZOOM2      # data frame first with the OLD registers
            pkt = bytearray(make_header(0x89, args.mode, 0, TURBO[0] * TURBO[1] * 2 // ROW, 0, data_pokes)) + frame.tobytes()
            if cur != "T":
                pkt += poke_only(POKES_ZOOM2)                          # then switch to 2x zoom right after the flip
                c["sw"] += 1
                cur, cur_pokes = "T", POKES_ZOOM2
                last_s, need_full = None, 2                            # sharp buffers are stale now
            send(pkt)
            last_t = frame
            c["rows"] += TURBO[1]
            c["bands"] += 1
        else:
            frame = np.frombuffer(buf, dtype="<u2").reshape(H, W)
            switching = cur != "S"
            if need_full > 0 or args.full or last_s is None or switching:
                runs = [(0, H)]
                changed = np.ones(H, dtype=bool) if last_s is None else (frame != last_s).any(axis=1)
                need_full = max(need_full - 1, 0)
            else:
                changed = (frame != last_s).any(axis=1)
                if not changed.any():
                    c["skip"] += 1                   # identical to what is on the panel: send nothing
                    t_rep = _maybe_report(c, t_rep, stats)
                    continue
                runs = runs_from_mask(changed | prev_changed)
            pkt = build_update(frame, runs, 0x89, args.mode, cur_pokes)   # stay on the current registers while data arrives
            if switching:
                pkt += poke_only(POKES_NORMAL)       # 1:1 registers right after the flip
                c["sw"] += 1
                cur, cur_pokes = "S", POKES_NORMAL
                last_t = None
            send(pkt)
            last_s, prev_changed = frame, changed
            c["rows"] += sum(y1 - y0 for y0, y1 in runs)
            c["bands"] += len(runs)
        t_rep = _maybe_report(c, t_rep, stats)


def run_c444(dev, box, stats, stop, fresh=False, loading_frame=None):
    """Stage-2 12-bit mode: load the decoder blob into the running stage-1 stub and stream c444-packed frames (see c444.py / s2_c444.py)."""
    import c444, s2_c444, xq_load
    HDR_C4, HDR_ST = 0x34433156, 0x54533156

    def read_ack(want, timeout=3000):
        end = time.time() + timeout / 1000
        while time.time() < end:
            try:
                raw = bytes(dev.read(IN_EP, 512, timeout=1500))
            except usb.core.USBError:
                continue
            if raw[:4] == want:
                return True
        return False

    def stop_blob():
        dev.write(OUT_EP, xq_load.pkt(HDR_ST), timeout=4000)
        return read_ack(b"XQD1")

    dev.write(OUT_EP, bytes(PKT), timeout=4000)                     # first packet after a fresh load may be lost
    if not fresh:
        print("stopping any decoder blob still running ...", flush=True)
        stop_blob()
    # A fresh stage-1 starts with single-buffered OUT (0x88). V1ST is ignored
    # there, so it does NOT enable 0x89. Changing buffering in the XQ header
    # while its payload is already queued can lose the first code packet.
    # Complete a command/ack round trip BEFORE sending any blob data.
    print("synchronizing loader and USB buffering ...", flush=True)
    xq_load.cmd(dev, pokes=POKES_NORMAL)
    print("loading the stage-2 decoder blob ...", flush=True)
    blob=s2_c444.blob()
    xq_load.xq_load(dev, blob, 0x00800000, run=False)
    expected=list(struct.unpack('<4I',blob[:16]))
    actual=xq_load.cmd(dev,peeks=[0xa0800000+i*4 for i in range(4)])
    if actual!=expected:raise RuntimeError('Decoder code upload readback differs: '+repr(actual))
    print('DECODER_UPLOAD_VERIFIED: first instructions match',flush=True)
    xq_load.xq_load(dev,b'',0x00800000,run=True,wait=False)
    if not read_ack(b'C4RD',timeout=5000):
        raise RuntimeError('Decoder did not signal ready for its first frame')
    hdr = xq_load.pkt(HDR_C4, band=(0, c444.NPKT))
    # Verify that the decoder consumed an entire frame. Never report startup
    # success merely because the host accepted a TCP capture connection.
    loading=loading_frame.read_bytes() if loading_frame else bytes(c444.NPKT*PKT)
    if len(loading)!=c444.NPKT*PKT:raise RuntimeError('Loading artwork has incorrect packed frame size')
    dev.write(OUT_EP, hdr + loading, timeout=10000)
    if not read_ack(b"C4F1", timeout=5000):
        raise RuntimeError("Decoder did not acknowledge startup frame")
    print("DISPLAY_READY: packed decoder acknowledged loading picture", flush=True)
    last, seq, t_rep = None, 0, time.time()
    c = {"upd": 0, "skip": 0, "rows": 0, "bands": 0, "bytes": 0, "sw": 0}
    n_since_drain = 0
    try:
        while not stop["now"]:
            item, new_seq = box.get(seq)
            if new_seq == seq or item is None:
                continue
            seq = new_seq
            buf = item[1]
            if last is not None and buf == last:
                c["skip"] += 1
                t_rep = _maybe_report(c, t_rep, stats)
                continue
            data = hdr + bytes(buf)
            for off in range(0, len(data), 1 << 20):
                dev.write(OUT_EP, data[off:off + (1 << 20)], timeout=10000)
            if last is None:
                if not read_ack(b'C4F1',timeout=5000):raise RuntimeError('First desktop frame was not acknowledged')
                print('FIRST_DESKTOP_FRAME: acknowledged by frame',flush=True)
            last = buf
            c["upd"] += 1
            c["bytes"] += len(data)
            n_since_drain += 1
            if n_since_drain >= 8:                                   # keep the stub's IN endpoint free
                n_since_drain = 0
                try:
                    dev.read(IN_EP, 512, timeout=2)
                except usb.core.USBError:
                    pass
            t_rep = _maybe_report(c, t_rep, stats)
    finally:
        print("stopping the decoder blob (stub returns to its loader loop) ...", flush=True)
        stop_blob()


def _maybe_report(c, t_rep, stats):
    now = time.time()
    if now - t_rep >= 2.0:
        dt = now - t_rep
        upd = max(c["upd"], 1)
        print("updates %.1f/s | unchanged skipped %.1f/s | avg %d rows in %.1f bands | USB %.1f MB/s | received %.1f fps | mode switches %d" % (
            c["upd"] / dt, c["skip"] / dt, c["rows"] // upd, c["bands"] / upd, c["bytes"] / dt / 1e6, stats["rx"] / dt, c["sw"]), flush=True)
        for k in c:
            c[k] = 0
        stats["rx"] = 0
        return now
    return t_rep


if __name__ == "__main__":
    main()
