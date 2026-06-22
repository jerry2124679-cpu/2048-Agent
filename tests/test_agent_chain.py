import json
import os
import subprocess
import unittest

import live_agent
import replay_agent


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestAgentChain(unittest.TestCase):
    def test_live_move_board_merges_once(self):
        board = [
            [2, 2, 2, 0],
            [4, 4, 4, 4],
            [0, 0, 0, 0],
            [8, 0, 8, 8],
        ]

        moved_board, reward, moved = live_agent.move_board(board, 1)

        self.assertTrue(moved)
        self.assertEqual(moved_board[0], [4, 2, 0, 0])
        self.assertEqual(moved_board[1], [8, 8, 0, 0])
        self.assertEqual(moved_board[3], [16, 8, 0, 0])
        self.assertEqual(reward, 36)

    def test_board_code(self):
        board = [
            [0, 2, 4, 8],
            [16, 32, 64, 128],
            [256, 512, 1024, 2048],
            [4096, 8192, 16384, 32768],
        ]

        self.assertEqual(live_agent.board_code(board), "0123456789ABCDEF")
        self.assertEqual(replay_agent.board_code(board), "0123456789ABCDEF")

    def test_replay_board_validation(self):
        self.assertTrue(replay_agent.is_valid_board([[0, 2, 4, 8]] * 4))
        self.assertFalse(replay_agent.is_valid_board([[0, 2, 4]] * 4))

    @unittest.skipUnless(
        os.path.exists(os.path.join(ROOT, "cpp_2048_agent.exe")),
        "cpp_2048_agent.exe is not available",
    )
    def test_cpp_choose_board_json_interface(self):
        exe = os.path.join(ROOT, "cpp_2048_agent.exe")
        completed = subprocess.run(
            [
                exe,
                "--choose-board",
                "2,2,0,0,4,0,0,0,0,0,0,0,0,0,0,0",
                "--depth",
                "2",
                "--black-depth",
                "3",
                "--chance-limit",
                "2",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertIn(payload["dir"], [0, 1, 2, 3])
        self.assertTrue(payload["moved"])
        self.assertGreaterEqual(payload["nodes"], 1)


if __name__ == "__main__":
    unittest.main()

