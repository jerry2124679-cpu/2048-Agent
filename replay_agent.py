import argparse
import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REPLAY_LOG = os.path.join(SCRIPT_DIR, "last_live_replay.jsonl")

DIR_NAMES = {
    -1: "",
    0: "Up",
    1: "Left",
    2: "Down",
    3: "Right",
}

TILE_COLORS = {
    0: ("#CDC1B4", "#776E65"),
    2: ("#EEE4DA", "#776E65"),
    4: ("#EDE0C8", "#776E65"),
    8: ("#F2B179", "#F9F6F2"),
    16: ("#F59563", "#F9F6F2"),
    32: ("#F67C5F", "#F9F6F2"),
    64: ("#F65E3B", "#F9F6F2"),
    128: ("#EDCF72", "#F9F6F2"),
    256: ("#EDCC61", "#F9F6F2"),
    512: ("#EDC850", "#F9F6F2"),
    1024: ("#EDC53F", "#F9F6F2"),
    2048: ("#EDC22E", "#F9F6F2"),
    4096: ("#5EA7D8", "#F9F6F2"),
    8192: ("#4C7BD9", "#F9F6F2"),
    16384: ("#3E4FB8", "#F9F6F2"),
    32768: ("#2B2F8F", "#F9F6F2"),
}


def resolve_path(path):
    if os.path.isabs(path):
        return path
    return os.path.join(SCRIPT_DIR, path)


def max_tile(board):
    if not board:
        return 0
    return max(max(row) for row in board)


def tile_code(value):
    if value == 0:
        return "0"
    if value > 0 and value & (value - 1) == 0:
        exp = value.bit_length() - 1
        if 0 <= exp <= 15:
            return "0123456789ABCDEF"[exp]
    return "?"


def board_code(board):
    return "".join(tile_code(value) for row in board for value in row)


def is_valid_board(board):
    if not isinstance(board, list) or len(board) != 4:
        return False
    for row in board:
        if not isinstance(row, list) or len(row) != 4:
            return False
        for value in row:
            if not isinstance(value, int) or value < 0:
                return False
    return True


