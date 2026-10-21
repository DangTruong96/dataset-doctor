"""Tests for dataset_doctor. Run: python -m unittest discover -s tests -v"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dataset_doctor as dd

ROOT = os.path.join(os.path.dirname(__file__), "..")
GOOD = os.path.join(ROOT, "examples", "good.jsonl")
MESSY = os.path.join(ROOT, "examples", "messy.jsonl")
DUPES = os.path.join(ROOT, "examples", "dupes.jsonl")

CHAT = ('{"messages": [{"role": "user", "content": "Hi"}, '
        '{"role": "assistant", "content": "Hello"}]}')


def write_tmp(testcase, content, binary=False):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    mode = "wb" if binary else "w"
    with os.fdopen(fd, mode, encoding=None if binary else "utf-8") as fh:
        fh.write(content)
    testcase.addCleanup(os.unlink, path)
    return path


def error_messages(report):
    return [e["message"] for e in report["errors"]]


class TestEstimateTokens(unittest.TestCase):
    def test_latin_text(self):
        self.assertEqual(dd.estimate_tokens("abcd"), 1)
        self.assertEqual(dd.estimate_tokens("abcdefgh"), 2)

    def test_cjk_counts_one_per_char(self):
        self.assertEqual(dd.estimate_tokens("こんにちは"), 5)

    def test_whitespace_ignored(self):
        self.assertEqual(dd.estimate_tokens("a b c d"), 1)


class TestHashes(unittest.TestCase):
    def test_canonical_ignores_key_order(self):
        a = {"b": 1, "a": 2}
        b = {"a": 2, "b": 1}
        self.assertEqual(dd.canonical_hash(a), dd.canonical_hash(b))

    def test_normalized_ignores_case_and_spacing(self):
        a = {"messages": [{"role": "user", "content": "Hello   World"}]}
        b = {"messages": [{"role": "user", "content": "hello world"}]}
        self.assertNotEqual(dd.canonical_hash(a), dd.canonical_hash(b))
        self.assertEqual(dd.normalized_hash(a), dd.normalized_hash(b))


class TestCheckValid(unittest.TestCase):
    def test_good_file_passes(self):
        report = dd.validate_file(GOOD)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["warnings"], [])
        self.assertEqual(report["examples"], 6)
        self.assertEqual(report["valid"], 6)
        self.assertEqual(report["format"], "chat")

    def test_prompt_completion_file_passes(self):
        path = write_tmp(self, '{"prompt": "Q?", "completion": " A"}\n'
                               '{"prompt": "Q2?", "completion": " B"}\n')
        report = dd.validate_file(path)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["format"], "prompt-completion")


class TestCheckDefects(unittest.TestCase):
    def test_invalid_json_reports_line_number(self):
        path = write_tmp(self, CHAT + "\n{not json\n" + CHAT + "\n")
        report = dd.validate_file(path)
        self.assertTrue(any(e["line"] == 2 and "invalid JSON" in e["message"]
                            for e in report["errors"]))

    def test_bom_is_an_error(self):
        path = write_tmp(self, b"\xef\xbb\xbf" + CHAT.encode() + b"\n",
                         binary=True)
        report = dd.validate_file(path)
        self.assertTrue(any("BOM" in m for m in error_messages(report)))

    def test_non_object_line(self):
        path = write_tmp(self, '["just", "a", "list"]\n')
        report = dd.validate_file(path)
        self.assertTrue(any("not an object" in m
                            for m in error_messages(report)))

    def test_missing_assistant_ending(self):
        path = write_tmp(
            self, '{"messages": [{"role": "user", "content": "Hi"}]}\n')
        report = dd.validate_file(path)
        msgs = error_messages(report)
        self.assertTrue(any("no assistant" in m for m in msgs))
        self.assertTrue(any("does not end with an assistant" in m
                            for m in msgs))

    def test_invalid_role(self):
        path = write_tmp(
            self,
            '{"messages": [{"role": "human", "content": "Hi"}, '
            '{"role": "assistant", "content": "Hello"}]}\n')
        report = dd.validate_file(path)
        self.assertTrue(any("invalid role" in m
                            for m in error_messages(report)))

    def test_empty_assistant_content(self):
        path = write_tmp(
            self,
            '{"messages": [{"role": "user", "content": "Hi"}, '
            '{"role": "assistant", "content": ""}]}\n')
        report = dd.validate_file(path)
        self.assertTrue(any("empty content" in m
                            for m in error_messages(report)))

    def test_system_not_first(self):
        path = write_tmp(
            self,
            '{"messages": [{"role": "user", "content": "Hi"}, '
            '{"role": "system", "content": "late"}, '
            '{"role": "assistant", "content": "Hello"}]}\n')
        report = dd.validate_file(path)
        self.assertTrue(any("must be the first" in m
                            for m in error_messages(report)))

    def test_mixed_format_file(self):
        report = dd.validate_file(MESSY)
        self.assertTrue(any("differs from the file's format" in m
                            for m in error_messages(report)))

    def test_exact_and_normalized_duplicates_flagged(self):
        report = dd.validate_file(DUPES)
        msgs = [w["message"] for w in report["warnings"]]
        self.assertTrue(any("exact duplicate of line 1" in m for m in msgs))
        self.assertTrue(any("near-duplicate of line 1" in m for m in msgs))
        self.assertEqual(report["errors"], [])

    def test_conflicting_answers_flagged(self):
        path = write_tmp(
            self,
            '{"messages": [{"role": "user", "content": "Capital of France?"},'
            ' {"role": "assistant", "content": "Paris."}]}\n'
            '{"messages": [{"role": "user", "content": "Capital of France?"},'
            ' {"role": "assistant", "content": "Lyon."}]}\n')
        report = dd.validate_file(path)
        msgs = [w["message"] for w in report["warnings"]]
        self.assertTrue(any("different" in m and "answer" in m
                            for m in msgs))

    def test_overlong_example_warns(self):
        big = "x" * 20000
        path = write_tmp(
            self,
            '{"messages": [{"role": "user", "content": "%s"}, '
            '{"role": "assistant", "content": "ok"}]}\n' % big)
        report = dd.validate_file(path, max_tokens=4096)
        msgs = [w["message"] for w in report["warnings"]]
        self.assertTrue(any("estimated tokens" in m for m in msgs))

    def test_messy_example_file_fails_with_line_numbers(self):
        report = dd.validate_file(MESSY)
        self.assertGreaterEqual(len(report["errors"]), 4)
        lines_with_errors = {e["line"] for e in report["errors"]}
        self.assertIn(2, lines_with_errors)   # truncated JSON
        self.assertIn(5, lines_with_errors)   # bad role
        self.assertIn(6, lines_with_errors)   # empty content


class TestDedupeSplitLeakage(unittest.TestCase):
    def test_dedupe_exact(self):
        kept, removed = dd.dedupe_file(DUPES)
        self.assertEqual(len(kept), 3)
        self.assertEqual(removed, 1)

    def test_dedupe_normalized(self):
        kept, removed = dd.dedupe_file(DUPES, normalized=True)
        self.assertEqual(len(kept), 2)
        self.assertEqual(removed, 2)

    def test_split_is_deterministic_disjoint_and_complete(self):
        raw = [json.dumps({"n": i}) for i in range(20)]
        train1, val1 = dd.split_lines(raw, 0.25, seed=42)
        train2, val2 = dd.split_lines(raw, 0.25, seed=42)
        self.assertEqual((train1, val1), (train2, val2))
        self.assertEqual(len(val1), 5)
        self.assertEqual(sorted(train1 + val1), sorted(raw))
        self.assertFalse(set(train1) & set(val1))

    def test_leakage_detects_shared_example(self):
        a = write_tmp(self, CHAT + "\n" + CHAT.replace("Hi", "Other") + "\n")
        b = write_tmp(self, CHAT + "\n")
        result = dd.leakage_report(a, b)
        self.assertEqual(len(result["exact"]), 1)
        # an exact match must not be double-reported as normalized-only
        self.assertEqual(len(result["normalized_only"]), 0)

    def test_leakage_clean_pair(self):
        a = write_tmp(self, CHAT + "\n")
        b = write_tmp(self, CHAT.replace("Hi", "Different") + "\n")
        result = dd.leakage_report(a, b)
        self.assertEqual(len(result["exact"]), 0)
        self.assertEqual(len(result["normalized_only"]), 0)


class TestCliEndToEnd(unittest.TestCase):
    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "dataset_doctor.py"),
             *argv],
            capture_output=True, text=True)

    def test_check_good_exit_0(self):
        proc = self.run_cli("check", GOOD)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("check passed", proc.stdout)

    def test_check_messy_exit_1_and_json(self):
        proc = self.run_cli("check", MESSY, "--json")
        self.assertEqual(proc.returncode, 1)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["ok"])
        self.assertGreaterEqual(
            len(payload["files"][0]["errors"]), 4)

    def test_check_missing_file_exit_2(self):
        proc = self.run_cli("check", "/nonexistent/nope.jsonl")
        self.assertEqual(proc.returncode, 1)  # unreadable file = errors
        payload = self.run_cli("check", "/nonexistent/nope.jsonl",
                               "--json")
        self.assertFalse(json.loads(payload.stdout)["ok"])

    def test_dedupe_then_check_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "clean.jsonl")
            proc = self.run_cli("dedupe", DUPES, "--normalized", "-o", out)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            proc = self.run_cli("check", out)
            self.assertEqual(proc.returncode, 0, proc.stdout)
            with open(out, encoding="utf-8") as fh:
                self.assertEqual(len(fh.read().strip().splitlines()), 2)

    def test_split_then_no_leakage(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "all.jsonl")
            with open(src, "w", encoding="utf-8") as fh:
                for i in range(10):
                    fh.write(json.dumps(
                        {"messages": [
                            {"role": "user", "content": "q%d" % i},
                            {"role": "assistant", "content": "a%d" % i}]})
                        + "\n")
            train = os.path.join(tmp, "train.jsonl")
            val = os.path.join(tmp, "val.jsonl")
            proc = self.run_cli("split", src, "--train-out", train,
                                "--val-out", val, "--val-ratio", "0.2")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            proc = self.run_cli("leakage", train, val)
            self.assertEqual(proc.returncode, 0, proc.stdout)
            proc = self.run_cli("leakage", train, train)
            self.assertEqual(proc.returncode, 1)

    def test_help(self):
        proc = self.run_cli("--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("dedupe", proc.stdout)


if __name__ == "__main__":
    unittest.main()
