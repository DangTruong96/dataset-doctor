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
SIMILAR = os.path.join(ROOT, "examples", "similar.jsonl")

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


PARA_A = ("To reset your password, open the settings page, choose "
          "security, and follow the link we email to you to create a new "
          "password for your account.")
PARA_B = ("To reset your password, open the settings page, choose "
          "security, and follow the link we send by email to create a "
          "new strong password for your account.")
UNRELATED = ("The mitochondria is the powerhouse of the cell and "
             "produces most of the chemical energy needed to power the "
             "cell's biochemical reactions.")


class TestTextShingles(unittest.TestCase):
    def test_shingles_are_character_5grams(self):
        self.assertEqual(dd.text_shingles("abcdefgh"),
                         {"abcde", "bcdef", "cdefg", "defgh"})

    def test_shingles_normalize_case_and_whitespace(self):
        self.assertEqual(dd.text_shingles("Hello   World"),
                         dd.text_shingles("hello world"))

    def test_shingles_short_text_is_a_single_shingle(self):
        self.assertEqual(dd.text_shingles("abc"), {"abc"})
        self.assertEqual(dd.text_shingles("abcde"), {"abcde"})

    def test_shingles_empty_text(self):
        self.assertEqual(dd.text_shingles(""), set())
        self.assertEqual(dd.text_shingles("   "), set())

    def test_shingles_cjk_text(self):
        shingles = dd.text_shingles("こんにちは世界")
        self.assertEqual(len(shingles), 3)  # 7 chars -> three 5-grams
        self.assertIn("こんにちは", shingles)


class TestJaccardSimilarity(unittest.TestCase):
    def test_identical_sets(self):
        self.assertEqual(dd.jaccard_similarity({"a", "b"}, {"a", "b"}),
                         1.0)

    def test_disjoint_sets(self):
        self.assertEqual(dd.jaccard_similarity({"a"}, {"b"}), 0.0)

    def test_partial_overlap(self):
        self.assertEqual(
            dd.jaccard_similarity({"a", "b", "c"}, {"b", "c", "d"}), 0.5)

    def test_empty_sets(self):
        self.assertEqual(dd.jaccard_similarity(set(), {"a"}), 0.0)
        self.assertEqual(dd.jaccard_similarity(set(), set()), 0.0)


class TestSimilarPairs(unittest.TestCase):
    TEXTS = [(1, PARA_A), (2, PARA_B), (3, UNRELATED)]

    def test_paraphrase_detected_unrelated_ignored(self):
        pairs = dd.similar_pairs(self.TEXTS, 0.5)
        self.assertEqual([(a, b) for a, b, _s in pairs], [(1, 2)])
        self.assertGreaterEqual(pairs[0][2], 0.5)
        self.assertLess(pairs[0][2], 1.0)  # similar, not identical

    def test_threshold_is_respected(self):
        # the paraphrase pair scores ~0.78: found at 0.5, not at 0.95
        self.assertEqual(len(dd.similar_pairs(self.TEXTS, 0.5)), 1)
        self.assertEqual(dd.similar_pairs(self.TEXTS, 0.95), [])

    def test_identical_texts_score_one(self):
        pairs = dd.similar_pairs([(1, PARA_A), (2, PARA_A)], 0.99)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][2], 1.0)

    def test_skip_pairs_are_not_reported(self):
        pairs = dd.similar_pairs(self.TEXTS, 0.5,
                                 skip_pairs=frozenset({(1, 2)}))
        self.assertEqual(pairs, [])

    def test_skip_groups_suppress_whole_clusters(self):
        # keys 1 and 2 are in one duplicate cluster: their pair is
        # suppressed; key 3 still pairs — once, with the earliest key
        texts = [(1, PARA_A), (2, PARA_A), (3, PARA_B)]
        groups = {1: "cluster-x", 2: "cluster-x", 3: "cluster-y"}
        pairs = dd.similar_pairs(texts, 0.5, skip_groups=groups)
        self.assertEqual([(a, b) for a, b, _s in pairs], [(1, 3)])

    def test_one_report_per_later_key_against_earliest_match(self):
        texts = [(1, PARA_A), (2, PARA_A), (3, PARA_A)]
        pairs = dd.similar_pairs(texts, 0.5)
        self.assertEqual([(a, b) for a, b, _s in pairs], [(1, 2), (1, 3)])

    def test_reportable_rejection_does_not_use_up_the_report(self):
        # key 3 resembles both key 1 (rejected by the predicate) and
        # key 2 (accepted): the accepted pair is still reported
        texts = [(1, PARA_A), (2, PARA_B), (3, PARA_A)]
        pairs = dd.similar_pairs(
            texts, 0.5, reportable=lambda a, b: a != 1)
        self.assertEqual([(a, b) for a, b, _s in pairs], [(2, 3)])

    def test_empty_texts_never_pair(self):
        self.assertEqual(dd.similar_pairs([(1, ""), (2, "")], 0.1), [])
        self.assertEqual(dd.similar_pairs([(1, "  "), (2, PARA_A)], 0.1),
                         [])

    def test_pairs_follow_input_order(self):
        texts = [(10, PARA_A), (20, UNRELATED), (30, PARA_B)]
        pairs = dd.similar_pairs(texts, 0.5)
        self.assertEqual([(a, b) for a, b, _s in pairs], [(10, 30)])


