#!/usr/bin/env python3
"""DatasetDoctor — pre-flight checks for fine-tuning / eval JSONL datasets.

Validates chat-format ({"messages": [...]}) and prompt/completion JSONL
files the way training APIs wish you had *before* upload: every problem is
reported with its line number. Also detects exact and normalized
duplicate examples, conflicting answers to the same prompt, near-duplicate
examples that differ in wording (character-shingle text similarity,
opt-in via --similarity), train/val leakage between two files (exact,
normalized, or paraphrased), and provides deterministic dedupe and split
commands.

Born from a recurring public failure: fine-tuning jobs rejected for
"invalid training file" with no line number, leaving users to binary-search
20,000-line files by hand. DatasetDoctor finds the line in seconds,
offline, without sending proprietary training data anywhere.

Pure Python standard library. No third-party dependencies.

Exit codes: 0 = clean / success, 1 = problems found, 2 = usage or I/O
error.
"""

import argparse
import hashlib
import json
import math
import os
import random
import statistics
import sys
from collections import Counter

__version__ = "0.2.0"

VALID_ROLES = ("system", "user", "assistant", "tool")
DEFAULT_MAX_TOKENS = 4096
_BOM = b"\xef\xbb\xbf"


# ---------------------------------------------------------------------------
# Token estimation (heuristic — labelled as an estimate everywhere it is
# shown; it is for spotting outliers, not for billing)
# ---------------------------------------------------------------------------

def _is_cjk(ch):
    o = ord(ch)
    return (0x3040 <= o <= 0x30FF      # hiragana / katakana
            or 0x3400 <= o <= 0x9FFF   # CJK unified ideographs
            or 0xAC00 <= o <= 0xD7AF   # hangul syllables
            or 0xF900 <= o <= 0xFAFF)  # CJK compatibility ideographs


def estimate_tokens(text):
    """Rough token estimate: ~1 token per CJK character, ~4 chars/token
    for everything else. Good enough to spot the 40k-token outlier in a
    dataset of 2k-token examples; not a billing number."""
    cjk = sum(1 for ch in text if _is_cjk(ch))
    other = sum(1 for ch in text
                if not _is_cjk(ch) and not ch.isspace())
    return cjk + math.ceil(other / 4)


# ---------------------------------------------------------------------------
# Hashing for duplicate / leakage detection
# ---------------------------------------------------------------------------

def _normalize_value(value):
    if isinstance(value, str):
        return " ".join(value.split()).casefold()
    if isinstance(value, list):
        return [_normalize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize_value(v) for k, v in value.items()}
    return value


