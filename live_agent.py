import argparse
import json
import os
import queue
import random
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REPLAY_LOG = os.path.join(SCRIPT_DIR, "last_live_replay.jsonl")

DIR_NAMES = {
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
    local = os.path.join(SCRIPT_DIR, path)
    return local if os.path.exists(local) else path


def clone_board(board):
    return [row[:] for row in board]


def max_tile(board):
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


def slide_left(line):
    tiles = [value for value in line if value]
    out = []
    reward = 0
    i = 0
    while i < len(tiles):
        if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:
            merged = tiles[i] * 2
            out.append(merged)
            reward += merged
            i += 2
        else:
            out.append(tiles[i])
            i += 1
    out.extend([0] * (4 - len(out)))
    return out, reward


def move_board(board, direction):
    next_board = [[0] * 4 for _ in range(4)]
    reward = 0

    if direction == 1:
        for row in range(4):
            next_board[row], gained = slide_left(board[row])
            reward += gained
    elif direction == 3:
        for row in range(4):
            moved, gained = slide_left(list(reversed(board[row])))
            next_board[row] = list(reversed(moved))
            reward += gained
    elif direction == 0:
        for col in range(4):
            moved, gained = slide_left([board[row][col] for row in range(4)])
            reward += gained
            for row in range(4):
                next_board[row][col] = moved[row]
    elif direction == 2:
        for col in range(4):
            moved, gained = slide_left([board[row][col] for row in reversed(range(4))])
            moved = list(reversed(moved))
            reward += gained
            for row in range(4):
                next_board[row][col] = moved[row]
    else:
        return clone_board(board), 0, False

    return next_board, reward, next_board != board


def has_moves(board):
    for row in range(4):
        for col in range(4):
            value = board[row][col]
            if value == 0:
                return True
            if row + 1 < 4 and board[row + 1][col] == value:
                return True
            if col + 1 < 4 and board[row][col + 1] == value:
                return True
    return False


class LiveAgentApp:
    def __init__(self, root, args):
        self.root = root
        self.args = args
        self.exe = resolve_path(args.exe)
        self.replay_log = resolve_path(args.replay_log)
        self.fixed_seed = args.seed is not None
        if self.args.seed is None:
            self.args.seed = self.fresh_seed()
        self.rng = random.Random(self.args.seed)
        self.board = [[0] * 4 for _ in range(4)]
        self.score = 0
        self.moves = 0
        self.auto_playing = False
        self.thinking = False
        self.result_queue = queue.Queue()
        self.last_nodes = 0
        self.last_source = ""
        self.last_dir = ""
        self.last_reward = 0

        self.root.title("2048 Live AI Agent")
        self.root.geometry("760x610")
        self.root.minsize(680, 560)
        self.root.configure(bg="#FAF8EF")
        self._build_ui()
        self._bind_keys()
        self.new_game(initial=True)

        if not getattr(args, "paused", False):
            self.root.after(300, self.toggle_auto)
        self.root.after(80, self._poll_result_queue)

    def _build_ui(self):
        title = tk.Label(
            self.root,
            text="2048 Live AI Agent",
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

        tk.Button(controls, text="New", command=self.new_game, width=8).grid(row=0, column=0, padx=3, pady=3)
        tk.Button(controls, text="AI Step", command=self.ai_step, width=8).grid(row=0, column=1, padx=3, pady=3)
        self.auto_button = tk.Button(controls, text="Auto", command=self.toggle_auto, width=8)
        self.auto_button.grid(row=0, column=2, padx=3, pady=3)

        tk.Button(controls, text="Up", command=lambda: self.manual_move(0), width=8).grid(row=1, column=1, padx=3, pady=3)
        tk.Button(controls, text="Left", command=lambda: self.manual_move(1), width=8).grid(row=2, column=0, padx=3, pady=3)
        tk.Button(controls, text="Down", command=lambda: self.manual_move(2), width=8).grid(row=2, column=1, padx=3, pady=3)
        tk.Button(controls, text="Right", command=lambda: self.manual_move(3), width=8).grid(row=2, column=2, padx=3, pady=3)

        tk.Label(side, text="Speed", bg="#FAF8EF", fg="#776E65").pack(anchor="w", pady=(8, 0))
        self.speed = tk.Scale(
            side,
            from_=500,
            to=0,
            orient="horizontal",
            bg="#FAF8EF",
            highlightthickness=0,
            length=220,
        )
        self.speed.set(self.args.speed)
        self.speed.pack(fill="x")
        speed_labels = tk.Frame(side, bg="#FAF8EF")
        speed_labels.pack(fill="x")
        tk.Label(speed_labels, text="Slow", bg="#FAF8EF", fg="#776E65").pack(side="left")
        tk.Label(speed_labels, text="Fast", bg="#FAF8EF", fg="#776E65").pack(side="right")

        self.status_label = tk.Label(
            side,
            text="",
            wraplength=230,
            justify="left",
            anchor="nw",
            bg="#FAF8EF",
            fg="#776E65",
        )
        self.status_label.pack(fill="both", expand=True, pady=(14, 0))

        self.tile_rects = []
        self.tile_texts = []
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

    def _bind_keys(self):
        self.root.bind("<Up>", lambda _event: self.manual_move(0))
        self.root.bind("<Left>", lambda _event: self.manual_move(1))
        self.root.bind("<Down>", lambda _event: self.manual_move(2))
        self.root.bind("<Right>", lambda _event: self.manual_move(3))
        self.root.bind("<space>", lambda _event: self.ai_step())
        self.root.bind("p", lambda _event: self.toggle_auto())
        self.root.bind("n", lambda _event: self.new_game())

    def new_game(self, initial=False):
        self.auto_playing = False
        self.thinking = False
        self.auto_button.config(text="Auto")
        if not initial:
            if not self.fixed_seed:
                self.args.seed = self.fresh_seed()
            self.rng = random.Random(self.args.seed)
        self.board = [[0] * 4 for _ in range(4)]
        self.score = 0
        self.moves = 0
        self.last_nodes = 0
        self.last_source = ""
        self.last_dir = ""
        self.last_reward = 0
        self.spawn_tile()
        self.spawn_tile()
        self.reset_replay_log()
        self.render()
        self.record_replay_event("start", -1, "system", 0, 0, "New game started.")
        self.set_status("Ready. Press Auto, AI Step, or arrow keys.")

    def spawn_tile(self):
        empty = [(row, col) for row in range(4) for col in range(4) if self.board[row][col] == 0]
        if not empty:
            return False
        row, col = self.rng.choice(empty)
        self.board[row][col] = 4 if self.rng.random() < 0.1 else 2
        return True

    @staticmethod
    def fresh_seed():
        return random.SystemRandom().randrange(1, 2_147_483_647)

    def render(self):
        for row in range(4):
            for col in range(4):
                value = self.board[row][col]
                bg, fg = TILE_COLORS.get(value, ("#2F6FA5", "#F9F6F2"))
                self.canvas.itemconfig(self.tile_rects[row][col], fill=bg)
                self.canvas.itemconfig(
                    self.tile_texts[row][col],
                    text="" if value == 0 else str(value),
                    fill=fg,
                    font=("Segoe UI", self._font_size(value), "bold"),
                )
        self.stat_label.config(
            text=(
                f"Score: {self.score}\n"
                f"Max:   {max_tile(self.board)}\n"
                f"Move:  {self.moves}\n"
                f"Dir:   {self.last_dir}\n"
                f"Src:   {self.last_source}\n"
                f"Nodes: {self.last_nodes}\n"
                f"Code:  {board_code(self.board)}"
            )
        )

    def _font_size(self, value):
        if value < 1000:
            return 24
        if value < 10000:
            return 21
        return 18

    def set_status(self, text):
        self.status_label.config(text=text)

    def manual_move(self, direction):
        if self.thinking:
            return
        self.auto_playing = False
        self.auto_button.config(text="Auto")
        self.apply_move(direction, "manual", 0, "manual")

    def ai_step(self):
        if self.thinking or not has_moves(self.board):
            return
        self.request_ai_move()

    def toggle_auto(self):
        if self.thinking and not self.auto_playing:
            return
        self.auto_playing = not self.auto_playing
        self.auto_button.config(text="Pause" if self.auto_playing else "Auto")
        if self.auto_playing and not self.thinking:
            self.request_ai_move()

    def request_ai_move(self):
        if self.thinking:
            return
        if not has_moves(self.board):
            self.finish_game("Game over.")
            return
        self.thinking = True
        snapshot = clone_board(self.board)
        self.set_status("Thinking...")
        thread = threading.Thread(target=self._ai_worker, args=(snapshot,), daemon=True)
        thread.start()

    def _ai_worker(self, snapshot):
        board_arg = ",".join(str(value) for row in snapshot for value in row)
        cmd = [
            self.exe,
            "--choose-board",
            board_arg,
            "--depth",
            str(self.args.depth),
            "--black-depth",
            str(self.args.black_depth),
            "--chance-limit",
            str(self.args.chance_limit),
            "--time-ms",
            str(self.args.time_ms),
        ]
        try:
            completed = subprocess.run(
                cmd,
                cwd=SCRIPT_DIR,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=self.args.ai_timeout,
            )
            if completed.returncode != 0:
                message = completed.stderr.strip() or completed.stdout.strip() or "agent failed"
                self.result_queue.put(("error", message))
                return
            output = completed.stdout.strip().splitlines()[-1]
            data = json.loads(output)
            self.result_queue.put(("move", snapshot, data))
        except Exception as exc:
            self.result_queue.put(("error", str(exc)))

    def _poll_result_queue(self):
        try:
            while True:
                item = self.result_queue.get_nowait()
                if item[0] == "error":
                    self.thinking = False
                    self.auto_playing = False
                    self.auto_button.config(text="Auto")
                    self.set_status(f"AI error:\n{item[1]}")
                    self.record_replay_event("error", -1, "ai", 0, 0, item[1])
                    messagebox.showerror("AI error", item[1])
                elif item[0] == "move":
                    _kind, snapshot, data = item
                    self.thinking = False
                    if snapshot != self.board:
                        continue
                    direction = int(data.get("dir", -1))
                    self.apply_move(
                        direction,
                        data.get("source", "search"),
                        int(data.get("nodes", 0)),
                        "ai",
                    )
        except queue.Empty:
            pass
        self.root.after(80, self._poll_result_queue)

    def apply_move(self, direction, source, nodes, actor):
        next_board, reward, moved = move_board(self.board, direction)
        if not moved:
            if actor == "ai":
                self.finish_game(f"AI returned illegal move: {direction}")
            return
        self.board = next_board
        self.score += reward
        self.moves += 1
        self.spawn_tile()
        self.last_dir = DIR_NAMES.get(direction, str(direction))
        self.last_nodes = nodes
        self.last_source = source
        self.last_reward = reward
        self.render()
        self.record_replay_event(actor, direction, source, nodes, reward, "Move applied.")

        current_max = max_tile(self.board)
        if self.moves >= self.args.max_moves:
            self.finish_game(f"Stopped at max moves: {self.args.max_moves}.")
            return
        if self.args.stop_at_target and current_max >= self.args.target:
            self.finish_game(f"Reached {self.args.target}.")
            return
        if not has_moves(self.board):
            self.finish_game("Game over.")
            return

        self.set_status("Auto running." if self.auto_playing else "Ready.")
        if self.auto_playing:
            self.root.after(max(0, int(self.speed.get())), self.request_ai_move)

    def finish_game(self, message):
        self.auto_playing = False
        self.thinking = False
        self.auto_button.config(text="Auto")
        self.render()
        self.record_replay_event("finish", -1, "system", 0, 0, message)
        self.set_status(message)

    def reset_replay_log(self):
        try:
            with open(self.replay_log, "w", encoding="utf-8") as handle:
                handle.write("")
        except OSError as exc:
            self.set_status(f"Replay log error: {exc}")

    def record_replay_event(self, event, direction, source, nodes, reward, status):
        payload = {
            "event": event,
            "move": self.moves,
            "dir": int(direction),
            "dir_name": DIR_NAMES.get(direction, ""),
            "source": str(source),
            "nodes": int(nodes),
            "reward": int(reward),
            "score": int(self.score),
            "max": int(max_tile(self.board)),
            "seed": int(self.args.seed),
            "status": str(status),
            "board": clone_board(self.board),
        }
        try:
            with open(self.replay_log, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError as exc:
            self.set_status(f"Replay log error: {exc}")


def parse_args():
    parser = argparse.ArgumentParser(description="Live 2048 board driven by cpp_2048_agent.")
    parser.add_argument("--exe", default="cpp_2048_agent.exe")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--target", type=int, default=16384)
    parser.add_argument("--depth", type=int, default=5)
    parser.add_argument("--black-depth", type=int, default=5)
    parser.add_argument("--chance-limit", type=int, default=6)
    parser.add_argument("--time-ms", type=int, default=0)
    parser.add_argument("--max-moves", type=int, default=10000)
    parser.add_argument("--speed", type=int, default=60, help="Initial delay in ms; 0 is fastest.")
    parser.add_argument("--ai-timeout", type=float, default=120.0)
    parser.add_argument("--stop-at-target", action="store_true")
    parser.add_argument("--paused", action="store_true")
    parser.add_argument("--replay-log", default=DEFAULT_REPLAY_LOG)
    return parser.parse_args()


def run_live(args):
    args.exe = resolve_path(args.exe)
    if not os.path.exists(args.exe):
        print(f"Executable not found: {args.exe}", file=sys.stderr)
        sys.exit(1)
    if not hasattr(args, "ai_timeout"):
        args.ai_timeout = 120.0
    if not hasattr(args, "paused"):
        args.paused = False
    root = tk.Tk()
    LiveAgentApp(root, args)
    root.mainloop()


def main():
    run_live(parse_args())


if __name__ == "__main__":
    main()