class TestCheckSimilarity(unittest.TestCase):
    def test_similarity_off_by_default(self):
        report = dd.validate_file(SIMILAR)
        msgs = [w["message"] for w in report["warnings"]]
        self.assertFalse(any("similar to line" in m for m in msgs))
        self.assertEqual(report["errors"], [])

    def test_paraphrase_flagged_with_both_line_numbers(self):
        report = dd.validate_file(SIMILAR, similarity=0.8)
        hits = [w for w in report["warnings"]
                if "similar to line 1" in w["message"]]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["line"], 2)
        self.assertEqual(report["errors"], [])

    def test_duplicates_not_double_reported_as_similar(self):
        # dupes.jsonl's pairs are exact/normalized duplicates; even at a
        # low similarity threshold they must not reappear as "similar"
        report = dd.validate_file(DUPES, similarity=0.5)
        msgs = [w["message"] for w in report["warnings"]]
        self.assertTrue(any("exact duplicate" in m for m in msgs))
        self.assertFalse(any("% similar" in m for m in msgs))

    def test_similarity_warnings_keep_line_order(self):
        with open(SIMILAR, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        other = ('{"messages": [{"role": "user", "content": "Which '
                 'organelle makes energy?"}, {"role": "assistant", '
                 '"content": "The mitochondria."}]}\n')
        other_shouted = other.replace("Which", "WHICH").replace(
            "mitochondria", "MITOCHONDRIA")
        path = write_tmp(self, lines[0] + "\n" + lines[1] + "\n"
                         + other + other_shouted)
        report = dd.validate_file(path, similarity=0.8)
        warn_lines = [w["line"] for w in report["warnings"]]
        self.assertIn(2, warn_lines)   # paraphrase of line 1
        self.assertIn(4, warn_lines)   # normalized duplicate of line 3
        self.assertEqual(warn_lines, sorted(warn_lines))


class TestLeakageSimilarity(unittest.TestCase):
    def _split_similar_example(self):
        with open(SIMILAR, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        a = write_tmp(self, lines[0] + "\n")
        b = write_tmp(self, lines[1] + "\n")
        return a, b

    def test_paraphrase_leakage_detected(self):
        a, b = self._split_similar_example()
        result = dd.leakage_report(a, b, similarity=0.8)
        self.assertEqual(result["exact"], [])
        self.assertEqual(result["normalized_only"], [])
        self.assertEqual(len(result["similar"]), 1)
        in_b, in_a, sim = result["similar"][0]
        self.assertEqual((in_b, in_a), (1, 1))
        self.assertGreaterEqual(sim, 0.8)

    def test_paraphrase_invisible_without_similarity(self):
        a, b = self._split_similar_example()
        result = dd.leakage_report(a, b)
        self.assertEqual(result["similar"], [])
        self.assertEqual(result["exact"], [])
        self.assertEqual(result["normalized_only"], [])

    def test_exact_match_not_repeated_as_similar(self):
        a, _b = self._split_similar_example()
        result = dd.leakage_report(a, a, similarity=0.8)
        self.assertEqual(len(result["exact"]), 1)
        self.assertEqual(result["similar"], [])


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
        # the README and module docstring promise exit 2 for I/O errors
        # (1 is reserved for "file read fine, dataset has errors")
        proc = self.run_cli("check", "/nonexistent/nope.jsonl")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot read file", proc.stdout)
        payload = self.run_cli("check", "/nonexistent/nope.jsonl",
                               "--json")
        self.assertEqual(payload.returncode, 2)
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


class TestCliSimilarity(unittest.TestCase):
    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "dataset_doctor.py"),
             *argv],
            capture_output=True, text=True)

    def _split_similar_example(self, testcase):
        with open(SIMILAR, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        a = write_tmp(testcase, lines[0] + "\n")
        b = write_tmp(testcase, lines[1] + "\n")
        return a, b

    def test_check_similarity_flag(self):
        proc = self.run_cli("check", SIMILAR, "--similarity", "0.8")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("similar to line 1", proc.stdout)
        proc = self.run_cli("check", SIMILAR)
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("similar to line", proc.stdout)

    def test_check_similarity_json_contains_warning(self):
        proc = self.run_cli("check", SIMILAR, "--similarity", "0.8",
                            "--json")
        self.assertEqual(proc.returncode, 0)
        warnings = json.loads(proc.stdout)["files"][0]["warnings"]
        self.assertTrue(any("similar to line 1" in w["message"]
                            for w in warnings))

    def test_check_similarity_out_of_range_exit_2(self):
        for value in ("0", "1.5", "-0.2"):
            proc = self.run_cli("check", SIMILAR, "--similarity", value)
            self.assertEqual(proc.returncode, 2, value)

    def test_leakage_similarity_flag(self):
        a, b = self._split_similar_example(self)
        proc = self.run_cli("leakage", a, b)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        proc = self.run_cli("leakage", a, b, "--similarity", "0.8")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("paraphrase leakage", proc.stdout)

    def test_leakage_similarity_json(self):
        a, b = self._split_similar_example(self)
        proc = self.run_cli("leakage", a, b, "--similarity", "0.8",
                            "--json")
        self.assertEqual(proc.returncode, 1)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["leaked_examples"], 1)
        self.assertEqual(len(payload["similar"]), 1)
        self.assertGreaterEqual(payload["similar"][0]["similarity"], 0.8)


