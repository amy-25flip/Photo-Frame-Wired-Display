#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Windows side of the V100 wired monitor: capture a monitor, fit it into the target size, convert to RGB565 and push
frames to frame_sender.py (running in WSL) over localhost TCP.

Capture and processing run in two threads so grabbing the next frame overlaps resizing/converting/sending the last one.

usage: python mirror.py [--monitor 1] [--fps 60] [--size 1024x600 | --turbo | --auto] [--host 127.0.0.1] [--port 9100]
                        [--stretch] [--test N] [--hi 0.12] [--lo 0.03] [--calm 0.6]
  --monitor N   mss monitor index (1 = primary, 2 = next ...; 0 = all monitors joined)
  --size WxH    frame size to send (must match frame_sender.py: 1024x600 normally, 512x300 with --zoom)
  --turbo       shorthand for --size 512x300 (use with frame_sender.py --zoom: the display engine enlarges it 2x)
  --auto        send SHARP 1024x600 frames while the screen is calm and TURBO 512x300 frames while large areas are
                moving (use with frame_sender.py --auto). A thumbnail motion detector with hysteresis decides:
                  turbo after 3 consecutive frames where >= --hi (default 12 %) of the thumbnail changed,
                  back to sharp after --calm seconds (default 0.6) with < --lo (default 3 %) changed.
  --stretch     fill the frame (distorts) instead of letterboxing to keep the aspect ratio
  --test N      send N frames then exit (and print timing)