def canonical_hash(record):
    """Hash of the record with object key order normalized away."""
    blob = json.dumps(record, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def normalized_hash(record):
    """Hash after collapsing whitespace and case-folding every string —
    catches duplicates that differ only in spacing or capitalization."""
    blob = json.dumps(_normalize_value(record), ensure_ascii=False,
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def record_text(record):
    """All human-readable text in a record, for length estimation."""
    parts = []

    def walk(value):
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)

    walk(record)
    return "\n".join(parts)


def message_text(message):
    """Text content of one chat message (string content, or the text
    parts of a structured content list)."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [part.get("text", "") for part in content
                 if isinstance(part, dict)]
        return "\n".join(t for t in texts if t)
    return ""


# ---------------------------------------------------------------------------
# Text similarity — near-duplicates that normalization cannot see
#
# Two examples can say almost the same thing in different words (a
# paraphrase, a lightly edited copy, the same template answer pasted under
# reworded questions). Exact and normalized hashes miss those completely,
# yet they still bias training and — worse — leak across a train/val
# split, inflating eval scores.
#
# Similarity is the Jaccard index of the texts' character 5-gram
# ("shingle") sets, computed on whitespace-collapsed, case-folded text.
# Character shingles are used instead of word shingles because they work
# the same for unspaced scripts (Japanese, Chinese) as for spaced ones —
# this tool's token estimator is already CJK-aware, and duplicate
# detection should be too.
# ---------------------------------------------------------------------------

SHINGLE_SIZE = 5
DEFAULT_SIMILARITY = 0.8


def text_shingles(text):
    """Set of character 5-grams of the normalized text. Texts shorter
    than one shingle contribute their whole normalized form, so very
    short examples are still comparable (and identical short texts score
    1.0). Empty text yields an empty set."""
    normalized = " ".join(text.split()).casefold()
    if not normalized:
        return set()
    if len(normalized) <= SHINGLE_SIZE:
        return {normalized}
    return {normalized[i:i + SHINGLE_SIZE]
            for i in range(len(normalized) - SHINGLE_SIZE + 1)}


def jaccard_similarity(set_a, set_b):
    """|A ∩ B| / |A ∪ B|; 0.0 when either set is empty."""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    if not intersection:
        return 0.0
    return intersection / len(set_a | set_b)


def similar_pairs(texts, threshold, skip_pairs=frozenset(),
                  skip_groups=None, reportable=None):
    """Find pairs of texts whose shingle Jaccard similarity is at least
    `threshold` (0 < threshold <= 1).

    `texts` is a list of (key, text) with unique keys; the result is a
    list of (key_a, key_b, similarity) in input order, each unordered
    pair reported once. Pairs in `skip_pairs` (as (earlier_key,
    later_key)) are not reported, and neither are pairs whose keys map
    to the same label in `skip_groups` — callers use these to avoid
    repeating pairs already flagged as exact/normalized duplicates
    (a duplicate cluster shares one label, so no pair inside a cluster
    is ever re-reported as merely "similar").

    Each later key is reported at most once, against the *earliest*
    earlier key it resembles — the same convention as the exact-
    duplicate warnings ("duplicate of line N" names the first
    occurrence). Besides keeping reports readable, this bounds the
    work: inside a large cluster of mutually similar texts the number
    of reported pairs is linear in the input size, not quadratic.
    `reportable`, when given, is a callable (earlier_key, later_key)
    -> bool: pairs it rejects are skipped *without* using up the
    later key's one report (leakage uses it to consider only
    cross-file pairs).

    Candidate pairs come from a prefix index: for Jaccard threshold t,
    two sets can only reach t if the rarest-first prefixes of their
    shingle sets (length |A| - ceil(t*|A|) + 1) overlap, so only prefix
    sharers are ever compared in full. The filter is exact — it prunes
    comparisons, never results.
    """
    docs = []
    doc_freq = Counter()
    for key, text in texts:
        shingles = text_shingles(text)
        if not shingles:
            continue
        docs.append((key, shingles))
        doc_freq.update(shingles)
    # Rarest shingles first: makes prefixes selective and the ordering
    # deterministic (frequency, then the shingle itself).
    rank = {shingle: i for i, shingle in
            enumerate(sorted(doc_freq, key=lambda s: (doc_freq[s], s)))}
    index = {}
    pairs = []
    for pos, (key, shingles) in enumerate(docs):
        ordered = sorted(shingles, key=lambda s: rank[s])
        prefix_len = len(ordered) - math.ceil(threshold * len(ordered)) + 1
        prefix = ordered[:max(1, prefix_len)]
        candidates = set()
        for shingle in prefix:
            candidates.update(index.get(shingle, ()))
        for other_pos in sorted(candidates):
            other_key, other_shingles = docs[other_pos]
            if (other_key, key) in skip_pairs:
                continue
            if reportable is not None \
                    and not reportable(other_key, key):
                continue
            if skip_groups is not None \
                    and skip_groups.get(other_key) is not None \
                    and skip_groups.get(other_key) == skip_groups.get(key):
                continue
            # Size filter: Jaccard >= t requires the set sizes to be
            # within a factor of t of each other.
            if len(other_shingles) < threshold * len(shingles) \
                    or len(shingles) < threshold * len(other_shingles):
                continue
            sim = jaccard_similarity(other_shingles, shingles)
            if sim >= threshold:
                pairs.append((other_key, key, sim))
                break  # one report per later key: the earliest match
        for shingle in prefix:
            index.setdefault(shingle, []).append(pos)
    return pairs


# ---------------------------------------------------------------------------
# File loading — byte level, so BOM and encoding damage get line numbers
# ---------------------------------------------------------------------------

def load_lines(path):
    """Return (raw_lines, fatal_error). raw_lines is a list of
    (line_number, text_or_None, decode_error_or_None)."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        return None, str(exc)
    has_bom = data.startswith(_BOM)
    raw = data.split(b"\n")
    lines = []
    for i, chunk in enumerate(raw, start=1):
        if i == len(raw) and chunk == b"":
            continue  # trailing newline at EOF is not an empty example
        if i == 1 and has_bom:
            chunk = chunk[len(_BOM):]
        try:
            lines.append((i, chunk.decode("utf-8"), None))
        except UnicodeDecodeError as exc:
            lines.append((i, None, str(exc)))
    return (lines, has_bom), None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _json_type_name(value):
    """JSON's name for a parsed value's type (object, array, string,
    number, boolean, null) — error messages speak JSON, not Python."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def detect_format(record):
    if isinstance(record, dict):
        if "messages" in record:
            return "chat"
        if "prompt" in record or "completion" in record:
            # Either key alone means a *broken* prompt/completion
            # record, so the missing-key error in
            # _check_prompt_completion can fire — classifying it as
            # generic would let it pass with only a warning.
            return "prompt-completion"
    return "generic"


def _check_chat(record, line_no, add):
    messages = record.get("messages")
    if not isinstance(messages, list) or not messages:
        add("error", line_no, "'messages' must be a non-empty list")
        return
    roles = []
    for j, message in enumerate(messages):
        where = "message %d" % (j + 1)
        if not isinstance(message, dict):
            add("error", line_no, "%s is not an object" % where)
            continue
        role = message.get("role")
        if role not in VALID_ROLES:
            add("error", line_no,
                "%s has missing/invalid role %r (expected one of %s)"
                % (where, role, ", ".join(VALID_ROLES)))
            continue
        roles.append(role)
        if role == "system" and j != 0:
            add("error", line_no,
                "system message must be the first message (found at %s)"
                % where)
        text = message_text(message)
        if "content" not in message:
            add("error", line_no, "%s has no 'content'" % where)
        else:
            content = message.get("content")
            if content is not None \
                    and not isinstance(content, (str, list)):
                # Training APIs require a string or a list of content
                # parts; a number/boolean/object used to slip through
                # silently because it produced no text. (None stays
                # tolerated: assistant tool-call messages carry
                # content: null legitimately.)
                add("error", line_no,
                    "%s (%s) has invalid 'content': a JSON %s — content "
                    "must be a string or a list of content parts"
                    % (where, role, _json_type_name(content)))
            elif isinstance(content, str) and not text.strip():
                # Structured content with no text (e.g. image-only) is
                # legal for user turns in multimodal sets; an empty
                # *string* is not.
                add("error", line_no,
                    "%s (%s) has empty content" % (where, role))
    if roles:
        if "user" not in roles:
            add("error", line_no, "conversation has no user message")
        if "assistant" not in roles:
            add("error", line_no, "conversation has no assistant message")
        if roles[-1] != "assistant":
            add("error", line_no,
                "conversation does not end with an assistant message "
                "(last role: %s) — SFT examples must end with the reply "
                "being taught" % roles[-1])
        for prev, cur in zip(roles, roles[1:]):
            if prev == cur == "user":
                add("warning", line_no,
                    "two consecutive user messages — usually a sign of a "
                    "split example or a missing assistant reply")
        if "tool" in roles:
            add("warning", line_no,
                "contains tool messages; tool-call structure is not fully "
                "validated in this version")


def _check_prompt_completion(record, line_no, add):
    for key in ("prompt", "completion"):
        if key not in record:
            add("error", line_no, "missing %r key" % key)
        elif not isinstance(record[key], str):
            add("error", line_no, "%r must be a string" % key)
    if isinstance(record.get("prompt"), str) \
            and not record["prompt"].strip():
        add("error", line_no, "prompt is empty")
    if isinstance(record.get("completion"), str) \
            and not record["completion"].strip():
        add("warning", line_no, "completion is empty")


def validate_file(path, max_tokens=DEFAULT_MAX_TOKENS, similarity=0.0):
    """Validate one JSONL file; return a report dict. With
    `similarity` > 0, also warn about example pairs whose text is at
    least that similar (character-shingle Jaccard) without being exact
    or normalized duplicates."""
    report = {
        "file": path,
        "format": None,
        "examples": 0,
        "valid": 0,
        "errors": [],
        "warnings": [],
        "stats": {},
    }

    def add(kind, line_no, message):
        report["errors" if kind == "error" else "warnings"].append(
            {"line": line_no, "message": message})

    loaded, fatal = load_lines(path) if not _is_stdin(path) \
        else (_read_stdin(), None)
    if fatal is not None:
        report["errors"].append({"line": None, "message":
                                 "cannot read file: %s" % fatal})
        report["fatal"] = True  # an I/O error: `check` exits 2, not 1
        return report
    lines, has_bom = loaded
    if has_bom:
        add("error", 1,
            "file starts with a UTF-8 BOM — several training APIs reject "
            "or mis-parse BOM files; save as UTF-8 without BOM")

    exact_seen = {}
    norm_seen = {}
    prompt_answers = {}
    token_counts = []
    role_counter = Counter()
    file_format = None
    record_texts = []   # (line_no, full text) for the similarity pass
    dupe_pairs = set()  # (first_line, later_line) already flagged as dupes
    norm_groups = {}    # line_no -> normalized hash (its duplicate cluster)

    for line_no, text, decode_error in lines:
        if decode_error is not None:
            add("error", line_no,
                "not valid UTF-8 (%s) — training APIs require UTF-8"
                % decode_error)
            continue
        if not text.strip():
            add("warning", line_no, "empty line")
            continue
        try:
            record = json.loads(text)
        except json.JSONDecodeError as exc:
            add("error", line_no,
                "invalid JSON: %s (column %d)" % (exc.msg, exc.colno))
            continue
        if not isinstance(record, dict):
            add("error", line_no,
                "line is a JSON %s, not an object — every example must be "
                "one JSON object on one line" % _json_type_name(record))
            continue

        report["examples"] += 1
        # Captured before *any* per-record error (including the
        # mixed-format error below), so "valid" only counts examples
        # with no error at all.
        before = len(report["errors"])
        fmt = detect_format(record)
        if file_format is None:
            file_format = fmt
            report["format"] = fmt
        elif fmt != file_format:
            add("error", line_no,
                "record format (%s) differs from the file's format (%s) — "
                "mixed-format files are rejected by training APIs"
                % (fmt, file_format))

        if fmt == "chat":
            _check_chat(record, line_no, add)
            for m in record.get("messages", []):
                if isinstance(m, dict):
                    role_counter[m.get("role", "?")] += 1
        elif fmt == "prompt-completion":
            _check_prompt_completion(record, line_no, add)
        else:
            add("warning", line_no,
                "unrecognized record shape (no 'messages', no "
                "prompt/completion pair) — only JSON validity was checked")

        text = record_text(record)
        record_texts.append((line_no, text))
        tokens = estimate_tokens(text)
        token_counts.append(tokens)
        if max_tokens and tokens > max_tokens:
            add("warning", line_no,
                "example is long: ~%d estimated tokens (limit %d) — "
                "over-length examples are truncated or rejected by many "
                "training APIs" % (tokens, max_tokens))

        chash = canonical_hash(record)
        nhash = normalized_hash(record)
        norm_groups[line_no] = nhash
        if chash in exact_seen:
            dupe_pairs.add((exact_seen[chash], line_no))
            add("warning", line_no,
                "exact duplicate of line %d — duplicates waste training "
                "budget and bias the model" % exact_seen[chash])
        else:
            exact_seen[chash] = line_no
            if nhash in norm_seen:
                dupe_pairs.add((norm_seen[nhash], line_no))
                add("warning", line_no,
                    "near-duplicate of line %d (identical after "
                    "whitespace/case normalization)" % norm_seen[nhash])
            else:
                norm_seen[nhash] = line_no

        if fmt == "chat" and isinstance(record.get("messages"), list):
            users = "\n".join(message_text(m) for m in record["messages"]
                              if isinstance(m, dict)
                              and m.get("role") == "user")
            assistants = [message_text(m) for m in record["messages"]
                          if isinstance(m, dict)
                          and m.get("role") == "assistant"]
            if users and assistants:
                key = normalized_hash({"u": users})
                answer = normalized_hash({"a": assistants[-1]})
                if key in prompt_answers \
                        and prompt_answers[key][0] != answer:
                    add("warning", line_no,
                        "same user prompt as line %d but a different "
                        "assistant answer — conflicting duplicates teach "
                        "inconsistent behaviour"
                        % prompt_answers[key][1])
                else:
                    prompt_answers.setdefault(key, (answer, line_no))

        if len(report["errors"]) == before:
            report["valid"] += 1

    if similarity and similarity > 0:
        for first_line, later_line, sim in similar_pairs(
                record_texts, similarity, skip_pairs=dupe_pairs,
                skip_groups=norm_groups):
            add("warning", later_line,
                "text is %.0f%% similar to line %d — possible "
                "near-duplicate with different wording, which exact and "
                "normalized duplicate checks cannot see; paraphrased "
                "duplicates still bias training and inflate eval scores "
                "when they cross a split"
                % (sim * 100, first_line))
        # The similarity pass runs after the per-line pass; restore
        # line order so the report reads top to bottom.
        report["warnings"].sort(
            key=lambda w: (w["line"] is None, w["line"] or 0))

    if report["examples"] == 0 and not report["errors"]:
        add("error", None, "file contains no examples")
    if token_counts:
        report["stats"] = {
            "estimated_tokens_total": sum(token_counts),
            "estimated_tokens_min": min(token_counts),
            "estimated_tokens_median": statistics.median(token_counts),
            "estimated_tokens_mean": round(statistics.mean(token_counts), 1),
            "estimated_tokens_max": max(token_counts),
            "roles": dict(role_counter),
        }
    return report


def _is_stdin(path):
    return path == "-"


def _read_stdin():
    data = sys.stdin.buffer.read()
    has_bom = data.startswith(_BOM)
    raw = data.split(b"\n")
    lines = []
    for i, chunk in enumerate(raw, start=1):
        if i == len(raw) and chunk == b"":
            continue
        if i == 1 and has_bom:
            chunk = chunk[len(_BOM):]
        try:
            lines.append((i, chunk.decode("utf-8"), None))
        except UnicodeDecodeError as exc:
            lines.append((i, None, str(exc)))
    return lines, has_bom


# ---------------------------------------------------------------------------
# Dedupe / split / leakage
# ---------------------------------------------------------------------------

def iter_records(path):
    """Yield (line_no, raw_text, record) for every parseable object
    line. raw_text is the line as written — only the CR of a CRLF
    ending is removed — so dedupe/split preserve the original text."""
    loaded, fatal = load_lines(path)
    if fatal is not None:
        raise OSError(fatal)
    lines, _ = loaded
    for line_no, text, decode_error in lines:
        if decode_error is not None or not text or not text.strip():
            continue
        try:
            record = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            raw = text[:-1] if text.endswith("\r") else text
            yield line_no, raw, record


def skipped_line_count(path):
    """How many non-blank lines iter_records skips: lines that are not
    parseable JSON objects (invalid JSON, JSON arrays/scalars, invalid
    UTF-8). dedupe and split report this so dropped lines are never
    silent."""
    loaded, fatal = load_lines(path)
    if fatal is not None:
        raise OSError(fatal)
    lines, _ = loaded
    skipped = 0
    for _line_no, text, decode_error in lines:
        if decode_error is not None:
            skipped += 1
            continue
        if not text.strip():
            continue
        try:
            record = json.loads(text)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not isinstance(record, dict):
            skipped += 1
    return skipped


def _skipped_note(skipped):
    return (", skipped %d unparseable line(s)" % skipped) if skipped \
        else ""


def dedupe_file(in_path, normalized=False):
    """Return (kept_raw_lines, removed_count)."""
    seen = set()
    kept = []
    removed = 0
    for _line_no, raw, record in iter_records(in_path):
        key = normalized_hash(record) if normalized \
            else canonical_hash(record)
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        kept.append(raw)
    return kept, removed


def split_lines(raw_lines, val_ratio, seed):
    idx = list(range(len(raw_lines)))
    random.Random(seed).shuffle(idx)
    n_val = int(round(len(raw_lines) * val_ratio))
    if raw_lines and val_ratio > 0:
        n_val = max(1, n_val)
    val_idx = set(idx[:n_val])
    train = [raw_lines[i] for i in range(len(raw_lines)) if i not in val_idx]
    val = [raw_lines[i] for i in sorted(val_idx)]
    return train, val


def leakage_report(path_a, path_b, similarity=0.0):
    """Compare two files for shared examples. Returns exact and
    normalized-hash overlaps as (line_in_b, line_in_a) pairs; with
    `similarity` > 0, also cross-file pairs whose text is at least that
    similar (paraphrase leakage), as (line_in_b, line_in_a, similarity)
    triples — pairs already reported as exact/normalized are not
    repeated in the similar list."""
    def hashes(path):
        exact, norm = {}, {}
        for line_no, _raw, record in iter_records(path):
            exact.setdefault(canonical_hash(record), line_no)
            norm.setdefault(normalized_hash(record), line_no)
        return exact, norm

    exact_a, norm_a = hashes(path_a)
    exact_b, norm_b = hashes(path_b)
    exact_overlap = [(exact_b[h], exact_a[h]) for h in exact_b
                     if h in exact_a]
    exact_pairs = set(exact_overlap)
    norm_overlap = [(norm_b[h], norm_a[h]) for h in norm_b
                    if h in norm_a
                    and (norm_b[h], norm_a[h]) not in exact_pairs]
    result = {"exact": exact_overlap, "normalized_only": norm_overlap,
              "similar": []}
    if similarity and similarity > 0:
        known = {(("a", a_line), ("b", b_line))
                 for b_line, a_line in exact_overlap + norm_overlap}
        texts = [(("a", line_no), record_text(record))
                 for line_no, _raw, record in iter_records(path_a)]
        texts += [(("b", line_no), record_text(record))
                  for line_no, _raw, record in iter_records(path_b)]
        cross_file = lambda key_a, key_b: key_a[0] != key_b[0]  # noqa: E731
        for key_a, key_b, sim in similar_pairs(
                texts, similarity, skip_pairs=known,
                reportable=cross_file):
            # a-records precede b-records in `texts`, so a cross pair
            # always arrives as (a_key, b_key)
            result["similar"].append((key_b[1], key_a[1], sim))
        result["similar"].sort()
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_issue_list(issues, label, cap=20):
    for issue in issues[:cap]:
        where = "line %s" % issue["line"] if issue["line"] else "file"
        print("  %s: %s" % (where, issue["message"]))
    if len(issues) > cap:
        print("  … and %d more %s" % (len(issues) - cap, label))


def _check_similarity_arg(args):
    """Return an error string if --similarity is out of range."""
    if args.similarity is not None \
            and not 0.0 < args.similarity <= 1.0:
        return ("--similarity must be in the range (0, 1], got %s"
                % args.similarity)
    return None


def cmd_check(args):
    bad = _check_similarity_arg(args)
    if bad:
        print("dataset-doctor: %s" % bad, file=sys.stderr)
        return 2
    if args.max_tokens < 0:
        print("dataset-doctor: --max-tokens must be 0 or greater, got %s"
              % args.max_tokens, file=sys.stderr)
        return 2
    reports = []
    any_errors = False
    any_fatal = False
    for path in args.files:
        report = validate_file(path, max_tokens=args.max_tokens,
                               similarity=args.similarity or 0.0)
        reports.append(report)
        if report["errors"]:
            any_errors = True
        if report.get("fatal"):
            any_fatal = True
    if args.json:
        print(json.dumps({"ok": not any_errors, "files": reports},
                         ensure_ascii=False, indent=2))
        if any_fatal:
            return 2  # I/O error, as documented — not a dataset error
        return 1 if any_errors else 0
    for report in reports:
        print("%s — format: %s, %d example(s), %d valid, %d error(s), "
              "%d warning(s)"
              % (report["file"], report["format"] or "unknown",
                 report["examples"], report["valid"],
                 len(report["errors"]), len(report["warnings"])))
        if report["stats"]:
            s = report["stats"]
            print("  estimated tokens: total %d, min %d, median %s, "
                  "mean %s, max %d"
                  % (s["estimated_tokens_total"], s["estimated_tokens_min"],
                     s["estimated_tokens_median"],
                     s["estimated_tokens_mean"],
                     s["estimated_tokens_max"]))
        if report["errors"]:
            print("  errors:")
            _print_issue_list(report["errors"], "errors")
        if report["warnings"]:
            print("  warnings:")
            _print_issue_list(report["warnings"], "warnings")
    if any_errors:
        print("check FAILED")
    else:
        print("check passed")
    if any_fatal:
        return 2
    return 1 if any_errors else 0


def cmd_dedupe(args):
    try:
        kept, removed = dedupe_file(args.input, normalized=args.normalized)
        skipped = skipped_line_count(args.input)
    except OSError as exc:
        print("dataset-doctor: %s" % exc, file=sys.stderr)
        return 2
    note = _skipped_note(skipped)
    payload = "\n".join(kept) + ("\n" if kept else "")
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(payload)
        except OSError as exc:
            print("dataset-doctor: %s" % exc, file=sys.stderr)
            return 2
        print("kept %d example(s), removed %d duplicate(s)%s → %s"
              % (len(kept), removed, note, args.output))
    else:
        sys.stdout.write(payload)
        print("kept %d, removed %d duplicate(s)%s"
              % (len(kept), removed, note), file=sys.stderr)
    return 0


def cmd_split(args):
    if not 0.0 <= args.val_ratio <= 1.0:
        print("dataset-doctor: --val-ratio must be between 0 and 1, "
              "got %s" % args.val_ratio, file=sys.stderr)
        return 2
    if os.path.abspath(args.train_out) == os.path.abspath(args.val_out):
        print("dataset-doctor: --train-out and --val-out must be "
              "different files", file=sys.stderr)
        return 2
    try:
        raw = [raw for _n, raw, _r in iter_records(args.input)]
        skipped = skipped_line_count(args.input)
    except OSError as exc:
        print("dataset-doctor: %s" % exc, file=sys.stderr)
        return 2
    if not raw:
        print("dataset-doctor: no parseable examples in %s" % args.input,
              file=sys.stderr)
        return 2
    train, val = split_lines(raw, args.val_ratio, args.seed)
    try:
        with open(args.train_out, "w", encoding="utf-8") as fh:
            fh.write("\n".join(train) + ("\n" if train else ""))
        with open(args.val_out, "w", encoding="utf-8") as fh:
            fh.write("\n".join(val) + ("\n" if val else ""))
    except OSError as exc:
        print("dataset-doctor: %s" % exc, file=sys.stderr)
        return 2
    print("split %d example(s) → %d train (%s), %d validation (%s), "
          "seed %d%s" % (len(raw), len(train), args.train_out, len(val),
                         args.val_out, args.seed,
                         _skipped_note(skipped)))
    return 0


def cmd_leakage(args):
    bad = _check_similarity_arg(args)
    if bad:
        print("dataset-doctor: %s" % bad, file=sys.stderr)
        return 2
    try:
        result = leakage_report(args.file_a, args.file_b,
                                similarity=args.similarity or 0.0)
    except OSError as exc:
        print("dataset-doctor: %s" % exc, file=sys.stderr)
        return 2
    total = len(result["exact"]) + len(result["normalized_only"]) \
        + len(result["similar"])
    if args.json:
        print(json.dumps({"leaked_examples": total,
                          "exact": [{"in_b_line": b, "in_a_line": a}
                                    for b, a in result["exact"]],
                          "normalized_only": [
                              {"in_b_line": b, "in_a_line": a}
                              for b, a in result["normalized_only"]],
                          "similar": [
                              {"in_b_line": b, "in_a_line": a,
                               "similarity": round(sim, 3)}
                              for b, a, sim in result["similar"]]},
                         indent=2))
    else:
        for b_line, a_line in result["exact"][:20]:
            print("LEAK: %s line %d is an exact duplicate of %s line %d"
                  % (args.file_b, b_line, args.file_a, a_line))
        for b_line, a_line in result["normalized_only"][:20]:
            print("LEAK: %s line %d matches %s line %d after "
                  "whitespace/case normalization"
                  % (args.file_b, b_line, args.file_a, a_line))
        for b_line, a_line, sim in result["similar"][:20]:
            print("LEAK: %s line %d is %.0f%% similar to %s line %d — "
                  "possible paraphrase leakage"
                  % (args.file_b, b_line, sim * 100,
                     args.file_a, a_line))
        if total:
            print("leakage FAILED — %d example(s) appear in both files"
                  % total)
        else:
            print("no leakage — the two files share no examples")
    return 1 if total else 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="dataset-doctor",
        description="Pre-flight checks for fine-tuning / eval JSONL "
                    "datasets: format validation with line numbers, "
                    "duplicate and leakage detection, dedupe and split.")
    parser.add_argument("--version", action="version",
                        version="dataset-doctor %s" % __version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser(
        "check", help="validate one or more JSONL dataset files")
    p_check.add_argument("files", nargs="+",
                         help="JSONL file(s) to validate (- for stdin)")
    p_check.add_argument("--max-tokens", type=int,
                         default=DEFAULT_MAX_TOKENS,
                         help="warn when an example's estimated tokens "
                              "exceed this (0 = off, default: %(default)s)")
    p_check.add_argument("--json", action="store_true",
                         help="print the full report as JSON")
    p_check.add_argument("--similarity", type=float, default=None,
                         metavar="T",
                         help="also warn about examples whose text is at "
                              "least T similar (0 < T <= 1, character-"
                              "shingle Jaccard) without being exact or "
                              "normalized duplicates — catches paraphrased "
                              "near-duplicates (suggested: 0.8)")
    p_check.set_defaults(func=cmd_check)

    p_dedupe = sub.add_parser(
        "dedupe", help="remove duplicate examples from a JSONL file")
    p_dedupe.add_argument("input", help="input JSONL file")
    p_dedupe.add_argument("-o", "--output",
                          help="output file (default: stdout)")
    p_dedupe.add_argument("--normalized", action="store_true",
                          help="also treat examples that differ only in "
                               "whitespace/case as duplicates")
    p_dedupe.set_defaults(func=cmd_dedupe)

    p_split = sub.add_parser(
        "split", help="deterministically split a dataset into "
                      "train/validation files (disjoint by construction)")
    p_split.add_argument("input", help="input JSONL file")
    p_split.add_argument("--train-out", required=True)
    p_split.add_argument("--val-out", required=True)
    p_split.add_argument("--val-ratio", type=float, default=0.1,
                         help="fraction for validation (default: 0.1)")
    p_split.add_argument("--seed", type=int, default=42,
                         help="shuffle seed (default: 42)")
    p_split.set_defaults(func=cmd_split)

    p_leak = sub.add_parser(
        "leakage", help="fail if two files (e.g. train and validation) "
                        "share any example")
    p_leak.add_argument("file_a")
    p_leak.add_argument("file_b")
    p_leak.add_argument("--json", action="store_true")
    p_leak.add_argument("--similarity", type=float, default=None,
                        metavar="T",
                        help="also fail on cross-file example pairs whose "
                             "text is at least T similar (0 < T <= 1, "
                             "character-shingle Jaccard) — catches "
                             "paraphrase leakage (suggested: 0.8)")
    p_leak.set_defaults(func=cmd_leakage)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