class TestPromptCompletionMissingKeys(unittest.TestCase):
    """A record with only one of prompt/completion is a broken
    prompt/completion record, not a 'generic' record that passes."""

    def test_prompt_without_completion_is_an_error(self):
        path = write_tmp(self, '{"prompt": "What is 2+2?"}\n')
        report = dd.validate_file(path)
        self.assertEqual(report["format"], "prompt-completion")
        self.assertTrue(any("missing 'completion'" in m
                            for m in error_messages(report)))
        self.assertEqual(report["valid"], 0)

    def test_completion_without_prompt_is_an_error(self):
        path = write_tmp(self, '{"completion": " 4"}\n')
        report = dd.validate_file(path)
        self.assertEqual(report["format"], "prompt-completion")
        self.assertTrue(any("missing 'prompt'" in m
                            for m in error_messages(report)))


class TestContentTypes(unittest.TestCase):
    """Chat 'content' must be a string or a list of parts; other JSON
    values are rejected by training APIs and must not pass silently."""

    def test_numeric_content_is_an_error(self):
        path = write_tmp(
            self,
            '{"messages": [{"role": "user", "content": 123}, '
            '{"role": "assistant", "content": "ok"}]}\n')
        report = dd.validate_file(path)
        self.assertTrue(any("invalid 'content'" in m
                            for m in error_messages(report)))
        self.assertEqual(report["valid"], 0)

    def test_dict_content_is_an_error(self):
        path = write_tmp(
            self,
            '{"messages": [{"role": "user", "content": {"text": "hi"}}, '
            '{"role": "assistant", "content": "ok"}]}\n')
        report = dd.validate_file(path)
        self.assertTrue(any("invalid 'content'" in m
                            for m in error_messages(report)))

    def test_null_content_is_tolerated(self):
        # assistant messages with tool calls legitimately carry
        # content: null; this must not become an error
        path = write_tmp(
            self,
            '{"messages": [{"role": "user", "content": "Hi"}, '
            '{"role": "assistant", "content": null}]}\n')
        report = dd.validate_file(path)
        self.assertEqual(report["errors"], [])


class TestValidCounting(unittest.TestCase):
    def test_mixed_format_record_is_not_counted_valid(self):
        path = write_tmp(
            self, CHAT + '\n{"prompt": "Q?", "completion": " A"}\n')
        report = dd.validate_file(path)
        self.assertEqual(report["examples"], 2)
        self.assertEqual(report["valid"], 1)

    def test_messy_file_valid_count(self):
        # errors sit on 4 of the 7 examples (lines 4, 5, 6, 8)
        report = dd.validate_file(MESSY)
        self.assertEqual(report["examples"], 7)
        self.assertEqual(report["valid"], 3)