"""
import argparse, socket, struct, sys, threading, time
import cv2
import mss
import numpy as np
import c444

SHARP = (1024, 600)
TURBO = (512, 300)
TAG_S, TAG_T = b"S\0\0\0", b"T\0\0\0"


def fit(shot, size, stretch):
    """Resize a BGR capture into `size` (letterboxed unless stretch) and convert to RGB565 bytes."""
    W, H = size
    if stretch:
        canvas = cv2.resize(shot, (W, H), interpolation=cv2.INTER_AREA)
    else:
        s = min(W / shot.shape[1], H / shot.shape[0])
        nw, nh = max(1, round(shot.shape[1] * s)), max(1, round(shot.shape[0] * s))
        small = cv2.resize(shot, (nw, nh), interpolation=cv2.INTER_AREA)
        canvas = np.zeros((H, W, 3), dtype=np.uint8)
        y0, x0 = (H - nh) // 2, (W - nw) // 2
        canvas[y0:y0 + nh, x0:x0 + nw] = small
    return cv2.cvtColor(canvas, cv2.COLOR_BGR2BGR565).tobytes()   # BGR in -> RGB565 out (red in the high bits)


def fit_c444(shot, stretch, dither):
    """Resize into 1024x600 (letterboxed unless stretch), RGB order, quantize to 12 bit (ordered dither) and pack for the stage-2 decoder."""
    W, H = SHARP
    if stretch:
        canvas = cv2.resize(shot, (W, H), interpolation=cv2.INTER_AREA)
    else:
        s = min(W / shot.shape[1], H / shot.shape[0])
        nw, nh = max(1, round(shot.shape[1] * s)), max(1, round(shot.shape[0] * s))
        small = cv2.resize(shot, (nw, nh), interpolation=cv2.INTER_AREA)
        canvas = np.zeros((H, W, 3), dtype=np.uint8)
        y0, x0 = (H - nh) // 2, (W - nw) // 2
        canvas[y0:y0 + nh, x0:x0 + nw] = small
    return c444.encode(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB), dither)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--monitor", type=int, default=1)
    ap.add_argument("--display-device", help="Stable Windows display name (e.g. \\\\.\\DISPLAY10); never falls back to primary")
    ap.add_argument("--cursor", action="store_true", help="Draw a pointer on Windows captures")
    ap.add_argument("--fps", type=float, default=60.0)
    ap.add_argument("--size", default="1024x600")
    ap.add_argument("--turbo", action="store_true")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--c444", action="store_true", help="12-bit packed frames for frame_sender.py --c444 (stage-2 decoder, ~29 fps at 1024x600)")
    ap.add_argument("--nodither", action="store_true", help="--c444: plain rounding instead of ordered dithering")
    ap.add_argument("--hi", type=float, default=0.12)
    ap.add_argument("--lo", type=float, default=0.03)
    ap.add_argument("--calm", type=float, default=0.6)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9100)
    ap.add_argument("--stretch", action="store_true")
    ap.add_argument("--test", type=int, default=0)
    args = ap.parse_args()
    size = TURBO if args.turbo else tuple(int(v) for v in args.size.lower().split("x"))

    sock = socket.create_connection((args.host, args.port), timeout=10)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.settimeout(None)
    print("connected to frame_sender at %s:%d, %s" % (args.host, args.port, "AUTO sharp<->turbo" if args.auto else "sending %dx%d frames" % size), flush=True)

    latest = {"img": None, "seq": 0, "grab_ms": 0.0}
    cv = threading.Condition()
    stop = threading.Event()

    def grabber():
        with mss.MSS() as sct:                           # mss handles are per-thread
            if args.display_device:
                import display_manager
                choices=[d for d in display_manager.displays() if d['name']==args.display_device and d['attached']]
                if len(choices)!=1:
                    stop.set()
                    with cv: cv.notify_all()
                    return
                d=choices[0]
                mon={k:d[k] for k in ('left','top','width','height')}
            else:
                mon = sct.monitors[args.monitor]
            print("capturing monitor %d: %dx%d" % (args.monitor, mon["width"], mon["height"]), flush=True)
            interval = 1.0 / args.fps
            try:                                          # 1 ms Windows timer resolution: accurate frame pacing
                import ctypes
                ctypes.windll.winmm.timeBeginPeriod(1)
            except Exception:
                pass
            next_t = time.perf_counter()
            while not stop.is_set():
                t0 = time.perf_counter()
                shot = np.asarray(sct.grab(mon))[:, :, :3]       # BGRA -> BGR view
                if args.cursor:
                    import ctypes as ct
                    from ctypes import wintypes as wt
                    class CURSORINFO(ct.Structure):
                        _fields_=[('cbSize',wt.DWORD),('flags',wt.DWORD),('hCursor',wt.HANDLE),('ptScreenPos',wt.POINT)]
                    ci=CURSORINFO();ci.cbSize=ct.sizeof(ci)
                    if ct.windll.user32.GetCursorInfo(ct.byref(ci)) and ci.flags&1:
                        x,y=ci.ptScreenPos.x-mon['left'],ci.ptScreenPos.y-mon['top']
                        if 0<=x<mon['width'] and 0<=y<mon['height']:
                            shot=np.ascontiguousarray(shot)
                            points=np.array([(x,y),(x,y+20),(x+5,y+15),(x+10,y+23),(x+13,y+21),(x+8,y+13),(x+16,y+13)],dtype=np.int32)
                            cv2.fillPoly(shot,[points],(255,255,255))
                            cv2.polylines(shot,[points],True,(0,0,0),1)
                with cv:
                    latest["img"], latest["grab_ms"] = shot, (time.perf_counter() - t0) * 1000
                    latest["seq"] += 1
                    cv.notify()
                next_t += interval                          # fixed schedule (no drift): frame n is due at start + n/fps
                now = time.perf_counter()
                if next_t < now - interval:                 # more than a frame late (e.g. system hiccup): resync, never burst
                    next_t = now
                rest = next_t - now
                if rest > 0.0015:
                    time.sleep(rest - 0.001)
                while time.perf_counter() < next_t:         # spin the last ~1 ms for an exact tick
                    pass

    threading.Thread(target=grabber, daemon=True).start()

    sent, seq, t_start = 0, 0, time.time()
    t_rep, sent_rep = time.time(), 0
    acc = {"proc": 0.0, "send": 0.0, "grab": 0.0, "n": 0, "S": 0, "T": 0}
    # auto-mode state
    mode, hi_count, calm_since, force_s = "S", 0, None, True
    prev_thumb, last_big, switches = None, None, 0
    try:
        while True:
            with cv:
                while latest["seq"] == seq:
                    if stop.is_set():
                        raise RuntimeError("Requested display is unavailable")
                    cv.wait(1.0)
                seq, shot, grab_ms = latest["seq"], latest["img"], latest["grab_ms"]
            t0 = time.perf_counter()
            if args.auto:
                thumb = cv2.resize(shot, (128, 75), interpolation=cv2.INTER_AREA)
                frac = 0.0
                if prev_thumb is not None:
                    d = cv2.absdiff(thumb, prev_thumb).max(axis=2)
                    frac = float(np.count_nonzero(d > 12)) / d.size
                prev_thumb = thumb
                now = time.time()
                if mode == "S":
                    hi_count = hi_count + 1 if frac >= args.hi else 0
                    if hi_count >= 3:
                        mode, calm_since, switches = "T", None, switches + 1
                else:
                    if frac < args.lo:
                        calm_since = calm_since or now
                        if now - calm_since >= args.calm:
                            mode, force_s, hi_count, switches = "S", True, 0, switches + 1
                    else:
                        calm_since = None
                if mode == "T":
                    payload = TAG_T + fit(shot, TURBO, args.stretch)
                else:
                    big = fit(shot, SHARP, args.stretch)
                    if not force_s and big == last_big:
                        acc["n"] += 0
                        continue                              # screen unchanged: send nothing
                    last_big, force_s = big, False
                    payload = TAG_S + big
                acc[mode] += 1
            elif args.c444:
                payload = fit_c444(shot, args.stretch, not args.nodither)
            else:
                payload = fit(shot, size, args.stretch)
            t1 = time.perf_counter()
            sock.sendall(payload)
            t2 = time.perf_counter()
            sent += 1
            acc["proc"] += (t1 - t0) * 1000; acc["send"] += (t2 - t1) * 1000; acc["grab"] += grab_ms; acc["n"] += 1
            now = time.time()
            if now - t_rep >= 2.0:
                n = max(acc["n"], 1)
                extra = " | mode %s (sharp %d, turbo %d frames, %d switches)" % (mode, acc["S"], acc["T"], switches) if args.auto else ""
                print("sending %.1f fps | grab %.1f ms | resize+convert %.1f ms | tcp send %.1f ms%s" % (
                    (sent - sent_rep) / (now - t_rep), acc["grab"] / n, acc["proc"] / n, acc["send"] / n, extra), flush=True)
                t_rep, sent_rep = now, sent
                acc = {"proc": 0.0, "send": 0.0, "grab": 0.0, "n": 0, "S": 0, "T": 0}
            if args.test and sent >= args.test:
                print("test done: %d frames in %.2f s" % (sent, now - t_start))
                return
    finally:
        stop.set()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
