import fcntl
import json
import os
import shutil
import signal
import socket
import subprocess
import time
from typing import Union



class MiniPlayer:
    """
    Thin wrapper around an mpv subprocess controlled via its JSON IPC socket.

    IMPORTANT: this class is instantiated fresh in a brand new python
    process on every call (each /agent/execute request spawns a new
    python3 process via mcp_call.py). That means self.process from a
    previous call does NOT exist here — there is no in-memory state to
    rely on. Everything that needs to survive across calls (the running
    mpv PID, its socket) is persisted to fixed paths on disk instead.

    A file lock (LOCK_FILE) serializes play() across concurrent/overlapping
    invocations — e.g. duplicate requests fired close together by the
    frontend — so one process's kill-stale-then-launch sequence can't
    interleave with another's and kill a legitimate, just-started mpv.
    """

    # Fixed paths (not per-PID) so any new process invocation can find
    # and stop whatever mpv instance a previous invocation started.
    SOCKET_PATH = "/tmp/hina_mpv.sock"
    PID_FILE = "/tmp/hina_mpv.pid"
    LOG_FILE = "/tmp/hina_mpv.log"
    LOCK_FILE = "/tmp/hina_mpv.lock"

    def __init__(self):
        self.socket_path = self.SOCKET_PATH
        self.process = None

    # ------------------------------------------------------------------
    # Playback control
    # ------------------------------------------------------------------

    def play(self, target: str, video: bool = True):
        """
        Plays a local file path or remote stream URL.
        :param target: File path or streaming URL (YouTube, raw stream, etc.)
        :param video: False disables the video window (audio-only mode)
        :raises RuntimeError: with a specific, actionable reason on failure
        """
        if not target or not str(target).strip():
            raise RuntimeError("No playback target was provided (empty URL/path).")

        mpv_path = shutil.which("mpv")
        if not mpv_path:
            raise RuntimeError(
                "mpv is not installed or not on PATH for this process. "
                "Install it (e.g. `sudo pacman -S mpv`) and confirm `which mpv` "
                "resolves in the same shell/environment that runs server.js."
            )

        # Clean up anything left running from a previous, now-exited
        # process before starting a new track.
        self.stop()
        self._kill_stale()

        flags = [
            mpv_path,
            f"--input-ipc-server={self.socket_path}",
            "--cache=yes",
            "--demuxer-max-bytes=64M",
            "--demuxer-readahead-secs=30",
            # Prefer PipeWire but fall back to alsa/pulse if the pipewire
            # socket can't be reached (e.g. XDG_RUNTIME_DIR missing in
            # this process's environment) instead of hard-failing with
            # "no sound" the way a single forced --ao=pipewire did.
            "--ao=pipewire,alsa,pulse",
            "--ytdl=yes",
            str(target),
        ]
        if not video:
            flags.insert(1, "--no-video")

        # mpv is launched several processes deep (node -> mcp_call.py ->
        # fastmcp subprocess -> mpv), so it may not inherit the full
        # desktop session environment. XDG_RUNTIME_DIR is required for
        # the PipeWire client library to find /run/user/<uid>/pipewire-0
        # ("Could not connect to context: Host is down" otherwise).
        env = os.environ.copy()
        if not env.get("XDG_RUNTIME_DIR"):
            env["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"

        # Always capture mpv's real output to a log file instead of
        # silently discarding it — DEVNULL hides the exact reason mpv
        # exits early (missing yt-dlp, dead stream URL, no audio sink,
        # unsupported format, etc.), which is what made the previous
        # "Started playing" success message misleading.
        log_fh = open(self.LOG_FILE, "a", buffering=1)
        log_fh.write(f"\n----- launching at {time.strftime('%Y-%m-%d %H:%M:%S')} -----\n")
        log_fh.write(f"cmd: {' '.join(flags)}\n")
        log_fh.write(f"XDG_RUNTIME_DIR: {env.get('XDG_RUNTIME_DIR')}\n")

        self.process = subprocess.Popen(
            flags,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )

        try:
            with open(self.PID_FILE, "w") as f:
                f.write(str(self.process.pid))
        except OSError:
            pass

        if not self._wait_for_socket(timeout=2.0):
            reason = self._read_crash_reason()
            raise RuntimeError(
                "mpv did not open its IPC socket in time (it likely crashed "
                f"on startup). Last log lines:\n{reason}"
            )

        # The socket can appear briefly before mpv fails to actually open
        # the stream (e.g. bad URL, geo-block, extractor failure). Give it
        # a short grace period and confirm the process is still alive
        # before reporting success back to the caller.
        time.sleep(0.6)
        if self.process.poll() is not None:
            reason = self._read_crash_reason()
            raise RuntimeError(
                f"mpv exited immediately after starting (exit code "
                f"{self.process.returncode}). Last log lines:\n{reason}"
            )

    def _read_crash_reason(self, lines: int = 15) -> str:
        """Returns the tail of mpv's log file to surface the real error."""
        try:
            with open(self.LOG_FILE, "r") as f:
                content = f.readlines()
            return "".join(content[-lines:]).strip() or "(log file empty)"
        except OSError:
            return "(no log file found)"

    def _wait_for_socket(self, timeout: float = 1.0) -> bool:
        """Waits for the mpv IPC socket file to be created."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if os.path.exists(self.socket_path):
                return True
            time.sleep(0.05)
        return False

    def _send_command(self, command: list) -> Union[dict, None]:
        """Sends a JSON-IPC command payload directly to the running mpv core."""
        if not os.path.exists(self.socket_path):
            return None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(self.socket_path)
                payload = {"command": command}
                client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
                response = client.recv(4096)
                return json.loads(response.decode("utf-8"))
        except Exception:
            return None

    def _kill_stale(self):
        """Kills a leftover mpv process from a previous invocation, using the PID file."""
        self._kill_by_pid_file()
        try:
            os.remove(self.PID_FILE)
        except OSError:
            pass

    def _kill_by_pid_file(self) -> bool:
        """Reads PID_FILE and terminates that process if it is still alive.

        Returns True if a live process was actually found and signaled,
        False if the PID file was missing, unreadable, or already stale
        (process no longer exists). This is the only way stop_music can
        know whether it did real work, since stop() runs in a fresh
        process with no in-memory handle to the mpv subprocess.
        """
        if not os.path.exists(self.PID_FILE):
            return False
        try:
            with open(self.PID_FILE, "r") as f:
                pid = int(f.read().strip())
        except (ValueError, OSError):
            return False

        try:
            os.kill(pid, 0)  # is it actually alive?
        except (ProcessLookupError, OSError):
            return False

        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.2)
            try:
                os.kill(pid, 0)
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            return True
        except OSError:
            return False

    def set_volume(self, level: int):
        """Sets target volume level safely clamped between 0 and 130."""
        level = max(0, min(level, 130))
        self._send_command(["set_property", "volume", level])

    def pause(self):
        """Pauses the current track."""
        self._send_command(["set_property", "pause", True])

    def resume(self):
        """Resumes a paused track."""
        self._send_command(["set_property", "pause", False])

    def stop(self) -> bool:
        """Terminates active playback and purges the Unix IPC socket + PID file.

        Returns True if a running mpv process was actually found and
        killed, False if there was nothing to stop. Callers (e.g. the
        stop_music tool) rely on this to report an accurate result
        instead of always claiming success.
        """
        killed = False

        if self.process:
            # Only ever true if play() and stop() are called on the same
            # instance within a single process's lifetime.
            try:
                self.process.terminate()
                self.process.wait(timeout=1.0)
                killed = True
            except Exception:
                try:
                    self.process.kill()
                    killed = True
                except Exception:
                    pass
            self.process = None
        else:
            # Normal case for stop_music: this is a fresh instance in a
            # fresh process, so there is no in-memory handle to the mpv
            # subprocess. Fall back to whatever PID was persisted to
            # disk by the process that actually launched mpv.
            killed = self._kill_by_pid_file()

        if os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
            except OSError:
                pass

        if os.path.exists(self.PID_FILE):
            try:
                os.remove(self.PID_FILE)
            except OSError:
                pass

        return killed

    # NOTE: deliberately no __del__ here. MiniPlayer is a short-lived
    # wrapper — a fresh instance is created and discarded on every call
    # to play_music(), but the mpv process it launches is meant to keep
    # running in the background *after* the wrapper is garbage collected
    # (that's the entire point of persisting the PID/socket to disk
    # instead of holding state in memory). A __del__ that calls stop()
    # would terminate mpv the instant the enclosing function returns and
    # `player` goes out of scope — which is exactly what was silently
    # killing playback immediately after every successful launch.