class TestNonObjectTypeNames(unittest.TestCase):
    def test_messages_use_json_type_names_not_python(self):
        path = write_tmp(self, 'null\n"a string"\n42\ntrue\n[1]\n')
        msgs = error_messages(dd.validate_file(path))
        self.assertTrue(any("JSON null" in m for m in msgs))
        self.assertTrue(any("JSON string" in m for m in msgs))
        self.assertTrue(any("JSON number" in m for m in msgs))
        self.assertTrue(any("JSON boolean" in m for m in msgs))
        self.assertTrue(any("JSON array" in m for m in msgs))
        self.assertFalse(any("NoneType" in m for m in msgs))


class TestSkippedLines(unittest.TestCase):
    DIRTY = CHAT + "\n{broken line\n[1, 2]\n\n" + CHAT + "\n"

    def test_skipped_line_count(self):
        path = write_tmp(self, self.DIRTY)
        # the broken-JSON line and the array line; the blank line and
        # the two valid records do not count
        self.assertEqual(dd.skipped_line_count(path), 2)

    def test_dedupe_reports_skipped_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "dirty.jsonl")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write(self.DIRTY)
            out = os.path.join(tmp, "out.jsonl")
            proc = subprocess.run(
                [sys.executable,
                 os.path.join(ROOT, "dataset_doctor.py"),
                 "dedupe", src, "-o", out],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("skipped 2 unparseable line(s)", proc.stdout)

    def test_split_reports_skipped_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "dirty.jsonl")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write(self.DIRTY)
            proc = subprocess.run(
                [sys.executable,
                 os.path.join(ROOT, "dataset_doctor.py"),
                 "split", src,
                 "--train-out", os.path.join(tmp, "train.jsonl"),
                 "--val-out", os.path.join(tmp, "val.jsonl")],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("skipped 2 unparseable line(s)", proc.stdout)


class TestDedupeLineFidelity(unittest.TestCase):
    def test_surrounding_whitespace_is_preserved(self):
        # README promises "original line text is preserved"
        line = '   {"prompt": "Q?", "completion": " A"}   '
        path = write_tmp(self, line + "\n")
        kept, removed = dd.dedupe_file(path)
        self.assertEqual(kept, [line])
        self.assertEqual(removed, 0)

    def test_crlf_cr_is_not_carried_into_output(self):
        path = write_tmp(
            self, b'{"prompt": "Q?", "completion": " A"}\r\n',
            binary=True)
        kept, _removed = dd.dedupe_file(path)
        self.assertEqual(kept, ['{"prompt": "Q?", "completion": " A"}'])


class TestCliFlagValidation(unittest.TestCase):
    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "dataset_doctor.py"),
             *argv],
            capture_output=True, text=True)

    def test_split_val_ratio_out_of_range_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            for value in ("1.5", "-0.5"):
                proc = self.run_cli(
                    "split", GOOD,
                    "--train-out", os.path.join(tmp, "t.jsonl"),
                    "--val-out", os.path.join(tmp, "v.jsonl"),
                    "--val-ratio", value)
                self.assertEqual(proc.returncode, 2, value)
                self.assertIn("--val-ratio", proc.stderr)

    def test_split_same_output_path_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            same = os.path.join(tmp, "same.jsonl")
            proc = self.run_cli("split", GOOD, "--train-out", same,
                                "--val-out", same)
            self.assertEqual(proc.returncode, 2)
            self.assertFalse(os.path.exists(same))

    def test_split_empty_side_writes_truly_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            train = os.path.join(tmp, "train.jsonl")
            val = os.path.join(tmp, "val.jsonl")
            proc = self.run_cli("split", GOOD, "--train-out", train,
                                "--val-out", val, "--val-ratio", "0")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(os.path.getsize(val), 0)
            self.assertGreater(os.path.getsize(train), 0)
            proc = self.run_cli("split", GOOD, "--train-out", train,
                                "--val-out", val, "--val-ratio", "1")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(os.path.getsize(train), 0)
            self.assertGreater(os.path.getsize(val), 0)

    def test_check_negative_max_tokens_exit_2(self):
        proc = self.run_cli("check", GOOD, "--max-tokens", "-1")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--max-tokens", proc.stderr)


if __name__ == "__main__":
    unittest.main()