class ReplayAgentApp:
    def __init__(self, root, args):
        self.root = root
        self.args = args
        self.replay_path = resolve_path(args.replay)
        self.frames = []
        self.index = 0
        self.playing = False
        self.after_id = None

        self.root.title("2048 Live Replay")
        self.root.geometry("760x610")
        self.root.minsize(680, 560)
        self.root.configure(bg="#FAF8EF")

        self.tile_rects = []
        self.tile_texts = []
        self._build_ui()
        self.load_replay(self.replay_path, quiet=True)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        title = tk.Label(
            self.root,
            text="2048 Live Replay",
            font=("Segoe UI", 20, "bold"),
            bg="#FAF8EF",
            fg="#776E65",
        )
        title.pack(pady=(16, 8))

        main = tk.Frame(self.root, bg="#FAF8EF")
        main.pack(fill="both", expand=True, padx=18, pady=8)

        self.canvas = tk.Canvas(
            main,
            width=452,
            height=452,
            bg="#BBADA0",
            highlightthickness=0,
        )
        self.canvas.pack(side="left", padx=(0, 18), pady=4)

        side = tk.Frame(main, bg="#FAF8EF")
        side.pack(side="left", fill="both", expand=True)

        self.stat_label = tk.Label(
            side,
            text="",
            justify="left",
            anchor="nw",
            font=("Consolas", 12),
            bg="#FAF8EF",
            fg="#776E65",
        )
        self.stat_label.pack(fill="x", pady=(8, 12))

        controls = tk.Frame(side, bg="#FAF8EF")
        controls.pack(fill="x", pady=(0, 10))

        tk.Button(controls, text="Open", command=self.open_replay, width=8).grid(row=0, column=0, padx=3, pady=3)
        tk.Button(controls, text="Play", command=self.play, width=8).grid(row=0, column=1, padx=3, pady=3)
        tk.Button(controls, text="Pause", command=self.pause, width=8).grid(row=0, column=2, padx=3, pady=3)
        tk.Button(controls, text="Prev", command=self.prev_frame, width=8).grid(row=1, column=0, padx=3, pady=3)
        tk.Button(controls, text="Next", command=self.next_frame, width=8).grid(row=1, column=1, padx=3, pady=3)
        tk.Button(controls, text="Reset", command=self.reset, width=8).grid(row=1, column=2, padx=3, pady=3)

        tk.Label(side, text="Speed", bg="#FAF8EF", fg="#776E65").pack(anchor="w", pady=(8, 0))
        self.speed = tk.Scale(
            side,
            from_=800,
            to=0,
            orient="horizontal",
            bg="#FAF8EF",
            highlightthickness=0,
            length=220,
        )
        self.speed.set(self.args.speed)
        self.speed.pack(fill="x")

        self.progress = tk.Scale(
            side,
            from_=0,
            to=0,
            orient="horizontal",
            bg="#FAF8EF",
            highlightthickness=0,
            length=220,
            command=self.seek,
        )
        self.progress.pack(fill="x", pady=(10, 0))

        self.status_label = tk.Label(
            side,
            text="No replay loaded.",
            wraplength=230,
            justify="left",
            anchor="nw",
            bg="#FAF8EF",
            fg="#776E65",
        )
        self.status_label.pack(fill="both", expand=True, pady=(14, 0))

        gap = 12
        tile = 95
        for row in range(4):
            rect_row = []
            text_row = []
            for col in range(4):
                x0 = gap + col * (tile + gap)
                y0 = gap + row * (tile + gap)
                x1 = x0 + tile
                y1 = y0 + tile
                rect = self.canvas.create_rectangle(x0, y0, x1, y1, fill="#CDC1B4", outline="", width=0)
                text = self.canvas.create_text(
                    (x0 + x1) // 2,
                    (y0 + y1) // 2,
                    text="",
                    font=("Segoe UI", 24, "bold"),
                    fill="#776E65",
                )
                rect_row.append(rect)
                text_row.append(text)
            self.tile_rects.append(rect_row)
            self.tile_texts.append(text_row)

    def open_replay(self):
        path = filedialog.askopenfilename(
            title="Open live replay",
            initialdir=SCRIPT_DIR,
            filetypes=[("JSON Lines", "*.jsonl"), ("All files", "*.*")],
        )
        if path:
            self.load_replay(path)

    def load_replay(self, path, quiet=False):
        self.pause()
        frames = []
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for line_no, line in enumerate(handle, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    frame = json.loads(line)
                    board = frame.get("board")
                    if not is_valid_board(board):
                        raise ValueError(f"invalid board at line {line_no}")
                    frames.append(frame)
        except FileNotFoundError:
            self.frames = []
            self.index = 0
            self.render_empty()
            self.status_label.config(text=f"No replay file found:\n{path}")
            if not quiet:
                messagebox.showwarning("Replay not found", path)
            return
        except Exception as exc:
            self.frames = []
            self.index = 0
            self.render_empty()
            self.status_label.config(text=f"Could not load replay:\n{exc}")
            if not quiet:
                messagebox.showerror("Could not load replay", str(exc))
            return

        self.replay_path = path
        self.frames = frames
        self.index = 0
        self.progress.config(to=max(0, len(frames) - 1))
        self.render_frame()
        self.status_label.config(text=f"Loaded {len(frames)} frame(s)\n{path}")

    def render_empty(self):
        self._draw_board([[0, 0, 0, 0] for _ in range(4)])
        self.stat_label.config(text="No replay loaded")
        self.progress.config(to=0)

    def _draw_board(self, board):
        for row in range(4):
            for col in range(4):
                value = board[row][col]
                bg, fg = TILE_COLORS.get(value, ("#2F6FA5", "#F9F6F2"))
                self.canvas.itemconfig(self.tile_rects[row][col], fill=bg)
                self.canvas.itemconfig(
                    self.tile_texts[row][col],
                    text="" if value == 0 else str(value),
                    fill=fg,
                    font=("Segoe UI", self._font_size(value), "bold"),
                )

    @staticmethod
    def _font_size(value):
        if value < 1000:
            return 24
        if value < 10000:
            return 21
        return 18

    def render_frame(self):
        if not self.frames:
            self.render_empty()
            return

        frame = self.frames[self.index]
        board = frame["board"]
        self._draw_board(board)

        direction = frame.get("dir_name") or DIR_NAMES.get(frame.get("dir", -1), "")
        text = (
            f"Frame: {self.index + 1}/{len(self.frames)}\n"
            f"Event: {frame.get('event', '')}\n"
            f"Score: {frame.get('score', 0)}\n"
            f"Max:   {frame.get('max', max_tile(board))}\n"
            f"Move:  {frame.get('move', 0)}\n"
            f"Dir:   {direction}\n"
            f"Src:   {frame.get('source', '')}\n"
            f"Nodes: {frame.get('nodes', 0)}\n"
            f"Code:  {board_code(board)}"
        )
        self.stat_label.config(text=text)
        if int(self.progress.get()) != self.index:
            self.progress.set(self.index)
        self.status_label.config(text=frame.get("status", ""))

    def seek(self, value):
        if not self.frames:
            return
        next_index = max(0, min(int(float(value)), len(self.frames) - 1))
        if next_index != self.index:
            self.index = next_index
            self.render_frame()

    def reset(self):
        self.pause()
        self.index = 0
        self.render_frame()

    def prev_frame(self):
        self.pause()
        if self.frames:
            self.index = max(0, self.index - 1)
            self.render_frame()

    def next_frame(self):
        self.pause()
        if self.frames:
            self.index = min(len(self.frames) - 1, self.index + 1)
            self.render_frame()

    def play(self):
        if not self.frames:
            return
        if self.index >= len(self.frames) - 1:
            self.index = 0
            self.render_frame()
        self.playing = True
        self.schedule_next()

    def pause(self):
        self.playing = False
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None

    def schedule_next(self):
        if not self.playing:
            return
        if self.index >= len(self.frames) - 1:
            self.pause()
            return
        self.index += 1
        self.render_frame()
        self.after_id = self.root.after(max(0, int(self.speed.get())), self.schedule_next)

    def on_close(self):
        self.pause()
        self.root.destroy()


def parse_args():
    parser = argparse.ArgumentParser(description="Replay the last live_agent session.")
    parser.add_argument("--replay", default=DEFAULT_REPLAY_LOG)
    parser.add_argument("--speed", type=int, default=120)
    return parser.parse_args()


def main():
    root = tk.Tk()
    ReplayAgentApp(root, parse_args())
    root.mainloop()


if __name__ == "__main__":
    main()

